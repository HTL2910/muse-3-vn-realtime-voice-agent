"""Tests for fix_missing_sme_onboarding_hub (approach_14, P1).

Checks: adapter registry with the common interface for all prebuilt
connectors, health-check (incl. missing config), UI field mapping +
normalisation, in-wizard test query, data-quality warnings/errors,
the ordered 5-step wizard, and go-live gating (blocked by incomplete
steps, failing test call, or garbage order data).
Portable: repo root derived from this file, no hardcoded paths.
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "sme_onboarding_hub", ROOT / "src" / "integrations" / "sme_onboarding_hub.py")
hub = importlib.util.module_from_spec(_spec)
sys.modules["sme_onboarding_hub"] = hub
_spec.loader.exec_module(hub)

FAQ = [{"question": "Đổi trả trong bao lâu?", "answer": "Trong 7 ngày."},
       {"question": "Phí ship bao nhiêu?", "answer": "25000 đồng nội thành."}]
RULES = {"sensitive": "transfer_priority", "customer_request": "transfer",
         "out_of_scope": "transfer"}
HOURS = {"open": "08:00", "close": "22:00"}
SHOPIFY_CFG = {"shop_domain": "shop.myshopify.com", "access_token": "x"}


def test_registry_has_all_prebuilt_connectors():
    names = {a["name"] for a in hub.AdapterRegistry().list_adapters()}
    assert {"shopify", "haravan", "sapo", "pancake", "kiotviet",
            "google_sheets", "rest_webhook"} <= names


def test_unknown_adapter_rejected():
    try:
        hub.AdapterRegistry().create("lazada_clone")
        raise AssertionError("unknown adapter accepted")
    except ValueError:
        pass


def test_health_check_missing_config():
    a = hub.AdapterRegistry().create("shopify", config={})
    h = a.health_check()
    assert not h.ok and set(h.missing_config) == {"shop_domain", "access_token"}


def test_health_check_sandbox_ok_with_config():
    a = hub.AdapterRegistry().create("kiotviet", config={
        "retailer": "shop", "client_id": "i", "client_secret": "s"})
    assert a.health_check().ok and a.sandbox


def test_field_mapping_normalises_to_canonical_order():
    a = hub.AdapterRegistry().create("haravan", config={
        "shop_domain": "s", "access_token": "t"})
    r = a.test_query()
    assert r.ok and r.records
    rec = r.records[0]
    assert rec["order_code"] == "HR200001"
    assert rec["phone"] == "0912345678"
    assert set(hub.REQUIRED_ORDER_FIELDS) <= set(rec)


def test_mapping_missing_required_field_fails_test_query():
    a = hub.AdapterRegistry().create(
        "shopify", config=SHOPIFY_CFG, mapping={"id": "order_code"})
    r = a.test_query()
    assert not r.ok and "unmapped_required_field" in r.detail


def test_google_sheets_import_with_vietnamese_headers():
    rows = [{"Mã đơn": "GS1", "SĐT": "0901112223", "Trạng thái": "new",
             "Tổng tiền": 100000, "Tên khách": "A", "Ngày tạo": "2026-11-22"}]
    a = hub.AdapterRegistry().create("google_sheets", rows=rows)
    r = a.test_query()
    assert r.ok and r.records[0]["order_code"] == "GS1"
    assert r.records[0]["phone"] == "0901112223"


def test_data_quality_flags_garbage():
    records = [
        {"order_code": "D1", "phone": "0901234567", "status": "new", "total": 10},
        {"order_code": "D1", "phone": "123", "status": "new", "total": -5},
        {"phone": "0901234567", "status": "new"},
    ]
    rep = hub.data_quality_report(records)
    assert not rep["ok"]
    assert any("duplicate_order_code" in e for e in rep["errors"])
    assert any("negative_total" in e for e in rep["errors"])
    assert any("missing_order_code" in e for e in rep["errors"])
    assert any("bad_phone_format" in w for w in rep["warnings"])


def _wizard_through_step4():
    w = hub.OnboardingWizard("tenant-1")
    w.complete_telephony("cloud_pbx", "19001234")
    w.connect_data_source("shopify", config=SHOPIFY_CFG)
    w.import_knowledge(FAQ)
    w.configure_escalation(RULES, HOURS)
    return w


def test_wizard_steps_cannot_be_skipped():
    w = hub.OnboardingWizard("t")
    try:
        w.import_knowledge(FAQ)  # step 3 before step 1
        raise AssertionError("out-of-order step accepted")
    except ValueError:
        pass
    assert w.progress()["current"] == "1_telephony"
    assert w.progress()["total_steps"] == 5


def test_wizard_full_happy_path_goes_live_with_just_orders_and_faq():
    w = _wizard_through_step4()
    assert w.run_test_call() is True
    out = w.go_live()
    assert out.live and w.live
    assert w.progress()["current"] is None


def test_go_live_blocked_before_test_call():
    w = _wizard_through_step4()
    out = w.go_live()
    assert not out.live and "test_call_not_passed" in out.blocked_reasons


def test_go_live_blocked_by_garbage_order_data():
    w = _wizard_through_step4()
    w.order_records.append({"order_code": "DH100001", "phone": "0901234567",
                            "status": "x"})  # duplicate of sandbox order
    w.run_test_call()
    out = w.go_live()
    assert not out.live
    assert any("order_data_errors" in b for b in out.blocked_reasons)


def test_step2_rejects_unhealthy_connector():
    w = hub.OnboardingWizard("t")
    w.complete_telephony("sip", "19009999", sip_trunk="trunk-1")
    try:
        w.connect_data_source("shopify", config={})  # missing credentials
        raise AssertionError("unhealthy connector accepted")
    except ValueError:
        pass


def test_step3_rejects_empty_faq_answers():
    w = hub.OnboardingWizard("t")
    w.complete_telephony("cloud_pbx", "19001234")
    w.connect_data_source("google_sheets")
    try:
        w.import_knowledge([{"question": "Hỏi?", "answer": "  "}])
        raise AssertionError("empty FAQ accepted")
    except ValueError:
        pass


def test_step4_requires_sensitive_and_customer_request_rules():
    w = hub.OnboardingWizard("t")
    w.complete_telephony("cloud_pbx", "19001234")
    w.connect_data_source("google_sheets")
    w.import_knowledge(FAQ)
    try:
        w.configure_escalation({"out_of_scope": "transfer"}, HOURS)
        raise AssertionError("incomplete rules accepted")
    except ValueError:
        pass


def test_live_transport_health_failure_is_unhealthy():
    def dead_transport(action, payload):
        raise RuntimeError("connection refused")

    a = hub.AdapterRegistry().create("sapo", config={
        "shop_domain": "s", "api_key": "k"}, transport=dead_transport)
    assert not a.health_check().ok


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("PASS", fn.__name__)
    print(f"{len(fns)} passed")
