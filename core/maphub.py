"""MapHub integration for project map publishing.

The MapHub API key is server-side only. Project geometry remains authoritative
in MongoDB; MapHub is a visualization/publishing target.
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests
from flask import current_app

from db.connection import get_db


class MapHubError(RuntimeError):
    """Raised when MapHub cannot create or update a project map."""


def _api_url(path: str) -> str:
    base = current_app.config["MAPHUB_BASE_URL"].rstrip("/")
    return f"{base}/api/1/{path.lstrip('/')}"


def _headers() -> dict[str, str]:
    key = current_app.config.get("MAPHUB_API_KEY")
    if not key:
        raise MapHubError(
            "MAPHUB_API_KEY is not configured. Add it to the server environment."
        )
    return {"Authorization": f"Token {key}"}


def _request(path: str, *, json: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = requests.post(
        _api_url(path),
        json=json,
        headers=headers or _headers(),
        timeout=current_app.config["MAPHUB_TIMEOUT_SECONDS"],
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise MapHubError(str(data["error"]))
    return data


def _safe_short_name(project_id: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", project_id.lower()).strip("-")
    return f"farm-irrigation-{value or 'project'}"[:80]


def project_geojson(project_id: str) -> dict[str, Any]:
    """Build the current project GeoJSON without exposing Mongo internals."""
    db = get_db()
    features: list[dict[str, Any]] = []

    collections = [
        ("property", "geom"),
        ("water_points", "location"),
        ("basins", "geom"),
        ("sectors", "geom"),
        ("zones", "geom"),
        ("pipes", "geom"),
        ("rows", "geom"),
        ("valves", "location"),
        ("trees", "location"),
        ("driplines", "geom"),
        ("manifolds", "geom"),
    ]

    for collection, geometry_field in collections:
        for doc in db[collection].find({"project_id": project_id}, {"_id": 0}):
            geometry = doc.get(geometry_field)
            if not geometry:
                continue

            name = doc.get("name") or doc.get("sector_code") or collection
            properties = {
                "title": str(name),
                "description": f"Farm Irrigation Workbench · {collection}",
                "collection": collection,
                "sector_code": doc.get("sector_code"),
                "zone_index": doc.get("zone_index"),
                "diameter_mm": doc.get("diameter_mm"),
                "elev_m": doc.get("elev_m"),
                "area_m2": doc.get("area_m2"),
                "species": doc.get("species"),
            }
            features.append({
                "type": "Feature",
                "properties": properties,
                "geometry": geometry,
            })

    return {"type": "FeatureCollection", "features": features}


def _create_map(project_id: str) -> dict[str, Any]:
    args = {
        "file_type": "empty",
        "title": f"Farm Irrigation · {project_id}",
        "short_name": _safe_short_name(project_id),
        "visibility": current_app.config["MAPHUB_VISIBILITY"],
    }
    headers = {
        **_headers(),
        "MapHub-API-Arg": json.dumps(args),
    }
    return _request("map/upload", headers=headers)


def sync_project_map(project_id: str) -> dict[str, Any]:
    """Create the project's MapHub map if needed, then replace its GeoJSON."""
    db = get_db()
    project = db.projects.find_one({"project_id": project_id}, {"maphub_map_id": 1})
    map_id = (project or {}).get("maphub_map_id")

    if not map_id:
        created = _create_map(project_id)
        map_id = created.get("id")
        if not map_id:
            raise MapHubError(f"MapHub did not return a map id: {created}")
        db.projects.update_one(
            {"project_id": project_id},
            {"$set": {"maphub_map_id": int(map_id)}},
        )

    data = _request(
        "map/update",
        json={
            "map_id": int(map_id),
            "title": f"Farm Irrigation · {project_id}",
            "geojson": project_geojson(project_id),
            "visibility": current_app.config["MAPHUB_VISIBILITY"],
        },
    )
    return data


def embed_url(map_id: int | str) -> str:
    """Return the public MapHub embed URL for a map id."""
    return f"{current_app.config['MAPHUB_EMBED_BASE_URL'].rstrip('/')}/{int(map_id)}?panel=1"
