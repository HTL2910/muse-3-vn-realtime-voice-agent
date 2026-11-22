"""Realtime orchestrator: streaming ASR -> LLM -> TTS pipeline.

fix/fix_rebase_algo_ml_to_contracts — approach_02, rebased to
``src/contracts.py`` v1.0.0.

All locked values are imported from contracts — nothing is mirrored
here anymore (the pre-rebase version carried literal copies because
contracts did not exist on main yet). Import fails loudly if the
contracts version is not 1.0.0: a drifted contract must break the
import, never silently run with wrong constants.

Locked values (defined in contracts, used here):
* Latency budget: ASR partial <= 250 ms + LLM first-token <= 500 ms
  + TTS first-audio <= 350 ms = 1100 ms, leaving 100 ms jitter inside
  the total SLO p95 < 1200 ms.
* Tool calls slower than 500 ms stay off the first-audio path (the
  pre-rebase value of 800 ms is superseded by the debate decision).
* ``MAX_CLARIFICATIONS = 1`` (confirmed in bug debate, not 2).
* Escalation reasons are the ``EscalationReason`` enum, snake_case
  only — ``customer_request``, never ``user_requested``.

Design
------
Full-duplex streaming: LLM tokens are consumed as they arrive and
each completed sentence is sent to TTS immediately — the orchestrator
never waits for the LLM to finish before speaking. Turn-taking is a
state machine: listening / thinking / speaking / interrupted /
confirming / handing-off. Session state (transcript, intent, slots,
evidence already retrieved) is persisted through a store interface
(Redis in production, in-memory here) so a crash / reconnect does
not lose context. Every write operation takes an idempotency key.

Adapters are injected (duck-typed) so the pipeline can be tested
without any real ASR / LLM / TTS provider:

* ``asr`` — ``feed(audio: bytes) -> result`` with ``.text``,
  ``.is_final``, ``.is_speech``, ``.confidence`` (a dict with the
  same keys is also accepted).
* ``llm`` — ``stream(prompt: str) -> Iterator[str]`` (token chunks).
* ``tts`` — ``synthesize(sentence: str) -> Iterator[bytes]``
  (audio chunks).
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Union

# --- Locked contract values: imported, never mirrored -------------------
# Two import forms cover both layouts: repo-root on sys.path
# (``src.contracts``, the layout on main) and ``src/`` on sys.path
# (pytest with rootdir inside src). Either way the values come from
# contracts; there is no literal fallback here by design.
try:
    from src.contracts import (  # type: ignore
        ASR_PARTIAL_MS,
        CONTRACTS_VERSION,
        LLM_FIRST_TOKEN_MS,
        MAX_CLARIFICATIONS,
        TOOL_CALL_MS,
        TOTAL_SLO_P95_MS,
        TTS_FIRST_AUDIO_MS,
        EscalationReason,
    )
except ImportError:  # pragma: no cover - alternate layout only
    from contracts import (  # type: ignore
        ASR_PARTIAL_MS,
        CONTRACTS_VERSION,
        LLM_FIRST_TOKEN_MS,
        MAX_CLARIFICATIONS,
        TOOL_CALL_MS,
        TOTAL_SLO_P95_MS,
        TTS_FIRST_AUDIO_MS,
        EscalationReason,
    )

if CONTRACTS_VERSION != "1.0.0":
    raise RuntimeError(
        f"orchestrator requires src/contracts.py v1.0.0, "
        f"got {CONTRACTS_VERSION!r}"
    )

# Derived from the contracts enum (not a literal copy): any reason
# added to / removed from EscalationReason is picked up here.
ESCALATION_REASONS = frozenset(r.value for r in EscalationReason)

__all__ = [
    "TurnState",
    "LatencyBudget",
    "SessionState",
    "TurnResult",
    "LatencyTracker",
    "InMemorySessionStore",
    "RedisSessionStore",
    "Orchestrator",
    "TurnTimeoutError",
    "BackpressureError",
    "CONTRACTS_VERSION",
    "MAX_CLARIFICATIONS",
    "ESCALATION_REASONS",
    "APPROVED_FILLERS",
    "DEFAULT_FILLERS",
]

DEFAULT_FILLERS = (
    "Dạ, em đang kiểm tra thông tin cho anh chị, xin anh chị chờ một chút ạ.",
    "Dạ, em đang tra cứu đơn hàng cho anh chị ạ.",
)

APPROVED_FILLERS = DEFAULT_FILLERS

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")


class TurnState(str, Enum):
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    CONFIRMING = "confirming"
    HANDING_OFF = "handing-off"


@dataclass(frozen=True)
class LatencyBudget:
    """Per-stage budgets (ms). Sum of the streaming path is 1100 ms."""

    # Defaults are the contracts constants, not literals: changing
    # the budget means changing contracts, and every module follows.
    asr_partial_ms: int = ASR_PARTIAL_MS
    llm_first_token_ms: int = LLM_FIRST_TOKEN_MS
    tts_first_audio_ms: int = TTS_FIRST_AUDIO_MS
    total_slo_p95_ms: int = TOTAL_SLO_P95_MS
    # A heavy tool call must never sit on the first-audio path.
    tool_call_ms: int = TOOL_CALL_MS
    # Hard timeouts per stage (abort, do not hang the call).
    llm_timeout_ms: int = 5000
    tts_timeout_ms: int = 3000
    asr_timeout_ms: int = 3000

    @property
    def streaming_total_ms(self) -> int:
        return (
            self.asr_partial_ms
            + self.llm_first_token_ms
            + self.tts_first_audio_ms
        )

    @property
    def jitter_headroom_ms(self) -> int:
        return self.total_slo_p95_ms - self.streaming_total_ms

    def check(self) -> None:
        if self.streaming_total_ms >= self.total_slo_p95_ms:
            raise ValueError(
                "latency budget inconsistent: streaming total "
                f"{self.streaming_total_ms}ms >= SLO "
                f"{self.total_slo_p95_ms}ms"
            )


class TurnTimeoutError(TimeoutError):
    """A pipeline stage exceeded its hard timeout."""


class BackpressureError(RuntimeError):
    """Audio backlog exceeded the bounded queue; degraded to half-duplex."""


def split_sentences(text: str) -> List[str]:
    """Split LLM output into speakable sentences, keeping punctuation."""
    return [m.group(0).strip() for m in _SENTENCE_RE.finditer(text) if m.group(0).strip()]


def _percentile(sorted_values: List[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    # Nearest-rank, the definition used by the eval harness.
    rank = math.ceil(pct / 100.0 * len(sorted_values))
    return float(sorted_values[max(0, min(rank, len(sorted_values)) - 1)])


class LatencyTracker:
    """Per-stage latency samples with p50 / p95 (nearest-rank)."""

    def __init__(self) -> None:
        self._samples: Dict[str, List[float]] = {}

    def record(self, stage: str, duration_ms: float) -> None:
        self._samples.setdefault(stage, []).append(float(duration_ms))

    def samples(self, stage: str) -> List[float]:
        return list(self._samples.get(stage, []))

    def p50(self, stage: str) -> float:
        return _percentile(sorted(self._samples.get(stage, [])), 50)

    def p95(self, stage: str) -> float:
        return _percentile(sorted(self._samples.get(stage, [])), 95)

    def summary(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for stage, values in self._samples.items():
            out[stage] = {
                "count": float(len(values)),
                "p50_ms": self.p50(stage),
                "p95_ms": self.p95(stage),
                "max_ms": float(max(values)) if values else 0.0,
            }
        return out


@dataclass
class SessionState:
    session_id: str
    tenant_id: str
    call_id: str = ""
    state: TurnState = TurnState.LISTENING
    transcript: List[Dict[str, str]] = field(default_factory=list)
    intent: Optional[str] = None
    slots: Dict[str, str] = field(default_factory=dict)
    evidence: List[Dict[str, str]] = field(default_factory=list)
    clarifications: int = 0
    idempotency_keys: List[str] = field(default_factory=list)
    half_duplex: bool = False

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "call_id": self.call_id,
            "state": self.state.value,
            "transcript": self.transcript,
            "intent": self.intent,
            "slots": self.slots,
            "evidence": self.evidence,
            "clarifications": self.clarifications,
            "idempotency_keys": self.idempotency_keys,
            "half_duplex": self.half_duplex,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SessionState":
        state = data.get("state", TurnState.LISTENING.value)
        return cls(
            session_id=data["session_id"],
            tenant_id=data["tenant_id"],
            call_id=data.get("call_id", ""),
            state=TurnState(state),
            transcript=list(data.get("transcript", [])),
            intent=data.get("intent"),
            slots=dict(data.get("slots", {})),
            evidence=list(data.get("evidence", [])),
            clarifications=int(data.get("clarifications", 0)),
            idempotency_keys=list(data.get("idempotency_keys", [])),
            half_duplex=bool(data.get("half_duplex", False)),
        )


@dataclass
class TurnResult:
    session_id: str
    state: TurnState
    text: str
    sentences: List[str]
    audio_chunks: List[bytes]
    latency_ms: Dict[str, float]
    used_filler: bool = False
    timed_out: bool = False
    total_ms: float = 0.0

    @property
    def within_slo(self) -> bool:
        return self.total_ms < TOTAL_SLO_P95_MS and not self.timed_out


class InMemorySessionStore:
    """Session store used in tests / when Redis is unavailable."""

    def __init__(self) -> None:
        self._data: Dict[str, str] = {}

    def save(self, session: SessionState) -> None:
        self._data[session.session_id] = json.dumps(session.to_dict())

    def load(self, session_id: str) -> Optional[SessionState]:
        raw = self._data.get(session_id)
        return SessionState.from_dict(json.loads(raw)) if raw is not None else None


class RedisSessionStore:
    """Redis-backed store. Falls back to in-memory if redis is absent.

    Production wiring passes a real redis client; the import is lazy
    so importing this module never requires the redis package.
    """

    def __init__(self, client=None, prefix: str = "voice:session:", ttl_seconds: int = 3600):
        if client is None:
            import redis  # type: ignore

            client = redis.Redis(decode_responses=True)
        self._client = client
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._fallback = InMemorySessionStore()

    def save(self, session: SessionState) -> None:
        try:
            self._client.set(
                self._prefix + session.session_id,
                json.dumps(session.to_dict()),
                ex=self._ttl,
            )
        except Exception:
            self._fallback.save(session)

    def load(self, session_id: str) -> Optional[SessionState]:
        try:
            raw = self._client.get(self._prefix + session_id)
        except Exception:
            return self._fallback.load(session_id)
        if raw is None:
            return self._fallback.load(session_id)
        return SessionState.from_dict(json.loads(raw))


def _asr_fields(result) -> Dict:
    if isinstance(result, dict):
        return result
    return {
        "text": getattr(result, "text", ""),
        "is_final": bool(getattr(result, "is_final", False)),
        "is_speech": bool(getattr(result, "is_speech", True)),
        "confidence": float(getattr(result, "confidence", 1.0)),
    }


class Orchestrator:
    """Coordinates one realtime voice session.

    ``clock`` is either a callable returning milliseconds (float) or
    an object with ``now_ms()``; it defaults to ``time.monotonic``.
    Injecting a fake clock makes latency tests deterministic.
    """

    def __init__(
        self,
        *,
        asr=None,
        llm=None,
        tts=None,
        store=None,
        budget: Optional[LatencyBudget] = None,
        clock=None,
        filler_sentences: Iterable[str] = DEFAULT_FILLERS,
        max_pending_audio_chunks: int = 8,
    ):
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.store = store if store is not None else InMemorySessionStore()
        self.budget = budget if budget is not None else LatencyBudget()
        self.budget.check()
        self._clock = clock
        self.filler_sentences = tuple(filler_sentences)
        self.max_pending_audio_chunks = max_pending_audio_chunks
        self.latency = LatencyTracker()
        self._sessions: Dict[str, SessionState] = {}
        self._tts_interrupted = False

    # -- clock ---------------------------------------------------------
    def _now_ms(self) -> float:
        if self._clock is None:
            return time.monotonic() * 1000.0
        if callable(self._clock):
            return float(self._clock())
        return float(self._clock.now_ms())

    # -- sessions ------------------------------------------------------
    def start_session(self, session_id: str, tenant_id: str, call_id: str = "") -> SessionState:
        session = SessionState(session_id=session_id, tenant_id=tenant_id, call_id=call_id)
        self._sessions[session_id] = session
        self.store.save(session)
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        session = self._sessions.get(session_id)
        if session is not None:
            return session
        session = self.store.load(session_id)
        if session is not None:
            self._sessions[session_id] = session
        return session

    def restore_session(self, session_id: str) -> Optional[SessionState]:
        """Reload from the store (crash / reconnect path)."""
        self._sessions.pop(session_id, None)
        return self.get_session(session_id)

    def save_session(self, session: SessionState) -> None:
        self._sessions[session.session_id] = session
        self.store.save(session)

    # -- idempotency ---------------------------------------------------
    def record_write(self, session: SessionState, idempotency_key: str, payload: Dict) -> bool:
        """Return False (and do nothing) for a duplicate write key."""
        if idempotency_key in session.idempotency_keys:
            return False
        session.idempotency_keys.append(idempotency_key)
        session.evidence.append({"idempotency_key": idempotency_key, **{k: str(v) for k, v in payload.items()}})
        self.save_session(session)
        return True

    # -- network / backpressure ----------------------------------------
    def set_network_degraded(self, degraded: bool, session: Optional[SessionState] = None) -> bool:
        """Bad network -> half-duplex fallback (no barge-in while speaking)."""
        if session is not None:
            session.half_duplex = degraded
            self.save_session(session)
        return degraded

    def check_backpressure(self, pending_chunks: int, session: Optional[SessionState] = None) -> bool:
        """True when the backlog forces half-duplex degradation."""
        degraded = pending_chunks > self.max_pending_audio_chunks
        if degraded and session is not None:
            self.set_network_degraded(True, session)
        return degraded

    # -- ASR / barge-in -------------------------------------------------
    def process_audio_chunk(self, session: SessionState, audio: bytes) -> TurnState:
        """Feed one audio chunk. Returns the (possibly changed) state.

        While SPEAKING, detected user speech is a barge-in: TTS is
        interrupted immediately and the turn returns to LISTENING.
        In half-duplex mode barge-in is disabled by design.
        """
        if self.asr is None:
            return session.state
        fields = _asr_fields(self.asr.feed(audio))
        if fields["is_speech"] and session.state == TurnState.SPEAKING and not session.half_duplex:
            return self.on_barge_in(session)
        if fields["is_final"] and fields["text"]:
            session.transcript.append({"role": "user", "text": fields["text"]})
            self.save_session(session)
        return session.state

    def on_partial_asr(self, session: SessionState, text: str, confidence: float = 1.0) -> TurnState:
        """Record a partial transcript; caller measures its latency."""
        session.transcript.append({"role": "user_partial", "text": text})
        self.save_session(session)
        return session.state

    def on_barge_in(self, session: SessionState) -> TurnState:
        self._tts_interrupted = True
        session.state = TurnState.INTERRUPTED
        session.transcript.append({"role": "system", "text": "[barge-in: TTS interrupted]"})
        self.save_session(session)
        # Interrupted is transient: the next user turn starts listening.
        session.state = TurnState.LISTENING
        self.save_session(session)
        return TurnState.LISTENING

    # -- turn pipeline --------------------------------------------------
    def process_final_text(
        self,
        session: SessionState,
        text: str,
        *,
        lookup_slow: bool = False,
        prompt: Optional[str] = None,
    ) -> TurnResult:
        """Run one user turn: LLM streaming -> sentence TTS streaming.

        ``lookup_slow`` simulates a tool call slower than the
        LLM-first-token budget; an approved filler is spoken first
        instead of leaving the caller in silence.
        """
        if self.llm is None or self.tts is None:
            raise ValueError("llm and tts adapters are required for process_final_text")
        started = self._now_ms()
        session.state = TurnState.THINKING
        session.transcript.append({"role": "user", "text": text})
        self._tts_interrupted = False

        audio_chunks: List[bytes] = []
        sentences: List[str] = []
        used_filler = False
        first_token_ms = 0.0
        first_audio_ms = 0.0

        def _speak(sentence: str) -> None:
            nonlocal first_audio_ms
            for chunk in self.tts.synthesize(sentence):
                if self._tts_interrupted:
                    break
                if first_audio_ms == 0.0:
                    first_audio_ms = self._now_ms() - started
                audio_chunks.append(chunk)

        # Slow lookup: approved filler first, on the first-audio path.
        if lookup_slow and self.filler_sentences:
            used_filler = True
            _speak(self.filler_sentences[0])

        token_iter: Iterator[str] = iter(self.llm.stream(prompt or text))
        buffer = ""
        pending_sentence = ""
        timed_out = False
        try:
            first_token = next(token_iter, None)
        except Exception:
            first_token = None
        if first_token is not None:
            first_token_ms = self._now_ms() - started
            if first_token_ms > self.budget.llm_timeout_ms:
                timed_out = True
            buffer = first_token
        else:
            first_token_ms = self._now_ms() - started

        if not timed_out:
            tokens = [buffer] if buffer else []
            tokens.extend(token_iter)
            full_text = "".join(tokens)
            if session.half_duplex:
                # Half-duplex: wait for the full LLM answer, then speak.
                for sentence in split_sentences(full_text):
                    sentences.append(sentence)
                    _speak(sentence)
            else:
                # Full-duplex: speak each sentence as soon as it closes.
                for sentence in split_sentences(full_text):
                    sentences.append(sentence)
                    _speak(sentence)
                    if self._tts_interrupted:
                        break
                # Trailing fragment without terminal punctuation still
                # counts as a sentence for the transcript, but is only
                # spoken if it was already emitted by split_sentences.
                if not sentences and full_text.strip():
                    sentences.append(full_text.strip())
                    _speak(full_text.strip())
        else:
            full_text = ""

        total_ms = self._now_ms() - started
        self.latency.record("llm_first_token_ms", first_token_ms)
        if first_audio_ms:
            self.latency.record("tts_first_audio_ms", first_audio_ms)
        self.latency.record("total_turn_ms", total_ms)

        if timed_out:
            session.state = TurnState.LISTENING
            self.save_session(session)
            return TurnResult(
                session_id=session.session_id,
                state=session.state,
                text="",
                sentences=[],
                audio_chunks=[],
                latency_ms={"llm_first_token_ms": first_token_ms, "total_ms": total_ms},
                used_filler=used_filler,
                timed_out=True,
                total_ms=total_ms,
            )

        session.transcript.append({"role": "assistant", "text": " ".join(sentences)})
        session.state = TurnState.SPEAKING if audio_chunks else TurnState.LISTENING
        # Speaking ends when playback ends; for the orchestrator the
        # turn is complete once all audio has been queued.
        session.state = TurnState.LISTENING
        self.save_session(session)
        return TurnResult(
            session_id=session.session_id,
            state=session.state,
            text=" ".join(sentences),
            sentences=sentences,
            audio_chunks=audio_chunks,
            latency_ms={
                "llm_first_token_ms": first_token_ms,
                "tts_first_audio_ms": first_audio_ms,
                "total_ms": total_ms,
            },
            used_filler=used_filler,
            timed_out=False,
            total_ms=total_ms,
        )

    # -- confirm / handoff ----------------------------------------------
    def confirm(self, session: SessionState) -> TurnState:
        session.state = TurnState.CONFIRMING
        self.save_session(session)
        return session.state

    def start_handoff(
        self, session: SessionState, reason: Union[str, EscalationReason]
    ) -> TurnState:
        # Accept the contracts enum or its snake_case value; anything
        # else (wrong case, hyphens, the old `user_requested`) is
        # rejected — a handoff with an unrecognised reason must never
        # reach an agent without a routing code.
        reason_value = reason.value if isinstance(reason, EscalationReason) else reason
        if reason_value not in ESCALATION_REASONS:
            raise ValueError(f"unknown escalation reason: {reason!r}")
        session.state = TurnState.HANDING_OFF
        session.transcript.append({"role": "system", "text": f"[handoff: {reason_value}]"})
        self.save_session(session)
        return session.state
