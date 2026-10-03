"""Pipe routing helpers."""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points


def direct_or_detour(poly, inner, start, end) -> list[tuple[float, float]]:
    if poly.contains(LineString([start, end])):
        return [start, end]

    boundary = inner.exterior
    p_start = Point(start)
    p_end = Point(end)
    near_start = nearest_points(p_start, boundary)[1]
    near_end = nearest_points(p_end, boundary)[1]
    coords = list(boundary.coords)

    def nearest_idx(pt):
        best_d, best_i = 1e18, 0
        for i, c in enumerate(coords):
            d = (c[0] - pt.x) ** 2 + (c[1] - pt.y) ** 2
            if d < best_d:
                best_d, best_i = d, i
        return best_i

    i0, i1 = nearest_idx(near_start), nearest_idx(near_end)
    if i0 <= i1:
        path = coords[i0:i1 + 1]
    else:
        path = coords[i0:] + coords[:i1 + 1]

    full = [start, (near_start.x, near_start.y)]
    full.extend(path)
    full.append((near_end.x, near_end.y))
    full.append(end)

    clean = [full[0]]
    for p in full[1:]:
        if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 0.5:
            clean.append(p)
    return clean