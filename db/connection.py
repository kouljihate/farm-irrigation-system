"""MongoDB connection helpers for the Farm Irrigation Workbench (Flask)."""
from __future__ import annotations

from typing import Any

from flask import Flask, current_app
from pymongo import MongoClient
from pymongo.database import Database


_client: MongoClient | None = None


def init_app(app: Flask) -> None:
    """Initialise the MongoClient from Flask config. Called once at app startup."""
    global _client
    kwargs: dict[str, Any] = {
        "host": app.config["MONGO_HOST"],
        "port": int(app.config["MONGO_PORT"]),
        "serverSelectionTimeoutMS": 5000,
    }
    if app.config.get("MONGO_USER"):
        kwargs["username"] = app.config["MONGO_USER"]
        kwargs["password"] = app.config["MONGO_PASSWORD"]
        kwargs["authSource"] = app.config["MONGO_AUTH_SRC"]
    _client = MongoClient(**kwargs)

    # Ensure collections and indexes exist (single source of truth: db.schema)
    with app.app_context():
        from .schema import ensure_indexes
        ensure_indexes()


def get_client() -> MongoClient:
    if _client is None:
        raise RuntimeError("MongoDB client not initialised. Call init_app().")
    return _client


def get_db() -> Database:
    """Return the configured database handle."""
    return get_client()[current_app.config["MONGO_DB"]]


def ping() -> bool:
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False