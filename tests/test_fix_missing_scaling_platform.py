"""Tests for fix_missing_scaling_platform — src/platform/scaling.py.

Merged from expert/systems-arch-m3 (not rewritten) and re-verified
against locked contracts v1.0.0. Run:
    PYTHONPATH=. python3 -m pytest tests/test_fix_missing_scaling_platform.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.contracts import CallMetrics, Priority  # noqa: E402
from src.platform.scaling import (  # noqa: E402
    Autoscaler, BulkheadManager, CostTracker, MultiAZPlacement, Release,
    ScalingMetrics, shed_decision,
)


def test_autoscaler_scales_up_on_concurrent_calls():
    sc = Autoscaler(now=lambda: 1000.0)
    d = sc.decide(ScalingMetrics(concurrent_calls=300, cpu_percent=50.0,
                                 queue_latency_ms=100.0))
    assert d.action == "scale_up" and d.desired_replicas >= 6


def test_autoscaler_holds_within_target_and_respects_cooldown():
    sc = Autoscaler(now=lambda: 1000.0)
    d = sc.decide(ScalingMetrics(concurrent_calls=10, cpu_percent=10.0,
                                 queue_latency_ms=100.0))
    assert d.action == "hold" and d.desired_replicas == 2
    # Scale up once, then a second decision inside the 120s cooldown holds.
    sc2 = Autoscaler(now=lambda: 1000.0)
    sc2.decide(ScalingMetrics(concurrent_calls=300, cpu_percent=50.0,
                              queue_latency_ms=100.0))
    d2 = sc2.decide(ScalingMetrics(concurrent_calls=500, cpu_percent=90.0,
                                   queue_latency_ms=900.0))
    assert d2.action == "hold"


def test_autoscaler_scale_to_zero_aux_workers_outside_hours():
    sc = Autoscaler(now=lambda: 1000.0)
    d = sc.decide(ScalingMetrics(concurrent_calls=0, cpu_percent=0.0,
                                 queue_latency_ms=0.0), hour=23)
    assert d.desired_replicas == 0 and d.action == "scale_to_zero"
    # Same zero load at noon: no scale-to-zero, live inbound stays up.
    d2 = sc.decide(ScalingMetrics(concurrent_calls=0, cpu_percent=0.0,
                                  queue_latency_ms=0.0), hour=12)
    assert d2.desired_replicas >= 2


def test_load_shedding_sheds_only_low_priority_new_calls():
    assert shed_decision(250, 200, Priority.LOW).shed_new_calls is True
    assert shed_decision(250, 200, Priority.NORMAL).shed_new_calls is True
    assert shed_decision(250, 200, Priority.HIGH).shed_new_calls is False
    assert shed_decision(250, 200, Priority.VIP).shed_new_calls is False
    assert shed_decision(100, 200, Priority.LOW).shed_new_calls is False


def test_bulkhead_ingestion_full_does_not_starve_inbound():
    bm = BulkheadManager(inbound=1, outbound=50, ingestion=1)
    assert bm.acquire("ingestion") is True
    assert bm.acquire("ingestion") is False  # ingestion pool full
    assert bm.acquire("inbound") is True     # inbound unaffected
    assert bm.acquire("inbound") is False    # inbound pool full on its own
    bm.release("inbound")
    assert bm.acquire("inbound") is True


def test_multi_az_placement_balanced_no_single_az_holds_all():
    placement = MultiAZPlacement(zones=("az-a", "az-b", "az-c"))
    assert placement.place(6) == {"az-a": 2, "az-b": 2, "az-c": 2}
    assert placement.place(7) == {"az-a": 3, "az-b": 2, "az-c": 2}
    assert sum(placement.place(10).values()) == 10
    assert placement.max_in_one_zone(10) == 4  # ceil(10/3), never 10
    assert placement.place(0) == {"az-a": 0, "az-b": 0, "az-c": 0}


def test_canary_and_rollback_blue_green():
    rel = Release(version="v2", canary_percent=10, stable_version="v1")
    assert rel.traffic_for_canary(5) is True
    assert rel.traffic_for_canary(50) is False
    rolled = rel.rollback()
    assert rolled.version == "v1" and rolled.canary_percent == 0


def test_cost_per_contained_call_uses_locked_final_containment():
    ct = CostTracker()
    # Call 1: provisional AND no recontact in 72h -> final.
    m1 = CallMetrics("C1", "shop-1", contained_provisional=True,
                     recontacted_within_window=False)
    ct.record_call(3.0, metrics=m1)
    # Call 2: provisional but customer called back -> NOT final.
    m2 = CallMetrics("C2", "shop-1", contained_provisional=True,
                     recontacted_within_window=True)
    ct.record_call(3.0, metrics=m2)
    assert ct.contained_provisional_calls == 2
    assert ct.contained_calls == 1  # only the final one counts
    assert ct.containment_rate == 0.5
    assert ct.provisional_containment_rate == 1.0
    # 6 minutes * $0.08 = $0.48, per 1 final contained call.
    assert abs(ct.cost_per_contained_call - 0.48) < 1e-9
    assert abs(ct.cost_per_contained_provisional_call - 0.24) < 1e-9
    assert ct.window_hours == 72


def test_cost_tracker_bare_bool_never_claims_final_containment():
    # m3 callers passing a bare bool mean provisional only: without a
    # CallMetrics record there is no 72h window to check.
    ct = CostTracker()
    ct.record_call(3.0, contained=True)
    ct.record_call(3.0, contained=False)
    assert ct.contained_provisional_calls == 1
    assert ct.contained_calls == 0
    assert ct.cost_per_contained_call is None
    assert ct.containment_rate == 0.0
