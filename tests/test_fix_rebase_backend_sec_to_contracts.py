"""Rebase verification: policy_engine must follow contracts v1.0.0.

Key locked values: MAX_CLARIFICATIONS == 1 (was 2 pre-rebase),
EscalationReason snake_case incl. customer_request, hard rule wins gate.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from src.dialog.policy_engine import (
        PolicyEngine, PolicyContext, PolicyAction, EscalationReason, MAX_CLARIFICATIONS)
    import src.dialog.policy_engine as pe
except Exception:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "dialog"))
    from policy_engine import (  # type: ignore
        PolicyEngine, PolicyContext, PolicyAction, EscalationReason, MAX_CLARIFICATIONS)
    import policy_engine as pe  # type: ignore


def test_max_clarifications_is_contracts_v1_value_1():
    assert MAX_CLARIFICATIONS == 1
    assert PolicyEngine().max_clarifications == 1

def test_no_divergent_local_constant_in_source():
    src = open(pe.__file__, encoding="utf-8").read()
    assert "MAX_CLARIFICATIONS = 2" not in src
    assert "MAX_CLARIFICATIONS=2" not in src

def test_clarification_boundary_at_one():
    e = PolicyEngine()
    # 1 clarification already used: still allowed to proceed
    assert not e.evaluate(PolicyContext(text="sao cơ?", clarification_count=1)).escalate
    # beyond the single allowed clarification: escalate
    d = e.evaluate(PolicyContext(text="sao cơ?", clarification_count=2, confidence=0.99))
    assert d.escalate and d.reason == EscalationReason.REPEATED_CLARIFICATION

def test_tenant_cannot_raise_cap_above_contracts():
    e = PolicyEngine(tenant_config={"max_clarifications": 99})
    assert e.max_clarifications == 1

def test_reason_codes_are_locked_snake_case():
    vals = {r.value for r in EscalationReason}
    assert vals == {"out_of_scope", "low_confidence", "sensitive",
                    "customer_request", "repeated_clarification", "repeated_failure"}
    assert "user_requested" not in vals and "OUT_OF_SCOPE" not in vals

def test_hard_rule_still_wins_over_gate_after_rebase():
    e = PolicyEngine()
    d = e.apply_gate(PolicyContext(text="Tôi yêu cầu bồi thường", confidence=1.0), gate_allows=True)
    assert d.escalate and d.rule_id == "compensation" and d.allow_llm_negotiation is False
    d2 = e.apply_gate(PolicyContext(text="Tôi sẽ kiện ra tòa án", confidence=1.0), gate_allows=True)
    assert d2.escalate

def test_normal_call_still_allowed_after_rebase():
    d = PolicyEngine().evaluate(PolicyContext(
        text="Đơn hàng của tôi đến đâu rồi?", confidence=0.95,
        intent="order_status", allowed_intents={"order_status"}))
    assert d.action == PolicyAction.ALLOW and not d.escalate

def test_audit_still_records_reason():
    e = PolicyEngine(); e.evaluate(PolicyContext(text="Cho gặp nhân viên", tenant_id="shop1"))
    assert e.audit_log[-1]["reason"] == "customer_request"
