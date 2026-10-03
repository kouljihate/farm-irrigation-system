"""Field section: Rows, Trees, Driplines."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)
from shapely.geometry import Polygon

from core.driplines import dripline_from_row
from core.geometry import (
    clean_linestring, clean_polygon, fall_direction, first_ring,
    local_projection, polyline_length_m,
)
from core.rows import build_rows
from core.trees import place_trees_on_row
from core.validation import validate_form, RowBuild, TreePlace, DriplineBuild
from db import queries, repository
from db.connection import get_db


bp = Blueprint("field", __name__, url_prefix="/field")


# ---------------------------------------------------------------- rows
@bp.route("/rows", methods=["GET", "POST"])
@validate_form(RowBuild)
def rows(data: RowBuild | None = None):
    pid = session.get("project_id", "")

    if request.method == "POST":
        assert data is not None
        count = _build_rows(pid, data.spacing, data.offset)
        if count:
            flash(f"Built {count} rows.", "success")
        return redirect(url_for("field.rows"))

    rows_list = queries.get_rows(pid)
    return render_template("field/rows.html", rows=rows_list)


def _build_rows(project_id: str, spacing: float, offset: float) -> int:
    zones = queries.get_zones(project_id)
    if not zones:
        flash("No zones.", "error")
        return 0

    revision = repository.new_revision(project_id, "08_rows", "Build rows")
    repository.clear_step(project_id, "rows")

    now = datetime.now(timezone.utc)
    total = 0

    for z in zones:
        ring = first_ring(z.get("geom"))
        if not ring:
            continue
        to_local, to_lonlat = local_projection(ring)
        pts_xy = [to_local(p[0], p[1]) for p in ring]
        poly = clean_polygon(Polygon(pts_xy))
        ux, uy = fall_direction(poly, [0.0] * len(pts_xy))

        for (ri, seg) in build_rows(poly, ux, uy, spacing, offset):
            seg_ll = clean_linestring([list(to_lonlat(x, y)) for x, y in seg])
            if len(seg_ll) < 2:
                continue
            name = f"{z['name']}-R{ri+1:02d}"
            repository.upsert("rows",
                {"project_id": project_id, "name": name},
                {"project_id": project_id, "name": name,
                 "zone_name": z["name"], "row_index": ri + 1,
                 "geom": {"type": "LineString",
                          "coordinates": [list(p) for p in seg_ll]},
                 "length_m": polyline_length_m(seg_ll),
                 "row_direction_deg": math.degrees(math.atan2(uy, ux)),
                 "revision_id": revision,
                 "created_at": now, "updated_at": now})
            total += 1

    current_app.logger.info("Built %d rows for %s", total, project_id)
    return total


# ---------------------------------------------------------------- trees
@bp.route("/trees", methods=["GET", "POST"])
@validate_form(TreePlace)
def trees(data: TreePlace | None = None):
    pid = session.get("project_id", "")

    if request.method == "POST":
        assert data is not None
        count = _place_trees(pid, data.spacing, data.fig_pct)
        if count:
            flash(f"Placed {count} trees.", "success")
        return redirect(url_for("field.trees"))

    trees_list = queries.get_trees(pid)
    return render_template("field/trees.html", trees=trees_list)


def _place_trees(project_id: str, spacing: float, fig_pct: int) -> int:
    rows_list = queries.get_rows(project_id)
    if not rows_list:
        flash("No rows.", "error")
        return 0

    revision = repository.new_revision(project_id, "09_trees", "Place trees")
    repository.clear_step(project_id, "trees")

    now = datetime.now(timezone.utc)
    total = 0
    fig_counter = 0

    for r in rows_list:
        line = (r.get("geom") or {}).get("coordinates") or []
        if len(line) < 2:
            continue
        start = (line[0][0], line[0][1])
        end = (line[-1][0], line[-1][1])
        to_local, to_lonlat = local_projection([start, end])
        pts = place_trees_on_row(to_local(*start), to_local(*end),
                                 spacing, center=True)
        for i, (x, y) in enumerate(pts):
            lon, lat = to_lonlat(x, y)
            fig_counter += 1
            species = "fig" if (fig_counter % 100) < fig_pct else "olive"
            name = f"T {r['name']}-T{i+1:02d}"
            repository.upsert("trees",
                {"project_id": project_id, "name": name},
                {"project_id": project_id, "name": name,
                 "row_name": r["name"], "zone_name": r["zone_name"],
                 "tree_index": i + 1,
                 "location": {"type": "Point", "coordinates": [lon, lat]},
                 "species": species, "revision_id": revision,
                 "created_at": now, "updated_at": now})
            total += 1

    current_app.logger.info("Placed %d trees for %s", total, project_id)
    return total


# ---------------------------------------------------------------- driplines
@bp.route("/driplines", methods=["GET", "POST"])
@validate_form(DriplineBuild)
def driplines(data: DriplineBuild | None = None):
    pid = session.get("project_id", "")

    if request.method == "POST":
        assert data is not None
        count = _build_driplines(pid, data.emitter_spacing)
        if count:
            flash(f"Built {count} driplines.", "success")
        return redirect(url_for("field.driplines"))

    drips = list(get_db().driplines.find({"project_id": pid}, {"_id": 0}))
    return render_template("field/driplines.html", driplines=drips)


def _build_driplines(project_id: str, emitter_spacing: float) -> int:
    rows_list = queries.get_rows(project_id)
    if not rows_list:
        flash("No rows.", "error")
        return 0

    revision = repository.new_revision(project_id, "10_driplines",
                                       "Build driplines")
    repository.clear_step(project_id, "driplines")

    now = datetime.now(timezone.utc)
    total = 0
    for r in rows_list:
        line = (r.get("geom") or {}).get("coordinates") or []
        if len(line) < 2:
            continue
        start = (line[0][0], line[0][1])
        end = (line[-1][0], line[-1][1])
        to_local, to_lonlat = local_projection([start, end])
        dl = dripline_from_row(to_local(*start), to_local(*end),
                               emitter_spacing)
        geom_ll = clean_linestring(
            [list(to_lonlat(x, y)) for x, y in dl["geometry"]])
        if len(geom_ll) < 2:
            continue
        name = f"DL {r['name']}"
        repository.upsert("driplines",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name,
             "row_name": r["name"], "zone_name": r["zone_name"],
             "geom": {"type": "LineString", "coordinates": geom_ll},
             "length_m": dl["length_m"],
             "emitter_count": dl["emitter_count"],
             "revision_id": revision,
             "created_at": now, "updated_at": now})
        total += 1

    current_app.logger.info("Built %d driplines for %s", total, project_id)
    return total