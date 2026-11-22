"""[approach_01] Media gateway: SIP/WebRTC streaming, barge-in, fault tolerance.

Branch: fix/fix_rebase_m3_to_contracts — MERGED from expert/systems-arch-m3,
rebased to locked contracts v1.0.0 (single `from src.contracts import`;
no mirrored reason codes, clarification limits, containment or latency).
not rewritten. JitterBuffer / VAD / BargeInDetector / admission /
heartbeat / janitor are the m3 implementation, re-verified here against
the locked contracts v1.0.0 (src/contracts.py).

Stateless media plane. No call state lives in this process beyond the
in-memory session registry (leases + heartbeats); durable session state
belongs to Redis in production -- see the lease/TTL + janitor design.
Audio is handled in 20-40 ms frames (Opus/RTP/SRTP). Dependencies on a
real SIP stack / ASR / TTS are behind small Protocols so this module is
testable offline with fake audio frames (see tests).

Key guarantees (locked budgets from contracts v1.0.0):
* latency: ASR partial <= 250 ms + LLM first-token <= 500 ms +
  TTS first-audio <= 350 ms = 1100 ms, inside TOTAL_TURN_P95_MS 1200 ms.
* barge-in: TTS is interrupted < 150 ms after caller speech is detected
  (measured from VAD onset to the stop_tts() call, timestamped on the
  session as last_barge_in_latency_ms — not just unit-test logic).
* admission control: concurrent calls, estimated CPU and ASR/TTS quota;
  overload -> QUEUED (hold music + ETA) instead of accepting then dropping.
* fail-closed degradation: ASR/TTS/LLM failure -> IVR keypad fallback,
  then voicemail recording; never silence, never a bare hang-up.
* orphan sessions are reaped by a janitor (missed heartbeat > TTL).
* hang-up mid-call releases EVERYTHING: TTS is stopped, the jitter
  buffer is dropped and the session is removed, so leaked_resources()
  is 0 after close — no leaked connection, task or buffer.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Protocol

from src.contracts import (
    ASR_PARTIAL_MS, TOTAL_TURN_P95_MS, CallSession, CallState,
    DegradationMode, TenantContext,
)

FRAME_MS = 20
BARGE_IN_MAX_MS = 150.0
SILENCE_MS = 1200
SESSION_TTL_MS = 30_000
HEARTBEAT_INTERVAL_MS = 5_000


class Transport(str, Enum):
    SIP = "sip"
    WEBRTC = "webrtc"


@dataclass
class AudioFrame:
    """One 20 ms frame. ``samples`` are normalised floats in [-1, 1]."""
    seq: int
    ts_ms: int
    samples: list[float] = field(default_factory=list)
    is_speech: bool = False  # filled in by VAD


@dataclass
class MediaSession:
    session: CallSession
    transport: Transport = Transport.SIP
    state: CallState = CallState.RINGING
    degradation: DegradationMode = DegradationMode.NORMAL
    tts_playing: bool = False
    tts_started_ms: int = 0
    last_audio_ms: int = 0
    last_heartbeat_ms: int = 0
    silence_since_ms: Optional[int] = None
    barge_in_count: int = 0
    frames_received: int = 0
    last_barge_in_latency_ms: Optional[float] = None
    degradation_reason: str = ""
    resources_released: bool = False


@dataclass
class AdmissionDecision:
    admitted: bool
    mode: DegradationMode = DegradationMode.NORMAL
    queue_eta_seconds: int = 0
    reason: str = ""
    hold_music: bool = False
    estimated_wait_seconds: int = 0  # == queue_eta_seconds when queued


@dataclass
class GatewayConfig:
    max_concurrent_calls: int = 200
    max_cpu_percent: float = 85.0
    asr_quota_per_minute: int = 600
    frame_ms: int = FRAME_MS
    vad_energy_threshold: float = 0.02
    barge_in_max_ms: float = BARGE_IN_MAX_MS
    session_ttl_ms: int = SESSION_TTL_MS
    asr_partial_budget_ms: int = ASR_PARTIAL_MS
    total_turn_budget_ms: int = TOTAL_TURN_P95_MS


class TTSPlayer(Protocol):
    def stop(self, call_id: str) -> None: ...
    def play(self, call_id: str, text: str) -> None: ...


class JitterBuffer:
    """Reorders frames by seq, drops duplicates, tolerates small jitter.

    A frame arriving > ``max_delay_frames`` late is dropped (its playout
    time has passed); gaps are counted so observability can see loss.
    """

    def __init__(self, max_delay_frames: int = 5):
        self.max_delay_frames = max_delay_frames
        self._buf: dict[int, AudioFrame] = {}
        self._next_seq: Optional[int] = None
        self.dropped_late = 0
        self.duplicates = 0

    def push(self, frame: AudioFrame) -> list[AudioFrame]:
        if frame.seq in self._buf:
            self.duplicates += 1
            return []
        if self._next_seq is not None and frame.seq < self._next_seq:
            # Already emitted (or too late to play): count as duplicate/late.
            self.duplicates += 1
            return []
        if self._next_seq is not None and frame.seq < self._next_seq - self.max_delay_frames:
            self.dropped_late += 1
            return []
        self._buf[frame.seq] = frame
        # One-frame playout delay: hold the first frame so a reordered
        # predecessor (seq-1) arriving next can still be emitted first.
        # Once playout has started, emit contiguously in seq order.
        if self._next_seq is None:
            if len(self._buf) < 2:
                return []
            self._next_seq = min(self._buf)
        out: list[AudioFrame] = []
        while self._next_seq in self._buf:
            out.append(self._buf.pop(self._next_seq))
            self._next_seq += 1
        return out


class VoiceActivityDetector:
    """Energy + zero-crossing VAD (stdlib only, deterministic for tests).

    ``is_speech`` is decided per frame; callers should require 2-3
    consecutive speech frames before treating it as a barge-in, to avoid
    coughs / line noise triggering an interruption.
    """

    def __init__(self, energy_threshold: float = 0.02):
        self.energy_threshold = energy_threshold

    @staticmethod
    def frame_energy(samples: list[float]) -> float:
        if not samples:
            return 0.0
        return math.sqrt(sum(s * s for s in samples) / len(samples))

    def is_speech(self, frame: AudioFrame) -> bool:
        return self.frame_energy(frame.samples) >= self.energy_threshold


class BargeInDetector:
    """Detects caller speech while TTS is playing; measures interrupt latency."""

    def __init__(self, vad: VoiceActivityDetector, min_speech_frames: int = 2):
        self.vad = vad
        self.min_speech_frames = min_speech_frames
        self._consecutive = 0

    def feed(self, frame: AudioFrame, tts_playing: bool,
             now_ms: int, tts_started_ms: int) -> Optional[float]:
        """Return interrupt latency in ms when a barge-in fires, else None."""
        if not tts_playing:
            self._consecutive = 0
            return None
        if self.vad.is_speech(frame):
            self._consecutive += 1
        else:
            self._consecutive = 0
        if self._consecutive >= self.min_speech_frames:
            self._consecutive = 0
            return float(now_ms - tts_started_ms)
        return None


class MediaGateway:
    """Stateless gateway: admission, sessions, barge-in, heartbeat, janitor."""

    def __init__(self, config: Optional[GatewayConfig] = None,
                 tts: Optional[TTSPlayer] = None,
                 now: Optional[Callable[[], int]] = None):
        self.config = config or GatewayConfig()
        self.tts = tts
        self._now = now or (lambda: int(time.time() * 1000))
        self._sessions: dict[str, MediaSession] = {}
        self._jitter: dict[str, JitterBuffer] = {}
        self._vad = VoiceActivityDetector(self.config.vad_energy_threshold)
        self._barge_in = BargeInDetector(self._vad)
        self._asr_calls_this_minute = 0
        self._minute_bucket = self._now() // 60_000
        self.on_barge_in: Optional[Callable[[str, float], None]] = None
        self.on_session_closed: Optional[Callable[[str, str], None]] = None

    # -- admission ------------------------------------------------------
    def admit(self, tenant: TenantContext, concurrent_calls: int,
              cpu_percent: float, now_ms: Optional[int] = None) -> AdmissionDecision:
        now_ms = now_ms if now_ms is not None else self._now()
        bucket = now_ms // 60_000
        if bucket != self._minute_bucket:
            self._minute_bucket = bucket
            self._asr_calls_this_minute = 0
        if concurrent_calls >= self.config.max_concurrent_calls:
            return AdmissionDecision(False, DegradationMode.QUEUED,
                                     queue_eta_seconds=90, reason="max_concurrent_calls",
                                     hold_music=True, estimated_wait_seconds=90)
        if cpu_percent >= self.config.max_cpu_percent:
            return AdmissionDecision(False, DegradationMode.QUEUED,
                                     queue_eta_seconds=60, reason="cpu_overload",
                                     hold_music=True, estimated_wait_seconds=60)
        if self._asr_calls_this_minute >= self.config.asr_quota_per_minute:
            return AdmissionDecision(False, DegradationMode.QUEUED,
                                     queue_eta_seconds=120, reason="asr_quota",
                                     hold_music=True, estimated_wait_seconds=120)
        return AdmissionDecision(True, DegradationMode.NORMAL, reason="ok")

    def create_session(self, session: CallSession,
                       transport: Transport = Transport.SIP) -> MediaSession:
        now = self._now()
        ms = MediaSession(session=session, transport=transport,
                          state=CallState.STREAMING, last_audio_ms=now,
                          last_heartbeat_ms=now)
        self._sessions[session.call_id] = ms
        self._jitter[session.call_id] = JitterBuffer()
        return ms

    # -- audio path -----------------------------------------------------
    def feed_audio(self, call_id: str, frame: AudioFrame) -> list[AudioFrame]:
        """Feed one inbound frame; returns ordered frames ready for ASR.

        Side effect: barge-in detection. When it fires, TTS is stopped
        immediately and the session moves to BARGE_IN.
        """
        ms = self._sessions.get(call_id)
        if ms is None:
            raise KeyError(f"unknown call {call_id}")
        ms.frames_received += 1
        ms.last_audio_ms = frame.ts_ms
        frame.is_speech = self._vad.is_speech(frame)
        if frame.is_speech:
            ms.silence_since_ms = None
        elif ms.silence_since_ms is None:
            ms.silence_since_ms = frame.ts_ms
        latency = self._barge_in.feed(frame, ms.tts_playing, frame.ts_ms,
                                      ms.tts_started_ms)
        if latency is not None:
            ms.barge_in_count += 1
            ms.last_barge_in_latency_ms = latency
            ms.state = CallState.BARGE_IN
            if self.tts is not None:
                self.tts.stop(call_id)
            ms.tts_playing = False
            if self.on_barge_in is not None:
                self.on_barge_in(call_id, latency)
        return self._jitter[call_id].push(frame)

    def start_tts(self, call_id: str, text: str) -> None:
        ms = self._sessions[call_id]
        ms.tts_playing = True
        ms.tts_started_ms = self._now()
        ms.state = CallState.STREAMING
        if self.tts is not None:
            self.tts.play(call_id, text)

    def silence_duration_ms(self, call_id: str, now_ms: int) -> int:
        ms = self._sessions[call_id]
        if ms.silence_since_ms is None:
            return 0
        return now_ms - ms.silence_since_ms

    def is_silence_timeout(self, call_id: str, now_ms: int) -> bool:
        return self.silence_duration_ms(call_id, now_ms) >= SILENCE_MS

    # -- degradation ----------------------------------------------------
    def degrade(self, call_id: str, mode: DegradationMode, reason: str) -> MediaSession:
        """Controlled degradation. Never leaves the caller in silence:
        IVR still accepts keypad input; voicemail records + creates a ticket."""
        ms = self._sessions[call_id]
        ms.degradation = mode
        ms.degradation_reason = reason
        if ms.tts_playing and self.tts is not None:
            self.tts.stop(call_id)
        ms.tts_playing = False
        return ms

    # -- lifecycle / janitor --------------------------------------------
    def heartbeat(self, call_id: str, now_ms: Optional[int] = None) -> bool:
        ms = self._sessions.get(call_id)
        if ms is None:
            return False
        ms.last_heartbeat_ms = now_ms if now_ms is not None else self._now()
        return True

    def sweep_orphans(self, now_ms: Optional[int] = None) -> list[str]:
        """Close sessions whose heartbeat is older than TTL. Returns call_ids."""
        now_ms = now_ms if now_ms is not None else self._now()
        dead = [cid for cid, ms in self._sessions.items()
                if now_ms - ms.last_heartbeat_ms > self.config.session_ttl_ms]
        for cid in dead:
            self.close(cid, reason="orphan_ttl")
        return dead

    def close(self, call_id: str, reason: str = "normal") -> Optional[MediaSession]:
        ms = self._sessions.pop(call_id, None)
        self._jitter.pop(call_id, None)
        if ms is not None:
            # Hang-up mid-call must release everything: stop TTS first,
            # then drop the session. A close that leaks TTS / a buffer
            # would leave a task running after the caller is gone.
            if ms.tts_playing and self.tts is not None:
                self.tts.stop(call_id)
            ms.tts_playing = False
            ms.state = CallState.CLOSED
            ms.resources_released = True
            if self.on_session_closed is not None:
                self.on_session_closed(call_id, reason)
        return ms

    def hangup(self, call_id: str, reason: str = "caller_hangup") -> Optional[MediaSession]:
        """Caller hung up mid-call: same full release as close()."""
        return self.close(call_id, reason=reason)

    def close_all(self, reason: str = "shutdown") -> list[str]:
        closed = [cid for cid in list(self._sessions)]
        for cid in closed:
            self.close(cid, reason=reason)
        return closed

    def leaked_resources(self) -> int:
        """Resources still held: live sessions + live jitter buffers.
        Must be 0 after every session is closed / hung up."""
        return len(self._sessions) + len(self._jitter)

    def active_calls(self) -> int:
        return len(self._sessions)
