"""Tests for fix_missing_dialogue_manager (approach_04).

Covers every intent, missing-slot clarification with the contracts limit
MAX_CLARIFICATIONS = 1 (second failure escalates with
``repeated_clarification``), slot correction, follow-ups, returning to a
previous topic, state serialisation and playbook tool gating.
Portable: repo root derived from this file, no hardcoded paths.
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "dialogue_manager", ROOT / "src" / "dialogue" / "dialogue_manager.py")
dm = importlib.util.module_from_spec(_spec)
sys.modules["dialogue_manager"] = dm
_spec.loader.exec_module(dm)

DialogueManager = dm.DialogueManager
Intent = dm.Intent
Action = dm.DialogueAction


def mgr():
    return DialogueManager()


def test_contracts_clarification_limit_is_one():
    assert dm.MAX_CLARIFICATIONS == 1


def test_order_tracking_with_code_is_ready():
    m = mgr(); s = m.new_state(call_id="c1")
    r = m.process_turn(s, "Tra cứu đơn hàng mã đơn là DH123456 giúp tôi")
    assert r.intent is Intent.ORDER_TRACKING
    assert r.action is Action.READY_FOR_TOOL
    assert r.slots["order_code"] == "DH123456"
    assert "get_order" in r.allowed_tools


def test_order_tracking_missing_code_clarifies_once_then_escalates():
    m = mgr(); s = m.new_state()
    r1 = m.process_turn(s, "Tôi muốn kiểm tra đơn hàng của tôi")
    assert r1.action is Action.ASK_CLARIFICATION
    assert "order_code" in r1.missing_slots and r1.prompt
    r2 = m.process_turn(s, "Tôi không nhớ nữa")
    assert r2.action is Action.ESCALATE
    assert r2.escalation_reason == "repeated_clarification"


def test_missing_slot_filled_on_clarification_turn():
    m = mgr(); s = m.new_state()
    m.process_turn(s, "Kiểm tra đơn hàng của tôi")
    r = m.process_turn(s, "Mã đơn là DH998877")
    assert r.action is Action.READY_FOR_TOOL
    assert r.slots["order_code"] == "DH998877"


def test_shipping_fee_intent_needs_address():
    m = mgr(); s = m.new_state()
    r = m.process_turn(s, "Phí ship về Hà Nội là bao nhiêu?")
    # No deliver-to address captured -> clarify, not guess a fee.
    assert r.intent is Intent.SHIPPING_FEE
    assert r.action is Action.ASK_CLARIFICATION
    r2 = m.process_turn(s, "Giao tới quận Hoàn Kiếm, Hà Nội")
    assert r2.action is Action.READY_FOR_TOOL
    assert r2.slots.get("address")


def test_return_exchange_intent_and_playbook():
    m = mgr(); s = m.new_state()
    r = m.process_turn(s, "Tôi muốn đổi trả sản phẩm, mã đơn DH111222")
    assert r.intent is Intent.RETURN_EXCHANGE
    assert r.action is Action.READY_FOR_TOOL
    assert "get_return_policy" in r.allowed_tools


def test_warranty_intent():
    m = mgr(); s = m.new_state()
    r = m.process_turn(s, "Sản phẩm còn bảo hành không, mã đơn DH222333")
    assert r.intent is Intent.WARRANTY
    assert r.action is Action.READY_FOR_TOOL


def test_book_appointment_needs_time_and_phone():
    m = mgr(); s = m.new_state()
    r = m.process_turn(s, "Tôi muốn đặt lịch hẹn")
    assert r.intent is Intent.BOOK_APPOINTMENT
    assert set(r.missing_slots) == {"appointment_time", "phone"}
    r2 = m.process_turn(s, "Ngày mai 9 giờ, số của tôi 0901234567")
    assert r2.action is Action.READY_FOR_TOOL
    assert r2.slots["phone"] == "0901234567"
    assert r2.slots["appointment_time"]


def test_confirm_info_intent_needs_phone_not_order_code():
    m = mgr(); s = m.new_state()
    r = m.process_turn(s, "Xác nhận thông tin của tôi, số 0912345678")
    assert r.intent is Intent.CONFIRM_INFO
    assert r.action is Action.READY_FOR_TOOL
    # Phone must not be misread as an order code.
    assert "order_code" not in r.slots


def test_unknown_intent_clarifies_once_then_escalates():
    m = mgr(); s = m.new_state()
    r1 = m.process_turn(s, "Hôm nay trời đẹp quá nhỉ")
    assert r1.action is Action.ASK_CLARIFICATION
    r2 = m.process_turn(s, "Ừ đúng vậy")
    assert r2.action is Action.ESCALATE
    assert r2.escalation_reason == "repeated_clarification"


def test_slot_correction_overrides_old_value():
    m = mgr(); s = m.new_state()
    m.process_turn(s, "Tra đơn mã đơn DH111111")
    r = m.process_turn(s, "Không phải, sửa thành DH222222")
    assert r.slots["order_code"] == "DH222222"
    assert "slot_correction" in s.steps_tried


def test_followup_switches_intent_but_keeps_order_code_and_can_return():
    m = mgr(); s = m.new_state()
    m.process_turn(s, "Tra cứu đơn mã đơn DH333444")
    r = m.process_turn(s, "Thế còn phí ship thì sao, giao tới Đà Nẵng")
    assert r.intent is Intent.SHIPPING_FEE
    assert s.topic_stack and s.topic_stack[-1]["intent"] == "order_tracking"
    r2 = m.process_turn(s, "Quay lại chuyện đơn hàng trước đi")
    assert r2.intent is Intent.ORDER_TRACKING
    assert r2.action is Action.READY_FOR_TOOL
    assert r2.slots["order_code"] == "DH333444"


def test_frustration_is_tracked_in_state():
    m = mgr(); s = m.new_state()
    m.process_turn(s, "Chờ quá lâu rồi, dịch vụ tệ quá, mã đơn DH555666")
    assert s.frustration_level >= 1


def test_tool_result_must_be_allowed_by_playbook():
    m = mgr(); s = m.new_state()
    m.process_turn(s, "Tra đơn mã đơn DH777888")
    m.record_tool_result(s, "get_order", {"status": "shipping"})
    assert s.looked_up_data["get_order"]["status"] == "shipping"
    try:
        m.record_tool_result(s, "book_appointment", {})
        raise AssertionError("disallowed tool was accepted")
    except ValueError:
        pass


def test_state_roundtrip_serialisation():
    m = mgr(); s = m.new_state(call_id="c9", tenant_id="shop1")
    m.process_turn(s, "Tra đơn mã đơn DH999000")
    d = s.to_dict()
    s2 = dm.DialogueState.from_dict(d)
    assert s2.intent is Intent.ORDER_TRACKING
    assert s2.slots["order_code"] == "DH999000"
    assert s2.schema_version == dm.STATE_SCHEMA_VERSION


def test_playbooks_are_versioned_and_complete():
    for intent in (Intent.ORDER_TRACKING, Intent.SHIPPING_FEE,
                   Intent.RETURN_EXCHANGE, Intent.WARRANTY,
                   Intent.BOOK_APPOINTMENT, Intent.CONFIRM_INFO):
        pb = dm.get_playbook(intent)
        assert pb.allowed_tools and pb.answer_template and pb.exit_conditions
    assert dm.INTENT_SCHEMA_VERSION and dm.SLOT_SCHEMA_VERSION


def test_llm_classifier_cannot_override_clear_keyword_intent():
    m = DialogueManager(llm_classifier=lambda t: "book_appointment")
    s = m.new_state()
    r = m.process_turn(s, "Tra cứu đơn hàng mã đơn DH123123")
    assert r.intent is Intent.ORDER_TRACKING


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("PASS", fn.__name__)
    print(f"{len(fns)} passed")
