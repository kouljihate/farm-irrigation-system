"""Write operations (insert, update, delete) for each entity."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .connection import get_db


def _now():
    return datetime.now(timezone.utc)


def new_revision(project_id: str, step: str, note: str = "") -> int:
    """Return a monotonically increasing revision number per project."""
    db = get_db()
    last = db.revisions.find_one(
        {"project_id": project_id},
        sort=[("revision_id", -1)],
    )
    next_id = (last["revision_id"] + 1) if last else 1
    db.revisions.insert_one({
        "project_id": project_id,
        "revision_id": next_id,
        "step": step,
        "note": note,
        "created_at": _now(),
    })
    return next_id


def upsert(coll_name: str, filter_doc: dict, doc: dict) -> None:
    db = get_db()
    db[coll_name].update_one(filter_doc, {"$set": doc}, upsert=True)


def insert_many(coll_name: str, docs: list[dict]) -> None:
    if docs:
        get_db()[coll_name].insert_many(docs)


def delete_where(coll_name: str, filter_doc: dict) -> int:
    return get_db()[coll_name].delete_many(filter_doc).deleted_count


def clear_step(project_id: str, coll_name: str) -> int:
    return delete_where(coll_name, {"project_id": project_id})


def create_project(project_id: str, name: str, description: str = "") -> None:
    db = get_db()
    db.projects.update_one(
        {"project_id": project_id},
        {"$set": {
            "project_id": project_id,
            "name": name,
            "description": description,
            "updated_at": _now(),
        }, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )