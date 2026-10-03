"""Export section: BOM and file exports (KML, DXF, GeoJSON, CSV)."""
from __future__ import annotations

import csv
import io
import json
import math
import os
from datetime import datetime

from flask import (
    Blueprint, flash, redirect, render_template, request,
    send_file, session, url_for,
)
from lxml import etree

from core.bom import compute_bom
from core.geometry import clean_linestring, first_ring
from db import queries
from db.connection import get_db


bp = Blueprint("export", __name__, url_prefix="/export")


# ---------------------------------------------------------------- helpers
def _ring(doc, field: str = "geom") -> list:
    """Exterior ring of a (Multi)Polygon, or ``[]`` when absent/invalid."""
    return first_ring(doc.get(field))


def _point(doc, field: str = "location"):
    """``(lon, lat)`` of a Point geometry, or ``None`` when absent."""
    coords = (doc.get(field) or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    return coords[0], coords[1]


def _line(doc, field: str = "geom") -> list:
    """LineString coordinates (de-duplicated), or ``[]`` when unusable."""
    return clean_linestring((doc.get(field) or {}).get("coordinates") or [])


# ---------------------------------------------------------------- BOM
@bp.route("/bom", methods=["GET", "POST"])
def bom():
    pid = session.get("project_id", "")
    rows = compute_bom(pid)

    if request.method == "POST":
        flash("BOM recomputed from current data.", "success")
        return redirect(url_for("export.bom"))

    total = sum(r["quantity"] * r["unit_price"] for r in rows)
    return render_template("export/bom.html", rows=rows, total=total)


# ---------------------------------------------------------------- KML
@bp.route("/kml")
def kml():
    pid = session.get("project_id", "")
    path = _write_kml(pid)
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))


def _write_kml(project_id: str) -> str:
    from config import Config
    db = get_db()

    Config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = Config.EXPORT_DIR / f"{project_id}_{datetime.now():%Y%m%d_%H%M%S}.kml"

    kml = etree.Element("kml", nsmap={None: "http://www.opengis.net/kml/2.2"})
    doc = etree.SubElement(kml, "Document")
    etree.SubElement(doc, "name").text = project_id

    def add_polygon(name, ring):
        if len(ring) < 3:
            return
        pm = etree.SubElement(doc, "Placemark")
        etree.SubElement(pm, "name").text = name
        poly = etree.SubElement(pm, "Polygon")
        obi = etree.SubElement(poly, "outerBoundaryIs")
        lr = etree.SubElement(obi, "LinearRing")
        cs = " ".join(f"{x},{y},0" for x, y in ring)
        etree.SubElement(lr, "coordinates").text = cs

    def add_line(name, coords):
        if len(coords) < 2:
            return
        pm = etree.SubElement(doc, "Placemark")
        etree.SubElement(pm, "name").text = name
        ls = etree.SubElement(pm, "LineString")
        etree.SubElement(ls, "tessellate").text = "1"
        etree.SubElement(ls, "altitudeMode").text = "clampToGround"
        cs = " ".join(f"{x},{y},0" for x, y in coords)
        etree.SubElement(ls, "coordinates").text = cs

    def add_point(name, lon, lat):
        if lon is None or lat is None:
            return
        pm = etree.SubElement(doc, "Placemark")
        etree.SubElement(pm, "name").text = name
        p = etree.SubElement(pm, "Point")
        etree.SubElement(p, "coordinates").text = f"{lon},{lat},0"

    prop = db.property.find_one({"project_id": project_id})
    if prop:
        add_polygon("P1", _ring(prop))

    for s in queries.get_sectors(project_id):
        add_polygon(s["name"], _ring(s))

    for z in queries.get_zones(project_id):
        add_polygon(z["name"], _ring(z))

    for v in queries.get_valves(project_id):
        add_point(v["name"], *_point(v))

    for p in queries.get_pipes(project_id):
        add_line(p["name"], _line(p))

    for r in queries.get_rows(project_id):
        add_line(r["name"], _line(r))

    for t in queries.get_trees(project_id):
        add_point(t["name"], *_point(t))

    etree.ElementTree(kml).write(
        str(out), xml_declaration=True, encoding="UTF-8", pretty_print=True
    )
    return str(out)


# ---------------------------------------------------------------- DXF
@bp.route("/dxf")
def dxf():
    pid = session.get("project_id", "")
    path = _write_dxf(pid)
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))


def _write_dxf(project_id: str) -> str:
    """Generate a DXF with one layer per entity type."""
    from config import Config
    import ezdxf

    db = get_db()
    Config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = Config.EXPORT_DIR / f"{project_id}_{datetime.now():%Y%m%d_%H%M%S}.dxf"

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    for lname, color in [
        ("property", 7),
        ("sectors", 4),
        ("zones", 3),
        ("valves", 1),
        ("pipes", 5),
        ("rows", 2),
        ("trees", 6),
    ]:
        doc.layers.add(lname, color=color)

    prop = db.property.find_one({"project_id": project_id})
    ring = _ring(prop) if prop else []

    if ring:
        lon0 = sum(p[0] for p in ring) / len(ring)
        lat0 = sum(p[1] for p in ring) / len(ring)
        R = 6371000.0

        def to_m(lon, lat):
            x = math.radians(lon - lon0) * R * math.cos(math.radians(lat0))
            y = math.radians(lat - lat0) * R
            return x, y
    else:
        def to_m(lon, lat):
            return lon, lat

    def add_polyline(layer, coords, closed=False):
        coords = clean_linestring(coords or [])
        if len(coords) < 2:
            return
        pts = [to_m(x, y) for x, y in coords]
        if closed and pts[0] != pts[-1]:
            pts.append(pts[0])
        msp.add_lwpolyline(pts, dxfattribs={"layer": layer})

    def add_point(layer, lon, lat):
        if lon is None or lat is None:
            return
        x, y = to_m(lon, lat)
        msp.add_point((x, y), dxfattribs={"layer": layer})

    if prop:
        add_polyline("property", _ring(prop), closed=True)

    for s in queries.get_sectors(project_id):
        add_polyline("sectors", _ring(s), closed=True)

    for z in queries.get_zones(project_id):
        add_polyline("zones", _ring(z), closed=True)

    for v in queries.get_valves(project_id):
        add_point("valves", *_point(v))

    for p in queries.get_pipes(project_id):
        add_polyline("pipes", _line(p))

    for r in queries.get_rows(project_id):
        add_polyline("rows", _line(r))

    for t in queries.get_trees(project_id):
        add_point("trees", *_point(t))

    doc.saveas(str(out))
    return str(out)


# ---------------------------------------------------------------- GeoJSON
@bp.route("/geojson")
def geojson():
    pid = session.get("project_id", "")
    path = _write_geojson(pid)
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))


def _write_geojson(project_id: str) -> str:
    from config import Config
    db = get_db()

    Config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = Config.EXPORT_DIR / f"{project_id}_{datetime.now():%Y%m%d_%H%M%S}.geojson"

    features = []
    for coll, gfield in [
        ("property", "geom"),
        ("sectors", "geom"),
        ("zones", "geom"),
        ("pipes", "geom"),
        ("rows", "geom"),
        ("valves", "location"),
        ("trees", "location"),
        ("driplines", "geom"),
        ("manifolds", "geom"),
    ]:
        for d in db[coll].find({"project_id": project_id}):
            geom = d.get(gfield)
            if not geom:
                continue
            features.append({
                "type": "Feature",
                "properties": {"name": d.get("name"), "collection": coll},
                "geometry": geom,
            })

    with open(out, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features},
                  f, indent=2)
    return str(out)


# ---------------------------------------------------------------- CSV
@bp.route("/trees.csv")
def trees_csv():
    pid = session.get("project_id", "")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "zone", "row", "species", "lon", "lat"])
    for t in queries.get_trees(pid):
        pt = _point(t)
        if not pt:
            continue
        w.writerow([t["name"], t["zone_name"], t["row_name"],
                    t.get("species", ""), pt[0], pt[1]])

    data = buf.getvalue().encode("utf-8")
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=f"{pid}_trees.csv",
        mimetype="text/csv",
    )