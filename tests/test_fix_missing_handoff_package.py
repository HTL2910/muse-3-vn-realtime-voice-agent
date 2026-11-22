"""Tests for fix_missing_handoff_package (approach_10).

Checks: contracts-shaped package, 3-part summary validated against the
transcript/evidence (fabricated facts rejected, safe fallback used),
one-screen Agent Desktop card with time-to-context far under 5s,
accept/push-back + notes on the same ticket, and the no-agent case
creating a callback ticket instead of a dead end.
Portable: repo root derived from this file, no hardcoded paths.
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "context_package", ROOT / "src" / "handoff" / "context_package.py")
cp = importlib.util.module_from_spec(_spec)
sys.modules["context_package"] = cp
_spec.loader.exec_module(cp)


def make_pkg(**over):
    base = dict(
        call_id="call-1", escalation_reason="sensitive", tenant_id="shop1",
        customer_id="cust-1", phone="0901234567",
        verified_customer={"name": "Anh Minh", "phone_verified": True,
                           "order_verified": True},
        intent="complaint", unresolved_needs=["xử lý khiếu nại đơn DH123456"],
        slots={"order_code": "DH123456"},
        transcript=[
            cp.TranscriptEntry("customer", "Đơn DH123456 giao sai, tôi rất bực", 12.0),
            cp.TranscriptEntry("agent_ai", "Em kiểm tra đơn giúp anh ạ", 20.0),
        ],
        tool_calls=[cp.ToolCallRecord(
            "get_order", {"order_code": "DH123456"},
            {"status": "delivered_wrong_item"}, timestamp=25.0, duration_ms=300)],
        recording_url="https://rec.example/call-1.wav",
        priority="high", sentiment="angry", urgency="high",
        frustration_level=3, ticket_id="CB-000001",
    )
    base.update(over)
    return cp.ContextPackage(**base)


def test_package_rejects_non_snake_case_reason():
    try:
        make_pkg(escalation_reason="SENSITIVE")
        raise AssertionError("invalid reason accepted")
    except ValueError:
        pass


def test_transcript_entry_requires_timestamp():
    try:
        cp.TranscriptEntry("customer", "alo", None)
        raise AssertionError("timestamp-less entry accepted")
    except ValueError:
        pass


def test_evidence_summary_is_three_parts_and_valid():
    pkg = cp.build_context_package(make_pkg())
    assert pkg.summary.who_and_verified
    assert pkg.summary.discussed_and_looked_up
    assert pkg.summary.next_action
    assert cp.validate_summary(pkg) == []
    assert "DH123456" in pkg.summary.all_text()


def test_llm_summary_with_fabricated_fact_is_rejected_and_replaced():
    def bad_summarizer(pkg):
        return cp.SummaryParts(
            who_and_verified="Anh Minh, đã xác minh",
            discussed_and_looked_up="Đơn DH999999 bị mất, bồi thường 5000000 đồng",
            next_action="Hoàn tiền ngay")

    pkg = cp.build_context_package(make_pkg(), summarizer=bad_summarizer)
    # Fabricated order code / amount must not survive validation.
    assert "DH999999" not in pkg.summary.all_text()
    assert cp.validate_summary(pkg) == []


def test_llm_summary_grounded_in_evidence_is_accepted():
    def good_summarizer(pkg):
        return cp.SummaryParts(
            who_and_verified="Anh Minh (0901234567), đã xác minh đơn DH123456",
            discussed_and_looked_up="Khách báo đơn DH123456 giao sai sản phẩm",
            next_action="Nhân viên xử lý khiếu nại đơn DH123456")

    pkg = cp.build_context_package(make_pkg(), summarizer=good_summarizer)
    assert "giao sai sản phẩm" in pkg.summary.discussed_and_looked_up


def test_validate_summary_flags_each_empty_part():
    pkg = make_pkg()
    errs = cp.validate_summary(pkg, cp.SummaryParts("", "", ""))
    assert "summary_part1_empty" in errs
    assert "summary_part2_empty" in errs
    assert "summary_part3_empty" in errs


def test_desktop_card_is_one_screen_with_all_key_facts():
    pkg = cp.build_context_package(make_pkg())
    card = cp.build_desktop_card(pkg)
    assert card["one_screen"] is True
    assert len(card["lines"]) <= cp.CARD_MAX_LINES
    joined = " ".join(card["lines"])
    assert "DH123456" in joined or "DH123456" in card["discussed"]
    assert card["actions"] == ["accept", "push_back"]
    assert card["note_field"]["ticket_id"] == "CB-000001"
    assert card["transcript"][0]["timestamp"] == 12.0


def test_time_to_context_well_under_5_seconds():
    pkg = cp.build_context_package(make_pkg())
    elapsed = cp.measure_time_to_context(pkg)
    assert elapsed < cp.TIME_TO_CONTEXT_BUDGET_S
    assert elapsed < 1.0  # building a card must be near-instant in practice


def test_accept_pushback_and_notes_stay_on_same_ticket():
    pkg = cp.build_context_package(make_pkg())
    cp.accept_handoff(pkg, "agent-7")
    assert pkg.status == "accepted"
    cp.add_agent_note(pkg, "agent-7", "Đã gọi lại, khách đồng ý đổi hàng")
    cp.push_back_handoff(pkg, "agent-7", "cần bộ phận kho")
    notes = pkg.agent_notes
    assert [n["type"] for n in notes] == ["accept", "note", "push_back"]
    assert notes[1]["ticket_id"] == "CB-000001"  # same ticket, no restart


def test_no_agent_creates_callback_ticket_with_package():
    pkg = cp.build_context_package(make_pkg(ticket_id=None))
    out = cp.ensure_no_dead_end(pkg, agent_available=False)
    assert out["outcome"] == "callback"
    assert out["ticket_id"].startswith("CB-")
    assert out["package"]["call_id"] == "call-1"
    assert out["package"]["summary"]["next_action"]
    assert pkg.status == "callback_pending"


def test_agent_available_returns_handoff_card():
    pkg = cp.build_context_package(make_pkg())
    out = cp.ensure_no_dead_end(pkg, agent_available=True)
    assert out["outcome"] == "handoff" and "card" in out


def test_package_roundtrip():
    pkg = cp.build_context_package(make_pkg())
    pkg2 = cp.ContextPackage.from_dict(pkg.to_dict())
    assert pkg2.intent == "complaint"
    assert pkg2.transcript[0].text.startswith("Đơn DH123456")
    assert pkg2.tool_calls[0].tool == "get_order"
    assert pkg2.summary.next_action == pkg.summary.next_action


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("PASS", fn.__name__)
    print(f"{len(fns)} passed")
