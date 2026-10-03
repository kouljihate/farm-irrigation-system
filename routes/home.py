"""Home page: choose between loading a KML or opening an existing project."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)

from core import kml_io
from core.validation import validate_form, NewProject
from db import repository
from db.connection import get_db


bp = Blueprint("home", __name__)


@bp.route("/")
def home():
    # list existing projects
    db = get_db()
    projects = list(db.projects.find({}, {"_id": 0}).sort("updated_at", -1))
    return render_template("home.html", projects=projects)


@bp.route("/new", methods=["POST"])
@validate_form(NewProject)
def new_project(data: NewProject):
    """Create a new project (empty). User then uploads a KML in /project/initial."""
    pid = data.project_id

    db = get_db()
    exists = db.projects.find_one({"project_id": pid})
    if exists:
        flash(f"Project '{pid}' already exists — opening it.",
              "success")
    else:
        repository.create_project(pid, pid, description="")
        flash(f"Project '{pid}' created. Upload a KML to begin.",
              "success")

    session["project_id"] = pid
    return redirect(url_for("project.initial"))


@bp.route("/open/<pid>")
def open_project(pid: str):
    """Open an existing project."""
    db = get_db()
    exists = db.projects.find_one({"project_id": pid})
    if not exists:
        flash(f"Project '{pid}' not found.", "error")
        return redirect(url_for("home.home"))
    session["project_id"] = pid
    flash(f"Opened project '{pid}'.", "success")
    return redirect(url_for("project.index"))


@bp.route("/delete/<pid>", methods=["POST"])
def delete_project(pid: str):
    """Delete a project and all its data."""
    db = get_db()
    for coll in ("projects", "revisions", "property", "water_points",
                 "basins", "sectors", "zones", "valves", "pipes", "rows",
                 "trees", "driplines", "manifolds", "bom_items", "logs"):
        db[coll].delete_many({"project_id": pid})
    flash(f"Deleted project '{pid}'.", "success")
    return redirect(url_for("home.home"))