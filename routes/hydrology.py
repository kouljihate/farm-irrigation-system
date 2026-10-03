"""Hydrology section: MainLine, SubLines, Valves."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)
from shapely.geometry import Polygon

from core.geometry import (
    centroid_lonlat, clean_linestring, clean_polygon, first_ring,
    inward_offset, local_projection, polyline_length_m,
)
from core.piping import direct_or_detour
from core.valve_rules import group_sector_map
from core.validation import validate_form, MainlineBuild, SubmainBuild
from db import queries, repository
from db.connection import get_db


bp = Blueprint("hydrology", __name__, url_prefix="/hydrology")


# ---------------------------------------------------------------- mainline
@bp.route("/mainline", methods=["GET", "POST"])
@validate_form(MainlineBuild)
def mainline(data: MainlineBuild | None = None):
    pid = session.get("project_id", "")

    if request.method == "POST":
        assert data is not None
        count = _build_mainline(pid, data.offset, data.diameter)
        if count:
            flash(f"Built {count} mainline pipes.", "success")
        return redirect(url_for("hydrology.mainline"))

    pipes = [p for p in queries.get_pipes(pid, "mainline")]
    return render_template("hydrology/mainline.html", pipes=pipes)


def _build_mainline(project_id: str, offset: float, diameter: int) -> int:
    db = get_db()
    prop = db.property.find_one({"project_id": project_id})
    basin = db.basins.find_one({"project_id": project_id})
    mvs = {v["name"]: v for v in queries.get_valves(project_id, "MV")}
    if not prop or not basin or not mvs:
        flash("Need P1, basin, and MV valves first.", "error")
        return 0

    ring = first_ring(prop.get("geom"))
    basin_center = centroid_lonlat(basin.get("geom"))
    if not ring or not basin_center:
        flash("Property or basin geometry is missing.", "error")
        return 0

    to_local, to_lonlat = local_projection(ring)
    p1_xy = clean_polygon(Polygon([to_local(p[0], p[1]) for p in ring]))
    try:
        inner = inward_offset(p1_xy, offset)
    except ValueError as exc:
        flash(str(exc), "error")
        return 0
    basin_xy = to_local(*basin_center)

    revision = repository.new_revision(project_id, "06_mainline",
                                       f"Mainline offset={offset}m Ø{diameter}")
    repository.delete_where("pipes",
        {"project_id": project_id, "pipe_type": "mainline"})

    now = datetime.now(timezone.utc)
    count = 0
    for mv_name, mv in mvs.items():
        loc = (mv.get("location") or {}).get("coordinates")
        if not loc:
            continue
        mv_xy = to_local(loc[0], loc[1])
        path = direct_or_detour(p1_xy, inner, basin_xy, mv_xy)
        path_ll = clean_linestring([list(to_lonlat(x, y)) for x, y in path])
        if len(path_ll) < 2:
            continue

        name = f"MAIN-BASIN-{mv_name}"
        repository.upsert("pipes",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name,
             "pipe_type": "mainline",
             "geom": {"type": "LineString",
                      "coordinates": [list(p) for p in path_ll]},
             "length_m": polyline_length_m(path_ll), "diameter_mm": diameter,
             "material": "HDPE PE100 PN10",
             "revision_id": revision,
             "created_at": now, "updated_at": now})
        count += 1

    current_app.logger.info("Mainline built for %s (%d pipes)", project_id, count)
    return count


# ---------------------------------------------------------------- sub-mains
@bp.route("/submains", methods=["GET", "POST"])
@validate_form(SubmainBuild)
def submains(data: SubmainBuild | None = None):
    pid = session.get("project_id", "")

    if request.method == "POST":
        assert data is not None
        count = _build_submains(pid, data.offset, data.diameter)
        if count:
            flash(f"Built {count} sub-main pipes.", "success")
        return redirect(url_for("hydrology.submains"))

    pipes = queries.get_pipes(pid, "submain")
    return render_template("hydrology/submains.html", pipes=pipes)


def _build_submains(project_id: str, offset: float, diameter: int) -> int:
    db = get_db()
    prop = db.property.find_one({"project_id": project_id})
    mvs = {v["name"]: v for v in queries.get_valves(project_id, "MV")}
    zvs = queries.get_valves(project_id, "ZV")
    if not prop or not mvs or not zvs:
        flash("Need P1, MV valves, and ZV valves first.", "error")
        return 0

    ring = first_ring(prop.get("geom"))
    if not ring:
        flash("Property geometry is missing.", "error")
        return 0

    to_local, to_lonlat = local_projection(ring)
    p1_xy = clean_polygon(Polygon([to_local(p[0], p[1]) for p in ring]))
    try:
        inner = inward_offset(p1_xy, offset)
    except ValueError as exc:
        flash(str(exc), "error")
        return 0

    sector_map = group_sector_map(
        [s.get("sector_code") or s["name"] for s in queries.get_sectors(project_id)])

    revision = repository.new_revision(project_id, "07_submains",
                                       f"Sub-mains Ø{diameter}")
    repository.delete_where("pipes",
        {"project_id": project_id, "pipe_type": "submain"})

    now = datetime.now(timezone.utc)
    count = 0
    for zv in zvs:
        code = zv.get("sector_code")
        mv_name = sector_map.get(code)
        if mv_name not in mvs:
            continue
        mv_loc = (mvs[mv_name].get("location") or {}).get("coordinates")
        zv_loc = (zv.get("location") or {}).get("coordinates")
        if not mv_loc or not zv_loc:
            continue
        start = to_local(mv_loc[0], mv_loc[1])
        end = to_local(zv_loc[0], zv_loc[1])
        path = direct_or_detour(p1_xy, inner, start, end)
        path_ll = clean_linestring([list(to_lonlat(x, y)) for x, y in path])
        if len(path_ll) < 2:
            continue

        name = f"{mv_name}-{zv['name']}"
        repository.upsert("pipes",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name,
             "pipe_type": "submain", "parent_pipe": mv_name,
             "geom": {"type": "LineString",
                      "coordinates": [list(p) for p in path_ll]},
             "length_m": polyline_length_m(path_ll), "diameter_mm": diameter,
             "material": "HDPE PE100 PN10",
             "revision_id": revision,
             "created_at": now, "updated_at": now})
        count += 1

    current_app.logger.info("Sub-mains built for %s (%d)", project_id, count)
    return count


# ---------------------------------------------------------------- valves
@bp.route("/valves", methods=["GET", "POST"])
def valves():
    """Manage main and zone valves in the Hydrology domain."""
    pid = session.get("project_id", "")
    if request.method == "POST":
        sectors = queries.get_sectors(pid)
        zones = queries.get_zones(pid)
        if not sectors or not zones:
            flash("Need sectors and zones first.", "error")
        else:
            from core.valve_rules import build_mv_groups, zv_name
            revision = repository.new_revision(pid, "05_valves", "Generate valves")
            repository.clear_step(pid, "valves")
            now = datetime.now(timezone.utc)
            by_code = {(s.get("sector_code") or s["name"]): s for s in sectors}
            count = 0
            for mv, sector_codes in build_mv_groups(list(by_code)).items():
                center = centroid_lonlat((by_code.get(sector_codes[0]) or {}).get("geom"))
                if center:
                    repository.upsert("valves", {"project_id": pid, "name": mv},
                        {"project_id": pid, "name": mv, "valve_type": "MV",
                         "sector_code": sector_codes[0],
                         "location": {"type": "Point", "coordinates": list(center)},
                         "diameter_mm": 50, "revision_id": revision,
                         "created_at": now, "updated_at": now})
                    count += 1
            for z in zones:
                code, zi, center = z.get("sector_code"), z.get("zone_index"), centroid_lonlat(z.get("geom"))
                if code and zi is not None and center:
                    name = zv_name(code, zi)
                    repository.upsert("valves", {"project_id": pid, "name": name},
                        {"project_id": pid, "name": name, "valve_type": "ZV",
                         "sector_code": code, "zone_name": z.get("name"),
                         "location": {"type": "Point", "coordinates": list(center)},
                         "diameter_mm": 32, "revision_id": revision,
                         "created_at": now, "updated_at": now})
                    count += 1
            flash(f"Built {count} valves.", "success")
        return redirect(url_for("hydrology.valves"))
    return render_template("hydrology/valves.html",
                           mvs=queries.get_valves(pid, "MV"),
                           zvs=queries.get_valves(pid, "ZV"))


# ---------------------------------------------------------------- manifold
@bp.route("/manifold", methods=["GET", "POST"])
def manifold():
    pid = session.get("project_id", "")

    if request.method == "POST":
        count = _build_manifolds(pid)
        if count:
            flash(f"Built {count} manifolds.", "success")
        return redirect(url_for("hydrology.manifold"))

    manifolds = list(get_db().manifolds.find(
        {"project_id": pid}, {"_id": 0}))
    return render_template("hydrology/manifold.html", manifolds=manifolds)


def _build_manifolds(project_id: str) -> int:
    zones = queries.get_zones(project_id)
    if not zones:
        flash("No zones.", "error")
        return 0

    revision = repository.new_revision(project_id, "11_manifold",
                                       "Build manifolds")
    repository.clear_step(project_id, "manifolds")

    now = datetime.now(timezone.utc)
    n = 0
    for z in zones:
        rows = queries.get_rows(project_id, z.get("name"))
        starts = []
        for r in rows:
            line = (r.get("geom") or {}).get("coordinates") or []
            if line:
                starts.append((line[0][0], line[0][1]))
        if len(starts) < 2:
            continue
        starts_sorted = sorted(starts, key=lambda p: p[0])
        manifold_ll = clean_linestring(
            [starts_sorted[0], starts_sorted[-1]])
        if len(manifold_ll) < 2:
            continue
        name = f"MANIFOLD {z['name']}"
        repository.upsert("manifolds",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name,
             "zone_name": z["name"],
             "geom": {"type": "LineString", "coordinates": manifold_ll},
             "length_m": polyline_length_m(manifold_ll),
             "revision_id": revision,
             "created_at": now, "updated_at": now})
        n += 1

    current_app.logger.info("Built %d manifolds for %s", n, project_id)
    return n