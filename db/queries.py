"""Read operations for the workbench."""
from __future__ import annotations

from typing import Any

from .connection import get_db


def list_projects() -> list[dict]:
    return list(get_db().projects.find({}, {"_id": 0}))


def project_summary(project_id: str) -> dict:
    db = get_db()
    return {
        "sectors": db.sectors.count_documents({"project_id": project_id}),
        "zones": db.zones.count_documents({"project_id": project_id}),
        "valves": db.valves.count_documents({"project_id": project_id}),
        "pipes": db.pipes.count_documents({"project_id": project_id}),
        "rows": db.rows.count_documents({"project_id": project_id}),
        "trees": db.trees.count_documents({"project_id": project_id}),
        "driplines": db.driplines.count_documents({"project_id": project_id}),
        "revisions": db.revisions.count_documents({"project_id": project_id}),
    }


def get_sectors(project_id: str) -> list[dict]:
    return list(get_db().sectors.find({"project_id": project_id}, {"_id": 0}))


def get_zones(project_id: str, sector_code: str | None = None) -> list[dict]:
    q: dict[str, Any] = {"project_id": project_id}
    if sector_code:
        q["sector_code"] = sector_code
    return list(get_db().zones.find(q, {"_id": 0}))


def get_valves(project_id: str, valve_type: str | None = None) -> list[dict]:
    q: dict[str, Any] = {"project_id": project_id}
    if valve_type:
        q["valve_type"] = valve_type
    return list(get_db().valves.find(q, {"_id": 0}))


def get_pipes(project_id: str, pipe_type: str | None = None) -> list[dict]:
    q: dict[str, Any] = {"project_id": project_id}
    if pipe_type:
        q["pipe_type"] = pipe_type
    return list(get_db().pipes.find(q, {"_id": 0}))


def get_rows(project_id: str, zone_name: str | None = None) -> list[dict]:
    q: dict[str, Any] = {"project_id": project_id}
    if zone_name:
        q["zone_name"] = zone_name
    return list(get_db().rows.find(q, {"_id": 0}))


def get_trees(project_id: str, zone_name: str | None = None) -> list[dict]:
    q: dict[str, Any] = {"project_id": project_id}
    if zone_name:
        q["zone_name"] = zone_name
    return list(get_db().trees.find(q, {"_id": 0}))


def get_revisions(project_id: str) -> list[dict]:
    return list(get_db().revisions.find(
        {"project_id": project_id},
        {"_id": 0},
    ).sort("revision_id", 1))


def bom_summary(project_id: str) -> list[dict]:
    pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {
            "_id": "$category",
            "items": {"$sum": 1},
            "total": {"$sum": "$total_price"},
        }},
        {"$sort": {"_id": 1}},
    ]
    return list(get_db().bom_items.aggregate(pipeline))