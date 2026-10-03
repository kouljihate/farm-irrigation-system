"""Place tree points along a row."""
from __future__ import annotations

import math


def place_trees_on_row(
    row_start: tuple[float, float],
    row_end: tuple[float, float],
    spacing_m: float,
    center: bool = True,
) -> list[tuple[float, float]]:
    x0, y0 = row_start
    x1, y1 = row_end
    length = math.hypot(x1 - x0, y1 - y0)
    if length < spacing_m * 0.5:
        return []

    n = int(length // spacing_m) + 1
    margin = (length - (n - 1) * spacing_m) / 2.0 if center else 0.0

    ux = (x1 - x0) / length
    uy = (y1 - y0) / length

    out = []
    for i in range(n):
        d = margin + i * spacing_m
        out.append((x0 + ux * d, y0 + uy * d))
    return out