"""Build driplines from rows."""
from __future__ import annotations


def dripline_from_row(
    row_start: tuple[float, float],
    row_end: tuple[float, float],
    emitter_spacing_m: float = 0.5,
) -> dict:
    """
    Return a dict describing the dripline geometry and emitter count.
    Geometry is the same as the row (dripline runs along the row).
    """
    import math
    length = math.hypot(row_end[0] - row_start[0], row_end[1] - row_start[1])
    emitters = int(length / emitter_spacing_m) + 1
    return {
        "geometry": [row_start, row_end],
        "length_m": length,
        "emitter_count": emitters,
        "emitter_spacing_m": emitter_spacing_m,
    }