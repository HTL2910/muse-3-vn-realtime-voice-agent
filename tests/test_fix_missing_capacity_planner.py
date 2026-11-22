"""Tests for fix/fix_missing_capacity_planner.

Stdlib-only (pytest). Edge cases: c=1 matches M/M/1, overload
returns prob_wait -> 1 with overloaded=True and no negative/NaN,
and a deterministic peak simulation.
Chưa chạy — kết quả thật do CI báo lại.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import math  # noqa: E402

import pytest  # noqa: E402

from queueing.capacity_planner import (  # noqa: E402
    CapacityPlanner,
    erlang_b,
    erlang_c_probability_wait,
)


# --- Erlang-C / M/M/1 edge -------------------------------------------------

def test_erlang_b_known_value():
    # a=1, c=1: B = a/(1+a) = 0.5
    assert erlang_b(1, 1.0) == pytest.approx(0.5)
    assert erlang_b(1, 0.0) == 0.0
    assert erlang_b(0, 1.0) == 1.0


def test_c1_erlang_c_matches_mm1():
    # M/M/1: lambda=0.2/min, service 3 min -> mu=1/3, a=0.6, rho=0.6.
    # P(wait) = rho = 0.6; Wq = rho/(mu-lambda) = 0.6/0.1333 = 4.5 min.
    planner = CapacityPlanner(containment=0.0)
    m = planner.erlang_c_metrics(0.2, 3.0, 1)
    assert m.prob_wait == pytest.approx(0.6)
    assert m.expected_wait_seconds == pytest.approx(270.0, rel=1e-6)
    assert m.offered_load == pytest.approx(0.6)
    assert not m.overloaded
    assert erlang_c_probability_wait(1, 0.6) == pytest.approx(0.6)


def test_erlang_a_with_long_patience_approaches_erlang_c():
    # Patience 1 day: almost nobody abandons, so Erlang-A must be
    # close to Erlang-C for the same load.
    planner = CapacityPlanner(containment=0.0)
    m_a = planner.metrics(0.2, 3.0, 1, patience_seconds=86400.0)
    m_c = planner.erlang_c_metrics(0.2, 3.0, 1)
    assert m_a.prob_wait == pytest.approx(m_c.prob_wait, rel=0.05)
    assert m_a.expected_wait_seconds == pytest.approx(
        m_c.expected_wait_seconds, rel=0.10)
    assert m_a.prob_abandon < 0.01


# --- overload: prob_wait -> 1, no negative / NaN ---------------------------

def test_overload_returns_overloaded_not_negative_or_nan():
    planner = CapacityPlanner(containment=0.0)
    # a = 10/min * 3 min = 30 Erlangs against 5 servers: rho = 6.
    m = planner.metrics(10.0, 3.0, 5)
    assert m.overloaded
    assert m.prob_wait > 0.99  # tends to 1 under overload
    assert m.prob_wait <= 1.0
    assert 0.0 <= m.prob_abandon <= 1.0
    assert math.isfinite(m.expected_wait_seconds) and m.expected_wait_seconds > 0
    assert math.isfinite(m.expected_queue_length) and m.expected_queue_length >= 0
    assert m.utilization == pytest.approx(6.0)


def test_overload_erlang_c_returns_inf_wait_not_nan():
    planner = CapacityPlanner(containment=0.0)
    m = planner.erlang_c_metrics(10.0, 3.0, 5)
    assert m.overloaded
    assert m.prob_wait == 1.0
    assert math.isinf(m.expected_wait_seconds)
    assert not math.isnan(m.expected_wait_seconds)


def test_zero_load_is_quiet():
    planner = CapacityPlanner(containment=0.0)
    m = planner.metrics(0.0, 3.0, 5)
    assert m.prob_wait == 0.0 and m.prob_abandon == 0.0
    assert m.expected_wait_seconds == 0.0 and not m.overloaded


def test_invalid_inputs_rejected():
    planner = CapacityPlanner()
    with pytest.raises(ValueError):
        planner.metrics(1.0, 3.0, 0)
    with pytest.raises(ValueError):
        planner.metrics(-1.0, 3.0, 5)
    with pytest.raises(ValueError):
        CapacityPlanner(containment=1.0)


# --- AI front layer ----------------------------------------------------------

def test_ai_containment_halves_human_load():
    planner = CapacityPlanner(containment=0.52)
    # 10 calls/min in, 5.2 resolved by AI, 4.8 reach humans.
    m = planner.metrics(10.0, 3.0, 10)
    assert m.offered_load == pytest.approx(4.8 * 3.0)
    no_ai = CapacityPlanner(containment=0.0).metrics(10.0, 3.0, 10)
    assert m.expected_wait_seconds < no_ai.expected_wait_seconds
    assert m.prob_abandon < no_ai.prob_abandon


def test_servers_needed_grows_with_load_and_meets_targets():
    planner = CapacityPlanner(containment=0.52)
    light = planner.servers_needed(2.0, 3.0)
    heavy = planner.servers_needed(10.0, 3.0)
    assert heavy > light >= 1
    m = planner.metrics(10.0, 3.0, heavy)
    assert m.expected_wait_seconds <= 60.0
    assert m.prob_abandon <= 0.05


# --- forecast / callback ------------------------------------------------------

def test_forecast_peak_hour_is_higher_than_night():
    planner = CapacityPlanner()
    peak = planner.forecast_lambda(5.0, hour=10)
    night = planner.forecast_lambda(5.0, hour=2)
    assert peak == pytest.approx(5.0 * 1.60)
    assert peak > night
    campaign = planner.forecast_lambda(5.0, hour=10, campaign_factor=2.0)
    assert campaign == pytest.approx(peak * 2.0)
    with pytest.raises(ValueError):
        planner.forecast_lambda(5.0, hour=25)


def test_callback_threshold_60_90_seconds():
    planner = CapacityPlanner()
    assert not planner.should_offer_callback(30.0)
    assert not planner.should_offer_callback(59.9)
    assert planner.should_offer_callback(60.0)
    assert planner.should_offer_callback(75.0)
    assert planner.should_offer_callback(120.0)
    assert planner.callback_slots(30.0) == []
    assert planner.callback_slots(120.0) == ["+15min", "+30min", "+45min", "+60min"]


def test_plan_day_covers_24_hours_and_flags_peak():
    planner = CapacityPlanner(containment=0.52)
    plan = planner.plan_day(5.0, 3.0)
    assert len(plan) == 24
    assert all(p.hour == i for i, p in enumerate(plan))
    peak = plan[10]
    night = plan[2]
    assert peak.servers_needed >= night.servers_needed
    assert peak.lambda_per_min > night.lambda_per_min


# --- peak simulation ------------------------------------------------------------

def test_simulate_peak_flags_callback_and_overload():
    planner = CapacityPlanner(containment=0.0)
    result = planner.simulate_peak(10.0, 3.0, 5, hours=2)
    assert result["overloaded"]
    assert result["offer_callback"]
    assert result["worst_prob_wait"] > 0.99
    assert 0.0 <= result["worst_prob_abandon"] <= 1.0
    assert math.isfinite(result["worst_expected_wait_seconds"])

    calm = planner.simulate_peak(0.5, 3.0, 10, hours=1)
    assert not calm["overloaded"]
    assert not calm["offer_callback"]
    assert calm["worst_expected_wait_seconds"] < 60.0
