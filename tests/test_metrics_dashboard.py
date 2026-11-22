import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.observability.metrics_dashboard import (
    MetricsDashboard, CallRecord, percentile, redact_pii)
from src.contracts import EscalationReason, CONTAINMENT_WINDOW_HOURS

T0 = 1_700_000_000.0

def call(**kw):
    base = dict(trace_id="tr1", call_id="c1", tenant_id="shopA", phone="0901234567",
                intent="order_status", department="sales", started_at=T0, ended_at=T0 + 120,
                wait_s=5, duration_s=120, handled_by_ai=True, evidence_verified=True,
                resolved_first_contact=True, cost=0.24, ai_minutes=2.0,
                latencies_ms={"asr": 200, "llm": 400, "tts": 300, "total": 900})
    base.update(kw)
    return CallRecord(**base)

def test_percentile_nearest_rank():
    assert percentile([], 95) == 0.0
    assert percentile([10, 20, 30, 40], 50) == 20
    assert percentile([10, 20, 30, 40], 95) == 40

def test_window_is_contracts_fixed_72h():
    assert CONTAINMENT_WINDOW_HOURS == 72
    assert MetricsDashboard().window_hours == 72.0
    for bad in (48, 24, 100):
        try:
            MetricsDashboard(window_hours=bad); assert False, bad
        except ValueError:
            pass

def test_provisional_requires_verified_evidence():
    d = MetricsDashboard()
    d.record_call(call(evidence_verified=False))
    s = d.compute(now=T0)
    assert s["containment_provisional_rate"] == 0.0 and s["containment_final_rate"] == 0.0

def test_final_two_layer_and_repeat_within_72h_revokes():
    d = MetricsDashboard()
    d.record_call(call())
    s = d.compute(now=T0 + 100)
    assert s["containment_provisional_rate"] == 1.0 and s["containment_final_rate"] == 1.0
    assert s["kpi_containment"] == s["containment_final_rate"] and s["contained_final"] == 1
    d.record_call(call(trace_id="tr2", call_id="c2", started_at=T0 + 71 * 3600))
    s2 = d.compute(now=T0 + 72 * 3600)
    assert s2["containment_provisional_rate"] == 1.0 and s2["containment_final_rate"] == 0.5

def test_repeat_after_72h_does_not_revoke():
    d = MetricsDashboard()
    d.record_call(call())
    d.record_call(call(trace_id="tr2", call_id="c2", started_at=T0 + 73 * 3600))
    assert d.compute(now=T0 + 74 * 3600)["containment_final_rate"] == 1.0

def test_cost_per_contained_uses_final_layer():
    d = MetricsDashboard()
    d.record_call(call(cost=0.4))
    d.record_call(call(trace_id="t2", call_id="c2", started_at=T0 + 3600, cost=0.4))
    s = d.compute(now=T0 + 3700)
    assert s["containment_final_count"] == 1 and s["cost_per_contained_call"] == 0.8

def test_escalation_reasons_and_correct_department():
    d = MetricsDashboard()
    d.record_call(call(escalated=True, handled_by_ai=False, escalation_reason=EscalationReason.SENSITIVE, correct_department=True))
    d.record_call(call(trace_id="t2", call_id="c2", phone="0902", escalated=True, handled_by_ai=False,
                       escalation_reason="out_of_scope", correct_department=False))
    s = d.compute(now=T0)
    assert s["escalation_rate"] == 1.0
    assert s["escalation_by_reason"] == {"sensitive": 1, "out_of_scope": 1}
    assert s["correct_department_rate"] == 0.5 and s["containment_final_rate"] == 0.0

def test_abandonment_wait_fcr_aht_csat():
    d = MetricsDashboard()
    d.record_call(call(abandoned=True, handled_by_ai=False, resolved_first_contact=False, csat=2))
    d.record_call(call(trace_id="t2", call_id="c2", phone="0902", wait_s=15, duration_s=60, csat=5))
    s = d.compute(now=T0)
    assert s["abandonment_rate"] == 0.5 and s["avg_wait_s"] == 10
    assert s["fcr_rate"] == 0.5 and s["aht_s"] == 90 and s["csat_avg"] == 3.5

def test_latency_p50_p95_bargein_provider_verifier_and_slo():
    d = MetricsDashboard()
    for i, tot in enumerate((800, 900, 1000, 1100)):
        d.record_call(call(trace_id=f"t{i}", call_id=f"c{i}", phone=f"090{i}",
                           latencies_ms={"asr": 100 + i * 10, "llm": 300, "tts": 200, "total": tot},
                           barge_in_count=1 if i == 0 else 0,
                           provider_errors={"fpt_asr": 1} if i == 0 else {},
                           verifier_attempts=2, verifier_blocked=1 if i < 2 else 0,
                           cost=0.2, ai_minutes=2.0))
    s = d.compute(now=T0)
    assert s["latency_ms"]["total"]["p50"] == 900 and s["latency_ms"]["total"]["p95"] == 1100
    assert s["latency_slo_p95_ms"] == 1200 and s["latency_slo_breached"] is False
    assert s["barge_in_rate"] == 0.25 and s["provider_errors"] == {"fpt_asr": 1}
    assert s["verifier_block_rate"] == 0.25 and s["verifier_blocked_count"] == 2
    assert s["cost_per_ai_minute"] == 0.1 and s["cost_per_contained_call"] == 0.2

def test_breakdowns_by_intent_department_hour():
    d = MetricsDashboard()
    d.record_call(call())
    d.record_call(call(trace_id="t2", call_id="c2", phone="0909", intent="refund",
                       department="support", escalated=True, handled_by_ai=False))
    s = d.compute(now=T0)
    assert s["by_intent"]["order_status"]["containment_final_rate"] == 1.0
    assert s["by_intent"]["refund"]["escalation_rate"] == 1.0
    assert s["by_department"]["support"]["total"] == 1
    assert sum(v["total"] for v in s["by_hour"].values()) == 2

def test_benchmarks_kept_separate_and_no_80_percent_claim():
    d = MetricsDashboard()
    d.record_call(call())
    d.set_benchmarks({"ada_vendor_containment": 0.52, "gartner_forecast_2029": 0.80})
    s = d.compute(now=T0)
    assert s["source"] == "internal_measured" and s["benchmarks_mixed_into_kpi"] is False
    assert s["benchmarks_external"]["ada_vendor_containment"] == 0.52
    assert s["claimed_resolution_rate"] is None and s["kpi_containment"] == 1.0

def test_transcript_redacted_before_analytics_and_retention_purge():
    d = MetricsDashboard(retention_days=30)
    d.record_call(call(transcript="SDT 0901234567 email a@example.com CCCD 079123456789"))
    stored = d.analytics_transcripts()[0]["transcript"]
    assert "0901234567" not in stored and "a@example.com" not in stored and "079123456789" not in stored
    assert redact_pii("0901234567") == "09******67"
    assert d.purge_expired(now=T0 + 31 * 86400) == 1
    assert d.compute(now=T0)["total_calls"] == 0
