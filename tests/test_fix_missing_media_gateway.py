"""Tests for fix_missing_media_gateway — src/telephony/media_gateway.py.

Merged from expert/systems-arch-m3 (not rewritten) and re-verified
against locked contracts v1.0.0. Run:
    PYTHONPATH=. python3 -m pytest tests/test_fix_missing_media_gateway.py -q

The barge-in test is TIMESTAMPED: a fake TTS records the wall-clock
millisecond at which stop() is called, and the session records
last_barge_in_latency_ms. The assertion is on that measured latency
(< 150 ms), not on unit-test logic alone.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.contracts import (  # noqa: E402
    ASR_PARTIAL_MS, TOTAL_TURN_P95_MS, CallSession, CallerInfo,
    DegradationMode, TenantContext, TranscriptTurn,
)
from src.telephony.media_gateway import (  # noqa: E402
    BARGE_IN_MAX_MS, AudioFrame, GatewayConfig, JitterBuffer,
    MediaGateway, VoiceActivityDetector,
)


def _session(call_id="C1"):
    return CallSession(call_id=call_id, tenant=TenantContext("shop-1", "shop-1"),
                       caller=CallerInfo(phone="0901234567"),
                       transcript=[TranscriptTurn("caller", "Cho toi hoi don DH240101")],
                       slots={"intent": "tra_don", "order_code": "DH240101"})


def _loud(seq, ts):
    return AudioFrame(seq, ts, samples=[0.5] * 160)


def _quiet(seq, ts):
    return AudioFrame(seq, ts, samples=[0.001] * 160)


class FakeTTS:
    """Records the timestamp of every stop() call, from the frame clock."""

    def __init__(self):
        self.stops: list[tuple[str, int]] = []
        self.plays: list[tuple[str, str]] = []
        self.now_ms = 0

    def stop(self, call_id: str) -> None:
        self.stops.append((call_id, self.now_ms))

    def play(self, call_id: str, text: str) -> None:
        self.plays.append((call_id, text))


class FakeClock:
    def __init__(self, start: int = 1000):
        self.now = start

    def __call__(self) -> int:
        return self.now


def test_barge_in_latency_measured_by_timestamp_under_150ms():
    tts = FakeTTS()
    clock = FakeClock(1000)
    gw = MediaGateway(GatewayConfig(), tts=tts, now=clock)
    gw.create_session(_session())
    gw.start_tts("C1", "Xin chao")  # tts_started_ms == 1000 (fake clock)
    # Caller speaks 100 ms after TTS started: two loud frames.
    tts.now_ms = 1050
    gw.feed_audio("C1", _loud(1, 1050))
    tts.now_ms = 1100
    gw.feed_audio("C1", _loud(2, 1100))
    session = gw._sessions["C1"]
    assert session.barge_in_count == 1
    assert session.last_barge_in_latency_ms is not None
    # Measured latency = frame time - TTS start = 1100 - 1000 = 100 ms.
    assert session.last_barge_in_latency_ms == 100.0
    assert session.last_barge_in_latency_ms < BARGE_IN_MAX_MS
    assert session.last_barge_in_latency_ms < 150.0
    assert tts.stops, "TTS must actually be stopped on barge-in"
    assert session.tts_playing is False


def test_barge_in_does_not_fire_on_single_frame_or_silence():
    gw = MediaGateway(GatewayConfig(), tts=FakeTTS(), now=FakeClock(1000))
    gw.create_session(_session())
    gw.start_tts("C1", "Xin chao")
    gw.feed_audio("C1", _loud(1, 1050))  # only 1 loud frame: not enough
    assert gw._sessions["C1"].barge_in_count == 0
    assert gw._sessions["C1"].tts_playing is True
    gw.feed_audio("C1", _quiet(2, 1070))
    assert gw._sessions["C1"].barge_in_count == 0


def test_admission_overload_queues_with_hold_music_and_eta():
    gw = MediaGateway(GatewayConfig(max_concurrent_calls=2))
    for concurrent, cpu, reason in [
            (2, 10.0, "max_concurrent_calls"),
            (0, 90.0, "cpu_overload")]:
        d = gw.admit(TenantContext("s"), concurrent_calls=concurrent, cpu_percent=cpu)
        assert not d.admitted
        assert d.mode == DegradationMode.QUEUED
        assert d.hold_music is True
        assert d.queue_eta_seconds > 0
        assert d.estimated_wait_seconds == d.queue_eta_seconds
        assert d.reason == reason
    d = gw.admit(TenantContext("s"), concurrent_calls=0, cpu_percent=10.0)
    assert d.admitted and d.mode == DegradationMode.NORMAL
    assert d.hold_music is False


def test_jitter_buffer_reorders_and_drops_duplicates():
    jb = JitterBuffer()
    assert jb.push(AudioFrame(2, 20, [])) == []
    out = jb.push(AudioFrame(1, 0, []))
    assert [f.seq for f in out] == [1, 2]
    assert jb.push(AudioFrame(1, 0, [])) == [] and jb.duplicates == 1


def test_degrade_to_ivr_then_voicemail_stops_tts():
    tts = FakeTTS()
    gw = MediaGateway(GatewayConfig(), tts=tts, now=FakeClock(1000))
    gw.create_session(_session())
    gw.start_tts("C1", "Xin chao")
    ms = gw.degrade("C1", DegradationMode.IVR_FALLBACK, reason="asr_timeout")
    assert ms.degradation == DegradationMode.IVR_FALLBACK
    assert ms.degradation_reason == "asr_timeout"
    assert ms.tts_playing is False
    ms = gw.degrade("C1", DegradationMode.VOICEMAIL, reason="llm_error")
    assert ms.degradation == DegradationMode.VOICEMAIL
    assert tts.stops  # TTS was stopped on the first degrade, not left playing


def test_janitor_reaps_orphan_but_not_heartbeating_session():
    gw = MediaGateway(now=FakeClock(0))
    gw.create_session(_session("C1"))
    gw.create_session(_session("C2"))
    gw.heartbeat("C2", now_ms=25_000)  # C2 alive, C1 orphaned
    assert gw.sweep_orphans(now_ms=31_000) == ["C1"]
    assert gw.active_calls() == 1
    # leaked_resources counts sessions + jitter buffers: 1 session + 1 buffer.
    assert gw.leaked_resources() == 2


def test_hangup_mid_call_releases_everything():
    tts = FakeTTS()
    gw = MediaGateway(GatewayConfig(), tts=tts, now=FakeClock(1000))
    gw.create_session(_session("C1"))
    gw.create_session(_session("C2"))
    gw.start_tts("C1", "Xin chao")
    gw.feed_audio("C1", _loud(1, 1010))
    assert gw.leaked_resources() == 4  # 2 sessions + 2 jitter buffers
    closed = gw.hangup("C1", reason="caller_hangup")
    assert closed is not None and closed.resources_released is True
    assert closed.tts_playing is False
    assert tts.stops, "hangup must stop TTS"
    assert gw.active_calls() == 1
    assert gw.leaked_resources() == 2  # only C2 remains
    gw.close_all(reason="shutdown")
    assert gw.active_calls() == 0
    assert gw.leaked_resources() == 0


def test_feed_audio_unknown_call_raises():
    gw = MediaGateway(now=FakeClock(0))
    with pytest.raises(KeyError):
        gw.feed_audio("no-such-call", _loud(1, 0))


def test_silence_timeout():
    gw = MediaGateway(now=FakeClock(0))
    gw.create_session(_session())
    gw.feed_audio("C1", _quiet(1, 0))
    assert gw.is_silence_timeout("C1", now_ms=500) is False
    assert gw.is_silence_timeout("C1", now_ms=1300) is True


def test_latency_constants_match_locked_contracts_v1_0_0():
    assert ASR_PARTIAL_MS == 250
    assert TOTAL_TURN_P95_MS == 1200
    cfg = GatewayConfig()
    assert cfg.asr_partial_budget_ms == ASR_PARTIAL_MS
    assert cfg.total_turn_budget_ms == TOTAL_TURN_P95_MS
    assert cfg.barge_in_max_ms == BARGE_IN_MAX_MS == 150.0
    # Locked budget arithmetic: 250 + 500 + 350 = 1100 <= 1200.
    from src.contracts import (  # noqa: E402
        LATENCY_BUDGET_SUM_MS, check_latency_budget,
    )
    assert LATENCY_BUDGET_SUM_MS == 1100
    assert check_latency_budget() is True


def test_vad_silence_vs_speech():
    vad = VoiceActivityDetector()
    assert vad.is_speech(_loud(1, 0)) is True
    assert vad.is_speech(_quiet(1, 0)) is False
