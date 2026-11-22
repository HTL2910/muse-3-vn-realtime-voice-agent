"""Rebase verification for the 3 remaining backend-sec modules.

Locked contracts v1.0.0 values: containment window FIXED 72h,
TOTAL_SLO_P95_MS = 1200 (name after fix_latency_constant_name),
CONTRACTS_VERSION = '1.0.0', EscalationReason snake_case.
Supersedes the 3 pre-rebase metrics tests that asserted a variable
24-72h window (test_window_must_be_within_locked_24_72h,
test_provisional_vs_final_and_repeat_revokes with 48h,
test_repeat_outside_window_does_not_revoke with 24h).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.observability.metrics_dashboard import MetricsDashboard, CallRecord
import src.observability.metrics_dashboard as md
from src.security.voice_security_policy import AuditLog
import src.security.voice_security_policy as vs
from src.callback.callback_ticket_service import CallbackTicketService
import src.callback.callback_ticket_service as cb

T0 = 1_700_000_000.0

def call(**kw):
    base = dict(trace_id="tr1", call_id="c1", phone="0901234567", intent="order_status",
                started_at=T0, handled_by_ai=True, cost=0.2, ai_minutes=2.0,
                latencies_ms={"total": 900})
    base.update(kw)
    return CallRecord(**base)

# --- metrics: 72h fixed ---
def test_metrics_window_defaults_to_contracts_72h():
    d = MetricsDashboard()
    assert d.window_hours == 72.0
    s = d.compute(now=T0)
    assert s["containment_window_hours"] == 72.0 and s["contracts_version"] == "1.0.0"

def test_metrics_window_48h_is_rejected_not_silently_used():
    for bad in (48, 24, 100):
        try:
            MetricsDashboard(window_hours=bad); assert False, bad
        except ValueError:
            pass

def test_repeat_within_72h_revokes_after_72h_does_not():
    d = MetricsDashboard()
    d.record_call(call())
    d.record_call(call(trace_id="t2", call_id="c2", started_at=T0 + 71 * 3600))
    assert d.compute(now=T0 + 72 * 3600)["containment_final_rate"] == 0.5
    d2 = MetricsDashboard()
    d2.record_call(call())
    d2.record_call(call(trace_id="t2", call_id="c2", started_at=T0 + 73 * 3600))
    assert d2.compute(now=T0 + 74 * 3600)["containment_final_rate"] == 1.0

def test_cost_per_contained_uses_final_layer():
    d = MetricsDashboard()
    d.record_call(call(cost=0.4))
    d.record_call(call(trace_id="t2", call_id="c2", started_at=T0 + 3600, cost=0.4))
    s = d.compute(now=T0 + 3700)
    # provisional contained = 2, final contained = 1 -> cost/contained = 0.8/1
    assert s["containment_final_count"] == 1 and s["cost_per_contained_call"] == 0.8

def test_slo_constant_comes_from_contracts():
    d = MetricsDashboard()
    d.record_call(call(latencies_ms={"total": 1500}))
    s = d.compute(now=T0)
    assert s["latency_slo_p95_ms"] == 1200 and s["latency_slo_breached"] is True
    d2 = MetricsDashboard(); d2.record_call(call())
    assert d2.compute(now=T0)["latency_slo_breached"] is False

# --- security + callback: contracts stamped, no mirror drift ---
def test_security_audit_carries_contracts_version():
    log = AuditLog(); e = log.append("tool_call", "ai")
    assert e["contracts_version"] == "1.0.0" and vs.CONTRACTS_VERSION == "1.0.0"
    assert vs.TOTAL_SLO_P95_MS == 1200

def test_callback_outbox_payload_carries_contracts_version():
    s = CallbackTicketService()
    seen = []
    s.create_ticket(phone="0901", intent="order_status", now=T0)
    s.drain_outbox(lambda p: seen.append(p), now=T0)
    assert seen and seen[0]["contracts_version"] == "1.0.0"
    assert cb.CONTRACTS_VERSION == "1.0.0"

def test_grep_no_mirror_constants_left():
    for mod in (md, vs, cb):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "from src.contracts import" in src, mod.__file__
        assert "MAX_CLARIFICATIONS = 2" not in src
        assert "window_hours: float = 48" not in src
        assert "default 48" not in src
        assert "user_requested" not in src
