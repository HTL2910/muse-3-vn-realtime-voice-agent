"""Context package for handoff + Agent Desktop card (approach_10).

fix_missing_handoff_package — the ContextPackage is split out of the m3
handoff code into its own module. NO new schema is invented: the fields
are exactly the HandoffPackage fields locked in contracts (verified
customer identity, intent/need, collected slots, transcript, tool calls,
recording URL, snake_case escalation reason, priority) plus the summary
and sentiment/urgency fields the council spec adds.

Summary contract:
- Exactly 3 parts: (1) who the customer is + what was verified,
  (2) what was discussed and looked up, (3) what the agent must do next.
- A summary may be drafted by an LLM (injected ``summarizer``), but it is
  only used after ``validate_summary`` proves every concrete fact it
  mentions (order codes, phone numbers, amounts, dates) appears in the
  evidence: transcript, slots, verified customer or tool results.
  If validation fails, a deterministic evidence-only summary is built
  instead — an unvalidated summary never reaches the agent.

Agent Desktop contract:
- ``build_desktop_card`` returns a one-screen card (bounded lines/fields)
  an agent can absorb before picking up; ``measure_time_to_context``
  measures how long building + reading the card's key facts takes and
  the tests assert it is far below the 5-second budget.
- Card actions: accept / push back; agent notes append to the SAME
  ticket (``add_agent_note``), so the conversation is never restarted.
- ``ensure_no_dead_end``: when no agent is available, a callback ticket
  carrying the full package is created instead of dropping the customer.
"""
from __future__ import annotations

import itertools
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

# Rebased onto contracts v1.0.0 (fix_rebase_remaining_fullstack):
# the valid reason set is derived from contracts' EscalationReason —
# no local mirror of the locked snake_case values.
from src.contracts import EscalationReason

VALID_REASONS = {r.value for r in EscalationReason}
VALID_PRIORITIES = {"normal", "high", "vip", "urgent"}
TIME_TO_CONTEXT_BUDGET_S = 5.0
CARD_MAX_LINES = 12


def _check_reason(reason: str) -> str:
    if reason not in VALID_REASONS:
        raise ValueError(f"invalid_escalation_reason:{reason}")
    return reason


@dataclass
class TranscriptEntry:
    role: str                       # customer | agent_ai | agent_human | system
    text: str
    timestamp: float                # seconds from call start (required)

    def __post_init__(self):
        if self.timestamp is None:
            raise ValueError("transcript_entry_requires_timestamp")

    def to_dict(self):
        return asdict(self)


@dataclass
class ToolCallRecord:
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[float] = None
    duration_ms: Optional[int] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class SummaryParts:
    who_and_verified: str = ""      # part 1
    discussed_and_looked_up: str = ""  # part 2
    next_action: str = ""           # part 3

    def all_text(self) -> str:
        return " ".join([self.who_and_verified, self.discussed_and_looked_up,
                         self.next_action])

    def to_dict(self):
        return asdict(self)


@dataclass
class ContextPackage:
    # --- HandoffPackage (contracts) fields --------------------------------
    call_id: str
    escalation_reason: str
    tenant_id: str = ""
    customer_id: str = ""
    phone: str = ""
    verified_customer: Dict[str, Any] = field(default_factory=dict)
    intent: str = ""
    unresolved_needs: List[str] = field(default_factory=list)
    slots: Dict[str, Any] = field(default_factory=dict)
    transcript: List[TranscriptEntry] = field(default_factory=list)
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    recording_url: str = ""
    priority: str = "normal"
    # --- spec additions -----------------------------------------------------
    summary: SummaryParts = field(default_factory=SummaryParts)
    sentiment: str = "neutral"      # neutral | negative | angry
    urgency: str = "normal"         # normal | high | critical
    frustration_level: int = 0
    ticket_id: Optional[str] = None
    agent_notes: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "ready"           # ready | accepted | pushed_back | callback_pending

    def __post_init__(self):
        _check_reason(self.escalation_reason)
        if self.priority not in VALID_PRIORITIES:
            raise ValueError(f"invalid_priority:{self.priority}")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ContextPackage":
        d = dict(d or {})
        if isinstance(d.get("summary"), dict):
            d["summary"] = SummaryParts(**d["summary"])
        d["transcript"] = [
            t if isinstance(t, TranscriptEntry) else TranscriptEntry(**t)
            for t in d.get("transcript", [])]
        d["tool_calls"] = [
            t if isinstance(t, ToolCallRecord) else ToolCallRecord(**t)
            for t in d.get("tool_calls", [])]
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


# The contracts name for the same unit.
HandoffPackage = ContextPackage


# --- Evidence & summary validation -------------------------------------------
_CODE_RE = re.compile(r"\b[A-Z]{1,4}\d{4,}\b")
_PHONE_RE = re.compile(r"\b0\d{9}\b")
_AMOUNT_RE = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+\b|\b\d{5,}\s?(?:đ|vnd|đồng)\b",
                        re.IGNORECASE)
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")


def _evidence_text(pkg: ContextPackage) -> str:
    parts = [e.text for e in pkg.transcript]
    parts += [str(v) for v in pkg.slots.values()]
    parts += [str(v) for v in pkg.verified_customer.values()]
    for tc in pkg.tool_calls:
        parts += [str(v) for v in tc.args.values()]
        parts += [str(v) for v in tc.result.values()]
    if pkg.phone:
        parts.append(pkg.phone)
    return " ".join(parts)


def _facts(text: str) -> set:
    facts = set(_CODE_RE.findall(text or ""))
    facts |= set(_PHONE_RE.findall(text or ""))
    facts |= {m.group(0) for m in _AMOUNT_RE.finditer(text or "")}
    facts |= set(_DATE_RE.findall(text or ""))
    return facts


def validate_summary(pkg: ContextPackage,
                     summary: Optional[SummaryParts] = None) -> List[str]:
    """Return a list of errors; empty means the summary is grounded."""
    s = summary or pkg.summary
    errors: List[str] = []
    if not s.who_and_verified.strip():
        errors.append("summary_part1_empty")
    if not s.discussed_and_looked_up.strip():
        errors.append("summary_part2_empty")
    if not s.next_action.strip():
        errors.append("summary_part3_empty")
    evidence_facts = _facts(_evidence_text(pkg))
    for fact in _facts(s.all_text()):
        if fact not in evidence_facts:
            errors.append(f"summary_fact_not_in_evidence:{fact}")
    return errors


def build_evidence_summary(pkg: ContextPackage) -> SummaryParts:
    """Deterministic summary built only from package evidence."""
    who = pkg.verified_customer.get("name") or pkg.customer_id or "Khách"
    verified_bits = [k for k in ("phone_verified", "order_verified",
                                 "identity_verified")
                     if pkg.verified_customer.get(k)]
    part1 = f"{who} (SĐT {pkg.phone or 'chưa có'}); đã xác minh: " \
            f"{', '.join(verified_bits) if verified_bits else 'chưa có mục nào'}."
    looked = "; ".join(f"{tc.tool} -> {tc.result}" for tc in pkg.tool_calls)
    needs = ", ".join(pkg.unresolved_needs) or pkg.intent or "nhu cầu chưa rõ"
    part2 = f"Nhu cầu: {needs}. Đã tra cứu: {looked or 'chưa tra cứu được dữ liệu'}."
    part3 = (f"Nhân viên tiếp tục xử lý: {needs}; lý do chuyển: "
             f"{pkg.escalation_reason}; mức ưu tiên: {pkg.priority}.")
    return SummaryParts(part1, part2, part3)


def build_context_package(pkg: ContextPackage,
                          summarizer: Optional[Callable] = None) -> ContextPackage:
    """Optionally let an injected LLM summarizer draft the 3-part summary,
    validate it against the transcript/evidence, and fall back to the
    deterministic evidence summary when validation fails."""
    if summarizer is not None:
        try:
            draft = summarizer(pkg)
            if isinstance(draft, dict):
                draft = SummaryParts(**{k: draft.get(k, "") for k in (
                    "who_and_verified", "discussed_and_looked_up", "next_action")})
            if isinstance(draft, SummaryParts) and not validate_summary(pkg, draft):
                pkg.summary = draft
                return pkg
        except Exception:
            pass  # fall through to the safe summary
    pkg.summary = build_evidence_summary(pkg)
    errors = validate_summary(pkg)
    if errors:  # evidence summary must always be valid; if not, blank is safer
        raise ValueError(f"evidence_summary_invalid:{errors}")
    return pkg


# --- Agent Desktop -------------------------------------------------------------
def build_desktop_card(pkg: ContextPackage) -> Dict[str, Any]:
    """One-screen pop-up card shown BEFORE the agent picks up."""
    lines = [
        f"[{pkg.priority.upper()}] {pkg.intent or 'Nhu cầu'} — {pkg.escalation_reason}",
        f"Khách: {pkg.verified_customer.get('name') or pkg.customer_id or '—'}"
        f" · {pkg.phone or '—'} · cảm xúc: {pkg.sentiment}/{pkg.urgency}",
        f"1) {pkg.summary.who_and_verified}",
        f"2) {pkg.summary.discussed_and_looked_up}",
        f"3) Việc tiếp theo: {pkg.summary.next_action}",
    ]
    if pkg.recording_url:
        lines.append(f"Ghi âm: {pkg.recording_url}")
    card = {
        "call_id": pkg.call_id,
        "ticket_id": pkg.ticket_id,
        "header": lines[0],
        "lines": lines[:CARD_MAX_LINES],
        "who": pkg.summary.who_and_verified,
        "discussed": pkg.summary.discussed_and_looked_up,
        "next_action": pkg.summary.next_action,
        "escalation_reason": pkg.escalation_reason,
        "priority": pkg.priority,
        "sentiment": pkg.sentiment,
        "urgency": pkg.urgency,
        "transcript": [e.to_dict() for e in pkg.transcript],
        "actions": ["accept", "push_back"],
        "note_field": {"ticket_id": pkg.ticket_id, "enabled": True},
        "one_screen": len(lines) <= CARD_MAX_LINES,
    }
    return card


def measure_time_to_context(pkg: ContextPackage) -> float:
    """Seconds to build the card and surface its 3 key facts. The agent's
    comprehension budget is 5s; building must be a tiny fraction of it."""
    start = time.perf_counter()
    card = build_desktop_card(pkg)
    _ = (card["who"], card["discussed"], card["next_action"])
    return time.perf_counter() - start


def accept_handoff(pkg: ContextPackage, agent_id: str) -> ContextPackage:
    pkg.status = "accepted"
    pkg.agent_notes.append({"agent_id": agent_id, "type": "accept",
                            "at": time.time()})
    return pkg


def push_back_handoff(pkg: ContextPackage, agent_id: str,
                      note: str = "") -> ContextPackage:
    pkg.status = "pushed_back"
    pkg.agent_notes.append({"agent_id": agent_id, "type": "push_back",
                            "note": note, "at": time.time()})
    return pkg


def add_agent_note(pkg: ContextPackage, agent_id: str, note: str) -> ContextPackage:
    """Append a note to the SAME ticket — never a new conversation."""
    pkg.agent_notes.append({"agent_id": agent_id, "type": "note",
                            "note": note, "ticket_id": pkg.ticket_id,
                            "at": time.time()})
    return pkg


# --- No dead end -----------------------------------------------------------------
_ticket_seq = itertools.count(1)


def create_callback_ticket(pkg: ContextPackage,
                           ticket_factory: Optional[Callable] = None) -> Dict[str, Any]:
    ticket_id = (ticket_factory(pkg) if ticket_factory
                 else f"CB-{next(_ticket_seq):06d}")
    pkg.ticket_id = ticket_id
    pkg.status = "callback_pending"
    return {"outcome": "callback", "ticket_id": ticket_id,
            "call_id": pkg.call_id, "package": pkg.to_dict()}


def ensure_no_dead_end(pkg: ContextPackage, agent_available: bool,
                       ticket_factory: Optional[Callable] = None) -> Dict[str, Any]:
    """Agent available -> desktop card; otherwise -> callback ticket with
    the full package attached."""
    if agent_available:
        return {"outcome": "handoff", "card": build_desktop_card(pkg)}
    return create_callback_ticket(pkg, ticket_factory)


__all__ = [
    "VALID_REASONS", "VALID_PRIORITIES", "TIME_TO_CONTEXT_BUDGET_S",
    "TranscriptEntry", "ToolCallRecord", "SummaryParts", "ContextPackage",
    "HandoffPackage", "validate_summary", "build_evidence_summary",
    "build_context_package", "build_desktop_card", "measure_time_to_context",
    "accept_handoff", "push_back_handoff", "add_agent_note",
    "create_callback_ticket", "ensure_no_dead_end",
]
