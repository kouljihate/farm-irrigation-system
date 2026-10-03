"""Farm Irrigation Workbench — Flask app factory."""
from __future__ import annotations

from urllib.parse import urlparse

from flask import Flask, abort, flash, redirect, request, session, url_for

from config import Config
from logging_config import setup_logging


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    setup_logging(Config.LOG_DIR, Config.LOG_LEVEL)

    # ---- extensions ----
    from db.connection import init_app as init_db
    init_db(app)

    from routes.auth import init_auth
    init_auth(app)

    from core.async_tasks import init_task_queue
    init_task_queue(app, max_workers=2)

    # ---- blueprints ----
    from routes.home import bp as home_bp
    from routes.project import bp as project_bp
    from routes.geometry import bp as geometry_bp
    from routes.hydrology import bp as hydrology_bp
    from routes.field import bp as field_bp
    from routes.export import bp as export_bp
    from routes.api import bp as api_bp
    from routes.map_view import bp as map_bp
    from routes.logs import bp as logs_bp
    from routes.auth import bp as auth_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(project_bp)
    app.register_blueprint(geometry_bp)
    app.register_blueprint(hydrology_bp)
    app.register_blueprint(field_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(map_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(auth_bp)

    # ---- session defaults ----
    @app.before_request
    def _default_project():
        if "project_id" not in session:
            session["project_id"] = ""  # empty until home chooses one

    # ---- require an open project for the step pages ----
    _NO_PROJECT_OK = {
        "home.home", "home.new_project", "home.open_project", "home.delete_project",
        "project.index", "project.close_project", "project.set_project",
        "logs.index", "map_view.map_page", "static",
    }

    @app.before_request
    def _require_open_project():
        endpoint = request.endpoint or ""
        if session.get("project_id"):
            return None
        if endpoint in _NO_PROJECT_OK or endpoint.startswith(("auth.", "api.")):
            return None
        flash("Open a project first.", "warning")
        return redirect(url_for("home.home"))

    # ---- CSRF defence: reject cross-origin unsafe requests ----
    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

    @app.before_request
    def _csrf_origin_check():
        if request.method in _SAFE_METHODS:
            return None
        source = request.headers.get("Origin") or request.headers.get("Referer")
        if not source:
            return None  # non-browser client (e.g. tests)
        if urlparse(source).netloc != request.host:
            abort(400, description="Cross-origin request blocked")
        return None

    # ---- context processor: inject global values into every template ----
    @app.context_processor
    def inject_globals():
        from db import queries
        from db.connection import get_db
        pid = session.get("project_id", "")
        summary = {}
        projects = []
        if pid:
            try:
                summary = queries.project_summary(pid)
            except Exception:
                summary = {}
        # Get all projects for selector
        try:
            db = get_db()
            projects = list(db.projects.find({}, {"_id": 0, "project_id": 1, "name": 1}).sort("updated_at", -1))
        except Exception:
            projects = []
        return {
            "app_title": app.config["APP_TITLE"],
            "app_version": app.config["APP_VERSION"],
            "app_defaults": app.config.get("DEFAULTS", {}),
            "project_id": pid or "(none)",
            "summary": summary,
            "projects": projects,
        }

    # ---- error handlers ----
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template
        app.logger.exception("Internal server error")
        return render_template("error.html", code=500,
                               message="Internal server error"), 500

    return app