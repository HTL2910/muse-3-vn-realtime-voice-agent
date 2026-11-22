import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.dialog.policy_engine import PolicyEngine, PolicyContext, PolicyAction
from src.contracts import EscalationReason, MAX_CLARIFICATIONS


def eng():
    return PolicyEngine()

def test_contracts_values_are_locked_v1():
    assert MAX_CLARIFICATIONS == 1
    assert {r.value for r in EscalationReason} == {
        "out_of_scope", "low_confidence", "sensitive",
        "customer_request", "repeated_clarification", "repeated_failure"}

def test_normal_request_allowed():
    d = eng().evaluate(PolicyContext(text="Don hang cua toi den dau roi?", confidence=0.95, intent="order_status", allowed_intents={"order_status"}))
    assert d.action == PolicyAction.ALLOW and not d.escalate

def test_hard_rule_wins_over_perfect_confidence_compensation():
    d = eng().evaluate(PolicyContext(text="Toi yeu cau boi thuong ngay", confidence=1.0))
    assert d.escalate and d.reason == EscalationReason.SENSITIVE and d.allow_llm_negotiation is False

def test_hard_rule_wins_over_perfect_confidence_legal():
    d = eng().evaluate(PolicyContext(text="Toi se kien cong ty ra toa an", confidence=0.99))
    assert d.escalate and d.priority in ("high", "critical")

def test_customer_request_human_keyword_and_flag():
    assert eng().evaluate(PolicyContext(text="Cho toi gap nhan vien nguoi that", confidence=0.99)).reason == EscalationReason.CUSTOMER_REQUEST
    assert eng().evaluate(PolicyContext(text="alo", customer_requested_human=True)).reason == EscalationReason.CUSTOMER_REQUEST

def test_unaccented_input_also_hits():
    d = eng().evaluate(PolicyContext(text="toi yeu cau boi thuong", confidence=0.99))
    assert d.escalate and d.rule_id == "compensation"

def test_clarification_boundary_at_contract_cap_1():
    e = eng()
    assert not e.evaluate(PolicyContext(text="sao co?", clarification_count=1)).escalate
    d = e.evaluate(PolicyContext(text="sao co?", clarification_count=2, confidence=0.99))
    assert d.escalate and d.reason == EscalationReason.REPEATED_CLARIFICATION

def test_tenant_cannot_raise_cap_above_contracts():
    assert PolicyEngine(tenant_config={"max_clarifications": 99}).max_clarifications == 1

def test_out_of_scope_and_strong_negative_sentiment():
    d = eng().evaluate(PolicyContext(text="ke chuyen cuoi di", intent="joke", allowed_intents={"order_status"}))
    assert d.escalate and d.reason == EscalationReason.OUT_OF_SCOPE
    d2 = eng().evaluate(PolicyContext(text="...", sentiment_score=-0.95, confidence=0.99))
    assert d2.escalate and d2.action == PolicyAction.ESCALATE_PRIORITY

def test_self_harm_is_critical_priority():
    d = eng().evaluate(PolicyContext(text="Toi muon chet, khong muon song nua", confidence=1.0))
    assert d.escalate and d.priority == "critical"

def test_sensitive_data_keywords_escalate():
    assert eng().evaluate(PolicyContext(text="Day la mat khau va ma OTP cua toi")).escalate

def test_angry_complaint_escalates_priority():
    d = eng().evaluate(PolicyContext(text="Cong ty lua dao, toi se tay chay va dang facebook phot", confidence=0.99))
    assert d.escalate and d.action == PolicyAction.ESCALATE_PRIORITY

def test_guard_response_blocks_compensation_negotiation():
    e = eng()
    assert not e.guard_response("Don cua ban dang tren duong giao.").escalate
    d = e.guard_response("Chung toi se boi thuong cho ban 500 nghin.")
    assert d.escalate and d.allow_llm_negotiation is False

def test_guard_response_blocks_legal_commitment():
    assert eng().guard_response("Chung toi cam ket phap ly se thang cho ban.").escalate

def test_apply_gate_hard_rule_wins_when_gate_allows():
    d = eng().apply_gate(PolicyContext(text="Toi yeu cau boi thuong", confidence=1.0), gate_allows=True)
    assert d.escalate and d.rule_id == "compensation"
    d2 = eng().apply_gate(PolicyContext(text="Tra don giup toi", confidence=0.1), gate_allows=False)
    assert d2.escalate and d2.reason == EscalationReason.LOW_CONFIDENCE

def test_audit_log_recorded_with_reason_and_version():
    e = eng(); e.evaluate(PolicyContext(text="Cho gap nhan vien", tenant_id="shop1"))
    assert e.audit_log[-1]["reason"] == "customer_request"
    assert e.audit_log[-1]["tenant_id"] == "shop1" and "contracts_version" in e.audit_log[-1]
