"""Tests for fix/fix_missing_grounded_answer.

Stdlib-only (pytest). Golden cases: (1) no record, (2) contradictory
records, (3) missing required field, (4) mismatched numbers — plus
happy paths, whitelist/blacklist and stale policy.
Intent names follow dialogue_manager's Intent enum
(order_tracking / shipping_fee / return_exchange / warranty /
book_appointment); payloads use the tool-gateway field names
(order_code, not order_id). Repo-root layout: run from the repo
root, after the reconciled src/contracts.py v1.0.0 is on main.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.grounding.grounded_answer import (  # noqa: E402
    APOLOGY_HANDOFF_TEXT,
    AnswerStatus,
    Evidence,
    GroundedAnswerer,
    extract_dates,
    extract_numbers,
    normalize_date,
    normalize_number,
)


def order_evidence(**overrides):
    payload = {"order_code": "DH123", "status": "đang giao", "eta_date": "26/11/2026"}
    payload.update(overrides)
    return Evidence(source="oms.get_order", source_id="DH123", kind="order",
                    payload=payload, queried_at="2026-11-22T10:00:00+07:00")


def fee_evidence(amount=35000):
    return Evidence(source="oms.get_fee", source_id="DH123", kind="order",
                    payload={"order_code": "DH123", "amount": amount},
                    queried_at="2026-11-22T10:00:00+07:00")


# --- happy paths ----------------------------------------------------------

def test_happy_path_order_tracking_rendered_from_evidence_with_citation():
    ans = GroundedAnswerer().answer_from_evidence("order_tracking", [order_evidence()])
    assert ans.status == AnswerStatus.ANSWERED
    assert ans.speakable
    assert "DH123" in ans.text and "đang giao" in ans.text and "26/11/2026" in ans.text
    assert ans.citations == ["oms.get_order:DH123 queried_at=2026-11-22T10:00:00+07:00"]
    assert ans.reason == "rendered_from_evidence"


def test_happy_path_draft_verified_when_numbers_match():
    ans = GroundedAnswerer().verify_draft(
        "shipping_fee", [fee_evidence(35000)],
        "Phí giao hàng là 35000 đồng ạ.")
    assert ans.status == AnswerStatus.ANSWERED
    assert ans.speakable


def test_money_normalisation_350_000_equals_350000():
    assert normalize_number("350.000") == 350000.0
    assert normalize_number("350,000") == 350000.0
    assert normalize_number("350k") == 350000.0
    assert normalize_date("25/11/2026") == "2026-11-25"
    assert normalize_date("2026-11-25") == "2026-11-25"
    assert extract_numbers("Phí 350.000 đồng") == [350000.0]
    assert extract_dates("giao ngày 26/11/2026") == ["2026-11-26"]


# --- golden case 1: no record ----------------------------------------------

def test_golden_no_record_returns_unknown_with_reason():
    ans = GroundedAnswerer().answer_from_evidence("order_tracking", [])
    assert ans.status == AnswerStatus.UNKNOWN
    assert ans.reason == "no_record"
    assert ans.escalation_reason == "out_of_scope"
    assert not ans.speakable
    assert ans.text == APOLOGY_HANDOFF_TEXT
    # Same for a draft: an LLM must not invent an order that does not exist.
    ans2 = GroundedAnswerer().verify_draft(
        "order_tracking", [], "Đơn DH999 đang giao ạ.")
    assert ans2.status == AnswerStatus.UNKNOWN
    assert ans2.reason == "no_record"


# --- golden case 2: contradictory records -----------------------------------

def test_golden_contradictory_records_rejected():
    ev1 = order_evidence(status="đang giao")
    ev2 = order_evidence(status="đã giao")
    ans = GroundedAnswerer().answer_from_evidence("order_tracking", [ev1, ev2])
    assert ans.status == AnswerStatus.REJECTED
    assert ans.reason.startswith("contradictory_evidence")
    assert ans.escalation_reason == "low_confidence"
    assert not ans.speakable
    assert ans.text == APOLOGY_HANDOFF_TEXT


# --- golden case 3: missing required field ----------------------------------

def test_golden_missing_required_field_returns_unknown():
    ev = Evidence(source="oms.get_order", source_id="DH123", kind="order",
                  payload={"order_code": "DH123"},  # no "status"
                  queried_at="2026-11-22T10:00:00+07:00")
    ans = GroundedAnswerer().answer_from_evidence("order_tracking", [ev])
    assert ans.status == AnswerStatus.UNKNOWN
    assert ans.reason == "missing_required_field:status"
    assert not ans.speakable
    assert ans.text == APOLOGY_HANDOFF_TEXT


# --- golden case 4: mismatched numbers ---------------------------------------

def test_golden_mismatched_amount_blocked_and_handed_off():
    ans = GroundedAnswerer().verify_draft(
        "shipping_fee", [fee_evidence(35000)],
        "Phí giao hàng là 50000 đồng ạ.")
    assert ans.status == AnswerStatus.REJECTED
    assert ans.reason.startswith("numeric_mismatch")
    assert not ans.speakable
    assert ans.text == APOLOGY_HANDOFF_TEXT
    assert "50000" not in ans.text  # the wrong number must never be spoken


def test_golden_mismatched_date_blocked():
    ans = GroundedAnswerer().verify_draft(
        "order_tracking", [order_evidence()],
        "Đơn DH123 dự kiến giao ngày 30/11/2026.")
    assert ans.status == AnswerStatus.REJECTED
    assert ans.reason.startswith("date_mismatch")


def test_golden_mismatched_order_code_blocked():
    ans = GroundedAnswerer().verify_draft(
        "order_tracking", [order_evidence()],
        "Đơn DH999 hiện đang giao.")
    assert ans.status == AnswerStatus.REJECTED
    assert ans.reason.startswith("code_mismatch")


# --- whitelist / blacklist / stale policy -------------------------------------

def test_intent_not_whitelisted_is_out_of_scope():
    ans = GroundedAnswerer().answer_from_evidence("chit_chat", [order_evidence()])
    assert ans.status == AnswerStatus.UNKNOWN
    assert ans.reason == "intent_not_whitelisted"
    assert ans.escalation_reason == "out_of_scope"


def test_sensitive_intent_and_topic_rejected():
    ans = GroundedAnswerer().answer_from_evidence("compensation", [order_evidence()])
    assert ans.status == AnswerStatus.REJECTED
    assert ans.escalation_reason == "sensitive"
    ans2 = GroundedAnswerer().verify_draft(
        "order_tracking", [order_evidence()],
        "Em sẽ bồi thường cho anh chị 50000 đồng.")
    assert ans2.status == AnswerStatus.REJECTED
    assert ans2.reason == "sensitive_topic"


def test_stale_policy_version_rejected():
    ev = Evidence(source="kb.get_policy", source_id="return-v3", kind="policy",
                  payload={"snippet": "Đổi trả trong 7 ngày."},
                  policy_version="v2")
    ans = GroundedAnswerer(current_policy_version="v3").answer_from_evidence(
        "return_exchange", [ev])
    assert ans.status == AnswerStatus.REJECTED
    assert ans.reason == "stale_policy"


def test_current_policy_version_passes_and_cites_version():
    ev = Evidence(source="kb.get_policy", source_id="return-v3", kind="policy",
                  payload={"snippet": "Đổi trả trong 7 ngày."},
                  policy_version="v3")
    ans = GroundedAnswerer(current_policy_version="v3").answer_from_evidence(
        "return_exchange", [ev])
    assert ans.status == AnswerStatus.ANSWERED
    assert "Đổi trả trong 7 ngày." in ans.text
    assert "policy_version=v3" in ans.citations[0]
