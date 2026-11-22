import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.grounding.tool_gateway import (
    ToolGateway, AuthenticatedSession, TransientError, TOOL_SCHEMAS)

ORDERS = {
    ("shopA", "DH001"): {"data": {"status": "delivering"}, "owner_phone": "0901234567",
                         "record_tenant_id": "shopA", "source_id": "oms",
                         "record_id": "DH001", "updated_at": "2026-11-22T10:00:00+07:00"},
    ("shopB", "DH002"): {"data": {"status": "paid"}, "owner_phone": "0909999999",
                         "record_tenant_id": "shopB", "source_id": "oms",
                         "record_id": "DH002", "updated_at": "2026-11-22T10:00:00+07:00"},
}

def order_adapter(tenant_id, shop_id, **params):
    rec = ORDERS.get((tenant_id, params["order_code"]))
    if rec is None:
        for (t, code), r in ORDERS.items():
            if code == params["order_code"]:
                return dict(r)
        return None
    return dict(rec)

def policy_adapter(tenant_id, shop_id, **params):
    return {"data": {"text": "Doi tra trong 7 ngay"}, "source_id": "kb:policy@v3",
            "record_id": "return-policy", "updated_at": "2026-11-01T00:00:00+07:00"}

def ticket_adapter(tenant_id, shop_id, **params):
    return {"data": {"ticket_id": 42}, "source_id": "crm",
            "record_id": "ticket-42", "updated_at": "2026-11-22T10:00:00+07:00"}

def gw():
    return ToolGateway(adapters={"get_order_status": order_adapter,
                                 "get_policy": policy_adapter,
                                 "create_callback_ticket": ticket_adapter})

def sess(tenant="shopA"):
    return AuthenticatedSession(session_id="s1", tenant_id=tenant, shop_id=tenant,
                                caller_phone="0901234567")

def test_unknown_tool_rejected():
    r = gw().call(sess(), "delete_all_orders", {})
    assert not r.ok and r.status == "rejected" and r.error == "unknown_tool"

def test_missing_tenant_rejected():
    assert not gw().call(None, "get_policy", {"topic": "return"}).ok
    s = sess(); s.authenticated = False
    assert gw().call(s, "get_policy", {"topic": "return"}).error == "missing_tenant"
    s2 = sess(); s2.tenant_id = ""
    assert not gw().call(s2, "get_policy", {"topic": "return"}).ok

def test_tenant_override_from_params_rejected():
    r = gw().call(sess("shopA"), "get_order_status",
                  {"order_code": "DH001", "phone_suffix": "567", "tenant_id": "shopB"})
    assert not r.ok and r.error == "tenant_override_attempt" and r.data == {}

def test_wrong_phone_suffix_returns_no_data():
    r = gw().call(sess(), "get_order_status", {"order_code": "DH001", "phone_suffix": "999"})
    assert not r.ok and r.error == "ownership_check_failed" and r.data == {} and r.evidence == []

def test_cross_tenant_record_rejected():
    r = gw().call(sess("shopA"), "get_order_status", {"order_code": "DH002", "phone_suffix": "999"})
    assert not r.ok and r.error in ("cross_tenant_record", "ownership_check_failed") and r.data == {}

def test_correct_lookup_returns_evidence():
    r = gw().call(sess(), "get_order_status", {"order_code": "DH001", "phone_suffix": "567"})
    assert r.ok and r.data == {"status": "delivering"}
    ev = r.evidence[0]
    assert ev["source_id"] == "oms" and ev["record_id"] == "DH001" and ev["updated_at"]

def test_schema_missing_and_extra_fields_rejected():
    assert gw().call(sess(), "get_order_status", {"order_code": "DH001"}).error.startswith("schema_violation_missing")
    assert gw().call(sess(), "get_policy", {"topic": "return", "admin": True}).error.startswith("schema_violation_extra")

def test_suspicious_sql_param_rejected():
    r = gw().call(sess(), "get_policy", {"topic": "return; SELECT * FROM orders"})
    assert not r.ok and r.error == "suspicious_params"

def test_timeout_config_must_be_800_to_1500():
    for bad in (100, 5000):
        try:
            ToolGateway(timeouts_ms={"get_policy": bad}); assert False
        except ValueError:
            pass
    ToolGateway(timeouts_ms={"get_policy": 1200})

def test_transient_error_retried_then_ok_and_nontransient_not():
    calls = {"n": 0}
    def flaky(tenant_id, shop_id, **params):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientError("502")
        return policy_adapter(tenant_id, shop_id, **params)
    g = ToolGateway(adapters={"get_policy": flaky}, max_retries=1)
    assert g.call(sess(), "get_policy", {"topic": "return"}).ok and calls["n"] == 2
    calls2 = {"n": 0}
    def broken(tenant_id, shop_id, **params):
        calls2["n"] += 1; raise RuntimeError("bug")
    g2 = ToolGateway(adapters={"get_policy": broken}, max_retries=3)
    r = g2.call(sess(), "get_policy", {"topic": "return"})
    assert not r.ok and calls2["n"] == 1

def test_missing_evidence_is_error_not_answer():
    def bare(tenant_id, shop_id, **params):
        return {"data": {"text": "khong nguon"}}
    g = ToolGateway(adapters={"get_policy": bare})
    r = g.call(sess(), "get_policy", {"topic": "return"})
    assert not r.ok and r.error == "missing_evidence" and r.evidence == []

def test_create_callback_ticket_idempotent_and_policy_cache():
    g = gw()
    p = {"phone": "0901234567", "summary": "goi lai", "idempotency_key": "k-1"}
    a = g.call(sess(), "create_callback_ticket", p)
    b = g.call(sess(), "create_callback_ticket", p)
    assert a.ok and b.ok and b.deduplicated
    r1 = g.call(sess(), "get_policy", {"topic": "return"})
    r2 = g.call(sess(), "get_policy", {"topic": "return"})
    assert r1.ok and r2.ok and r1.evidence == r2.evidence
    assert set(TOOL_SCHEMAS) == {"get_order_status", "get_inventory", "get_appointment",
                                 "get_policy", "create_callback_ticket"}
