"""
Policy engine (approach_08) - hard rules that ALWAYS win over confidence gate.

Fail-closed decision table, configurable per tenant (thresholds/keywords may
be extended per tenant, hard rules may NOT be disabled per tenant).
Every decision is audit-logged with an EscalationReason from contracts.

Contracts integration (REBASED to contracts v1.0.0): imports
EscalationReason / MAX_CLARIFICATIONS from src.contracts - the single
source of truth. The fallback below exists only so the module imports on
an empty main, and it carries EXACTLY the v1.0.0 locked values
(snake_case reasons, MAX_CLARIFICATIONS = 1, CONTRACTS_VERSION 1.0.0).
No module-local divergent constant is defined anywhere else in this file.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

try:  # locked contracts v1.0.0, when present on main
    from src.contracts import EscalationReason, MAX_CLARIFICATIONS, CONTRACTS_VERSION  # type: ignore
except Exception:  # pragma: no cover - fallback for empty main
    try:
        from contracts import EscalationReason, MAX_CLARIFICATIONS, CONTRACTS_VERSION  # type: ignore
    except Exception:
        MAX_CLARIFICATIONS = 1  # contracts v1.0.0 locked value (was 2 pre-rebase)
        CONTRACTS_VERSION = "1.0.0"

        class EscalationReason(str, Enum):
            OUT_OF_SCOPE = "out_of_scope"
            LOW_CONFIDENCE = "low_confidence"
            SENSITIVE = "sensitive"
            CUSTOMER_REQUEST = "customer_request"
            REPEATED_CLARIFICATION = "repeated_clarification"
            REPEATED_FAILURE = "repeated_failure"


class PolicyAction(str, Enum):
    ALLOW = "allow"
    ESCALATE_NOW = "escalate_now"                # chuyen ngay
    ESCALATE_PRIORITY = "escalate_priority"      # chuyen uu tien
    CALLBACK_TICKET = "callback_ticket"          # ghi nhan + hen goi lai


def _fold(text: str) -> str:
    """Lowercase + strip Vietnamese diacritics for robust keyword matching."""
    text = (text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("đ", "d")


@dataclass
class PolicyContext:
    text: str = ""
    tenant_id: str = ""
    intent: Optional[str] = None
    confidence: float = 0.0            # confidence-gate / LLM confidence, if any
    clarification_count: int = 0
    failure_count: int = 0
    sentiment_score: float = 0.0       # -1.0 (very negative) .. 1.0
    customer_requested_human: bool = False
    allowed_intents: Optional[set] = None


@dataclass
class PolicyDecision:
    action: PolicyAction
    escalate: bool
    reason: Optional[Any] = None       # EscalationReason
    rule_id: str = "allow"
    priority: str = "normal"           # normal | high | critical
    allow_llm_negotiation: bool = True
    forbidden: list = field(default_factory=list)
    audit: dict = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action == PolicyAction.ALLOW


# Keyword tables (matched on folded text, so unaccented input also hits)
_RULES: list[tuple[str, PolicyAction, str, list[str], list[str]]] = [
    # rule_id, action, priority, keywords, forbidden
    ("self_harm_violence", PolicyAction.ESCALATE_PRIORITY, "critical",
     ["tu tu", "tu hai", "muon chet", "ket lieu", "giet nguoi", "danh nhau",
      "bom", "khung bo", "tu sat"],
     []),
    ("legal", PolicyAction.ESCALATE_PRIORITY, "high",
     ["kiện", "kiện tụng", "luat su", "toa an", "phap ly", "cong an",
      "thua kien", "khoi kien", "vi pham phap luat"],
     ["legal_commitment"]),
    ("compensation", PolicyAction.ESCALATE_NOW, "high",
     ["boi thuong", "den bu", "bat den", "doi boi thuong", "yeu cau boi thuong"],
     ["compensation_negotiation", "legal_commitment"]),
    ("angry_complaint", PolicyAction.ESCALATE_PRIORITY, "high",
     ["lua dao", "tay chay", "phot", "qua te", "vo trach nhiem",
      "lam an nhu", "khieu nai", "bao cao len bao", "dang facebook"],
     []),
    ("sensitive_health_finance", PolicyAction.ESCALATE_NOW, "high",
     ["mat khau", "ma otp", "so the tin dung", "so cccd", "can cuoc cong dan",
      "benh an", "chan doan benh", "toa thuoc", "tu van y khoa"],
     ["sensitive_advice"]),
    ("customer_request_human", PolicyAction.ESCALATE_NOW, "normal",
     ["gap nhan vien", "gap nguoi that", "cho gap nguoi", "noi chuyen voi nguoi",
      "may moc", "khong muon noi voi may", "chuyen may cho nhan vien",
      "gap tong dai vien"],
     []),
]

_REASON_BY_RULE = {
    "self_harm_violence": EscalationReason.SENSITIVE,
    "legal": EscalationReason.SENSITIVE,
    "compensation": EscalationReason.SENSITIVE,
    "angry_complaint": EscalationReason.SENSITIVE,
    "sensitive_health_finance": EscalationReason.SENSITIVE,
    "customer_request_human": EscalationReason.CUSTOMER_REQUEST,
    "out_of_scope": EscalationReason.OUT_OF_SCOPE,
    "repeated_clarification": EscalationReason.REPEATED_CLARIFICATION,
    "repeated_failure": EscalationReason.REPEATED_FAILURE,
    "strong_negative_sentiment": EscalationReason.SENSITIVE,
}

# Phrases that mean an LLM draft is illegally negotiating / committing
_COMPENSATION_DRAFT = ["se boi thuong", "cam ket boi thuong", "boi thuong cho anh",
                       "boi thuong cho chi", "boi thuong cho ban", "se den bu",
                       "hoan tien 100%", "hoan lai 100%"]
_LEGAL_DRAFT = ["cam ket phap ly", "chac chan thang kien", "dam bao ve mat phap ly",
                "chung toi chiu trach nhiem phap ly"]


class PolicyEngine:
    """Rule + lightweight classifier running in parallel with the LLM.

    Hard rules are evaluated BEFORE any confidence consideration:
    a matching rule escalates regardless of confidence (even 1.0).
    """

    def __init__(self, tenant_config: Optional[dict] = None,
                 max_clarifications: int = MAX_CLARIFICATIONS,
                 sentiment_threshold: float = -0.8):
        self.tenant_config = tenant_config or {}
        # Tenant may lower (stricter) but never raise the clarification cap
        # above the contract constant, and may not disable hard rules.
        requested = int(self.tenant_config.get("max_clarifications", max_clarifications))
        self.max_clarifications = min(requested, int(max_clarifications))
        self.sentiment_threshold = float(
            self.tenant_config.get("sentiment_threshold", sentiment_threshold))
        self.audit_log: list[dict] = []
        extra = self.tenant_config.get("extra_keywords", {})
        self._rules = []
        for rule_id, action, priority, kws, forbidden in _RULES:
            merged = [_fold(k) for k in kws] + [_fold(k) for k in extra.get(rule_id, [])]
            self._rules.append((rule_id, action, priority, merged, list(forbidden)))

    # ------------------------------------------------------------------
    def evaluate(self, ctx: PolicyContext | str, **kw) -> PolicyDecision:
        if isinstance(ctx, str):
            ctx = PolicyContext(text=ctx, **kw)
        elif kw:
            for k, v in kw.items():
                setattr(ctx, k, v)
        folded = _fold(ctx.text)

        decision = self._decide(ctx, folded)
        audit = {
            "ts": time.time(), "tenant_id": ctx.tenant_id,
            "rule_id": decision.rule_id,
            "action": decision.action.value,
            "reason": decision.reason.value if decision.reason else None,
            "priority": decision.priority,
            "confidence_seen": ctx.confidence,
            "clarification_count": ctx.clarification_count,
        }
        decision.audit = audit
        self.audit_log.append(audit)
        return decision

    # Backwards/alternate names other modules commonly use
    check = evaluate
    decide = evaluate

    def _decide(self, ctx: PolicyContext, folded: str) -> PolicyDecision:
        # 1) Hard keyword rules - always first, always win
        for rule_id, action, priority, kws, forbidden in self._rules:
            if rule_id == "customer_request_human" and not ctx.customer_requested_human:
                pass  # keyword path below still applies
            if any(k in folded for k in kws):
                return PolicyDecision(
                    action=action, escalate=True,
                    reason=_REASON_BY_RULE[rule_id], rule_id=rule_id,
                    priority=priority,
                    allow_llm_negotiation=("compensation_negotiation" not in forbidden
                                           and "legal_commitment" not in forbidden),
                    forbidden=forbidden)

        # 2) Explicit human request flag from dialogue layer
        if ctx.customer_requested_human:
            return PolicyDecision(
                action=PolicyAction.ESCALATE_NOW, escalate=True,
                reason=EscalationReason.CUSTOMER_REQUEST,
                rule_id="customer_request_human", priority="normal",
                allow_llm_negotiation=False)

        # 3) Clarification / failure loops (contract cap = 1 in v1.0.0)
        if ctx.clarification_count > self.max_clarifications:
            return PolicyDecision(
                action=PolicyAction.ESCALATE_NOW, escalate=True,
                reason=EscalationReason.REPEATED_CLARIFICATION,
                rule_id="repeated_clarification", priority="normal",
                allow_llm_negotiation=False)
        if ctx.failure_count >= 3:
            return PolicyDecision(
                action=PolicyAction.CALLBACK_TICKET, escalate=True,
                reason=EscalationReason.REPEATED_FAILURE,
                rule_id="repeated_failure", priority="normal",
                allow_llm_negotiation=False)

        # 4) Out of scope intent
        if ctx.intent and ctx.allowed_intents is not None \
                and ctx.intent not in ctx.allowed_intents:
            return PolicyDecision(
                action=PolicyAction.ESCALATE_NOW, escalate=True,
                reason=EscalationReason.OUT_OF_SCOPE,
                rule_id="out_of_scope", priority="normal",
                allow_llm_negotiation=False)

        # 5) Strong negative sentiment classifier signal
        if ctx.sentiment_score <= self.sentiment_threshold:
            return PolicyDecision(
                action=PolicyAction.ESCALATE_PRIORITY, escalate=True,
                reason=EscalationReason.SENSITIVE,
                rule_id="strong_negative_sentiment", priority="high",
                allow_llm_negotiation=False)

        return PolicyDecision(action=PolicyAction.ALLOW, escalate=False)

    # ------------------------------------------------------------------
    def guard_response(self, draft: str) -> PolicyDecision:
        """Block an LLM draft that negotiates compensation / commits legally.

        Returns ALLOW if clean; otherwise an escalate decision - the draft
        must NOT be spoken to the customer.
        """
        folded = _fold(draft)
        if any(p in folded for p in _COMPENSATION_DRAFT):
            d = PolicyDecision(
                action=PolicyAction.ESCALATE_NOW, escalate=True,
                reason=EscalationReason.SENSITIVE,
                rule_id="compensation_negotiation_blocked", priority="high",
                allow_llm_negotiation=False,
                forbidden=["compensation_negotiation"])
        elif any(p in folded for p in _LEGAL_DRAFT):
            d = PolicyDecision(
                action=PolicyAction.ESCALATE_NOW, escalate=True,
                reason=EscalationReason.SENSITIVE,
                rule_id="legal_commitment_blocked", priority="high",
                allow_llm_negotiation=False, forbidden=["legal_commitment"])
        else:
            return PolicyDecision(action=PolicyAction.ALLOW, escalate=False,
                                  rule_id="draft_ok")
        self.audit_log.append({
            "ts": time.time(), "rule_id": d.rule_id,
            "action": d.action.value, "reason": d.reason.value,
            "priority": d.priority, "event": "guard_response"})
        return d

    def apply_gate(self, ctx: PolicyContext, gate_allows: bool) -> PolicyDecision:
        """Combine with confidence gate: hard rule wins even if gate allows."""
        decision = self.evaluate(ctx)
        if decision.escalate:
            return decision
        if not gate_allows:
            return PolicyDecision(
                action=PolicyAction.ESCALATE_NOW, escalate=True,
                reason=EscalationReason.LOW_CONFIDENCE,
                rule_id="gate_blocked", priority="normal",
                allow_llm_negotiation=False)
        return decision
