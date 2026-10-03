"""Ensure MongoDB collections and indexes exist."""
from __future__ import annotations

from pymongo import ASCENDING, GEOSPHERE, IndexModel

from .connection import get_db


COLLECTIONS = [
    "projects",
    "revisions",
    "property",
    "water_points",
    "basins",
    "sectors",
    "zones",
    "valves",
    "pipes",
    "rows",
    "trees",
    "driplines",
    "manifolds",
    "bom_items",
    "settings",
    "logs",
]


# Collections whose geometry/location field gets a 2dsphere index.
GEOMETRY_INDEXES = [
    ("property", "geom"),
    ("water_points", "location"),
    ("basins", "geom"),
    ("sectors", "geom"),
    ("zones", "geom"),
    ("valves", "location"),
    ("pipes", "geom"),
    ("rows", "geom"),
    ("trees", "location"),
    ("driplines", "geom"),
    ("manifolds", "geom"),
]


# Collections with a unique (project_id, <name>) business key.
BUSINESS_KEY_INDEXES = [
    ("sectors", "sector_code"),
    ("zones", "name"),
    ("valves", "name"),
    ("pipes", "name"),
    ("rows", "name"),
    ("trees", "name"),
    ("driplines", "name"),
    ("manifolds", "name"),
    ("property", "name"),
    ("water_points", "name"),
    ("basins", "name"),
]


def ensure_indexes() -> None:
    db = get_db()

    # make sure collections exist
    existing = set(db.list_collection_names())
    for name in COLLECTIONS:
        if name not in existing:
            try:
                db.create_collection(name)
            except Exception:
                pass

    project_idx = IndexModel([("project_id", ASCENDING)])
    created_idx = IndexModel([("created_at", ASCENDING)])

    # 2dsphere + common indexes on geometry collections
    for coll, field in GEOMETRY_INDEXES:
        try:
            db[coll].create_indexes([
                IndexModel([(field, GEOSPHERE)]),
                project_idx,
                created_idx,
            ])
        except Exception:
            pass

    # business-key indexes
    for coll, field in BUSINESS_KEY_INDEXES:
        try:
            db[coll].create_index(
                [("project_id", ASCENDING), (field, ASCENDING)], unique=True)
        except Exception:
            pass

    # revisions lookup indexes
    try:
        db["revisions"].create_index(
            [("project_id", ASCENDING), ("step", ASCENDING), ("created_at", ASCENDING)])
        db["revisions"].create_index(
            [("project_id", ASCENDING), ("revision_id", ASCENDING)], unique=True)
    except Exception:
        pass
