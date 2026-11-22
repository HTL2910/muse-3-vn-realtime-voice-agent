"""Grounded answering, fail-closed, with a mandatory anti-hallucination verifier.

fix/fix_missing_grounded_answer — approach_06.

Self-contained, stdlib-only. No import from ``src.contracts`` (there
is no contracts file on ``main`` yet) and no dependency on the tool
gateway: evidence is passed in as data, so this module can be tested
in isolation and the gateway can be wired in later without changing
the verifier. The locked values mirror the contract agreed in
COUNCIL_BUG_DEBATE (move verbatim into ``src/contracts.py`` v1.0.0):

* Escalation reasons are snake_case: ``out_of_scope``,
  ``low_confidence``, ``sensitive``, ``customer_request``,
  ``repeated_clarification``, ``repeated_failure``.
* Containment = answered from verified evidence AND no callback on
  the same issue within 72h.

Rules (fail-closed, in order — the first failure wins)
------------------------------------------------------
1. Blacklisted / sensitive intent or topic -> REJECTED (``sensitive``).
2. Intent not on the auto-answer whitelist -> UNKNOWN (``out_of_scope``).
3. No evidence -> UNKNOWN (``no_record``).
4. Contradictory evidence for the same field -> REJECTED
   (``contradictory_evidence``).
5. Missing required field for the intent -> UNKNOWN
   (``missing_required_field``).
6. Stale policy version -> REJECTED (``stale_policy``).
7. Verifier: every number / amount of money / date in the answer
   must match a value in the tool payload, after normalisation
   (``350.000`` == ``350000`` == ``350k``; ``25/11/2026`` ==
   ``2026-11-25``). Any mismatch -> REJECTED (``numeric_mismatch``)
   and the spoken text is replaced by a fixed apology + handoff —
   the unverified draft is NEVER spoken.

The safe path is ``answer_from_evidence``: it renders from the
structured payload via a template, so there is no free text for the
LLM to hallucinate into. ``verify_draft`` is the gate for any
LLM-drafted wording: it must pass the same checks before speaking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set

__all__ = [
    "AnswerStatus",
    "Evidence",
    "GroundedAnswer",
    "GroundedAnswerer",
    "WHITELIST_INTENTS",
    "BLACKLIST_INTENTS",
    "BLACKLIST_TOPICS",
    "REQUIRED_FIELDS",
    "APOLOGY_HANDOFF_TEXT",
    "extract_numbers",
    "extract_dates",
    "normalize_number",
    "normalize_date",
]

WHITELIST_INTENTS = frozenset({
    "track_order",
    "check_fee",
    "check_inventory",
    "check_appointment",
    "return_policy",
    "warranty_policy",
    "faq",
    "usage_guide",
    "book_appointment",
    "confirm_info",
})

BLACKLIST_INTENTS = frozenset({
    "compensation",
    "legal",
    "complaint_severe",
    "refund_negotiation",
    "health_advice",
    "financial_advice",
})

# Sensitive topics anywhere in the draft / intent, even if the
# intent label itself looks innocent.
BLACKLIST_TOPICS = (
    "bồi thường", "đền bù", "kiện", "luật sư", "pháp lý",
    "tự tử", "tự hại", "bạo lực",
)

REQUIRED_FIELDS: Dict[str, List[str]] = {
    "track_order": ["order_id", "status"],
    "check_fee": ["amount"],
    "check_inventory": ["sku", "stock_qty"],
    "check_appointment": ["appointment_id", "date"],
    "return_policy": ["policy_version", "snippet"],
    "warranty_policy": ["policy_version", "snippet"],
    "faq": ["snippet"],
    "usage_guide": ["snippet"],
    "book_appointment": ["date"],
    "confirm_info": ["order_id"],
}

APOLOGY_HANDOFF_TEXT = (
    "Dạ, em xin lỗi, em chưa xác minh được thông tin này nên em "
    "không dám trả lời. Em chuyển anh chị gặp nhân viên để được "
    "kiểm tra chính xác ạ."
)

_NUMBER_RE = re.compile(r"\d[\d.,]*\d|\d")
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{1,2}-\d{1,2}\b")
_CODE_RE = re.compile(r"\b[A-Z]{1,4}\d{2,}\b")


class AnswerStatus(str, Enum):
    ANSWERED = "answered"
    UNKNOWN = "unknown"
    REJECTED = "rejected"
    HANDOFF = "handoff"


@dataclass(frozen=True)
class Evidence:
    """One verified tool result. ``payload`` is the tool's raw data."""

    source: str                    # e.g. "oms.get_order"
    source_id: str                 # e.g. order_id / SKU / faq id
    kind: str                      # order | inventory | appointment | faq | policy
    payload: Dict[str, object]
    queried_at: str = ""           # ISO timestamp of the tool call
    policy_version: Optional[str] = None
    snippet: Optional[str] = None

    def citation(self) -> str:
        parts = [f"{self.source}:{self.source_id}"]
        if self.policy_version:
            parts.append(f"policy_version={self.policy_version}")
        if self.queried_at:
            parts.append(f"queried_at={self.queried_at}")
        return " ".join(parts)


@dataclass
class GroundedAnswer:
    status: AnswerStatus
    text: str
    citations: List[str] = field(default_factory=list)
    reason: str = ""
    escalation_reason: Optional[str] = None

    @property
    def speakable(self) -> bool:
        """Only an ANSWERED answer may be spoken to the customer."""
        return self.status == AnswerStatus.ANSWERED


def normalize_number(token: str) -> Optional[float]:
    """350.000 / 350,000 / 350000 / 350k -> 350000.0 ; None if not a number."""
    t = token.strip().lower().replace("đ", "").replace("vnd", "").strip()
    mult = 1.0
    if t.endswith("k"):
        mult = 1000.0
        t = t[:-1]
    t = t.replace(",", "").replace(".", "").replace(" ", "")
    if not t or not t.replace("-", "").isdigit():
        return None
    try:
        return float(t) * mult
    except ValueError:
        return None


def normalize_date(token: str) -> Optional[str]:
    """25/11/2026, 25-11-2026, 2026-11-25 -> 2026-11-25 ; None if unparseable."""
    t = token.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_numbers(text: str) -> List[float]:
    """Numbers that are NOT part of a date or an order/SKU code.

    The day/month/year inside ``30/11/2026`` and the ``999`` inside
    ``DH999`` are checked by the date / code checks, not here —
    otherwise a wrong date would be reported as a (misleading)
    ``numeric_mismatch:30`` and a wrong code as ``numeric_mismatch:999``.
    """
    covered: List[tuple] = []
    for pat in (_DATE_RE, _CODE_RE):
        covered.extend((m.start(), m.end()) for m in pat.finditer(text))
    out: List[float] = []
    for m in _NUMBER_RE.finditer(text):
        if any(s <= m.start() < e for s, e in covered):
            continue
        v = normalize_number(m.group(0))
        if v is not None:
            out.append(v)
    return out


def extract_dates(text: str) -> List[str]:
    out: List[str] = []
    for m in _DATE_RE.finditer(text):
        d = normalize_date(m.group(0))
        if d is not None:
            out.append(d)
    return out


def _flatten_values(payload: Dict[str, object]) -> List[str]:
    values: List[str] = []
    for v in payload.values():
        if isinstance(v, dict):
            values.extend(_flatten_values(v))
        elif isinstance(v, (list, tuple)):
            values.extend(str(x) for x in v)
        elif v is not None:
            values.append(str(v))
    return values


class GroundedAnswerer:
    """Fail-closed answerer + verifier. See module docstring for the order."""

    def __init__(
        self,
        *,
        whitelist: Set[str] = WHITELIST_INTENTS,
        blacklist: Set[str] = BLACKLIST_INTENTS,
        current_policy_version: Optional[str] = None,
    ):
        self.whitelist = set(whitelist)
        self.blacklist = set(blacklist)
        self.current_policy_version = current_policy_version

    # -- internal gates ---------------------------------------------------
    def _unknown(self, reason: str, escalation: str) -> GroundedAnswer:
        return GroundedAnswer(AnswerStatus.UNKNOWN, APOLOGY_HANDOFF_TEXT,
                              reason=reason, escalation_reason=escalation)

    def _rejected(self, reason: str, escalation: str) -> GroundedAnswer:
        return GroundedAnswer(AnswerStatus.REJECTED, APOLOGY_HANDOFF_TEXT,
                              reason=reason, escalation_reason=escalation)

    def _gate(self, intent: str, evidence: Sequence[Evidence], draft: str = ""):
        """Return a GroundedAnswer if a gate fails, else None."""
        lowered_intent = intent.lower()
        if lowered_intent in self.blacklist:
            return self._rejected("blacklisted_intent", "sensitive")
        haystack = (intent + " " + draft).lower()
        if any(topic in haystack for topic in BLACKLIST_TOPICS):
            return self._rejected("sensitive_topic", "sensitive")
        if lowered_intent not in self.whitelist:
            return self._unknown("intent_not_whitelisted", "out_of_scope")
        if not evidence:
            return self._unknown("no_record", "out_of_scope")
        return None

    def _check_contradictions(self, evidence: Sequence[Evidence]):
        seen: Dict[str, str] = {}
        for ev in evidence:
            for key, value in ev.payload.items():
                val = str(value)
                if key in seen and seen[key] != val:
                    return self._rejected(
                        f"contradictory_evidence:{key}", "low_confidence")
                seen[key] = val
        return None

    def _check_required(self, intent: str, evidence: Sequence[Evidence]):
        merged: Dict[str, object] = {}
        for ev in evidence:
            merged.update(ev.payload)
            if ev.snippet:
                merged.setdefault("snippet", ev.snippet)
            if ev.policy_version:
                merged.setdefault("policy_version", ev.policy_version)
        missing = [f for f in REQUIRED_FIELDS.get(intent.lower(), [])
                   if f not in merged or merged[f] in (None, "")]
        if missing:
            return self._unknown(
                f"missing_required_field:{','.join(missing)}", "low_confidence"), merged
        return None, merged

    def _check_policy(self, evidence: Sequence[Evidence]):
        if self.current_policy_version is None:
            return None
        for ev in evidence:
            if ev.policy_version and ev.policy_version != self.current_policy_version:
                return self._rejected("stale_policy", "low_confidence")
        return None

    def _verify_numbers_and_dates(self, text: str, evidence: Sequence[Evidence]):
        values = []
        for ev in evidence:
            values.extend(_flatten_values(ev.payload))
            if ev.snippet:
                values.append(ev.snippet)
        blob = " ".join(values)
        ev_numbers = set(extract_numbers(blob))
        ev_dates = set(extract_dates(blob))
        ev_codes = set(_CODE_RE.findall(blob))
        for num in extract_numbers(text):
            if num not in ev_numbers:
                return self._rejected(f"numeric_mismatch:{num:g}", "low_confidence")
        for date in extract_dates(text):
            if date not in ev_dates:
                return self._rejected(f"date_mismatch:{date}", "low_confidence")
        for code in _CODE_RE.findall(text):
            if code not in ev_codes:
                return self._rejected(f"code_mismatch:{code}", "low_confidence")
        return None

    # -- public API ---------------------------------------------------------
    def verify_draft(self, intent: str, evidence: Sequence[Evidence], draft: str) -> GroundedAnswer:
        """Gate an LLM draft: speak it only if it passes every check."""
        for gate in (self._gate(intent, evidence, draft),
                     self._check_contradictions(evidence),
                     self._check_policy(evidence)):
            if gate is not None:
                return gate
        missing, _ = self._check_required(intent, evidence)
        if missing is not None:
            return missing
        bad = self._verify_numbers_and_dates(draft, evidence)
        if bad is not None:
            return bad
        citations = [ev.citation() for ev in evidence]
        return GroundedAnswer(AnswerStatus.ANSWERED, draft,
                              citations=citations, reason="verified")

    def answer_from_evidence(self, intent: str, evidence: Sequence[Evidence]) -> GroundedAnswer:
        """Render an answer from the structured payload only (safe path)."""
        for gate in (self._gate(intent, evidence),
                     self._check_contradictions(evidence),
                     self._check_policy(evidence)):
            if gate is not None:
                return gate
        missing, merged = self._check_required(intent, evidence)
        if missing is not None:
            return missing
        text = self._render(intent.lower(), merged)
        bad = self._verify_numbers_and_dates(text, evidence)
        if bad is not None:
            # A template bug must never leak a wrong number: fail closed.
            return bad
        return GroundedAnswer(AnswerStatus.ANSWERED, text,
                              citations=[ev.citation() for ev in evidence],
                              reason="rendered_from_evidence")

    @staticmethod
    def _render(intent: str, merged: Dict[str, object]) -> str:
        if intent == "track_order":
            text = f"Đơn {merged['order_id']} hiện {merged['status']}."
            if merged.get("eta_date"):
                text += f" Dự kiến giao ngày {merged['eta_date']}."
            return text
        if intent == "check_fee":
            return f"Phí giao hàng là {merged['amount']} đồng."
        if intent == "check_inventory":
            return f"Sản phẩm {merged['sku']} còn {merged['stock_qty']} chiếc."
        if intent == "check_appointment":
            return f"Lịch hẹn {merged['appointment_id']} vào ngày {merged['date']}."
        if intent in ("return_policy", "warranty_policy", "faq", "usage_guide"):
            return str(merged["snippet"])
        if intent == "book_appointment":
            return f"Dạ, em đã đặt lịch cho anh chị vào ngày {merged['date']}."
        if intent == "confirm_info":
            return f"Dạ, em xác nhận đơn {merged['order_id']}."
        return str(merged.get("snippet", ""))
