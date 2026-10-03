"""Full-screen MapHub project map view."""
from __future__ import annotations

from flask import Blueprint, flash, render_template, session

from core.maphub import MapHubError, embed_url, sync_project_map


bp = Blueprint("map_view", __name__)


@bp.route("/map")
def map_page():
    pid = session.get("project_id", "")
    maphub_url = None
    error = None

    if pid:
        try:
            result = sync_project_map(pid)
            map_id = result.get("id")
            if map_id:
                maphub_url = embed_url(map_id)
        except MapHubError as exc:
            error = str(exc)

    return render_template(
        "map.html",
        project_id=pid,
        maphub_url=maphub_url,
        maphub_error=error,
    )
