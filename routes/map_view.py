"""Full-screen Leaflet project map view."""
from __future__ import annotations

from flask import Blueprint, render_template, session

bp = Blueprint("map_view", __name__)


@bp.route("/map")
def map_page():
    return render_template(
        "map.html",
        project_id=session.get("project_id", ""),
    )
