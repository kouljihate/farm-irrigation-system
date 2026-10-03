"""Project section: Initialize, Water & Basin, Settings."""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone

from flask import (
    Blueprint, flash, redirect, render_template, request,
    session, url_for, current_app,
)
from pydantic import ValidationError
from werkzeug.utils import secure_filename

from config import Config
from core import hydraulics, kml_io
from core.geometry import centroid_lonlat, geojson_polygon_area_m2
from core.validation import (
    BASIN_SOURCE_TYPE, SOURCE_TYPE_BADGES, SOURCE_TYPE_ICONS,
    SOURCE_TYPE_LABELS, SOURCE_TYPE_ORDER, WaterSourceCreate,
)
from db import repository, queries
from db.connection import get_db


bp = Blueprint("project", __name__)


# ---------------------------------------------------------------- overview
@bp.route("/overview")
def index():
    pid = session.get("project_id", "")
    if not pid:
        return redirect(url_for("home.home"))

    summary = queries.project_summary(pid)

    # has_data is True if any entity exists for this project
    db = get_db()
    has_data = any(
        db[coll].find_one({"project_id": pid}, {"_id": 1}) is not None
        for coll in ("property", "sectors", "zones", "valves",
                     "pipes", "rows", "trees", "driplines", "manifolds")
    )

    return render_template("index.html", summary=summary, has_data=has_data)

# ---------------------------------------------------------------- initialize
@bp.route("/project/initial", methods=["GET", "POST"])
def initial():
    pid = session.get("project_id", "")

    if request.method == "POST":
        f = request.files.get("kml")
        if not f or not f.filename:
            flash("No file uploaded.", "error")
            return redirect(url_for("project.initial"))

        safe_name = secure_filename(f.filename)
        if not safe_name:
            flash("Invalid file name.", "error")
            return redirect(url_for("project.initial"))

        os.makedirs(current_app.config["IMPORT_DIR"], exist_ok=True)
        save_path = os.path.join(current_app.config["IMPORT_DIR"], safe_name)
        f.save(save_path)
        current_app.logger.info("Saved upload: %s", save_path)

        if request.form.get("action") == "preview":
            data = kml_io.read_kml(save_path)
            rows = [{"name": n, "kind": v["kind"], "vertices": len(v["coords"])}
                    for n, v in data.items()]
            return render_template("project/initial.html", preview=rows,
                                   preview_count=len(rows))

        _import_project(pid, save_path, safe_name)
        flash(f"Imported {f.filename} to project {pid}.", "success")
        return redirect(url_for("project.initial"))

    return render_template("project/initial.html")


def _import_project(project_id: str, kml_path: str, source_name: str) -> None:
    db = get_db()
    revision = repository.new_revision(project_id, "01_initial",
                                       f"Import {source_name}")
    repository.create_project(project_id, project_id, description="")

    for coll in ("property", "water_points", "basins", "sectors", "zones"):
        repository.clear_step(project_id, coll)

    data = kml_io.read_kml(kml_path)
    now = datetime.now(timezone.utc)
    counts = {"property": 0, "water_points": 0, "basins": 0,
              "sectors": 0, "zones": 0}

    for name, item in data.items():
        kind = item["kind"]
        coords = item["coords"]

        if name == "P1" and kind == "polygon":
            geom = kml_io.to_geojson_polygon(coords)
            repository.upsert("property",
                {"project_id": project_id, "name": name},
                {"project_id": project_id, "name": name, "geom": geom,
                 "revision_id": revision, "created_at": now, "updated_at": now})
            counts["property"] += 1

        elif kind == "point" and ("eau" in name.lower() or "water" in name.lower() or "well" in name.lower()):
            lon, lat, ele = coords[0]
            repository.upsert("water_points",
                {"project_id": project_id, "name": name},
                {"project_id": project_id, "name": name,
                 "location": kml_io.to_geojson_point(lon, lat),
                 "elev_m": ele, "revision_id": revision,
                 "created_at": now, "updated_at": now})
            counts["water_points"] += 1

        elif kind == "polygon" and "basin" in name.lower():
            geom = kml_io.to_geojson_polygon(coords)
            ele = max(c[2] for c in coords) if coords else 0.0
            repository.upsert("basins",
                {"project_id": project_id, "name": name},
                {"project_id": project_id, "name": name, "geom": geom,
                 "elev_m": ele, "revision_id": revision,
                 "created_at": now, "updated_at": now})
            counts["basins"] += 1

        elif (kind == "polygon"
              and name.upper().startswith("S")
              and "-" not in name):
            geom = kml_io.to_geojson_polygon(coords)
            repository.upsert("sectors",
                {"project_id": project_id, "sector_code": name},
                {"project_id": project_id, "name": name,
                 "sector_code": name, "geom": geom,
                 "area_m2": geojson_polygon_area_m2(geom),
                 "revision_id": revision,
                 "created_at": now, "updated_at": now})
            counts["sectors"] += 1

        elif (kind == "polygon"
              and name.upper().startswith("S")
              and "-Z" in name.upper()):
            geom = kml_io.to_geojson_polygon(coords)
            sector_code, _, ztoken = name.partition("-")
            digits = "".join(ch for ch in ztoken if ch.isdigit())
            zone_index = int(digits) if digits else 0
            repository.upsert("zones",
                {"project_id": project_id, "name": name},
                {"project_id": project_id, "name": name,
                 "sector_code": sector_code, "zone_index": zone_index,
                 "geom": geom, "area_m2": geojson_polygon_area_m2(geom),
                 "revision_id": revision,
                 "created_at": now, "updated_at": now})
            counts["zones"] += 1

    current_app.logger.info(
        "Imported to %s: %s", project_id, counts
    )



# ---------------------------------------------------------------- well & basin
_SOURCE_COLLECTIONS = {
    "well": "water_points",
    "river": "water_points",
    "other": "water_points",
    "basin": "basins",
}


def _basin_polygon(lon: float, lat: float, length: float, width: float) -> dict:
    """Axis-aligned rectangular basin footprint (meters) around lon/lat."""
    m_per_deg_lat = 110540.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat)) or 111320.0
    dlon = (width / 2.0) / m_per_deg_lon
    dlat = (length / 2.0) / m_per_deg_lat
    ring = [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _property_center(db, pid: str) -> tuple[float | None, float | None]:
    """Centroid of the property boundary, used to prefill the modal."""
    doc = db.property.find_one({"project_id": pid}, {"geom": 1})
    center = centroid_lonlat((doc or {}).get("geom"))
    if not center:
        return None, None
    return round(center[0], 7), round(center[1], 7)


def _collect_sources(db, pid: str) -> list[dict]:
    """Flatten water_points + basins into one display-ready table."""
    rows: list[dict] = []

    for doc in db.water_points.find({"project_id": pid}, {"_id": 0}):
        coords = (doc.get("location") or {}).get("coordinates") or [None, None]
        stype = doc.get("source_type") or "well"
        rows.append({
            "collection": "water_points",
            "source_type": stype if stype in _SOURCE_COLLECTIONS else "well",
            "name": doc.get("name", ""),
            "lon": coords[0] if len(coords) > 0 else None,
            "lat": coords[1] if len(coords) > 1 else None,
            "elev": doc.get("elev_m"),
            "depth": doc.get("depth_m"),
            "length": doc.get("length_m"),
            "width": doc.get("width_m"),
            "discharge": doc.get("discharge_lps"),
            "notes": doc.get("notes", "") or "",
            "revision_id": doc.get("revision_id"),
            "updated_at": doc.get("updated_at"),
        })

    for doc in db.basins.find({"project_id": pid}, {"_id": 0}):
        center = centroid_lonlat(doc.get("geom"))
        rows.append({
            "collection": "basins",
            "source_type": "basin",
            "name": doc.get("name", ""),
            "lon": round(center[0], 7) if center else None,
            "lat": round(center[1], 7) if center else None,
            "elev": doc.get("elev_m"),
            "depth": doc.get("depth_m"),
            "length": doc.get("length_m"),
            "width": doc.get("width_m"),
            "discharge": doc.get("discharge_lps"),
            "notes": doc.get("notes", "") or "",
            "revision_id": doc.get("revision_id"),
            "updated_at": doc.get("updated_at"),
        })

    order = {t: i for i, t in enumerate(SOURCE_TYPE_ORDER)}
    rows.sort(key=lambda r: (order.get(r["source_type"], 99), r["name"].lower()))
    return rows


def _first_error(exc: ValidationError) -> str:
    """Flatten a Pydantic error into a short, user-facing message."""
    errors = exc.errors()
    if not errors:
        return str(exc)
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()) if p != "__root__")
    msg = first.get("msg", "invalid value")
    msg = msg.removeprefix("Value error, ")
    return f"{loc}: {msg}" if loc else msg


@bp.route("/project/water", methods=["GET", "POST"])
def water():
    pid = session.get("project_id", "")
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action", "")

        if action in ("save_source", "add_well", "add_basin"):
            payload = request.form.to_dict(flat=True)
            if not payload.get("source_type"):          # legacy add_* forms
                payload["source_type"] = ("basin" if action == "add_basin"
                                          else "well")
            try:
                data = WaterSourceCreate(**payload)
            except ValidationError as exc:
                flash(_first_error(exc), "error")
                return redirect(url_for("project.water"))

            coll = _SOURCE_COLLECTIONS[data.source_type]
            now = datetime.now(timezone.utc)
            doc = {
                "project_id": pid,
                "name": data.name,
                "source_type": data.source_type,
                "elev_m": data.elev,
                "depth_m": data.depth,
                "length_m": data.length or None,
                "width_m": data.width or None,
                "discharge_lps": data.discharge or None,
                "notes": data.notes,
                "updated_at": now,
            }

            if data.source_type == BASIN_SOURCE_TYPE:
                doc["geom"] = _basin_polygon(data.lon, data.lat,
                                             data.length, data.width)
            else:
                doc["location"] = kml_io.to_geojson_point(data.lon, data.lat)

            # rename / re-type: drop the row we are replacing
            orig_name = (request.form.get("orig_name") or "").strip()
            orig_type = (request.form.get("orig_type") or "").strip()
            if orig_name and (orig_name != data.name or orig_type != data.source_type):
                old_coll = _SOURCE_COLLECTIONS.get(orig_type, coll)
                repository.delete_where(old_coll,
                                        {"project_id": pid, "name": orig_name})

            revision = repository.new_revision(
                pid, "02_well_basin",
                f"{SOURCE_TYPE_LABELS[data.source_type][0]} {data.name}",
            )
            doc["revision_id"] = revision
            repository.upsert(coll, {"project_id": pid, "name": data.name}, doc)
            flash(f"{SOURCE_TYPE_LABELS[data.source_type][0]} {data.name} "
                  f"saved (revision {revision}).", "success")
            return redirect(url_for("project.water"))

        if action == "delete_source":
            coll = ("basins" if request.form.get("collection") == "basins"
                    else "water_points")
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Nothing to remove.", "error")
                return redirect(url_for("project.water"))

            removed = repository.delete_where(coll,
                                              {"project_id": pid, "name": name})
            revision = repository.new_revision(pid, "02_well_basin",
                                               f"Remove {name}")
            current_app.logger.info("Removed %s/%s from %s (rev %s)",
                                    coll, name, pid, revision)
            flash((f"{name} removed (revision {revision})." if removed
                   else f"{name} was already gone."),
                  "success" if removed else "warning")

        return redirect(url_for("project.water"))

    default_lon, default_lat = _property_center(db, pid)
    return render_template(
        "project/water.html",
        sources=_collect_sources(db, pid),
        source_types=[
            {"value": t,
             "label_en": SOURCE_TYPE_LABELS[t][0],
             "label_ar": SOURCE_TYPE_LABELS[t][1],
             "icon": SOURCE_TYPE_ICONS[t],
             "badge": SOURCE_TYPE_BADGES[t]}
            for t in SOURCE_TYPE_ORDER
        ],
        default_lon=default_lon,
        default_lat=default_lat,
    )


# ---------------------------------------------------------------- settings
@bp.route("/project/settings", methods=["GET", "POST"])
def settings():
    pid = session.get("project_id", "")

    if request.method == "POST":
        action = request.form.get("action")
        if action == "wipe_rows_trees":
            repository.clear_step(pid, "rows")
            repository.clear_step(pid, "trees")
            flash("Wiped rows and trees.", "success")
        elif action == "wipe_all":
            for coll in ("property", "water_points", "basins", "sectors",
                         "zones", "valves", "pipes", "rows", "trees",
                         "driplines", "manifolds", "bom_items", "revisions"):
                repository.clear_step(pid, coll)
            flash(f"Wiped project {pid}.", "success")
        return redirect(url_for("project.settings"))

    from db.connection import ping
    summary = queries.project_summary(pid)
    revisions = queries.get_revisions(pid)
    return render_template("project/settings.html",
                           mongo_ok=ping(),
                           summary=summary,
                           revisions=revisions)


# ---------------------------------------------------------------- design checks
@bp.route("/project/checks")
def checks():
    """Hydraulic sanity report: demand, pipe velocities, capacity, losses."""
    pid = session.get("project_id", "")
    db = get_db()

    pipes = list(db.pipes.find({"project_id": pid}, {"_id": 0}))
    driplines = list(db.driplines.find({"project_id": pid}, {"_id": 0}))
    sources = list(db.water_points.find({"project_id": pid}, {"_id": 0}))
    irrigated_area = sum(float(z.get("area_m2") or 0.0)
                         for z in db.zones.find({"project_id": pid},
                                                {"_id": 0, "area_m2": 1}))

    report = hydraulics.evaluate(pipes, driplines, sources, irrigated_area)
    return render_template("project/checks.html",
                           report=report,
                           assumptions=Config.HYDRAULICS)
                           
@bp.route("/set_project", methods=["POST"])
def set_project():
    pid = request.form.get("project_id", "").strip()
    if pid:
        session["project_id"] = pid
    return redirect(request.referrer or url_for("project.index"))

@bp.route("/close")
def close_project():
    session.pop("project_id", None)
    flash("Project closed. / تم إغلاق المشروع.", "success")
    return redirect(url_for("home.home"))