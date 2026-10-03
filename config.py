"""Flask configuration for the Farm Irrigation Workbench."""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class MongoDBConfig(BaseModel):
    host: str = "localhost"
    port: int = Field(default=27017, ge=1, le=65535)
    database: str = "farm_irrigation"
    username: str | None = None
    password: str | None = None
    auth_source: str = "admin"


class PathsConfig(BaseModel):
    imports: str = "imports"
    exports: str = "exports"


class AppConfig(BaseModel):
    title: str = "Farm Irrigation Workbench"
    version: str = "1.0.0"


class DefaultsConfig(BaseModel):
    row_spacing_m: float = Field(default=4.0, gt=0)
    tree_spacing_m: float = Field(default=4.0, gt=0)
    first_row_offset_m: float = Field(default=2.0, ge=0)
    pipe_main_diameter_mm: int = Field(default=75, gt=0)
    pipe_submain_diameter_mm: int = Field(default=32, gt=0)
    mainline_offset_m: float = Field(default=5.0, ge=0)
    submain_offset_m: float = Field(default=5.0, ge=0)
    emitter_spacing_m: float = Field(default=0.5, gt=0)


class HydraulicsConfig(BaseModel):
    """Every engineering assumption used by the design checks."""

    emitter_discharge_lph: float = Field(default=2.0, gt=0)
    operating_hours_per_day: float = Field(default=6.0, gt=0, le=24)
    demand_margin: float = Field(default=1.15, ge=1.0)
    hazen_williams_c: float = Field(default=150.0, gt=0)
    design_slope: float = Field(default=0.002, gt=0)
    min_velocity_ms: float = Field(default=0.3, gt=0)
    max_velocity_ms: float = Field(default=2.0, gt=0)
    oversized_below_ratio: float = Field(default=0.8, gt=0, le=1.0)
    undersized_above_ratio: float = Field(default=1.25, ge=1.0)
    max_headloss_m: float = Field(default=10.0, gt=0)


class RootConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    mongodb: MongoDBConfig = Field(default_factory=MongoDBConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    hydraulics: HydraulicsConfig = Field(default_factory=HydraulicsConfig)


def _load_yaml() -> dict:
    path = BASE_DIR / "config.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _validate_config(raw: dict) -> RootConfig:
    try:
        return RootConfig(**raw)
    except ValidationError as e:
        errors = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
        raise RuntimeError(f"Invalid config.yaml: {errors}") from e


_raw = _load_yaml()
_config = _validate_config(_raw)
_yaml = _config.model_dump()


def _resolve_secret_key() -> str:
    """Return SECRET_KEY from the environment, or a persisted random key.

    Falling back to a random key avoids shipping a well-known default while
    keeping sessions stable across restarts.
    """
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        persisted = key_file.read_text(encoding="utf-8").strip()
        if persisted:
            return persisted
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


class Config:
    # Flask core
    SECRET_KEY = _resolve_secret_key()
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

    # Session / cookie hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # Paths
    BASE_DIR = BASE_DIR
    IMPORT_DIR = BASE_DIR / _yaml.get("paths", {}).get("imports", "imports")
    EXPORT_DIR = BASE_DIR / _yaml.get("paths", {}).get("exports", "exports")
    LOG_DIR    = BASE_DIR / "logs"

    # Uploads
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB

    # MongoDB
    MONGO_HOST     = _yaml.get("mongodb", {}).get("host", "localhost")
    MONGO_PORT     = int(_yaml.get("mongodb", {}).get("port", 27017))
    MONGO_DB       = _yaml.get("mongodb", {}).get("database", "farm_irrigation")
    MONGO_USER     = _yaml.get("mongodb", {}).get("username")
    MONGO_PASSWORD = _yaml.get("mongodb", {}).get("password")
    MONGO_AUTH_SRC = _yaml.get("mongodb", {}).get("auth_source", "admin")

    # App
    APP_TITLE   = _yaml.get("app", {}).get("title", "Farm Irrigation Workbench")
    APP_VERSION = _yaml.get("app", {}).get("version", "1.0.0")

    # Geometry / Defaults
    GEOMETRY = _yaml.get("geometry", {})
    DEFAULTS = _yaml.get("defaults", {})

    # Engineering assumptions for the design checks (core/hydraulics.py)
    HYDRAULICS = _yaml.get("hydraulics", {})

    # Logging
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


# ensure runtime folders exist
for d in (Config.IMPORT_DIR, Config.EXPORT_DIR, Config.LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)