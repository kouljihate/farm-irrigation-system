"""Deterministic geometry planning for Smart Create / Smart Split.

The service chooses a geometry strategy from project data, while polygon
construction remains deterministic and testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Polygon

from .geometry import clean_polygon, geojson_polygon_area_m2, first_ring


@dataclass(frozen=True)
class SmartSectorPlan:
    number_of_sectors: int
    target_area_m2: float
    strategy: str
    water_priority: bool
    elevation_used: bool


def _local_projection(ring):
    lon0 = sum(p[0] for p in ring) / len(ring)
    lat0 = sum(p[1] for p in ring) / len(ring)
    radius = 6371000.0
    coslat = math.cos(math.radians(lat0))

    def to_xy(lon, lat):
        return (math.radians(lon - lon0) * radius * coslat,
                math.radians(lat - lat0) * radius)

    def to_ll(x, y):
        return [lon0 + math.degrees(x / (radius * coslat)),
                lat0 + math.degrees(y / radius)]

    return to_xy, to_ll


def _direction_from_water(poly, water_points):
    if not water_points:
        return None
    c = poly.centroid
    nearest = min(
        water_points,
        key=lambda p: (p[0] - c.x) ** 2 + (p[1] - c.y) ** 2,
    )
    dx, dy = c.x - nearest[0], c.y - nearest[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-9 else None


def _principal_direction(poly):
    coords = list(poly.exterior.coords)[:-1]
    mx = sum(x for x, _ in coords) / len(coords)
    my = sum(y for _, y in coords) / len(coords)
    sxx = sum((x - mx) ** 2 for x, _ in coords)
    syy = sum((y - my) ** 2 for _, y in coords)
    sxy = sum((x - mx) * (y - my) for x, y in coords)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return math.cos(theta), math.sin(theta)


def _split_equal_area(poly, n_parts, direction):
    """Split into equal-area bands normal to the supplied direction."""
    ux, uy = direction
    n = math.hypot(ux, uy) or 1.0
    ux, uy = ux / n, uy / n
    tx, ty = -uy, ux
    minx, miny, maxx, maxy = poly.bounds
    extent = max(maxx - minx, maxy - miny) * 4 + 100.0

    def project(x, y):
        return x * ux + y * uy

    corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
    lo = min(project(x, y) for x, y in corners)
    hi = max(project(x, y) for x, y in corners)

    def band_polygon(a, b):
        return Polygon([
            (ux * a + tx * extent, uy * a + ty * extent),
            (ux * a - tx * extent, uy * a - ty * extent),
            (ux * b - tx * extent, uy * b - ty * extent),
            (ux * b + tx * extent, uy * b + ty * extent),
        ])

    cuts = []
    for k in range(1, n_parts):
        target = poly.area * k / n_parts
        left, right = lo, hi
        for _ in range(55):
            mid = (left + right) / 2
            if poly.intersection(band_polygon(lo - extent, mid)).area < target:
                left = mid
            else:
                right = mid
        cuts.append((left + right) / 2)

    edges = [lo - extent, *cuts, hi + extent]
    result = []
    for a, b in zip(edges[:-1], edges[1:]):
        part = poly.intersection(band_polygon(a, b))
        if part.is_empty:
            continue
        if part.geom_type == "MultiPolygon":
            part = max(part.geoms, key=lambda g: g.area)
        if part.geom_type == "Polygon" and part.area > 0:
            result.append(part)
    return result


def build_sector_plan(property_geom, water_points=None, target_area_m2=10000.0):
    """Build sectors from land boundary and optional water points."""
    ring = first_ring(property_geom)
    if len(ring) < 4:
        raise ValueError("land boundary has no usable polygon")

    to_xy, to_ll = _local_projection(ring)
    poly = clean_polygon(Polygon([to_xy(p[0], p[1]) for p in ring]))
    if poly.is_empty or poly.area <= 0:
        raise ValueError("land boundary has zero area")

    n = max(1, int(round(poly.area / target_area_m2)))
    n = min(n, 100)

    local_water = [to_xy(lon, lat) for lon, lat in (water_points or [])]
    direction = _direction_from_water(poly, local_water)
    water_priority = direction is not None
    if direction is None:
        direction = _principal_direction(poly)

    parts = _split_equal_area(poly, n, direction)
    if len(parts) != n:
        raise ValueError(f"smart split produced {len(parts)} sectors; expected {n}")

    parts.sort(key=lambda p: (p.centroid.y, p.centroid.x), reverse=True)
    output = []
    for idx, part in enumerate(parts, start=1):
        ring_ll = [to_ll(x, y) for x, y in part.exterior.coords]
        output.append({
            "code": f"S{idx}",
            "geom": {"type": "Polygon", "coordinates": [ring_ll]},
            "area_m2": geojson_polygon_area_m2(
                {"type": "Polygon", "coordinates": [ring_ll]}
            ),
        })

    return SmartSectorPlan(
        number_of_sectors=n,
        target_area_m2=target_area_m2,
        strategy=("water-aligned equal-area bands" if water_priority
                  else "principal-axis equal-area bands"),
        water_priority=water_priority,
        elevation_used=False,
    ), output
