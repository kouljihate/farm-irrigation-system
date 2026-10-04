"""Read KML/KMZ into Python dicts; write Python dicts out to KML."""
from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

KML_NS = "http://www.opengis.net/kml/2.2"


def qn(tag: str) -> str:
    return f"{{{KML_NS}}}{tag}"


def read_kml(path: str) -> dict:
    """Return dict {placemark_name: {'kind': ..., 'coords': [...]}}.

    Accepts both plain .kml XML files and .kmz ZIP archives containing KML.
    """
    path = Path(path)
    if path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(path, "r") as archive:
            kml_names = [
                name for name in archive.namelist()
                if name.lower().endswith(".kml") and not name.endswith("/")
            ]
            if not kml_names:
                raise ValueError("KMZ archive does not contain a KML file.")
            kml_name = next(
                (name for name in kml_names if name.lower() == "doc.kml"),
                kml_names[0],
            )
            root = etree.fromstring(archive.read(kml_name))
    else:
        root = etree.parse(str(path)).getroot()

    out: dict = {}
    for pm in root.iter(qn("Placemark")):
        n = pm.find(qn("name"))
        if n is None or not n.text:
            continue
        name = n.text.strip()

        poly = pm.find(f".//{qn('Polygon')}/{qn('outerBoundaryIs')}"
                       f"/{qn('LinearRing')}/{qn('coordinates')}")
        line = pm.find(f".//{qn('LineString')}/{qn('coordinates')}")
        point = pm.find(f".//{qn('Point')}/{qn('coordinates')}")

        if poly is not None and poly.text:
            coords = _parse_coords(poly.text)
            out[name] = {"kind": "polygon", "coords": coords}
        elif line is not None and line.text:
            coords = _parse_coords(line.text)
            out[name] = {"kind": "line", "coords": coords}
        elif point is not None and point.text:
            coords = _parse_coords(point.text)
            out[name] = {"kind": "point", "coords": coords}
    return out


def _parse_coords(text: str) -> list[tuple[float, float, float]]:
    coords = []
    for tok in text.split():
        parts = tok.split(",")
        if len(parts) >= 2:
            lon = float(parts[0])
            lat = float(parts[1])
            ele = float(parts[2]) if len(parts) > 2 else 0.0
            coords.append((lon, lat, ele))
    return coords


def to_geojson_polygon(coords_ll: list[tuple[float, float, float]]) -> dict:
    ring = [[c[0], c[1]] for c in coords_ll]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def to_geojson_linestring(coords_ll: list[tuple[float, float, float]]) -> dict:
    return {"type": "LineString", "coordinates": [[c[0], c[1]] for c in coords_ll]}


def to_geojson_point(lon: float, lat: float) -> dict:
    return {"type": "Point", "coordinates": [lon, lat]}


def from_geojson_polygon(geom: dict) -> list[tuple[float, float, float]]:
    ring = geom["coordinates"][0]
    return [(x, y, 0.0) for x, y in ring]


def from_geojson_linestring(geom: dict) -> list[tuple[float, float, float]]:
    return [(x, y, 0.0) for x, y in geom["coordinates"]]