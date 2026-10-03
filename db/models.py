"""Lightweight dataclasses for DB documents."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from flask_login import UserMixin


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BaseDoc:
    project_id: str
    name: str = ""
    revision_id: int | None = None
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_id", None)
        return d


@dataclass
class Project(BaseDoc):
    description: str = ""
    active: bool = True


@dataclass
class Sector(BaseDoc):
    sector_code: str = ""
    geom: dict = field(default_factory=dict)     # GeoJSON Polygon
    area_m2: float = 0.0


@dataclass
class Zone(BaseDoc):
    sector_code: str = ""
    zone_index: int = 0
    geom: dict = field(default_factory=dict)
    area_m2: float = 0.0
    fall_dir_deg: float = 0.0


@dataclass
class Valve(BaseDoc):
    valve_type: str = ""        # "MV" or "ZV"
    sector_code: str = ""
    zone_name: str = ""
    location: dict = field(default_factory=dict)   # GeoJSON Point
    diameter_mm: int = 32


@dataclass
class Pipe(BaseDoc):
    pipe_type: str = ""         # "mainline", "submain", "dripline", "manifold"
    parent_pipe: str = ""
    geom: dict = field(default_factory=dict)       # GeoJSON LineString
    length_m: float = 0.0
    diameter_mm: int = 32
    material: str = "HDPE PE100 PN10"


@dataclass
class Row(BaseDoc):
    zone_name: str = ""
    row_index: int = 0
    geom: dict = field(default_factory=dict)
    length_m: float = 0.0
    row_direction_deg: float = 0.0


@dataclass
class Tree(BaseDoc):
    row_name: str = ""
    zone_name: str = ""
    tree_index: int = 0
    location: dict = field(default_factory=dict)
    species: str = "olive"


@dataclass
class Dripline(BaseDoc):
    row_name: str = ""
    zone_name: str = ""
    geom: dict = field(default_factory=dict)
    length_m: float = 0.0
    emitter_count: int = 0


@dataclass
class BOMItem(BaseDoc):
    category: str = ""
    description: str = ""
    spec: str = ""
    unit: str = "pcs"
    quantity: float = 0.0
    unit_price: float = 0.0
    total_price: float = 0.0


@dataclass
class User(BaseDoc, UserMixin):
    """User model for authentication."""
    username: str = ""
    email: str = ""
    password_hash: str = ""
    role: str = "user"  # "admin", "user"
    active: bool = True

    def get_id(self) -> str:
        return str(self.name)  # username as ID