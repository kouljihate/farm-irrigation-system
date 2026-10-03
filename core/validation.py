"""Pydantic validation schemas for API endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from config import Config

# Build-parameter defaults live in config.yaml (single source of truth).
_D = Config.DEFAULTS


def _d(key: str, fallback):
    return _D.get(key, fallback)


class SectorSave(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    coords: str = Field(..., min_length=1)

    @field_validator("coords")
    @classmethod
    def validate_coords(cls, v: str) -> str:
        lines = [line.strip() for line in v.splitlines() if line.strip()]
        if len(lines) < 3:
            raise ValueError("need at least 3 coordinate lines")
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                raise ValueError(f"bad line: {line}")
            try:
                float(parts[0])
                float(parts[1])
            except ValueError:
                raise ValueError(f"not a number: {line}")
        return v


class SectorAdd(BaseModel):
    """Create a new sector from a drawn polygon."""
    coords: str = Field(..., min_length=1)
    code: str = Field(default="", max_length=50)

    @field_validator("coords")
    @classmethod
    def validate_coords(cls, v: str) -> str:
        lines = [line.strip() for line in v.splitlines() if line.strip()]
        if len(lines) < 3:
            raise ValueError("need at least 3 coordinate lines")
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                raise ValueError(f"bad line: {line}")
            try:
                float(parts[0])
                float(parts[1])
            except ValueError:
                raise ValueError(f"not a number: {line}")
        return v

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return v.strip()


class SectorCodes(BaseModel):
    """Remove / merge operate on a set of sector codes."""
    codes: str = Field(..., min_length=1, max_length=2000)
    cascade: int = Field(default=0, ge=0, le=1)

    @field_validator("codes")
    @classmethod
    def validate_codes(cls, v: str) -> str:
        codes = [c.strip() for c in v.split(",") if c.strip()]
        if not codes:
            raise ValueError("no sector codes given")
        if len(codes) > 64:
            raise ValueError("too many sectors at once")
        return ",".join(dict.fromkeys(codes))


class SectorSplit(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    parts: int = Field(default=2, ge=2, le=10)
    split_mode: str = Field(default="contour")

    @field_validator("split_mode")
    @classmethod
    def validate_split_mode(cls, v: str) -> str:
        if v not in ("contour", "fan", "strip"):
            raise ValueError(f"unknown split_mode: {v}")
        return v


class ZoneBuild(BaseModel):
    n_parts: int = Field(default=3, ge=1, le=20)
    offset: float = Field(default=0.0, ge=0)
    split_mode: str = Field(default="contour")

    @field_validator("split_mode")
    @classmethod
    def validate_split_mode(cls, v: str) -> str:
        if v not in ("contour", "fan", "strip"):
            raise ValueError(f"unknown split_mode: {v}")
        return v


class MainlineBuild(BaseModel):
    offset: float = Field(default_factory=lambda: _d("mainline_offset_m", 5.0), ge=0)
    diameter: int = Field(default_factory=lambda: _d("pipe_main_diameter_mm", 75), gt=0)


class SubmainBuild(BaseModel):
    offset: float = Field(default_factory=lambda: _d("submain_offset_m", 5.0), ge=0)
    diameter: int = Field(default_factory=lambda: _d("pipe_submain_diameter_mm", 32), gt=0)


class RowBuild(BaseModel):
    spacing: float = Field(default_factory=lambda: _d("row_spacing_m", 4.0), gt=0)
    offset: float = Field(default_factory=lambda: _d("first_row_offset_m", 2.0), ge=0)


class TreePlace(BaseModel):
    spacing: float = Field(default_factory=lambda: _d("tree_spacing_m", 4.0), gt=0)
    fig_pct: int = Field(default=20, ge=0, le=100)


class DriplineBuild(BaseModel):
    emitter_spacing: float = Field(default_factory=lambda: _d("emitter_spacing_m", 0.5), gt=0)


class BasinCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    lon: float
    lat: float
    length: float = Field(default=30.0, gt=0)
    width: float = Field(default=30.0, gt=0)
    depth: float = Field(default=2.0, gt=0)
    elev: float = Field(default=0.0)

    @model_validator(mode="before")
    @classmethod
    def remove_empty_strings(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data


class WellCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    lon: float
    lat: float
    elev: float = Field(default=0.0)
    depth: float = Field(default=50.0, gt=0)

    @model_validator(mode="before")
    @classmethod
    def remove_empty_strings(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data


# ------------------------------------------------------- water & basin step
WATER_SOURCE_TYPES: tuple[str, ...] = ("well", "river", "basin", "other")
BASIN_SOURCE_TYPE = "basin"
POINT_SOURCE_TYPES: tuple[str, ...] = tuple(
    t for t in WATER_SOURCE_TYPES if t != BASIN_SOURCE_TYPE
)
# display order in the Water & Basin table
SOURCE_TYPE_ORDER: tuple[str, ...] = WATER_SOURCE_TYPES

SOURCE_TYPE_LABELS: dict[str, tuple[str, str]] = {
    "well":   ("Well", "بئر"),
    "river":  ("River", "نهر"),
    "basin":  ("Basin", "حوض"),
    "other":  ("Other water source", "مصدر مياه آخر"),
}

SOURCE_TYPE_ICONS: dict[str, str] = {
    "well": "🕳️", "river": "🏞️", "basin": "🛢️", "other": "💧",
}

SOURCE_TYPE_BADGES: dict[str, str] = {
    "well":  "text-bg-primary",
    "river": "text-bg-info",
    "basin": "text-bg-success",
    "other": "text-bg-secondary",
}


class WaterSourceCreate(BaseModel):
    """Well / river / basin / other water source (Step 02)."""

    name: str = Field(..., min_length=1, max_length=100)
    source_type: str = Field(default="well")
    lon: float
    lat: float
    elev: float = Field(default=0.0)
    depth: float = Field(default=0.0)
    length: float = Field(default=0.0, ge=0)
    width: float = Field(default=0.0, ge=0)
    discharge: float = Field(default=0.0, ge=0)
    notes: str = Field(default="", max_length=500)

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: str) -> str:
        v = (v or "well").strip().lower()
        if v not in WATER_SOURCE_TYPES:
            raise ValueError(
                f"unknown source_type: {v} "
                f"(expected one of {', '.join(WATER_SOURCE_TYPES)})"
            )
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError("longitude must be between -180 and 180")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        return v

    @model_validator(mode="before")
    @classmethod
    def remove_empty_strings(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data

    @model_validator(mode="after")
    def basin_needs_size(self):
        if self.source_type == BASIN_SOURCE_TYPE and (self.length <= 0 or self.width <= 0):
            raise ValueError("a basin needs a length and a width greater than 0")
        return self


class NewProject(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=100)

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("project_id must not be blank")
        if any(ch in v for ch in ("/", "\\", "\x00")) or any(ord(ch) < 32 for ch in v):
            raise ValueError("project_id contains invalid characters")
        return v


def validate_json(model: type[BaseModel]) -> Any:
    """Decorator to validate request JSON against a Pydantic model."""
    from functools import wraps
    from flask import request, jsonify

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not request.is_json:
                return jsonify({"ok": False, "error": "Content-Type must be application/json"}), 400
            try:
                data = model(**request.get_json())
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            return f(data, *args, **kwargs)
        return wrapper
    return decorator


def validate_form(model: type[BaseModel]) -> Any:
    """Decorator to validate request form data against a Pydantic model."""
    from functools import wraps
    from flask import request, jsonify

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                data = model(**request.form.to_dict())
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            return f(data, *args, **kwargs)
        return wrapper
    return decorator