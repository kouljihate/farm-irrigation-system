"""Geometry section: Sectors and Zones."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template,
    request, session, url_for,
)
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from core.async_tasks import get_project_tasks, get_task_status, submit_async_task
from core.geometry import (
    centroid_lonlat, clean_polygon, fall_direction, first_ring, ring_area_m2,
)
from core.valve_rules import build_mv_groups, zv_name
from core.validation import (
    SectorAdd, SectorCodes, SectorSave, SectorSplit, ZoneBuild, validate_form,
)
from db import queries, repository
from db.connection import get_db


bp = Blueprint("geometry", __name__, url_prefix="/geometry")


# ---------------------------------------------------------------- sectors
@bp.route("/sectors")
def sectors():
    pid = session.get("project_id", "")
    if not pid:
        return redirect(url_for("home.home"))

    rows = queries.get_sectors(pid)
    sectors = []
    for s in rows:
        ring = first_ring(s.get("geom"))
        if not ring:
            continue
        sectors.append({
            "code":  s.get("sector_code") or s["name"],
            "name":  s["name"],
            "coords_text": "\n".join(f"{x:.7f},{y:.7f}" for x, y in ring),
            "vertices": len(ring),
            "area_m2":  s.get("area_m2", 0),
        })
    return render_template("geometry/sectors.html", sectors=sectors)


@bp.route("/sectors/save", methods=["POST"])
@validate_form(SectorSave)
def save_sector(data: SectorSave):
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    code = data.code
    coords_text = data.coords

    # parse lines "lon,lat" (or "lon,lat,ele")
    ring = []
    for line in coords_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        lon = float(parts[0])
        lat = float(parts[1])
        ring.append([lon, lat])

    if len(ring) < 3:
        return jsonify({"ok": False, "error": "need at least 3 points"}), 400

    # auto-close ring
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    # compute area via lon/lat -> meters approximation
    area_m2 = ring_area_m2(ring)

    revision = repository.new_revision(pid, "03_sectors_edit",
                                       f"Edit {code}")
    now = datetime.now(timezone.utc)

    repository.upsert("sectors",
        {"project_id": pid, "sector_code": code},
        {
            "project_id": pid,
            "name": code,
            "sector_code": code,
            "geom": {"type": "Polygon", "coordinates": [ring]},
            "area_m2": area_m2,
            "revision_id": revision,
            "updated_at": now,
        })

    return jsonify({
        "ok": True,
        "vertices": len(ring) - 1,   # excluding closing duplicate
        "area_m2": area_m2,
        "area_ha": area_m2 / 10000.0,
    })


# ---------------------------------------------------------------- sector ops
# Add / Remove / Merge / Split. Zones and valves are *derived* data derived
# from sectors, so every mutation reports exactly what it cascaded instead of
# leaving dangling references behind.

_EARTH_R = 6371000.0


def _parse_ring(coords_text: str) -> list[list[float]]:
    """Parse 'lon,lat' lines into a closed ring ([[lon, lat], ...])."""
    ring: list[list[float]] = []
    for line in coords_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        ring.append([float(parts[0]), float(parts[1])])
    if len(ring) < 3:
        raise ValueError("need at least 3 points")
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def _to_local_xy(ring: list[list[float]]):
    """Project a lon/lat ring to local metres (equirectangular, per-ring origin)."""
    lon0 = sum(p[0] for p in ring) / len(ring)
    lat0 = sum(p[1] for p in ring) / len(ring)
    coslat = math.cos(math.radians(lat0))
    return ([(math.radians(x - lon0) * _EARTH_R * coslat,
              math.radians(y - lat0) * _EARTH_R) for x, y in ring], lon0, lat0)


def _to_lonlat(x: float, y: float, lon0: float, lat0: float) -> list[float]:
    coslat = math.cos(math.radians(lat0))
    return [lon0 + math.degrees(x / (_EARTH_R * coslat)),
            lat0 + math.degrees(y / _EARTH_R)]


def _poly_ring_to_ll(poly: Polygon, lon0: float, lat0: float) -> list[list[float]]:
    ring = [_to_lonlat(x, y, lon0, lat0) for x, y in poly.exterior.coords]
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def _sector_codes(pid: str) -> list[str]:
    db = get_db()
    return [d.get("sector_code") or d.get("name")
            for d in db.sectors.find({"project_id": pid}, {"sector_code": 1, "name": 1})]


def _next_sector_code(pid: str) -> str:
    """Allocate the next free ``S<n>`` code (1-based, gaps tolerated)."""
    highest = 0
    for code in _sector_codes(pid):
        m = re.fullmatch(r"S(\d+)", (code or "").strip(), flags=re.IGNORECASE)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"S{highest + 1}"


def _derived_impact(pid: str, codes: list[str]) -> dict:
    """Count zones/valves that depend on the given sectors."""
    db = get_db()
    codeset = set(codes)
    zones = db.zones.count_documents({"project_id": pid, "sector_code": {"$in": list(codeset)}})
    valves = db.valves.count_documents({"project_id": pid, "sector_code": {"$in": list(codeset)}})
    return {"zones": zones, "valves": valves}


def _drop_derived(pid: str, codes: list[str]) -> dict:
    """Delete zones (and valves) belonging to the given sectors."""
    impact = _derived_impact(pid, codes)
    filt = {"project_id": pid, "sector_code": {"$in": list(codes)}}
    repository.delete_where("zones", filt)
    repository.delete_where("valves", filt)
    return impact


def _store_sector(pid: str, code: str, ring: list[list[float]], revision: int,
                  now: datetime) -> float:
    area = ring_area_m2(ring)
    repository.upsert("sectors",
        {"project_id": pid, "sector_code": code},
        {
            "project_id": pid,
            "name": code,
            "sector_code": code,
            "geom": {"type": "Polygon", "coordinates": [ring]},
            "area_m2": area,
            "revision_id": revision,
            "created_at": now,
            "updated_at": now,
        })
    return area


@bp.route("/sectors/add", methods=["POST"])
@validate_form(SectorAdd)
def add_sector(data: SectorAdd):
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    try:
        ring = _parse_ring(data.coords)
    except (ValueError, IndexError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    poly = clean_polygon(Polygon([(x, y) for x, y in ring]))
    if poly.is_empty or poly.area <= 0:
        return jsonify({"ok": False, "error": "polygon has zero area"}), 400

    code = data.code or _next_sector_code(pid)
    existing = {c for c in _sector_codes(pid) if c}
    if code in existing:
        return jsonify({"ok": False, "error": f"{code} already exists"}), 409

    revision = repository.new_revision(pid, "03_sectors_edit", f"Add {code}")
    now = datetime.now(timezone.utc)
    area = _store_sector(pid, code, ring, revision, now)

    return jsonify({"ok": True, "code": code, "area_m2": area,
                    "area_ha": area / 10000.0})


@bp.route("/sectors/delete", methods=["POST"])
@validate_form(SectorCodes)
def delete_sectors(data: SectorCodes):
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    codes = data.codes.split(",")
    existing = set(c for c in _sector_codes(pid) if c)
    missing = [c for c in codes if c not in existing]
    if missing:
        return jsonify({"ok": False,
                        "error": f"unknown sector(s): {', '.join(missing)}"}), 404

    impact = _derived_impact(pid, codes)
    if (impact["zones"] or impact["valves"]) and not data.cascade:
        return jsonify({
            "ok": False,
            "needs_cascade": True,
            "error": (f"{len(codes)} sector(s) own {impact['zones']} zone(s) and "
                      f"{impact['valves']} valve(s). Those are rebuilt by "
                      f"'Build zones' / 'Generate valves'."),
            "zones": impact["zones"],
            "valves": impact["valves"],
        }), 409

    revision = repository.new_revision(pid, "03_sectors_edit",
                                       f"Remove {', '.join(codes)}")
    now = datetime.now(timezone.utc)
    removed = repository.delete_where("sectors",
                                      {"project_id": pid, "sector_code": {"$in": codes}})
    dropped = _drop_derived(pid, codes) if data.cascade else {"zones": 0, "valves": 0}

    return jsonify({"ok": True, "removed": removed, "codes": codes,
                    "zones_removed": dropped["zones"],
                    "valves_removed": dropped["valves"],
                    "revision_id": revision})


@bp.route("/sectors/merge", methods=["POST"])
@validate_form(SectorCodes)
def merge_sectors(data: SectorCodes):
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    codes = data.codes.split(",")
    if len(codes) < 2:
        return jsonify({"ok": False, "error": "select at least 2 sectors"}), 400

    db = get_db()
    rows = list(db.sectors.find({"project_id": pid, "sector_code": {"$in": codes}}))
    found = {r.get("sector_code") for r in rows}
    missing = [c for c in codes if c not in found]
    if missing:
        return jsonify({"ok": False,
                        "error": f"unknown sector(s): {', '.join(missing)}"}), 404

    # union in one shared local frame so shared borders stay shared
    all_pts = []
    rings = {}
    for r in rows:
        ring = first_ring(r.get("geom"))
        if not ring or len(ring) < 3:
            return jsonify({"ok": False,
                            "error": f"{r.get('sector_code')} has no usable geometry"}), 400
        rings[r["sector_code"]] = ring
        all_pts.extend(ring)
    lon0 = sum(p[0] for p in all_pts) / len(all_pts)
    lat0 = sum(p[1] for p in all_pts) / len(all_pts)
    coslat = math.cos(math.radians(lat0))

    def proj(ring):
        return Polygon([(math.radians(x - lon0) * _EARTH_R * coslat,
                         math.radians(y - lat0) * _EARTH_R) for x, y in ring])

    merged = clean_polygon(unary_union([proj(rings[c]) for c in codes]))
    if merged.is_empty or merged.area <= 0:
        return jsonify({"ok": False, "error": "merge produced an empty shape"}), 400
    if merged.geom_type != "Polygon":
        return jsonify({
            "ok": False,
            "error": ("these sectors do not touch, so merging them would create "
                      "a disconnected shape"),
        }), 409

    # keep the lowest code so existing references stay meaningful
    keep = sorted(codes)[0]
    drop = [c for c in codes if c != keep]

    revision = repository.new_revision(pid, "03_sectors_edit",
                                       f"Merge {', '.join(codes)} -> {keep}")
    now = datetime.now(timezone.utc)
    ring_ll = _poly_ring_to_ll(merged, lon0, lat0)
    area = _store_sector(pid, keep, ring_ll, revision, now)

    repository.delete_where("sectors", {"project_id": pid, "sector_code": {"$in": drop}})
    dropped = _drop_derived(pid, drop)

    return jsonify({"ok": True, "code": keep, "merged": codes, "dropped": drop,
                    "area_m2": area, "area_ha": area / 10000.0,
                    "zones_removed": dropped["zones"],
                    "valves_removed": dropped["valves"],
                    "revision_id": revision})


@bp.route("/sectors/split", methods=["POST"])
@validate_form(SectorSplit)
def split_sector(data: SectorSplit):
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    db = get_db()
    doc = db.sectors.find_one({"project_id": pid, "sector_code": data.code})
    if not doc:
        return jsonify({"ok": False, "error": f"unknown sector: {data.code}"}), 404

    ring = first_ring(doc.get("geom"))
    if not ring or len(ring) < 3:
        return jsonify({"ok": False, "error": "sector has no usable geometry"}), 400

    pts_xy, lon0, lat0 = _to_local_xy(ring)
    poly = clean_polygon(Polygon(pts_xy))
    if poly.is_empty or poly.area <= 0:
        return jsonify({"ok": False, "error": "sector has zero area"}), 400

    if data.split_mode == "contour":
        parts = _split_contour(poly, data.parts)
    elif data.split_mode == "fan":
        parts = _split_fan(poly, data.parts)
    elif data.split_mode == "strip":
        parts = _split_strip(poly, data.parts)
    else:
        parts = _split_contour(poly, data.parts)

    parts = [p for p in parts if p is not None and not p.is_empty
             and p.geom_type == "Polygon" and p.area > 0]
    if len(parts) < 2:
        return jsonify({"ok": False,
                        "error": f"could not cut {data.code} into {data.parts} parts"}), 422

    revision = repository.new_revision(
        pid, "03_sectors_edit",
        f"Split {data.code} -> {len(parts)} ({data.split_mode})")
    now = datetime.now(timezone.utc)

    created = []
    for part in parts:
        code = _next_sector_code(pid)
        ring_ll = _poly_ring_to_ll(part, lon0, lat0)
        area = _store_sector(pid, code, ring_ll, revision, now)
        created.append({"code": code, "area_m2": area})

    repository.delete_where("sectors",
                            {"project_id": pid, "sector_code": data.code})
    dropped = _drop_derived(pid, [data.code])

    return jsonify({"ok": True, "source": data.code, "created": created,
                    "parts": len(created), "mode": data.split_mode,
                    "area_m2": doc.get("area_m2", 0),
                    "zones_removed": dropped["zones"],
                    "valves_removed": dropped["valves"],
                    "revision_id": revision})


# ---------------------------------------------------------------- zones
@bp.route("/zones", methods=["GET", "POST"])
@validate_form(ZoneBuild)
def zones(data: ZoneBuild | None = None):
    pid = session.get("project_id", "")

    if request.method == "POST":
        assert data is not None
        # Check if async mode requested
        if request.form.get("async") == "1":
            task_id = submit_async_task(
                "build_zones",
                _do_build_zones,
                pid, data.n_parts, data.offset, data.split_mode,
                project_id=pid,
            )
            return jsonify({"ok": True, "task_id": task_id, "async": True})
        
        _do_build_zones(pid, data.n_parts, data.offset, data.split_mode)
        flash("Zones built.", "success")
        return redirect(url_for("geometry.zones"))

    rows = queries.get_zones(pid)
    table = []
    for z in rows:
        table.append({
            "name":     z["name"],
            "sector":   z.get("sector_code", ""),
            "area_m2":  round(z.get("area_m2", 0), 1),
        })
    return render_template("geometry/zones.html", zones=table)

def _do_build_zones(project_id: str, n_parts: int, offset: float,
                    split_mode: str = "contour") -> int:
    sectors = queries.get_sectors(project_id)
    if not sectors:
        return 0

    revision = repository.new_revision(
        project_id, "04_zones",
        f"Build {n_parts} zones/sector — split={split_mode}"
    )
    repository.clear_step(project_id, "zones")

    now = datetime.now(timezone.utc)
    R = 6371000.0
    total = 0

    for s in sectors:
        code = s.get("sector_code") or s["name"]
        ring = first_ring(s.get("geom"))
        if len(ring) < 3:
            continue
        pts_ll = [(x, y, 0.0) for x, y in ring]

        lon0 = sum(p[0] for p in pts_ll) / len(pts_ll)
        lat0 = sum(p[1] for p in pts_ll) / len(pts_ll)

        def to_local(lon, lat, _lon0=lon0, _lat0=lat0):
            x = math.radians(lon - _lon0) * R * math.cos(math.radians(_lat0))
            y = math.radians(lat - _lat0) * R
            return x, y

        pts_xy = [to_local(p[0], p[1]) for p in pts_ll]
        poly = clean_polygon(Polygon(pts_xy))

        if offset > 0:
            shrunk = poly.buffer(-offset, join_style=2)
            if not shrunk.is_empty:
                if shrunk.geom_type == "MultiPolygon":
                    shrunk = max(shrunk.geoms, key=lambda g: g.area)
                if shrunk.geom_type == "Polygon":
                    poly = shrunk

        # --- dispatch by split mode ---
        if split_mode == "contour":
            zones_xy = _split_contour(poly, n_parts)
        elif split_mode == "fan":
            zones_xy = _split_fan(poly, n_parts)
        elif split_mode == "strip":
            zones_xy = _split_strip(poly, n_parts)
        else:
            zones_xy = _split_contour(poly, n_parts)

        def to_lonlat(x, y, _lon0=lon0, _lat0=lat0):
            lon = _lon0 + math.degrees(x / (R * math.cos(math.radians(_lat0))))
            lat = _lat0 + math.degrees(y / R)
            return lon, lat

        for j, z in enumerate(zones_xy, start=1):
            if z is None or z.is_empty:
                continue
            if z.geom_type == "MultiPolygon":
                z = max(z.geoms, key=lambda g: g.area)
            if z.geom_type != "Polygon":
                continue

            ring_ll = [list(to_lonlat(x, y)) for x, y in z.exterior.coords]
            if ring_ll[0] != ring_ll[-1]:
                ring_ll.append(ring_ll[0])

            geom = {"type": "Polygon", "coordinates": [ring_ll]}
            zname = f"{code}-Z{j}"
            repository.upsert("zones",
                {"project_id": project_id, "name": zname},
                {"project_id": project_id, "name": zname,
                 "sector_code": code, "zone_index": j,
                 "geom": geom, "area_m2": z.area,
                 "split_mode": split_mode,
                 "revision_id": revision,
                 "created_at": now, "updated_at": now})
            total += 1

    return total


# ---------------------------------------------------------------- strategies

def _split_contour(poly: Polygon, n_parts: int):
    """
    Equal-area bands perpendicular to the fall line.
    Since we don't carry elevations here, fall direction defaults to
    'largest variance axis' — a stable proxy.
    """
    coords = list(poly.exterior.coords)
    # estimate principal axis via covariance
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in coords)
    # principal direction angle (largest variance = the long axis)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    # fall direction: perpendicular to long axis
    fall_ux = -math.sin(theta)
    fall_uy = math.cos(theta)

    return _split_by_direction(poly, n_parts, fall_ux, fall_uy)


def _split_fan(poly: Polygon, n_parts: int):
    """
    Equal-area fan: rays radiating from the centroid.
    Zones look like pie slices. Uses area sweep.
    """
    cx, cy = poly.centroid.x, poly.centroid.y
    # angles of each exterior vertex around the centroid
    coords = list(poly.exterior.coords)[:-1]
    angles = []
    for x, y in coords:
        a = math.atan2(y - cy, x - cx)
        if a < 0:
            a += 2 * math.pi
        angles.append(a)

    # target area per zone
    target = poly.area / n_parts

    # We'll sweep the full circle and find angles that accumulate `target`.
    # Simplify: sample 720 angles, integrate area by triangulating
    # with the centroid.
    samples = 720
    ang = [2 * math.pi * i / samples for i in range(samples + 1)]
    cum_area = [0.0] * (samples + 1)
    for i in range(samples):
        a0, a1 = ang[i], ang[i + 1]
        # tiny sector from centroid at [a0, a1]
        # approximate: use triangle (centroid, edge0, edge1) where edge
        # points are intersections of ray with polygon — but that's heavy.
        # Simpler: area of circle sector capped at a small angle,
        # scaled by whether the ray direction is inside the polygon.
        # Use radial intersection with the polygon.
        r0 = _ray_polygon_distance(poly, cx, cy, a0)
        r1 = _ray_polygon_distance(poly, cx, cy, a1)
        area = 0.5 * r0 * r1 * math.sin(a1 - a0) if a1 > a0 else 0
        cum_area[i + 1] = cum_area[i] + area

    total = cum_area[-1] or poly.area
    cut_angles = []
    for k in range(1, n_parts):
        want = total * k / n_parts
        # find index
        idx = 0
        for i in range(len(cum_area)):
            if cum_area[i] >= want:
                idx = i
                break
        cut_angles.append(ang[idx])

    # build wedge polygons
    zones = []
    boundaries = [0.0] + cut_angles + [2 * math.pi]
    for i in range(n_parts):
        a0 = boundaries[i]
        a1 = boundaries[i + 1]
        # sample boundary points
        steps = max(2, int((a1 - a0) * 30))
        pts = [(cx, cy)]
        for s in range(steps + 1):
            a = a0 + (a1 - a0) * s / steps
            r = _ray_polygon_distance(poly, cx, cy, a)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        wedge = Polygon(pts)
        clipped = wedge.intersection(poly)
        if clipped.is_empty:
            zones.append(None)
            continue
        if clipped.geom_type == "MultiPolygon":
            clipped = max(clipped.geoms, key=lambda g: g.area)
        zones.append(clipped if clipped.geom_type == "Polygon" else None)

    return zones


def _split_strip(poly: Polygon, n_parts: int):
    """
    Equal-area strips parallel to the longest edge of the polygon.
    """
    coords = list(poly.exterior.coords)[:-1]
    best_len = 0.0
    best_dir = (1.0, 0.0)
    for i in range(len(coords)):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % len(coords)]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L > best_len:
            best_len = L
            best_dir = (dx / L, dy / L)

    ux, uy = best_dir
    # fall direction for _split_by_direction is perpendicular to strips
    fall_ux, fall_uy = -uy, ux

    return _split_by_direction(poly, n_parts, fall_ux, fall_uy)


def _split_by_direction(poly: Polygon, n_parts: int,
                        fall_ux: float, fall_uy: float):
    """
    Cut the polygon into n equal-area bands perpendicular to
    (fall_ux, fall_uy). Returns a list of shapely Polygons.
    """
    theta = -math.pi / 2 - math.atan2(fall_uy, fall_ux)
    c, s = math.cos(theta), math.sin(theta)

    def rot(p):
        return (c * p[0] - s * p[1], s * p[0] + c * p[1])

    def rot_inv(p):
        return (c * p[0] + s * p[1], -s * p[0] + c * p[1])

    rot_poly = Polygon([rot(p) for p in poly.exterior.coords])
    if not rot_poly.is_valid:
        rot_poly = rot_poly.buffer(0)
    if rot_poly.geom_type == "MultiPolygon":
        rot_poly = max(rot_poly.geoms, key=lambda g: g.area)

    minx, miny, maxx, maxy = rot_poly.bounds
    target = rot_poly.area / n_parts

    def area_below(ycut):
        box = Polygon([(minx - 50, miny - 50),
                       (maxx + 50, miny - 50),
                       (maxx + 50, ycut),
                       (minx - 50, ycut)])
        return rot_poly.intersection(box).area

    cuts = []
    for k in range(1, n_parts):
        lo, hi = miny, maxy
        want = target * k
        for _ in range(60):
            mid = (lo + hi) / 2
            if area_below(mid) < want:
                lo = mid
            else:
                hi = mid
        cuts.append((lo + hi) / 2)
    cuts.sort()

    edges = [miny - 50] + cuts + [maxy + 50]
    zones = []
    for j in range(n_parts):
        y_lo = edges[n_parts - j - 1]
        y_hi = edges[n_parts - j]
        box = Polygon([(minx - 50, y_lo), (maxx + 50, y_lo),
                       (maxx + 50, y_hi), (minx - 50, y_hi)])
        zone = rot_poly.intersection(box)
        if zone.is_empty:
            zones.append(None)
            continue
        if zone.geom_type == "MultiPolygon":
            zone = max(zone.geoms, key=lambda g: g.area)
        if zone.geom_type != "Polygon":
            zones.append(None)
            continue
        back = [rot_inv(p) for p in zone.exterior.coords]
        zones.append(Polygon(back))
    return zones


def _ray_polygon_distance(poly: Polygon, cx: float, cy: float, ang: float) -> float:
    """Distance from (cx,cy) to the polygon boundary along direction `ang`."""
    maxR = 100000.0
    far = (cx + maxR * math.cos(ang), cy + maxR * math.sin(ang))
    ray = LineString([(cx, cy), far])
    inter = poly.exterior.intersection(ray)
    if inter.is_empty:
        return 0.0
    if inter.geom_type == "Point":
        return math.hypot(inter.x - cx, inter.y - cy)
    if inter.geom_type == "MultiPoint":
        pts = [(p.x, p.y) for p in inter.geoms]
    else:
        # LineString — take its end
        pts = list(inter.coords)
    return max(math.hypot(x - cx, y - cy) for x, y in pts)

# ---------------------------------------------------------------- valves (legacy compatibility)
@bp.route("/valves", methods=["GET", "POST"])
def valves_legacy():
    """Valves moved to Hydrology; keep the old URL as a compatibility redirect."""
    return redirect(url_for("hydrology.valves"))

@bp.route("/zones/build", methods=["POST"])
@validate_form(ZoneBuild)
def build_zones_api(data: ZoneBuild):
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    count = _do_build_zones(pid, data.n_parts, data.offset, data.split_mode)

    return jsonify({
        "ok": True,
        "zones": count,
        "n_parts": data.n_parts,
        "offset": data.offset,
        "split_mode": data.split_mode,
    })


@bp.route("/tasks/<task_id>")
def task_status(task_id: str):
    """Get status of an async task."""
    status = get_task_status(task_id)
    if not status:
        return jsonify({"ok": False, "error": "Task not found"}), 404
    return jsonify({"ok": True, "task": status})


@bp.route("/tasks")
def project_tasks():
    """Get all tasks for current project."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400
    tasks = get_project_tasks(pid)
    return jsonify({"ok": True, "tasks": tasks})