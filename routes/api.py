"""JSON API for the Leaflet map."""
from __future__ import annotations

from bson import ObjectId
from flask import Blueprint, jsonify, request, session
from db import queries
from db.connection import get_db


bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.route("/summary")
def summary():
    pid = session.get("project_id", "")
    if not pid:
        return jsonify(queries.project_summary(""))
    return jsonify(queries.project_summary(pid))


@bp.route("/geojson")
def geojson():
    """Return the full project as a GeoJSON FeatureCollection."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"type": "FeatureCollection", "features": []})
    db = get_db()
    features = []
    for coll, gfield in [("property", "geom"), ("basins", "geom"), ("water_points", "location"),
                         ("sectors", "geom"), ("zones", "geom"), ("pipes", "geom"),
                         ("rows", "geom"), ("valves", "location"),
                         ("trees", "location"), ("driplines", "geom"),
                         ("manifolds", "geom")]:
        for d in db[coll].find({"project_id": pid}):
            geom = d.get(gfield)
            if not geom:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "name": d.get("name"),
                    "id": str(d.get("_id")),
                    "collection": coll,
                    "diameter_mm": d.get("diameter_mm"),
                    "species": d.get("species"),
                    "elev_m": d.get("elev_m"),
                    "depth_m": d.get("depth_m"),
                    "sector_code": d.get("sector_code"),
                    "zone_index": d.get("zone_index"),
                    "area_m2": d.get("area_m2"),
                },
                "geometry": geom,
            })
    return jsonify({"type": "FeatureCollection", "features": features})


def _ext_rings(geom: dict | None):
    """Yield exterior rings ([[x, y], ...]) from a Polygon/MultiPolygon."""
    if not geom:
        return
    coords = geom.get("coordinates") or []
    gtype = geom.get("type")
    if gtype == "Polygon":
        if coords:
            yield coords[0]
    elif gtype == "MultiPolygon":
        for poly in coords:
            if poly:
                yield poly[0]


@bp.route("/bounds")
def bounds():
    """Return overall bounding box for map auto-fit (robust to MultiPolygon)."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"bounds": None})
    db = get_db()
    lons: list[float] = []
    lats: list[float] = []
    for prop in db.property.find({"project_id": pid}):
        for ring in _ext_rings(prop.get("geom")):
            for pt in ring:
                lons.append(pt[0])
                lats.append(pt[1])
    if not lons:
        return jsonify({"bounds": None})
    return jsonify({
        "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]]
    })

@bp.route("/zones")
def zones():
    """Return only zones as a FeatureCollection (used after zone rebuild)."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"type": "FeatureCollection", "features": []})

    db = get_db()
    features = []
    for d in db.zones.find({"project_id": pid}):
        geom = d.get("geom")
        if not geom:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "name":       d.get("name"),
                "sector":     d.get("sector_code"),
                "zone_index": d.get("zone_index"),
                "area_m2":    d.get("area_m2", 0),
                "collection": "zones",
            },
            "geometry": geom,
        })
    return jsonify({"type": "FeatureCollection", "features": features})

@bp.route("/geometry/<collection>/<object_id>", methods=["PUT"])
def update_geometry(collection: str, object_id: str):
    """Persist a Geoman-edited geometry for the current project."""
    pid = session.get("project_id", "")
    allowed = {"property", "basins", "water_points", "sectors", "zones", "pipes",
               "rows", "valves", "trees", "driplines", "manifolds"}
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400
    if collection not in allowed:
        return jsonify({"ok": False, "error": "unsupported geometry collection"}), 400
    payload = request.get_json(silent=True) or {}
    geometry = payload.get("geometry")
    if not isinstance(geometry, dict) or not geometry.get("type"):
        return jsonify({"ok": False, "error": "valid GeoJSON geometry is required"}), 400
    try:
        oid = ObjectId(object_id)
    except Exception:
        return jsonify({"ok": False, "error": "invalid geometry id"}), 400
    db = get_db()
    field = "location" if collection in {"water_points", "valves", "trees"} else "geom"
    result = db[collection].update_one(
        {"_id": oid, "project_id": pid},
        {"$set": {field: geometry}},
    )
    if result.matched_count != 1:
        return jsonify({"ok": False, "error": "geometry record not found"}), 404
    return jsonify({"ok": True, "collection": collection, "id": object_id})
