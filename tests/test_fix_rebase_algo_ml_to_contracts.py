"""Tests for fix/fix_rebase_algo_ml_to_contracts.

The orchestrator must take every locked value from src/contracts.py
v1.0.0 — no mirrored literals — and refuse to import against a
different contracts version. The same file also re-runs the
regression suite of the pre-rebase orchestrator (streaming,
barge-in, backpressure, idempotency, filler, timeout, handoff)
so the rebase is proven not to have broken behaviour.

Imports use the repo-root layout (``src.realtime...``), the layout
on main; on the VM a staging contracts stub implementing the locked
v1.0.0 surface stands in for systems-arch's contracts file, which
lands on main first by merge order.
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from src.contracts import (  # noqa: E402
    ASR_PARTIAL_MS,
    CONTRACTS_VERSION,
    LLM_FIRST_TOKEN_MS,
    MAX_CLARIFICATIONS,
    TOOL_CALL_MS,
    TOTAL_SLO_P95_MS,
    TTS_FIRST_AUDIO_MS,
    EscalationReason,
)
from src.realtime.orchestrator import (  # noqa: E402
    ESCALATION_REASONS,
    MAX_CLARIFICATIONS as ORCH_MAX_CLARIFICATIONS,
    InMemorySessionStore,
    LatencyBudget,
    LatencyTracker,
    Orchestrator,
    TurnState,
    split_sentences,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def now_ms(self):
        return self.now

    def advance(self, ms):
        self.now += ms


class FakeLLM:
    def __init__(self, clock, text, first_token_ms=100.0):
        self.clock = clock
        self.text = text
        self.first_token_ms = first_token_ms
        self.calls = 0

    def stream(self, prompt):
        self.calls += 1
        self.clock.advance(self.first_token_ms)
        half = len(self.text) // 2
        yield self.text[:half]
        yield self.text[half:]


class FakeTTS:
    def __init__(self, clock, first_audio_ms=80.0):
        self.clock = clock
        self.first_audio_ms = first_audio_ms
        self.sentences = []

    def synthesize(self, sentence):
        self.sentences.append(sentence)
        self.clock.advance(self.first_audio_ms)
        yield b"audio:" + sentence.encode()[:10]
        yield b"audio:more"


class FakeASR:
    def __init__(self, text="xin chào", is_speech=True, is_final=False):
        self.text = text
        self.is_speech = is_speech
        self.is_final = is_final

    def feed(self, audio):
        return {
            "text": self.text,
            "is_final": self.is_final,
            "is_speech": self.is_speech,
            "confidence": 0.95,
        }


def make_orchestrator(text="Đơn hàng của anh đang giao. Dự kiến ngày mai anh nhận được.",
                       first_token_ms=100.0, first_audio_ms=80.0):
    clock = FakeClock()
    orch = Orchestrator(
        llm=FakeLLM(clock, text, first_token_ms),
        tts=FakeTTS(clock, first_audio_ms),
        asr=FakeASR(),
        store=InMemorySessionStore(),
        clock=clock,
    )
    session = orch.start_session("s1", "tenant-a", call_id="call-1")
    return clock, orch, session


# --- contract binding (the rebase itself) ---------------------------------

def test_contracts_version_is_locked_1_0_0():
    assert CONTRACTS_VERSION == "1.0.0"


def test_orchestrator_budget_defaults_come_from_contracts():
    budget = LatencyBudget()
    assert budget.asr_partial_ms == ASR_PARTIAL_MS == 250
    assert budget.llm_first_token_ms == LLM_FIRST_TOKEN_MS == 500
    assert budget.tts_first_audio_ms == TTS_FIRST_AUDIO_MS == 350
    assert budget.total_slo_p95_ms == TOTAL_SLO_P95_MS == 1200
    # Debate decision: tool calls slower than 500 ms stay off the
    # first-audio path — the pre-rebase 800 ms is superseded.
    assert budget.tool_call_ms == TOOL_CALL_MS == 500
    assert budget.streaming_total_ms == 1100
    assert budget.streaming_total_ms < budget.total_slo_p95_ms
    assert budget.jitter_headroom_ms == 100
    budget.check()


def test_max_clarifications_is_one_not_two():
    # Bug debate confirmed 1; backend-sec's report said 2 — 2 is wrong.
    assert MAX_CLARIFICATIONS == 1
    assert ORCH_MAX_CLARIFICATIONS == MAX_CLARIFICATIONS


def test_escalation_reasons_come_from_contracts_enum():
    assert ESCALATION_REASONS == {r.value for r in EscalationReason}
    assert ESCALATION_REASONS == {
        "out_of_scope", "low_confidence", "sensitive",
        "customer_request", "repeated_clarification", "repeated_failure",
    }
    assert "user_requested" not in ESCALATION_REASONS  # old m3 name, banned


def test_orchestrator_refuses_wrong_contracts_version(tmp_path):
    # Fail-closed: a drifted contracts must break the import, never
    # silently run with wrong constants.
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).resolve().parents[1] / "src", root / "src")
    (root / "src" / "contracts.py").write_text(
        'CONTRACTS_VERSION = "9.9.9"\n'
        "MAX_CLARIFICATIONS = 1\n"
        "ASR_PARTIAL_MS = 250\nLLM_FIRST_TOKEN_MS = 500\n"
        "TTS_FIRST_AUDIO_MS = 350\nTOTAL_SLO_P95_MS = 1200\n"
        "TOOL_CALL_MS = 500\n"
        "from enum import Enum\n"
        "class EscalationReason(str, Enum):\n"
        '    OUT_OF_SCOPE = "out_of_scope"\n'
    )
    proc = subprocess.run(
        [sys.executable, "-c", "import src.realtime.orchestrator"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode != 0
    assert "1.0.0" in proc.stderr


def test_latency_budget_inconsistent_is_rejected():
    with pytest.raises(ValueError):
        LatencyBudget(asr_partial_ms=300, llm_first_token_ms=600,
                      tts_first_audio_ms=400).check()


# --- regression: pre-rebase behaviour unchanged ---------------------------

def test_streaming_turn_speaks_per_sentence():
    clock, orch, session = make_orchestrator()
    result = orch.process_final_text(session, "đơn của tôi đâu rồi")
    assert result.sentences == [
        "Đơn hàng của anh đang giao.",
        "Dự kiến ngày mai anh nhận được.",
    ]
    assert orch.tts.sentences == result.sentences
    assert len(result.audio_chunks) == 2 * len(result.sentences)
    assert result.state == TurnState.LISTENING
    assert not result.timed_out
    assert result.within_slo
    assert result.latency_ms["llm_first_token_ms"] == 100.0
    assert result.latency_ms["tts_first_audio_ms"] == 180.0
    assert result.latency_ms["total_ms"] == 100 + 2 * 80
    assert orch.latency.p50("llm_first_token_ms") == 100.0


def test_slow_lookup_uses_approved_filler_first():
    _, orch, session = make_orchestrator()
    result = orch.process_final_text(session, "tra đơn", lookup_slow=True)
    assert result.used_filler
    assert orch.tts.sentences[0].startswith("Dạ, em đang kiểm tra")


def test_half_duplex_and_backpressure():
    _, orch, session = make_orchestrator()
    orch.set_network_degraded(True, session)
    assert session.half_duplex
    assert orch.process_final_text(session, "tra đơn").sentences
    assert not orch.check_backpressure(3, session)
    assert orch.check_backpressure(99, session)
    assert session.half_duplex


def test_barge_in_interrupts_speaking():
    _, orch, session = make_orchestrator()
    session.state = TurnState.SPEAKING
    orch.save_session(session)
    assert orch.process_audio_chunk(session, b"audio-bytes") == TurnState.LISTENING
    assert any("barge-in" in t["text"] for t in session.transcript)


def test_no_barge_in_in_half_duplex():
    _, orch, session = make_orchestrator()
    session.state = TurnState.SPEAKING
    session.half_duplex = True
    assert orch.process_audio_chunk(session, b"audio-bytes") == TurnState.SPEAKING


def test_reconnect_restores_state_and_idempotency():
    _, orch, session = make_orchestrator()
    session.intent = "track_order"
    session.slots = {"order_id": "DH123"}
    orch.process_final_text(session, "tra đơn DH123")
    assert orch.record_write(session, "key-1", {"order_id": "DH123"})
    assert not orch.record_write(session, "key-1", {"order_id": "DH123"})
    restored = orch.restore_session("s1")
    assert restored is not None
    assert restored.intent == "track_order"
    assert restored.slots == {"order_id": "DH123"}
    assert restored.idempotency_keys == ["key-1"]


def test_llm_timeout_returns_timed_out_result_not_hang():
    clock = FakeClock()
    orch = Orchestrator(
        llm=FakeLLM(clock, "x", first_token_ms=6000.0),
        tts=FakeTTS(clock),
        store=InMemorySessionStore(),
        clock=clock,
    )
    session = orch.start_session("s-timeout", "tenant-a")
    result = orch.process_final_text(session, "hello")
    assert result.timed_out
    assert result.audio_chunks == []
    assert not result.within_slo


def test_handoff_accepts_enum_and_locked_strings_rejects_old_names():
    _, orch, session = make_orchestrator()
    assert orch.start_handoff(session, EscalationReason.LOW_CONFIDENCE) == TurnState.HANDING_OFF
    assert orch.start_handoff(session, "customer_request") == TurnState.HANDING_OFF
    for bad in ("user_requested", "OUT_OF_SCOPE", "out-of-scope", "no_such_reason"):
        with pytest.raises(ValueError):
            orch.start_handoff(session, bad)


def test_latency_tracker_p50_p95():
    tracker = LatencyTracker()
    for v in [100, 200, 300, 400, 500]:
        tracker.record("total_turn_ms", v)
    assert tracker.p50("total_turn_ms") == 300
    assert tracker.p95("total_turn_ms") == 500


def test_confirm_and_split_sentences():
    _, orch, session = make_orchestrator()
    assert orch.confirm(session) == TurnState.CONFIRMING
    assert split_sentences("Một câu. Hai câu! Ba câu?") == ["Một câu.", "Hai câu!", "Ba câu?"]
