"""Authentication module with Flask-Login."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from db.connection import get_db
from db.models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    db = get_db()
    user_doc = db.users.find_one({"name": user_id})
    if not user_doc:
        return None
    return User(
        project_id="",  # Not used for users
        name=user_doc["name"],
        username=user_doc.get("username", user_doc["name"]),
        email=user_doc.get("email", ""),
        password_hash=user_doc.get("password_hash", ""),
        role=user_doc.get("role", "user"),
        active=user_doc.get("active", True),
    )


def init_auth(app) -> None:
    """Initialize Flask-Login with the app."""
    login_manager.init_app(app)


def _safe_next(target: str) -> str | None:
    """Return ``target`` only if it is a same-site relative URL."""
    if not target or not target.startswith("/"):
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("auth/login.html")

        db = get_db()
        user_doc = db.users.find_one({"name": username})
        if not user_doc or not check_password_hash(user_doc.get("password_hash", ""), password):
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html")

        if not user_doc.get("active", True):
            flash("Account is disabled.", "error")
            return render_template("auth/login.html")

        user = User(
            project_id="",
            name=user_doc["name"],
            username=user_doc.get("username", user_doc["name"]),
            email=user_doc.get("email", ""),
            password_hash=user_doc.get("password_hash", ""),
            role=user_doc.get("role", "user"),
            active=user_doc.get("active", True),
        )
        login_user(user, remember=True)
        flash(f"Welcome back, {username}!", "success")

        next_page = _safe_next(request.args.get("next", ""))
        return redirect(next_page or url_for("home.home"))

    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("auth/register.html")

        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("auth/register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("auth/register.html")

        db = get_db()
        if db.users.find_one({"name": username}):
            flash("Username already exists.", "error")
            return render_template("auth/register.html")

        if email and db.users.find_one({"email": email}):
            flash("Email already registered.", "error")
            return render_template("auth/register.html")

        password_hash = generate_password_hash(password)
        db.users.insert_one({
            "name": username,
            "username": username,
            "email": email,
            "password_hash": password_hash,
            "role": "user",
            "active": True,
            "created_at": datetime.now(timezone.utc),
        })

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


# Decorator for admin-only routes
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if current_user.role != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("home.home"))
        return f(*args, **kwargs)
    return decorated_function