"""Tests for fix_missing_contracts — locked src/contracts.py v1.0.0.

Run:  PYTHONPATH=. python3 -m pytest tests/test_fix_missing_contracts.py -q

These tests LOCK the contract. Any change to a value, a constant or
the version must be a council decision with a version bump — a test
failing here means the contract moved, not that the test is stale.
Negative controls are included: the old m3 spellings must NOT exist.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.contracts import (  # noqa: E402
    ASR_PARTIAL_MS, CONTAINMENT_WINDOW_HOURS,
    LATENCY_BUDGET_SUM_MS, LATENCY_BUFFER_MS, LLM_FIRST_TOKEN_MS,
    MAX_CLARIFICATIONS, MAX_ELICITATIONS, TOOL_CALL_OFF_PATH_MS,
    TOTAL_TURN_P95_MS, TTS_FIRST_AUDIO_MS,
)
import src.contracts as contracts  # noqa: E402
from src.contracts import (  # noqa: E402
    CallMetrics, ConfidenceDecision, ContextPackage, Decision,
    EscalationReason, HandoffPackage, HandoffReason, decide_clarification,
)


def test_contracts_version_locked_to_1_0_0():
    assert contracts.CONTRACTS_VERSION == "1.0.0"


def test_escalation_reason_values_are_snake_case_exact():
    assert [r.value for r in EscalationReason] == [
        "out_of_scope", "low_confidence", "sensitive", "customer_request",
        "repeated_clarification", "repeated_failure", "no_agent",
        "system_error",
    ]
    for r in EscalationReason:
        assert r.value == r.value.lower()
        assert "-" not in r.value, f"hyphenated value {r.value!r} is forbidden"
        assert " " not in r.value
    assert len({r.value for r in EscalationReason}) == len(list(EscalationReason))


def test_m3_user_requested_is_gone_and_repeated_clarification_exists():
    values = {r.value for r in EscalationReason}
    assert "customer_request" in values
    assert "user_requested" not in values
    assert not hasattr(EscalationReason, "USER_REQUESTED")
    assert "repeated_clarification" in values
    assert EscalationReason.REPEATED_CLARIFICATION.value == "repeated_clarification"
    assert EscalationReason.REPEATED_CLARIFICATION is not EscalationReason.REPEATED_FAILURE


def test_handoff_reason_alias_is_the_same_enum():
    assert HandoffReason is EscalationReason
    assert HandoffReason.CUSTOMER_REQUEST is EscalationReason.CUSTOMER_REQUEST


def test_max_clarifications_counts_re_asks_not_initial_ask():
    # Locked counting rule: 1 re-ask, 2 elicitations total.
    assert MAX_CLARIFICATIONS == 1
    assert MAX_ELICITATIONS == 2
    assert MAX_ELICITATIONS == MAX_CLARIFICATIONS + 1


def test_clarification_budget_exhaustion_counts_re_asks():
    # 0 re-asks used -> may clarify (low confidence, no hard stop).
    d0 = ConfidenceDecision(Decision.CLARIFY, confidence=0.5, threshold=0.8,
                            escalation_reason=EscalationReason.LOW_CONFIDENCE,
                            clarifications_used=0)
    assert d0.can_clarify() is True
    # 1 re-ask used (= budget) -> must hand off, never a 2nd re-ask.
    d1 = ConfidenceDecision(Decision.CLARIFY, confidence=0.5, threshold=0.8,
                            escalation_reason=EscalationReason.LOW_CONFIDENCE,
                            clarifications_used=1)
    assert d1.can_clarify() is False
    # Hard stops never clarify, even with budget left.
    for reason in (EscalationReason.SENSITIVE, EscalationReason.CUSTOMER_REQUEST):
        d = ConfidenceDecision(Decision.HANDOFF, confidence=0.9, threshold=0.8,
                               escalation_reason=reason, clarifications_used=0)
        assert d.can_clarify() is False
        assert d.should_hand_off() is True


def test_log_only_reasons_map_to_callback():
    assert contracts.map_reason_to_decision(EscalationReason.NO_AGENT) == Decision.CALLBACK
    assert contracts.map_reason_to_decision(EscalationReason.SYSTEM_ERROR) == Decision.CALLBACK
    assert contracts.is_log_only_reason(EscalationReason.NO_AGENT) is True
    assert contracts.is_log_only_reason(EscalationReason.SYSTEM_ERROR) is True
    assert contracts.is_log_only_reason(EscalationReason.OUT_OF_SCOPE) is False
    for reason in (EscalationReason.OUT_OF_SCOPE, EscalationReason.LOW_CONFIDENCE,
                   EscalationReason.SENSITIVE, EscalationReason.CUSTOMER_REQUEST,
                   EscalationReason.REPEATED_CLARIFICATION,
                   EscalationReason.REPEATED_FAILURE):
        assert contracts.map_reason_to_decision(reason) == Decision.HANDOFF


def test_containment_two_layers_with_72h_window():
    assert CONTAINMENT_WINDOW_HOURS == 72
    # Provisional + no recontact in window -> final.
    m = CallMetrics("C1", "shop-1", contained_provisional=True,
                    recontacted_within_window=False)
    assert m.window_hours == 72
    assert m.compute_contained_final() is True
    assert m.contained_final is True
    # Same call, but the customer called back about the same issue -> not final.
    m2 = CallMetrics("C1", "shop-1", contained_provisional=True,
                     recontacted_within_window=True)
    assert m2.compute_contained_final() is False
    # Never provisional -> never final, even without recontact.
    m3 = CallMetrics("C1", "shop-1", contained_provisional=False,
                     recontacted_within_window=False)
    assert m3.compute_contained_final() is False


def test_latency_budget_constants_and_sum():
    assert ASR_PARTIAL_MS == 250
    assert LLM_FIRST_TOKEN_MS == 500
    assert TTS_FIRST_AUDIO_MS == 350
    assert TOTAL_TURN_P95_MS == 1200
    assert TOOL_CALL_OFF_PATH_MS == 500
    assert LATENCY_BUDGET_SUM_MS == 1100
    assert LATENCY_BUFFER_MS == 100
    assert contracts.check_latency_budget() is True
    # A turn inside every per-stage budget and the total passes;
    # a turn over the total fails even if stages look fine individually.
    ok = CallMetrics("C1", "shop-1", asr_partial_ms=250,
                     llm_first_token_ms=500, tts_first_audio_ms=350,
                     total_turn_ms=1100)
    assert ok.latency_within_budget() is True
    over = CallMetrics("C1", "shop-1", asr_partial_ms=250,
                       llm_first_token_ms=500, tts_first_audio_ms=350,
                       total_turn_ms=1300)
    assert over.latency_within_budget() is False


def test_decide_clarification_counting_rule_in_code():
    # Locked by debate round #2, enforced by decide_clarification():
    # 0 = no missing slot yet -> nothing to clarify.
    assert decide_clarification(0) == (False, None)
    # 1 = first missing-slot detection (initial elicitation) -> ONE re-ask.
    assert decide_clarification(1) == (True, None)
    # 2 = still missing after the one re-ask -> escalate, never a 2nd re-ask.
    # This is the rejected backend-sec variant (MAX_CLARIFICATIONS=2):
    # it must NOT clarify here.
    may, reason = decide_clarification(2)
    assert may is False
    assert reason == EscalationReason.REPEATED_CLARIFICATION
    assert decide_clarification(3)[1] == EscalationReason.REPEATED_CLARIFICATION
    # Hard stop never clarifies, whatever the count.
    assert decide_clarification(1, has_hard_stop=True)[0] is False


def test_ci_grep_bans_forbidden_spellings_and_duplicate_definitions():
    # The CI grep this test mirrors: scan src/ EXCLUDING contracts.py
    # itself (its enum member names are necessarily UPPER_SNAKE, e.g.
    # OUT_OF_SCOPE, and its docstring explains the exclusion).
    repo = Path(__file__).resolve().parents[1]
    src = repo / "src"
    banned = ("user_requested", "out-of-scope")
    for path in sorted(src.rglob("*.py")):
        if path.name == "contracts.py":
            continue
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{token} in {path}"
        # No second definition of the locked single source of truth.
        assert "class EscalationReason" not in text, path
        assert "MAX_CLARIFICATIONS =" not in text, path
        assert "MAX_CLARIFICATIONS=" not in text, path
    # And the contract file itself carries no banned VALUE spellings:
    # the old spelling and the hyphenated value must not appear as
    # a string literal anywhere in contracts.py.
    own = (src / "contracts.py").read_text(encoding="utf-8")
    assert '"user_requested"' not in own
    assert '"out-of-scope"' not in own


def test_handoff_package_is_context_package_renamed_not_reinvented():
    assert ContextPackage is HandoffPackage
    pkg = HandoffPackage(call_id="C1", tenant_id="shop-1", summary="Tra don.")
    assert pkg.reason == EscalationReason.OUT_OF_SCOPE
    assert pkg.summary == "Tra don."
    assert pkg.idempotency_key == ""
    pkg2 = HandoffPackage(call_id="C1", tenant_id="shop-1", summary="x",
                          reason=EscalationReason.CUSTOMER_REQUEST)
    assert pkg2.reason.value == "customer_request"
