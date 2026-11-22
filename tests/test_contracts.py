"""Tests for src/contracts.py v1.0.0 — the locked shared contracts.

Run:
    PYTHONPATH=. python3 -m pytest tests/test_contracts.py -q
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.contracts as contracts  # noqa: E402
from src.contracts import (  # noqa: E402
    ASR_PARTIAL_MS, CONTAINMENT_WINDOW_HOURS, CONTRACTS_VERSION,
    LATENCY_BUDGET_SUM_MS, LATENCY_BUFFER_MS, LLM_FIRST_TOKEN_MS,
    MAX_CLARIFICATIONS, MAX_ELICITATIONS, TOTAL_SLO_P95_MS,
    TOOL_CALL_OFF_PATH_MS, TTS_FIRST_AUDIO_MS, CallMetrics,
    CallSession, CallerInfo, ConfidenceDecision, Decision,
    EscalationReason, HandoffPackage, TenantContext,
    assert_contracts_version, check_latency_budget,
    decide_clarification, erlang_a_metrics,
    is_log_only_reason, map_reason_to_decision,
)

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
CONTRACTS = SRC / "contracts.py"

LATENCY_CONSTANTS = (
    "ASR_PARTIAL_MS", "LLM_FIRST_TOKEN_MS", "TTS_FIRST_AUDIO_MS",
    "TOTAL_SLO_P95_MS", "TOOL_CALL_OFF_PATH_MS",
)
# Retired literals, built without writing them plainly so this test
# file itself stays greppable the same way src/ is grepped.
RETIRED_REASON = "user_" + "requested"
RETIRED_SLO = "TOTAL_" + "TURN_P95_MS"


def test_version_locked():
    assert CONTRACTS_VERSION == "1.0.0"


def test_escalation_reasons_snake_case_complete():
    values = {r.value for r in EscalationReason}
    assert values == {
        "out_of_scope", "low_confidence", "sensitive",
        "customer_request", "repeated_clarification",
        "repeated_failure", "no_agent", "system_error",
    }
    assert "repeated_clarification" in values
    assert RETIRED_REASON not in values
    assert "out-of-scope" not in values


def test_log_only_reasons_map_to_callback():
    for reason in (EscalationReason.NO_AGENT, EscalationReason.SYSTEM_ERROR):
        assert is_log_only_reason(reason) is True
        assert map_reason_to_decision(reason) == Decision.CALLBACK
    assert map_reason_to_decision(EscalationReason.OUT_OF_SCOPE) == Decision.HANDOFF


def test_max_clarifications_one_and_counting_rule_in_code():
    assert MAX_CLARIFICATIONS == 1
    assert MAX_ELICITATIONS == 2
    assert decide_clarification(0) == (False, None)
    assert decide_clarification(1) == (True, None)
    assert decide_clarification(2) == (False, EscalationReason.REPEATED_CLARIFICATION)
    assert decide_clarification(1, has_hard_stop=True) == (False, EscalationReason.SENSITIVE)


def test_confidence_decision_can_clarify():
    d = ConfidenceDecision(action=Decision.CLARIFY, clarifications_used=0)
    assert d.can_clarify() is True
    d.clarifications_used = 1
    assert d.can_clarify() is False
    d.clarifications_used = 0
    d.escalation_reason = EscalationReason.SENSITIVE
    assert d.can_clarify() is False


def test_containment_two_layers_fixed_72h():
    assert CONTAINMENT_WINDOW_HOURS == 72
    m = CallMetrics(call_id="C1", tenant_id="s", contained_provisional=True)
    assert m.window_hours == 72
    assert m.compute_contained_final() is True
    m.recontacted_within_window = True
    assert m.compute_contained_final() is False


def test_latency_budget_arithmetic():
    assert (ASR_PARTIAL_MS, LLM_FIRST_TOKEN_MS, TTS_FIRST_AUDIO_MS) == (250, 500, 350)
    assert LATENCY_BUDGET_SUM_MS == 1100
    assert LATENCY_BUFFER_MS == 100
    assert LATENCY_BUDGET_SUM_MS + 100 == TOTAL_SLO_P95_MS == 1200
    assert TOOL_CALL_OFF_PATH_MS == 500
    assert check_latency_budget() is True


def test_single_slo_name_locked():
    assert TOTAL_SLO_P95_MS == 1200
    assert not hasattr(contracts, RETIRED_SLO)


def test_call_metrics_latency_uses_locked_slo():
    ok = CallMetrics(call_id="C1", tenant_id="s",
                     asr_partial_ms=250, llm_first_token_ms=500,
                     tts_first_audio_ms=350, total_turn_ms=1100)
    assert ok.latency_within_budget() is True
    over = CallMetrics(call_id="C2", tenant_id="s",
                       asr_partial_ms=250, llm_first_token_ms=500,
                       tts_first_audio_ms=350, total_turn_ms=1201)
    assert over.latency_within_budget() is False


def test_fail_closed_version_check():
    assert_contracts_version()  # 1.0.0 matches
    assert_contracts_version("1.0.0")
    with pytest.raises(RuntimeError):
        assert_contracts_version("9.9.9")


def test_erlang_a_sanity():
    # Peak hour: 300 calls/day is ~0.02/s average; use a busy minute:
    # 1 call every 5 s, mean service 180 s, 40 agents.
    m = erlang_a_metrics(arrival_rate_per_s=0.2, mean_service_s=180.0, servers=40)
    assert 0.0 <= m.p_wait <= 1.0
    assert 0.0 <= m.p_abandon <= 1.0
    assert m.offered_load_erlangs == pytest.approx(36.0)
    assert m.utilization == pytest.approx(0.9)
    assert m.mean_queue_length >= 0.0
    assert m.mean_wait_s >= 0.0


def test_erlang_a_patience_effect():
    # Same load, near-infinite patience -> almost nobody abandons.
    m = erlang_a_metrics(0.2, 180.0, 40, mean_patience_s=10_000.0)
    assert m.p_abandon < 0.01
    # Same load, 5 s patience -> most waiting callers abandon.
    m2 = erlang_a_metrics(0.2, 180.0, 40, mean_patience_s=5.0)
    assert m2.p_abandon > m.p_abandon


def test_erlang_a_stable_under_overload():
    # Offered load (36 Erlangs) exceeds servers (20): Erlang-C would
    # diverge; Erlang-A stays finite because abandonments absorb it.
    m = erlang_a_metrics(0.2, 180.0, 20)
    assert m.utilization > 1.0
    assert 0.0 < m.p_abandon < 1.0
    assert m.mean_wait_s < 1_000.0


def test_erlang_a_invalid_inputs():
    with pytest.raises(ValueError):
        erlang_a_metrics(0, 180.0, 40)
    with pytest.raises(ValueError):
        erlang_a_metrics(0.2, 0, 40)
    with pytest.raises(ValueError):
        erlang_a_metrics(0.2, 180.0, 0)
    with pytest.raises(ValueError):
        erlang_a_metrics(0.2, 180.0, 40, mean_patience_s=0)


def test_handoff_package_alias():
    assert contracts.ContextPackage is contracts.HandoffPackage
    assert contracts.HandoffReason is contracts.EscalationReason


def test_ci_grep_bans_forbidden_spellings_and_duplicate_definitions():
    for p in SRC.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if p.resolve() == CONTRACTS.resolve():
            assert RETIRED_REASON not in text
            assert RETIRED_SLO not in text
            assert "out-of-scope" not in text
            continue
        for token in (RETIRED_REASON, RETIRED_SLO, "out-of-scope"):
            assert token not in text, f"{token} in {p}"
        assert "class EscalationReason" not in text, p
        assert "MAX_CLARIFICATIONS =" not in text, p
        for name in LATENCY_CONSTANTS:
            assert re.search(r"^%s\s*=" % name, text, re.MULTILINE) is None, (name, p)


def test_contracts_defines_each_latency_constant_exactly_once():
    text = CONTRACTS.read_text(encoding="utf-8")
    for name in LATENCY_CONSTANTS:
        assert len(re.findall(r"^%s\s*=" % name, text, re.MULTILINE)) == 1, name


def test_session_smoke():
    s = CallSession(call_id="C1", tenant=TenantContext("shop-1"))
    assert s.state.value == "ringing"
    pkg = HandoffPackage(call_id="C1", tenant_id="shop-1", summary="tra don")
    assert pkg.reason == EscalationReason.OUT_OF_SCOPE
    assert CallerInfo(phone="0901234567").verified is False
