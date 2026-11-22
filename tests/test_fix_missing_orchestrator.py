"""Tests for fix/fix_missing_orchestrator — src/realtime/orchestrator.py.

Stdlib-only (pytest). Fake adapters advance a fake clock so latency
numbers are deterministic, and the reported P50/P95 are real
measurements from the tracker, not hardcoded claims.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from realtime.orchestrator import (  # noqa: E402
    ESCALATION_REASONS,
    MAX_CLARIFICATIONS,
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
    """Streams tokens; first token costs first_token_ms, rest are free."""

    def __init__(self, clock, text, first_token_ms=100.0):
        self.clock = clock
        self.text = text
        self.first_token_ms = first_token_ms
        self.calls = 0

    def stream(self, prompt):
        self.calls += 1
        self.clock.advance(self.first_token_ms)
        # Yield in two chunks so streaming (not whole-answer) is exercised.
        half = len(self.text) // 2
        yield self.text[:half]
        yield self.text[half:]


class FakeTTS:
    """First audio chunk costs first_audio_ms."""

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


# --- latency budget (fix_latency_budget_inconsistent) -------------------

def test_latency_budget_sums_below_slo():
    budget = LatencyBudget()
    assert budget.streaming_total_ms == 250 + 500 + 350 == 1100
    assert budget.streaming_total_ms < budget.total_slo_p95_ms == 1200
    assert budget.jitter_headroom_ms == 100
    budget.check()


def test_latency_budget_inconsistent_is_rejected():
    with pytest.raises(ValueError):
        LatencyBudget(asr_partial_ms=300, llm_first_token_ms=600,
                      tts_first_audio_ms=400).check()


def test_latency_tracker_p50_p95_are_real_measurements():
    tracker = LatencyTracker()
    for v in [100, 200, 300, 400, 500]:
        tracker.record("total_turn_ms", v)
    assert tracker.p50("total_turn_ms") == 300
    assert tracker.p95("total_turn_ms") == 500
    assert tracker.summary()["total_turn_ms"]["count"] == 5


# --- streaming turn ------------------------------------------------------

def test_streaming_turn_speaks_per_sentence_without_waiting_for_full_llm():
    clock, orch, session = make_orchestrator()
    result = orch.process_final_text(session, "đơn của tôi đâu rồi")
    assert result.sentences == [
        "Đơn hàng của anh đang giao.",
        "Dự kiến ngày mai anh nhận được.",
    ]
    # TTS was called once per sentence, i.e. streaming, not once at end.
    assert orch.tts.sentences == result.sentences
    assert len(result.audio_chunks) == 2 * len(result.sentences)
    assert result.state == TurnState.LISTENING
    assert not result.timed_out
    assert result.within_slo
    # Real measured latencies from the fake clock.
    assert result.latency_ms["llm_first_token_ms"] == 100.0
    assert result.latency_ms["tts_first_audio_ms"] == 180.0  # 100 + 80
    assert result.latency_ms["total_ms"] == 100 + 2 * 80
    # Tracker aggregates the same numbers.
    assert orch.latency.p50("llm_first_token_ms") == 100.0
    assert orch.latency.p95("tts_first_audio_ms") == 180.0


def test_slow_lookup_uses_approved_filler_first():
    clock, orch, session = make_orchestrator()
    result = orch.process_final_text(session, "tra đơn", lookup_slow=True)
    assert result.used_filler
    assert orch.tts.sentences[0].startswith("Dạ, em đang kiểm tra")


def test_half_duplex_fallback_still_answers():
    clock, orch, session = make_orchestrator()
    orch.set_network_degraded(True, session)
    assert session.half_duplex
    result = orch.process_final_text(session, "tra đơn")
    assert result.sentences
    assert result.audio_chunks


def test_backpressure_degrades_to_half_duplex():
    clock, orch, session = make_orchestrator()
    assert not orch.check_backpressure(3, session)
    assert orch.check_backpressure(99, session)
    assert session.half_duplex


# --- barge-in ------------------------------------------------------------

def test_barge_in_interrupts_speaking_and_returns_to_listening():
    clock, orch, session = make_orchestrator()
    session.state = TurnState.SPEAKING
    orch.save_session(session)
    state = orch.process_audio_chunk(session, b"audio-bytes")
    assert state == TurnState.LISTENING
    assert any("barge-in" in t["text"] for t in session.transcript)


def test_no_barge_in_in_half_duplex():
    clock, orch, session = make_orchestrator()
    session.state = TurnState.SPEAKING
    session.half_duplex = True
    state = orch.process_audio_chunk(session, b"audio-bytes")
    assert state == TurnState.SPEAKING


# --- session persistence / reconnect -------------------------------------

def test_reconnect_restores_transcript_intent_slots_and_evidence():
    clock, orch, session = make_orchestrator()
    session.intent = "track_order"
    session.slots = {"order_id": "DH123"}
    orch.process_final_text(session, "tra đơn DH123")
    assert orch.record_write(session, "key-1", {"order_id": "DH123"})
    assert not orch.record_write(session, "key-1", {"order_id": "DH123"})  # duplicate

    restored = orch.restore_session("s1")
    assert restored is not None
    assert restored.intent == "track_order"
    assert restored.slots == {"order_id": "DH123"}
    assert restored.transcript  # transcript survived the "crash"
    assert restored.idempotency_keys == ["key-1"]


def test_restore_unknown_session_returns_none():
    _, orch, _ = make_orchestrator()
    assert orch.restore_session("no-such-session") is None


# --- timeout / handoff / contract values ---------------------------------

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


def test_handoff_rejects_unknown_reason_and_accepts_locked_reasons():
    _, orch, session = make_orchestrator()
    with pytest.raises(ValueError):
        orch.start_handoff(session, "OUT_OF_SCOPE")  # wrong case: not locked
    with pytest.raises(ValueError):
        orch.start_handoff(session, "out-of-scope")  # wrong separator
    assert orch.start_handoff(session, "low_confidence") == TurnState.HANDING_OFF
    assert "low_confidence" in ESCALATION_REASONS
    assert MAX_CLARIFICATIONS == 1


def test_confirm_state():
    _, orch, session = make_orchestrator()
    assert orch.confirm(session) == TurnState.CONFIRMING


def test_split_sentences():
    assert split_sentences("Một câu. Hai câu! Ba câu?") == ["Một câu.", "Hai câu!", "Ba câu?"]
    assert split_sentences("không dấu chấm") == ["không dấu chấm"]
