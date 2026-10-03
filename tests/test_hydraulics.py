"""Unit tests for core.hydraulics — no database required."""
import math

import pytest

from config import Config
from core import hydraulics as H


# ---------------------------------------------------------------- geometry
def test_pipe_area_matches_circle_formula():
    # 100 mm pipe -> r = 0.05 m
    assert H.pipe_area_m2(100) == pytest.approx(math.pi * 0.05 ** 2)
    assert H.pipe_area_m2(0) == 0.0
    assert H.pipe_area_m2(-5) == 0.0


def test_velocity_and_inverse_are_consistent():
    for flow, dia in [(10.0, 32), (25.0, 75), (0.5, 110), (100.0, 160)]:
        v = H.velocity_ms(flow, dia)
        assert v > 0
        assert H.flow_for_velocity(dia, v) == pytest.approx(flow)


def test_velocity_of_zero_flow_is_zero():
    assert H.velocity_ms(0, 75) == 0.0
    assert H.velocity_ms(-3, 75) == 0.0


def test_velocity_scales_with_diameter_inversely():
    """Same flow through a bigger pipe must move slower."""
    assert H.velocity_ms(20, 110) < H.velocity_ms(20, 32)


# ---------------------------------------------------------------- demand
def test_emitter_count_floors_partial_emitters():
    assert H.emitter_count(100.0, 0.5) == 200
    assert H.emitter_count(100.4, 0.5) == 200
    assert H.emitter_count(99.9, 0.5) == 199
    assert H.emitter_count(0, 0.5) == 0
    assert H.emitter_count(100, 0) == 0
    assert H.emitter_count(-5, 0.5) == 0


def test_demand_conversions():
    # 1000 emitters at 2 L/h = 2000 L/h = 2 m3/h
    assert H.demand_lph(1000, 2.0) == pytest.approx(2000.0)
    assert H.demand_m3h(1000, 2.0) == pytest.approx(2.0)
    # margin is applied on top
    assert H.design_flow_m3h(1000, 2.0, 1.15) == pytest.approx(2.3)
    assert H.daily_volume_m3(2.3, 6.0) == pytest.approx(13.8)


def test_applied_depth_is_volume_over_area():
    # 10 m3/h for 6 h = 60 m3 over 6000 m2 -> 10 mm
    assert H.applied_depth_mm(10.0, 6.0, 6000.0) == pytest.approx(10.0)
    assert H.applied_depth_mm(10.0, 6.0, 0.0) == 0.0


# ---------------------------------------------------------------- friction
def test_capacity_grows_with_diameter_and_slope():
    base = H.capacity_m3h(75, 100.0, 0.002, 150)
    assert H.capacity_m3h(110, 100.0, 0.002, 150) > base
    # a gentle slope is friction limited, so it carries less
    assert H.capacity_m3h(75, 100.0, 0.0002, 150) < base


def test_capacity_never_exceeds_the_max_velocity_limit():
    v_max = Config.HYDRAULICS["max_velocity_ms"]
    # a very steep slope is limited by velocity, not by friction
    steep = H.capacity_m3h(75, 100.0, 0.5, 150)
    assert steep == pytest.approx(H.flow_for_velocity(75, v_max))


def test_friction_velocity_matches_the_hazen_williams_formula():
    """V = 0.849 · C · (D/4)^0.63 · S^0.54 — checked against a hand value."""
    d, slope, c = 0.075, 0.002, 150.0
    expected = 0.849 * c * ((d / 4) ** 0.63) * (slope ** 0.54)
    assert H.friction_velocity_ms(75, slope, c) == pytest.approx(expected)
    assert expected == pytest.approx(0.363, abs=0.01)


def test_headloss_agrees_with_the_slope_that_produces_that_flow():
    """At the friction-limited flow, hf must equal L·S (physics self-check)."""
    length, slope, c = 180.0, 0.002, 150.0
    v = H.friction_velocity_ms(75, slope, c)
    flow = H.flow_for_velocity(75, v)
    assert H.headloss_m(flow, 75, length, c) == pytest.approx(length * slope,
                                                              rel=0.02)


def test_headloss_hand_value():
    # 10 m3/h through 100 mm over 100 m, C = 150
    expected = (10.67 * 100.0 * ((10.0 / 3600.0) ** 1.852)
                / (150.0 ** 1.852 * 0.1 ** 4.87))
    assert H.headloss_m(10.0, 100, 100.0, 150) == pytest.approx(expected)
    # 2.78 L/s in a 100 mm pipe implies ~0.14% slope -> ~0.14 m over 100 m
    assert expected == pytest.approx(0.136, abs=0.005)


def test_capacity_guards_degenerate_inputs():
    assert H.capacity_m3h(0, 100, 0.002, 150) == 0.0
    assert H.capacity_m3h(75, 0, 0.002, 150) == 0.0
    assert H.capacity_m3h(75, 100, 0.0, 150) == 0.0


def test_headloss_is_zero_without_flow_and_increases_with_length():
    assert H.headloss_m(0.0, 75, 100.0, 150) == 0.0
    short = H.headloss_m(10.0, 75, 50.0, 150)
    long = H.headloss_m(10.0, 75, 200.0, 150)
    assert 0 < short < long
    # head loss falls as the pipe gets fatter
    assert H.headloss_m(10.0, 110, 200.0, 150) < long


# ---------------------------------------------------------------- evaluate
def _pipes():
    return [
        {"name": "MAIN-1", "pipe_type": "mainline", "diameter_mm": 75,
         "length_m": 120.0},
        {"name": "SUB-1", "pipe_type": "submain", "diameter_mm": 32,
         "length_m": 60.0},
        {"name": "SUB-2", "pipe_type": "submain", "diameter_mm": 32,
         "length_m": 60.0},
    ]


def _driplines(count_each=500, n=4):
    return [{"name": f"DL-{i}", "emitter_count": count_each} for i in range(n)]


def test_evaluate_reports_emitter_demand_and_daily_volume():
    res = H.evaluate(_pipes(), _driplines(), [])
    s = res["summary"]
    assert s["emitters"] == 2000
    assert s["design_flow_m3h"] == pytest.approx(2000 * 2.0 / 1000 * 1.15)
    assert s["daily_volume_m3"] == pytest.approx(s["design_flow_m3h"] * 6.0)
    assert res["pipes"] and len(res["pipes"]) == 3


def test_evaluate_flags_missing_source_and_missing_driplines():
    res = H.evaluate([], [], [])
    codes = {f["code"] for f in res["findings"]}
    assert "no_driplines" in codes
    assert "source_unknown" in codes
    assert res["summary"]["emitters"] == 0
    assert res["summary"]["design_flow_m3h"] == 0.0


def test_evaluate_flags_source_shortfall():
    res = H.evaluate(_pipes(), _driplines(),
                     [{"name": "Well", "discharge_lps": 0.1}])
    codes = {f["code"] for f in res["findings"]}
    assert "source_short" in codes
    assert res["summary"]["source_total_lps"] == pytest.approx(0.1)


def test_evaluate_passes_when_source_covers_demand():
    res = H.evaluate(_pipes(), _driplines(),
                     [{"name": "Well", "discharge_lps": 5.0}])
    codes = {f["code"] for f in res["findings"]}
    assert "source_short" not in codes
    assert "source_ok" in codes


def test_evaluate_flags_missing_diameter():
    res = H.evaluate([{"name": "X", "pipe_type": "mainline",
                       "length_m": 10.0}], _driplines(1, 1), [])
    codes = {f["code"] for f in res["findings"]}
    assert "pipe_no_diameter" in codes


def test_evaluate_flags_undersized_pipe():
    """Tiny pipe carrying the whole farm demand runs far too fast."""
    res = H.evaluate(
        [{"name": "THIN", "pipe_type": "mainline", "diameter_mm": 16,
          "length_m": 100.0}],
        _driplines(count_each=5000, n=8), [])
    codes = {f["code"] for f in res["findings"]}
    assert "pipe_undersized" in codes


def test_evaluate_flags_oversized_pipe():
    """Huge pipe with almost no demand is slower than the minimum."""
    res = H.evaluate(
        [{"name": "HUGE", "pipe_type": "mainline", "diameter_mm": 315,
          "length_m": 100.0}],
        _driplines(count_each=1, n=1), [])
    codes = {f["code"] for f in res["findings"]}
    assert "pipe_oversized" in codes


def test_evaluate_appends_flow_tiers_correctly():
    """Mainline takes the whole demand; sub-mains split it evenly."""
    res = H.evaluate(_pipes(), _driplines(), [])
    by_name = {r["name"]: r for r in res["pipes"]}
    total = res["summary"]["design_flow_m3h"]
    assert by_name["MAIN-1"]["flow_m3h"] == pytest.approx(total)
    assert by_name["SUB-1"]["flow_m3h"] == pytest.approx(total / 2)
    assert by_name["SUB-2"]["flow_m3h"] == pytest.approx(total / 2)


def test_findings_are_ordered_errors_first():
    res = H.evaluate(
        [{"name": "THIN", "pipe_type": "mainline", "diameter_mm": 16,
          "length_m": 500.0}],
        _driplines(count_each=5000, n=8),
        [{"name": "W", "discharge_lps": 0.01}])
    severities = [f["severity"] for f in res["findings"]]
    rank = {"error": 0, "warn": 1, "info": 2}
    assert severities == sorted(severities, key=lambda s: rank[s])


def test_evaluate_handles_pipes_without_flow():
    res = H.evaluate(_pipes(), [], [{"name": "W", "discharge_lps": 5.0}])
    codes = {f["code"] for f in res["findings"]}
    assert "no_demand" in codes
    for row in res["pipes"]:
        assert row["velocity_ms"] == 0.0
        assert row["headloss_m"] == 0.0