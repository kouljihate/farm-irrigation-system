"""Hydraulic design checks.

Pure functions plus one ``evaluate()`` entry point that turns a project's
pipes / driplines / water sources into a list of findings. No database or
Flask access here so the maths stays unit-testable.

Every engineering assumption (emitter discharge, operating hours, design
slope, friction factor, velocity limits) comes from ``config.yaml`` under
``hydraulics`` — nothing is hardcoded below.
"""
from __future__ import annotations

import math

from config import Config

_P = Config.HYDRAULICS


# ---------------------------------------------------------------- helpers
def _p(key: str):
    value = _P.get(key)
    if value is None:
        raise KeyError(f"hydraulics.{key} missing from config.yaml")
    return value


def pipe_area_m2(diameter_mm: float) -> float:
    """Internal cross-section of a pipe, in m²."""
    d = float(diameter_mm) / 1000.0
    if d <= 0:
        return 0.0
    return math.pi * (d / 2.0) ** 2


def velocity_ms(flow_m3h: float, diameter_mm: float) -> float:
    """Mean flow velocity in m/s for a given flow (m³/h) and diameter."""
    area = pipe_area_m2(diameter_mm)
    if area <= 0:
        return 0.0
    m3s = max(float(flow_m3h), 0.0) / 3600.0
    return m3s / area


def flow_for_velocity(diameter_mm: float, velocity: float) -> float:
    """Inverse of :func:`velocity_ms` — flow (m³/h) at a target velocity."""
    area = pipe_area_m2(diameter_mm)
    return max(float(velocity), 0.0) * area * 3600.0


# ---------------------------------------------------------------- demand
def emitter_count(length_m: float, spacing_m: float) -> int:
    """Emitters along a lateral of ``length_m`` at ``spacing_m`` intervals."""
    if spacing_m <= 0 or length_m <= 0:
        return 0
    return max(int(math.floor(length_m / spacing_m)), 0)


def demand_lph(n_emitters: int, emitter_discharge_lph: float) -> float:
    """Litres per hour needed to supply ``n_emitters`` at once."""
    return max(int(n_emitters), 0) * float(emitter_discharge_lph)


def demand_m3h(n_emitters: int, emitter_discharge_lph: float) -> float:
    return demand_lph(n_emitters, emitter_discharge_lph) / 1000.0


def design_flow_m3h(n_emitters: int, emitter_discharge_lph: float,
                    margin: float) -> float:
    """Peak flow to size pipes for, including the design margin."""
    return demand_m3h(n_emitters, emitter_discharge_lph) * float(margin)


def daily_volume_m3(flow_m3h: float, hours_per_day: float) -> float:
    return max(float(flow_m3h), 0.0) * float(hours_per_day)


def applied_depth_mm(flow_m3h: float, hours_per_day: float, area_m2: float) -> float:
    """Gross applied water depth over ``area_m2`` in mm."""
    if area_m2 <= 0:
        return 0.0
    return daily_volume_m3(flow_m3h, hours_per_day) * 1000.0 / float(area_m2)


# ---------------------------------------------------------------- friction
def friction_velocity_ms(diameter_mm: float, slope: float, c_factor: float) -> float:
    """Hazen-Williams full-bore velocity (m/s).

    V = 0.849 · C · R^0.63 · S^0.54  with the hydraulic radius R = D/4,
    SI units (m/s, m, m/m).
    """
    d = float(diameter_mm) / 1000.0
    if d <= 0 or slope <= 0:
        return 0.0
    r = d / 4.0
    return 0.849 * float(c_factor) * (r ** 0.63) * (float(slope) ** 0.54)


def capacity_m3h(diameter_mm: float, length_m: float, slope: float,
                 c_factor: float) -> float:
    """Pipe capacity (m³/h): friction limited, then capped at max velocity.

    A long flat pipe cannot report more than the velocity limit allows,
    which is the figure you actually design against.
    """
    if length_m <= 0:
        return 0.0
    v = min(friction_velocity_ms(diameter_mm, slope, c_factor),
            _p("max_velocity_ms"))
    return v * pipe_area_m2(diameter_mm) * 3600.0


def headloss_m(flow_m3h: float, diameter_mm: float, length_m: float,
               c_factor: float) -> float:
    """Friction loss (m of head) over ``length_m`` at ``flow_m3h``.

    Hazen-Williams: hf = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)
    """
    d = float(diameter_mm) / 1000.0
    if flow_m3h <= 0 or d <= 0 or length_m <= 0:
        return 0.0
    q = float(flow_m3h) / 3600.0
    return (10.67 * float(length_m) * (q ** 1.852)
            / (float(c_factor) ** 1.852 * d ** 4.87))


# ---------------------------------------------------------------- findings
def _finding(severity: str, code: str, message: str, entity: str = "") -> dict:
    return {"severity": severity, "code": code, "message": message,
            "entity": entity}


def _pipe_flow_m3h(pipe: dict, main_flow: float, n_submains: int) -> float:
    """Apportion design flow down the network.

    Mainlines are assumed to carry the whole farm demand; each sub-main
    carries an equal share (the worst case when they are evenly loaded).
    """
    ptype = str(pipe.get("pipe_type") or "").lower()
    if ptype == "mainline":
        return main_flow
    if ptype == "submain":
        return main_flow / max(n_submains, 1)
    return main_flow


def evaluate(pipes: list[dict], driplines: list[dict], sources: list[dict],
             irrigated_area_m2: float = 0.0) -> dict:
    """Run every check over plain document lists.

    Returns ``{"summary": {...}, "findings": [...], "pipes": [...]}``.
    """
    discharge_lph = _p("emitter_discharge_lph")
    hours = _p("operating_hours_per_day")
    margin = _p("demand_margin")
    slope = _p("design_slope")
    c_factor = _p("hazen_williams_c")
    v_min = _p("min_velocity_ms")
    v_max = _p("max_velocity_ms")
    over_ratio = _p("oversized_below_ratio")
    under_ratio = _p("undersized_above_ratio")
    max_headloss = _p("max_headloss_m")

    findings: list[dict] = []

    # ---- emitter demand ----
    n_emitters = 0
    for dl in driplines:
        n_emitters += int(dl.get("emitter_count") or 0)
    design_flow = design_flow_m3h(n_emitters, discharge_lph, margin)
    daily = daily_volume_m3(design_flow, hours)
    depth = applied_depth_mm(design_flow, hours, irrigated_area_m2)

    if n_emitters == 0:
        findings.append(_finding(
            "info", "no_driplines",
            "No driplines yet — build them to get a demand figure."))

    # ---- source capacity ----
    known_lps = [float(s.get("discharge_lps") or 0.0) for s in sources]
    known_lps = [q for q in known_lps if q > 0]
    required_lps = design_flow / 3.6
    source_total = sum(known_lps)
    if not known_lps:
        findings.append(_finding(
            "info", "source_unknown",
            "No water source has a recorded discharge — add one on "
            "Project → Water to check supply capacity."))
    elif source_total < required_lps:
        findings.append(_finding(
            "error", "source_short",
            f"Recorded source capacity {source_total:.2f} L/s is below the "
            f"required {required_lps:.2f} L/s."))
    else:
        findings.append(_finding(
            "info", "source_ok",
            f"Source capacity {source_total:.2f} L/s covers the required "
            f"{required_lps:.2f} L/s."))

    # ---- pipes ----
    n_submains = sum(1 for p in pipes
                     if str(p.get("pipe_type") or "").lower() == "submain")
    pipe_rows: list[dict] = []
    worst_headloss = 0.0

    for p in pipes:
        name = str(p.get("name") or "?")
        diameter = float(p.get("diameter_mm") or 0)
        length = float(p.get("length_m") or 0)
        flow = _pipe_flow_m3h(p, design_flow, n_submains)
        vel = velocity_ms(flow, diameter)
        cap = capacity_m3h(diameter, length, slope, c_factor)
        hl = headloss_m(flow, diameter, length, c_factor)
        worst_headloss = max(worst_headloss, hl)

        if diameter <= 0:
            findings.append(_finding(
                "error", "pipe_no_diameter",
                f"{name}: no diameter recorded.", name))
        elif vel > v_max * under_ratio:
            findings.append(_finding(
                "error", "pipe_undersized",
                f"{name}: {vel:.2f} m/s exceeds the {v_max} m/s limit — "
                f"increase the diameter.", name))
        elif vel > v_max:
            findings.append(_finding(
                "warn", "pipe_fast",
                f"{name}: {vel:.2f} m/s is above the {v_max} m/s limit.", name))
        elif vel < v_min * over_ratio:
            findings.append(_finding(
                "info", "pipe_oversized",
                f"{name}: {vel:.2f} m/s is far below the {v_min} m/s limit — "
                f"this pipe is larger than the design needs.", name))
        elif vel < v_min:
            findings.append(_finding(
                "warn", "pipe_slow",
                f"{name}: {vel:.2f} m/s is below the {v_min} m/s limit — "
                f"sediment risk.", name))

        if cap and flow > cap:
            findings.append(_finding(
                "error", "pipe_over_capacity",
                f"{name}: design flow {flow:.2f} m³/h exceeds the estimated "
                f"capacity {cap:.2f} m³/h.", name))

        if hl > max_headloss:
            findings.append(_finding(
                "warn", "pipe_headloss",
                f"{name}: friction loss {hl:.1f} m over {length:.0f} m — "
                f"above the {max_headloss} m ceiling.", name))

        pipe_rows.append({
            "name": name,
            "pipe_type": p.get("pipe_type") or "",
            "diameter_mm": diameter,
            "length_m": length,
            "flow_m3h": flow,
            "velocity_ms": vel,
            "capacity_m3h": cap,
            "headloss_m": hl,
        })

    if pipes and not design_flow:
        findings.append(_finding(
            "info", "no_demand",
            "Pipes exist but no emitter demand was found — the whole "
            "demand figure is zero."))

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 3))

    return {
        "summary": {
            "emitters": n_emitters,
            "emitter_discharge_lph": discharge_lph,
            "design_flow_m3h": design_flow,
            "daily_volume_m3": daily,
            "applied_depth_mm": depth,
            "irrigated_area_m2": irrigated_area_m2,
            "hours_per_day": hours,
            "source_total_lps": source_total,
            "required_lps": required_lps,
            "worst_headloss_m": worst_headloss,
            "errors": sum(1 for f in findings if f["severity"] == "error"),
            "warnings": sum(1 for f in findings if f["severity"] == "warn"),
        },
        "findings": findings,
        "pipes": sorted(pipe_rows, key=lambda r: -r["velocity_ms"]),
    }