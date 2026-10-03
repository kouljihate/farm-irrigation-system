"""View application logs (file log + MongoDB audit log)."""
from __future__ import annotations

from flask import Blueprint, current_app, render_template, session

from config import Config
from db import queries


bp = Blueprint("logs", __name__, url_prefix="/logs")


@bp.route("/")
def index():
    pid = session.get("project_id", "")

    # File log tail
    log_file = Config.LOG_DIR / "app.log"
    lines = []
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()[-200:]
        lines.reverse()

    # Mongo audit log
    from db.connection import get_db
    mongo_logs = list(get_db().logs.find(
        {"project_id": pid}, {"_id": 0}
    ).sort("timestamp", -1).limit(200))

    revisions = queries.get_revisions(pid)

    return render_template("logs.html",
                           file_lines=lines,
                           mongo_logs=mongo_logs,
                           revisions=revisions)