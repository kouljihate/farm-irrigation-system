"""Bill of materials calculation from DB contents."""
from __future__ import annotations

from db import queries


def compute_bom(project_id: str) -> list[dict]:
    """
    Return a list of BOM rows aggregated from the project's geometry.
    Prices are placeholders; user edits them in the BOM tab.
    """
    pipes = queries.get_pipes(project_id)
    valves = queries.get_valves(project_id)
    trees = queries.get_trees(project_id)
    rows = queries.get_rows(project_id)

    pipe_len_by_type: dict[str, float] = {}
    for p in pipes:
        pipe_len_by_type.setdefault(p["pipe_type"], 0.0)
        pipe_len_by_type[p["pipe_type"]] += p.get("length_m", 0.0)

    valve_count_by_type: dict[str, int] = {}
    for v in valves:
        valve_count_by_type.setdefault(v["valve_type"], 0)
        valve_count_by_type[v["valve_type"]] += 1

    bom = []
    for ptype, length in pipe_len_by_type.items():
        bom.append({
            "category": "Pipe",
            "description": f"{ptype} pipe",
            "spec": "HDPE PE100 PN10",
            "unit": "m",
            "quantity": round(length, 1),
            "unit_price": 0.0,
            "total_price": 0.0,
        })
    for vtype, count in valve_count_by_type.items():
        bom.append({
            "category": "Valve",
            "description": f"{vtype} valve",
            "spec": "solenoid w/ manual override",
            "unit": "pcs",
            "quantity": count,
            "unit_price": 0.0,
            "total_price": 0.0,
        })
    bom.append({
        "category": "Tree",
        "description": "Trees planted",
        "spec": "Olive / Fig 80/20",
        "unit": "pcs",
        "quantity": len(trees),
        "unit_price": 0.0,
        "total_price": 0.0,
    })
    bom.append({
        "category": "Dripline",
        "description": "Dripline rows",
        "spec": "16 mm PC, 4 L/h emitters",
        "unit": "row",
        "quantity": len(rows),
        "unit_price": 0.0,
        "total_price": 0.0,
    })
    return bom