import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "dialog"))
# Support both repo layout (src.dialog.policy_engine) and flat layout
try:
    from src.dialog.policy_engine import (
        PolicyEngine, PolicyContext, PolicyAction, EscalationReason, MAX_CLARIFICATIONS)
except Exception:
    from policy_engine import (  # type: ignore
        PolicyEngine, PolicyContext, PolicyAction, EscalationReason, MAX_CLARIFICATIONS)


def eng():
    return PolicyEngine()


def test_normal_request_allowed_even_low_setup():
    d = eng().evaluate(PolicyContext(text="Đơn hàng của tôi đến đâu rồi?", confidence=0.95, intent="order_status", allowed_intents={"order_status"}))
    assert d.action == PolicyAction.ALLOW and not d.escalate

def test_hard_rule_wins_over_perfect_confidence_compensation():
    d = eng().evaluate(PolicyContext(text="Tôi yêu cầu bồi thường ngay", confidence=1.0))
    assert d.escalate and d.reason == EscalationReason.SENSITIVE
    assert d.allow_llm_negotiation is False

def test_hard_rule_wins_over_perfect_confidence_legal():
    d = eng().evaluate(PolicyContext(text="Tôi sẽ kiện công ty ra tòa án", confidence=0.99))
    assert d.escalate and d.priority in ("high", "critical")

def test_customer_request_human_keyword_and_flag():
    assert eng().evaluate(PolicyContext(text="Cho tôi gặp nhân viên người thật", confidence=0.99)).reason == EscalationReason.CUSTOMER_REQUEST
    assert eng().evaluate(PolicyContext(text="alo", customer_requested_human=True)).reason == EscalationReason.CUSTOMER_REQUEST

def test_unaccented_input_also_hits():
    d = eng().evaluate(PolicyContext(text="toi yeu cau boi thuong", confidence=0.99))
    assert d.escalate and d.rule_id == "compensation"

def test_repeated_clarification_over_contract_cap():
    d = eng().evaluate(PolicyContext(text="sao cơ?", clarification_count=MAX_CLARIFICATIONS + 1, confidence=0.99))
    assert d.escalate and d.reason == EscalationReason.REPEATED_CLARIFICATION
    # at cap, not over: still allowed
    assert not eng().evaluate(PolicyContext(text="sao cơ?", clarification_count=MAX_CLARIFICATIONS)).escalate

def test_out_of_scope_and_strong_negative_sentiment():
    d = eng().evaluate(PolicyContext(text="kể chuyện cười đi", intent="joke", allowed_intents={"order_status"}))
    assert d.escalate and d.reason == EscalationReason.OUT_OF_SCOPE
    d2 = eng().evaluate(PolicyContext(text="...", sentiment_score=-0.95, confidence=0.99))
    assert d2.escalate and d2.action == PolicyAction.ESCALATE_PRIORITY

def test_self_harm_is_critical_priority():
    d = eng().evaluate(PolicyContext(text="Tôi muốn chết, không muốn sống nữa", confidence=1.0))
    assert d.escalate and d.priority == "critical"

def test_sensitive_data_keywords_escalate():
    assert eng().evaluate(PolicyContext(text="Đây là mật khẩu và mã OTP của tôi")).escalate

def test_guard_response_blocks_compensation_negotiation():
    e = eng()
    assert not e.guard_response("Đơn của bạn đang trên đường giao.").escalate
    d = e.guard_response("Chúng tôi sẽ bồi thường cho bạn 500 nghìn.")
    assert d.escalate and d.allow_llm_negotiation is False

def test_guard_response_blocks_legal_commitment():
    assert eng().guard_response("Chúng tôi cam kết pháp lý sẽ thắng cho bạn.").escalate

def test_apply_gate_hard_rule_wins_when_gate_allows():
    d = eng().apply_gate(PolicyContext(text="Tôi yêu cầu bồi thường", confidence=1.0), gate_allows=True)
    assert d.escalate and d.rule_id == "compensation"
    d2 = eng().apply_gate(PolicyContext(text="Tra đơn giúp tôi", confidence=0.1), gate_allows=False)
    assert d2.escalate and d2.reason == EscalationReason.LOW_CONFIDENCE

def test_audit_log_recorded_with_reason():
    e = eng(); e.evaluate(PolicyContext(text="Cho gặp nhân viên", tenant_id="shop1"))
    assert e.audit_log and e.audit_log[-1]["reason"] == "customer_request"
    assert e.audit_log[-1]["tenant_id"] == "shop1"

def test_tenant_cannot_raise_clarification_cap_or_disable_hard_rules():
    e = PolicyEngine(tenant_config={"max_clarifications": 99})
    assert e.max_clarifications <= MAX_CLARIFICATIONS
    assert e.evaluate(PolicyContext(text="Tôi sẽ kiện", confidence=1.0)).escalate
