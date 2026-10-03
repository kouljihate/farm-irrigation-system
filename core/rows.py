"""Trace rows inside a zone, perpendicular to the fall line."""
from __future__ import annotations

import math

from shapely.geometry import Polygon, LineString


def build_rows(
    zone_poly: Polygon,
    fall_ux: float,
    fall_uy: float,
    spacing_m: float = 4.0,
    first_offset_m: float = 2.0,
) -> list[tuple[int, list[tuple[float, float]]]]:
    """
    Return list of (row_index, [start_xy, end_xy]).
    Rows are perpendicular to (fall_ux, fall_uy) and run along the contour.
    """
    theta = -math.pi / 2 - math.atan2(fall_uy, fall_ux)
    c, s = math.cos(theta), math.sin(theta)

    def rot(p):
        return (c * p[0] - s * p[1], s * p[0] + c * p[1])

    def rot_inv(p):
        return (c * p[0] + s * p[1], -s * p[0] + c * p[1])

    rot_poly = Polygon([rot(p) for p in zone_poly.exterior.coords])
    minx, miny, maxx, maxy = rot_poly.bounds

    rows: list[tuple[int, list[tuple[float, float]]]] = []
    ri = 0
    y = maxy - first_offset_m
    while y >= miny:
        line = LineString([(minx - 10, y), (maxx + 10, y)])
        inter = rot_poly.intersection(line)
        if not inter.is_empty:
            segs = []
            if inter.geom_type == "LineString":
                segs = [list(inter.coords)]
            elif inter.geom_type == "MultiLineString":
                segs = [list(g.coords) for g in inter.geoms]
            for seg in segs:
                if len(seg) >= 2:
                    x0 = min(p[0] for p in seg)
                    x1 = max(p[0] for p in seg)
                    rows.append((ri, [rot_inv((x0, y)), rot_inv((x1, y))]))
                    ri += 1
        y -= spacing_m
    return rows