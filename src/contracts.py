"""Locked shared contracts — vn-realtime-voice-agent.

Branch: fix/fix_latency_constant_name — total SLO constant renamed
CONTRACTS_VERSION = '1.0.0' — locked. Do NOT change a value, a field,
or a constant in this file without a council decision and a version
bump + a test update in tests/test_fix_missing_contracts.py.

This is the FIRST file on main after repo init. Every module imports
from here with exactly one import style::

    from src.contracts import ...

No module may define its own escalation-reason enum, clarification
limit, containment definition, or latency budget. CI greps the rest
of the repo (excluding this file) for locally defined copies — in
particular the hyphenated spelling of the reason values and any
second enum with these values — and fails the build if one is found;
this file itself is the single allowed source. Only the Python 3.11+
standard library is used here.

Locked decisions (from COUNCIL_BUG_DEBATE, reconciled):
1. Escalation reasons are snake_case VALUES. The member names are
   UPPER_SNAKE by Python convention; the values — the strings that
   are logged, counted in metrics and asserted in eval — are always
   snake_case, never hyphenated. The m3 branch used a different
   spelling for the customer-request reason; the locked name is
   ``customer_request``. ``repeated_clarification``
   (clarification budget exhausted) is distinct from
   ``repeated_failure`` (the same step failed repeatedly for another
   reason) and was missing from m3.
2. Clarification counting (locked by debate round #2, enforced in
   code by ``decide_clarification`` below — not just in prose).
   ``MAX_CLARIFICATIONS = 1`` means ONE
   re-ask. Counting rule, locked: the initial elicitation does NOT
   count; each re-ask counts 1. So a slot may be elicited at most
   ``MAX_ELICITATIONS = MAX_CLARIFICATIONS + 1 = 2`` times in total.
   When ``clarifications_used == MAX_CLARIFICATIONS`` and the slot is
   still missing / confidence is still below threshold, the next
   action is HANDOFF, never a second re-ask.
3. Containment, two layers. ``contained_provisional``: the call ended
   with an answer grounded in verified evidence, no handoff and no
   callback ticket. ``contained_final``: provisional AND no recontact
   about the same issue within ``CONTAINMENT_WINDOW_HOURS = 72``.
   The window is stored on every CallMetrics record, so a metric can
   never be quoted without its window. Vendor numbers (52%/76%/80%)
   are NOT containment under this definition.
4. Latency budget (p95). The total SLO is named TOTAL_SLO_P95_MS
   (the p95 SLO in the problem statement); the earlier name for this
   constant is retired and banned by CI grep — no module may import
   it under the old spelling. ASR_PARTIAL_MS (250) + LLM_FIRST_TOKEN_MS
   (500) + TTS_FIRST_AUDIO_MS (350) = 1100 ms, leaving a 100 ms
   buffer inside TOTAL_SLO_P95_MS (1200). A tool call that would
   take longer than TOOL_CALL_OFF_PATH_MS (500) must NOT sit on the
   first-audio path: run it in parallel with an approved filler
   utterance, or prefetch it as soon as its slots are known.
5. ``no_agent`` and ``system_error`` are log-only reasons: they are
   recorded in CallMetrics, but they always map to the CALLBACK
   decision (create a ticket, do not leave the caller in a dead end),
   never to a bare HANDOFF with no agent to receive it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

CONTRACTS_VERSION = "1.0.0"

# ------------------------------------------------------------------
# Clarification budget (locked counting rule — see module docstring).
# ------------------------------------------------------------------
MAX_CLARIFICATIONS = 1
MAX_ELICITATIONS = MAX_CLARIFICATIONS + 1  # initial ask + 1 re-ask = 2

# ------------------------------------------------------------------
# Containment window (locked, hours). Stored on every CallMetrics.
# ------------------------------------------------------------------
CONTAINMENT_WINDOW_HOURS = 72

# ------------------------------------------------------------------
# Latency budget, milliseconds, p95 (locked). Sum of the three
# first-audio stages must stay below TOTAL_SLO_P95_MS.
# ------------------------------------------------------------------
ASR_PARTIAL_MS = 250
LLM_FIRST_TOKEN_MS = 500
TTS_FIRST_AUDIO_MS = 350
TOTAL_SLO_P95_MS = 1200
TOOL_CALL_OFF_PATH_MS = 500

LATENCY_BUDGET_SUM_MS = ASR_PARTIAL_MS + LLM_FIRST_TOKEN_MS + TTS_FIRST_AUDIO_MS
LATENCY_BUFFER_MS = TOTAL_SLO_P95_MS - LATENCY_BUDGET_SUM_MS
# Invariant, checked at import time and in tests: 1100 <= 1200.
assert LATENCY_BUDGET_SUM_MS <= TOTAL_SLO_P95_MS, (
    f"latency budget {LATENCY_BUDGET_SUM_MS}ms exceeds "
    f"TOTAL_SLO_P95_MS {TOTAL_SLO_P95_MS}ms")
assert LATENCY_BUFFER_MS >= 0


def check_latency_budget() -> bool:
    """True iff the locked per-stage budgets fit inside the total SLO."""
    return LATENCY_BUDGET_SUM_MS <= TOTAL_SLO_P95_MS


# ------------------------------------------------------------------ enums
class Decision(str, Enum):
    ANSWER = "answer"            # answer from verified evidence only
    HANDOFF = "handoff"          # transfer to a human with context
    CALLBACK = "callback"        # no agent free / out of hours: ticket
    CLARIFY = "clarify"          # one re-ask, then handoff on 2nd failure
    REJECTED = "rejected"        # forbidden / no evidence, fail-closed


class EscalationReason(str, Enum):
    """The ONLY escalation-reason enum in the repo. Values are snake_case."""
    OUT_OF_SCOPE = "out_of_scope"
    LOW_CONFIDENCE = "low_confidence"
    SENSITIVE = "sensitive"              # complaint / compensation / legal
    CUSTOMER_REQUEST = "customer_request"
    REPEATED_CLARIFICATION = "repeated_clarification"
    REPEATED_FAILURE = "repeated_failure"
    # Log-only: recorded in metrics, always map to CALLBACK (see below).
    NO_AGENT = "no_agent"
    SYSTEM_ERROR = "system_error"


# Backwards-compatible alias for the m3 branch, which used this name.
# It is the SAME enum object, not a second definition.
HandoffReason = EscalationReason

LOG_ONLY_REASONS: frozenset[EscalationReason] = frozenset({
    EscalationReason.NO_AGENT, EscalationReason.SYSTEM_ERROR,
})


def is_log_only_reason(reason: EscalationReason) -> bool:
    return reason in LOG_ONLY_REASONS


def map_reason_to_decision(reason: EscalationReason) -> Decision:
    """Log-only reasons -> CALLBACK; every other reason -> HANDOFF."""
    if reason in LOG_ONLY_REASONS:
        return Decision.CALLBACK
    return Decision.HANDOFF


class Skill(str, Enum):
    ORDER = "order"              # tra don / phi ship / giao hang
    RETURN_WARRANTY = "return_warranty"   # doi tra / bao hanh
    TECHNICAL = "technical"      # huong dan su dung
    BOOKING = "booking"          # dat lich / xac nhan
    COMPLAINT = "complaint"      # khieu nai gay gat
    GENERAL = "general"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    VIP = "vip"


class CallState(str, Enum):
    RINGING = "ringing"
    STREAMING = "streaming"
    BARGE_IN = "barge_in"
    HANDOFF = "handoff"
    CLOSED = "closed"


class DegradationMode(str, Enum):
    NORMAL = "normal"
    IVR_FALLBACK = "ivr_fallback"        # keypad IVR when ASR/LLM fails
    VOICEMAIL = "voicemail"              # record a message, create ticket
    QUEUED = "queued"                    # overload: music + ETA, then AI


class TicketStatus(str, Enum):
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    CALLING = "calling"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class KnowledgeStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    CONFLICT = "conflict"


class ToolName(str, Enum):
    GET_ORDER_STATUS = "get_order_status"
    GET_INVENTORY = "get_inventory"
    GET_APPOINTMENT = "get_appointment"
    GET_POLICY = "get_policy"
    CREATE_CALLBACK_TICKET = "create_callback_ticket"


ALLOWED_TOOLS = frozenset(t.value for t in ToolName)
# Only create_callback_ticket writes; the rest are strictly read-only.
READ_ONLY_TOOLS = frozenset({
    ToolName.GET_ORDER_STATUS.value, ToolName.GET_INVENTORY.value,
    ToolName.GET_APPOINTMENT.value, ToolName.GET_POLICY.value,
})


# ------------------------------------------------------------------ data
@dataclass(frozen=True)
class Evidence:
    """Provenance for one grounded fact. An answer without evidence is forbidden."""
    source_id: str          # e.g. "oms", "wms", "kb:policy-return@v3"
    record_id: str          # e.g. order code, SKU, policy chunk id
    updated_at: str         # ISO-8601 of the source record
    snippet: str = ""       # short verbatim source text (for audit, not TTS)


@dataclass
class ToolResult:
    tool: str
    ok: bool
    data: dict = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    error: str = ""
    status: str = "ok"      # ok | not_found | rejected | timeout | error
    latency_ms: float = 0.0


@dataclass
class TenantContext:
    tenant_id: str          # shop_id from the authenticated trunk/session
    shop_id: str = ""
    channel: str = "sip"    # sip | webrtc | pstn


@dataclass
class CallerInfo:
    phone: str = ""                     # partially masked in logs
    name: str = ""
    verified: bool = False              # ownership check passed
    verification_method: str = ""       # phone_suffix | otp | none


@dataclass
class TranscriptTurn:
    speaker: str            # "caller" | "ai" | "agent"
    text: str
    ts_ms: int = 0


@dataclass
class CallSession:
    call_id: str
    tenant: TenantContext
    caller: CallerInfo = field(default_factory=CallerInfo)
    state: CallState = CallState.RINGING
    skill: Skill = Skill.GENERAL
    priority: Priority = Priority.NORMAL
    transcript: list[TranscriptTurn] = field(default_factory=list)
    slots: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    created_at_ms: int = 0
    last_heartbeat_ms: int = 0


@dataclass
class ConfidenceDecision:
    """One gate decision. ``clarifications_used`` counts RE-ASKS only
    (see the locked counting rule): 0 = no re-ask yet, 1 = budget used."""
    action: Decision
    confidence: float = 0.0
    threshold: float = 0.0
    escalation_reason: Optional[EscalationReason] = None
    clarifications_used: int = 0
    evidence_present: bool = False

    def can_clarify(self) -> bool:
        """True only if a re-ask is still within budget AND the reason
        is not a hard-stop (sensitive / customer request)."""
        if self.escalation_reason in (EscalationReason.SENSITIVE,
                                      EscalationReason.CUSTOMER_REQUEST):
            return False
        return self.clarifications_used < MAX_CLARIFICATIONS

    def should_hand_off(self) -> bool:
        return self.action in (Decision.HANDOFF, Decision.CALLBACK)


def decide_clarification(elicitations_used: int,
                         has_hard_stop: bool = False
                         ) -> tuple[bool, Optional[EscalationReason]]:
    """Locked counting rule (debate round #2), in code.

    Counting: the FIRST time a missing slot is detected is the
    initial elicitation (elicitations_used == 1 after it) — it is
    NOT a clarification. A re-ask is allowed exactly once
    (``MAX_CLARIFICATIONS = 1``): elicitations_used == 1 -> clarify.
    If the slot is STILL missing after that one re-ask
    (elicitations_used >= MAX_ELICITATIONS == 2) -> escalate with
    ``repeated_clarification``. A hard stop (sensitive /
    customer_request) never clarifies, whatever the count.
    The rejected backend-sec variant (2 re-asks) is NOT implemented:
    elicitations_used == 1 is the only clarifying state.
    Returns (may_clarify, escalation_reason_if_not).
    """
    if has_hard_stop:
        return False, EscalationReason.SENSITIVE
    if elicitations_used < 1:
        return False, None  # no missing slot detected yet; nothing to clarify
    if elicitations_used == 1:
        return True, None
    return False, EscalationReason.REPEATED_CLARIFICATION


@dataclass
class HandoffPackage:
    """The handoff payload: everything an agent needs, no re-asking.

    Renamed from ContextPackage (m3 branch); same schema, no new
    fields invented. ``reason`` uses the locked EscalationReason.
    """
    call_id: str
    tenant_id: str
    summary: str                        # 3-5 lines, Vietnamese
    transcript: list[TranscriptTurn] = field(default_factory=list)
    caller: CallerInfo = field(default_factory=CallerInfo)
    intent: str = ""
    slots: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    reason: EscalationReason = EscalationReason.OUT_OF_SCOPE
    skill: Skill = Skill.GENERAL
    priority: Priority = Priority.NORMAL
    idempotency_key: str = ""


# Backwards-compatible alias for the m3 branch. Same dataclass, not a copy.
ContextPackage = HandoffPackage


@dataclass
class CallbackTicket:
    ticket_id: str
    call_id: str
    tenant_id: str
    phone: str
    summary: str
    preferred_time: str = ""            # ISO-8601 window chosen by caller
    status: TicketStatus = TicketStatus.QUEUED
    attempts: int = 0
    idempotency_key: str = ""
    reason: EscalationReason = EscalationReason.NO_AGENT


@dataclass
class KnowledgeChunk:
    chunk_id: str
    doc_id: str
    text: str
    version: int
    status: KnowledgeStatus = KnowledgeStatus.PUBLISHED
    source: str = ""
    tenant_id: str = ""
    effective_from: str = ""
    effective_to: str = ""
    approved_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallMetrics:
    """Per-call metrics. Containment is two-layer (see module docstring):
    provisional is decided at call end; final is decided only after
    the window elapses without a recontact on the same issue.
    ``window_hours`` is stored on every record, so the number is
    never quoted without its window."""
    call_id: str
    tenant_id: str
    contained_provisional: bool = False
    contained_final: bool = False
    window_hours: int = CONTAINMENT_WINDOW_HOURS
    recontacted_within_window: bool = False
    evidence_present: bool = False
    escalation_reason: Optional[EscalationReason] = None
    asr_partial_ms: float = 0.0
    llm_first_token_ms: float = 0.0
    tts_first_audio_ms: float = 0.0
    total_turn_ms: float = 0.0

    def compute_contained_final(self) -> bool:
        """Final containment: provisional AND no recontact in the window."""
        self.contained_final = bool(
            self.contained_provisional and not self.recontacted_within_window)
        return self.contained_final

    def latency_within_budget(self) -> bool:
        """Per-stage budgets fit the total SLO (checked on real timings)."""
        return (
            self.asr_partial_ms <= ASR_PARTIAL_MS
            and self.llm_first_token_ms <= LLM_FIRST_TOKEN_MS
            and self.tts_first_audio_ms <= TTS_FIRST_AUDIO_MS
            and self.total_turn_ms <= TOTAL_SLO_P95_MS
        )


@dataclass
class ScalingMetrics:
    concurrent_calls: int
    cpu_percent: float
    queue_latency_ms: float
    timestamp_ms: int = 0


@dataclass
class ScalingDecision:
    desired_replicas: int
    action: str                         # scale_up | scale_down | hold | shed
    reason: str = ""
    shed_new_calls: bool = False
