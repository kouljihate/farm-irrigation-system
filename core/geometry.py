"""Shapely helpers used across the workbench."""
from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.validation import make_valid


def polygon_from_geojson(geom: dict) -> Polygon:
    return shape(geom)


def geojson_from_polygon(poly: Polygon) -> dict:
    return mapping(poly)


def clean_polygon(poly: Polygon) -> Polygon:
    if poly.is_valid:
        return poly
    fixed = make_valid(poly)
    if fixed.geom_type == "MultiPolygon":
        fixed = max(fixed.geoms, key=lambda g: g.area)
    return fixed


def fall_direction(poly: Polygon, elevations: list[float]) -> tuple[float, float]:
    """Return (ux, uy) unit vector pointing downhill."""
    import numpy as np
    coords = list(poly.exterior.coords)[:-1]
    xs = np.array([c[0] for c in coords])
    ys = np.array([c[1] for c in coords])
    zs = np.array(elevations[:len(coords)])
    cx, cy = xs.mean(), ys.mean()
    A = np.column_stack([xs - cx, ys - cy, np.ones_like(xs)])
    coef, *_ = np.linalg.lstsq(A, zs, rcond=None)
    gx, gy = -coef[0], -coef[1]
    n = math.hypot(gx, gy)
    if n < 1e-9:
        return (1.0, 0.0)
    return (gx / n, gy / n)


def inward_offset(poly: Polygon, meters: float) -> Polygon:
    inner = poly.buffer(-meters, join_style=2)
    if inner.is_empty:
        raise ValueError(f"Offset {meters} m is too large for polygon")
    if inner.geom_type == "MultiPolygon":
        inner = max(inner.geoms, key=lambda g: g.area)
    return inner


def line_inside(poly: Polygon, p1: tuple[float, float], p2: tuple[float, float]) -> bool:
    return poly.contains(LineString([p1, p2]))


# ------------------------------------------------------- GeoJSON helpers
def first_ring(geom: dict | None) -> list:
    """Exterior ring ``[[lon, lat], ...]`` of a (Multi)Polygon, else ``[]``."""
    if not geom:
        return []
    coords = geom.get("coordinates") or []
    if geom.get("type") == "MultiPolygon":
        coords = coords[0] if coords else []
    if not coords:
        return []
    first = coords[0]
    if first and isinstance(first[0], (list, tuple)):
        return list(first)
    return list(coords)


def centroid_lonlat(geom: dict | None) -> tuple[float, float] | None:
    """Average lon/lat of a (Multi)Polygon exterior ring, or ``None``."""
    ring = first_ring(geom)
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts))


def geojson_polygon_area_m2(geom: dict | None) -> float:
    """Approximate area (m²) of a GeoJSON (Multi)Polygon using a local metric."""
    if not geom:
        return 0.0
    try:
        poly = shape(geom)
    except Exception:
        return 0.0
    if poly.is_empty:
        return 0.0
    lat = math.radians(poly.centroid.y)
    m_per_deg_lat = (111132.92 - 559.82 * math.cos(2 * lat)
                     + 1.175 * math.cos(4 * lat)
                     - 0.0023 * math.cos(6 * lat))
    m_per_deg_lon = (111412.84 * math.cos(lat)
                     - 93.5 * math.cos(3 * lat)
                     + 0.118 * math.cos(5 * lat))
    return float(poly.area * m_per_deg_lat * m_per_deg_lon)


def ring_area_m2(ring: list) -> float:
    """Approximate area (m²) of a lon/lat ring ``[[lon, lat], ...]``."""
    if not ring:
        return 0.0
    return geojson_polygon_area_m2({"type": "Polygon", "coordinates": [ring]})


def local_projection(ring: list):
    """Return ``(to_local, to_lonlat)`` for an equirectangular projection
    centred on ``ring``. Coordinates are metres relative to the centre."""
    lon0 = sum(p[0] for p in ring) / len(ring)
    lat0 = sum(p[1] for p in ring) / len(ring)
    R = 6371000.0
    coslat = math.cos(math.radians(lat0))

    def to_local(lon, lat):
        return (math.radians(lon - lon0) * R * coslat,
                math.radians(lat - lat0) * R)

    def to_lonlat(x, y):
        return (lon0 + math.degrees(x / (R * coslat)),
                lat0 + math.degrees(y / R))

    return to_local, to_lonlat


def clean_linestring(coords: list) -> list:
    """Return ``[[lon, lat], ...]`` with consecutive duplicate vertices removed."""
    out: list = []
    for p in coords:
        if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append([p[0], p[1]])
    return out


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def polyline_length_m(coords: list) -> float:
    """Total great-circle length (m) of ``[[lon, lat], ...]``."""
    return sum(
        haversine_m(coords[i][0], coords[i][1],
                    coords[i + 1][0], coords[i + 1][1])
        for i in range(len(coords) - 1)
    )