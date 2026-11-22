"""Handoff service: skill-based routing and warm transfer.

fix_missing_handoff_service — merged from expert/systems-arch-m3 design
(approach_09/10/11) and aligned to the locked contracts:
- EscalationReason values are snake_case only.
- The context unit is a HandoffPackage.

Behaviour (council-agreed, verified end-to-end by the tests):
- Routing: least-loaded among eligible agents, with sticky preference
  (same customer -> same agent) and VIP preference (VIP/high-priority
  customers -> VIP-capable agents first). Eligibility = on shift,
  available, has capacity, matches required skill/department and language.
- Warm transfer: context is pushed FIRST and must be ACKed (with retry);
  only then is the call bridged via SIP REFER / conference bridge.
  If the context push ultimately fails, the call is NOT bridged blind —
  it falls back to a callback ticket.
- No eligible agent (off shift / busy / none registered): outcome is
  CALLBACK with a ticket_id, never a dead end.
- reason_counts records every request under its exact snake_case
  escalation reason.

Transports are injected callables so the service is testable without a
real PBX: ``context_push(agent_id, package) -> bool`` (ACK),
``bridge(call_id, agent_id, mode) -> bool``, and
``ticket_factory(package, reason) -> str``.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# Rebased onto contracts v1.0.0 (fix_rebase_remaining_fullstack):
# EscalationReason is imported from contracts — no local mirror enum.
from src.contracts import EscalationReason  # noqa: F401  (re-exported)


def _reason_value(reason) -> str:
    """Normalise a reason to its locked snake_case value; reject others."""
    if isinstance(reason, EscalationReason):
        return reason.value
    val = str(reason)
    valid = {r.value for r in EscalationReason}
    if val not in valid:
        raise ValueError(f"invalid_escalation_reason:{val}")
    return val


class HandoffOutcome(str, Enum):
    WARM_TRANSFER = "warm_transfer"
    CALLBACK = "callback"


# Alias used by some callers/tests
HandoffStatus = HandoffOutcome


@dataclass
class HandoffPackage:
    call_id: str
    escalation_reason: str
    tenant_id: str = ""
    customer_id: str = ""
    phone: str = ""
    intent: str = ""
    summary: str = ""
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    slots: Dict[str, Any] = field(default_factory=dict)
    verified_customer: Dict[str, Any] = field(default_factory=dict)
    looked_up_data: Dict[str, Any] = field(default_factory=dict)
    required_skill: str = "general"
    department: str = ""
    language: str = "vi"
    priority: str = "normal"          # normal | high | vip
    is_vip: bool = False

    def __post_init__(self):
        self.escalation_reason = _reason_value(self.escalation_reason)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ContextPackage is the same unit under its systems-arch name.
ContextPackage = HandoffPackage


@dataclass
class Agent:
    agent_id: str
    skills: List[str] = field(default_factory=lambda: ["general"])
    departments: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=lambda: ["vi"])
    capacity: int = 1
    active_calls: int = 0
    on_shift: bool = True
    available: bool = True
    vip_capable: bool = False

    @property
    def load_ratio(self) -> float:
        return self.active_calls / max(1, self.capacity)

    def eligible(self, pkg: HandoffPackage) -> bool:
        if not self.on_shift or not self.available:
            return False
        if self.active_calls >= self.capacity:
            return False
        if pkg.required_skill not in self.skills and "general" not in self.skills:
            # 'general' agents may take any skill only if no skill required
            if pkg.required_skill != "general":
                return False
        if pkg.department and self.departments and pkg.department not in self.departments:
            return False
        if pkg.language and self.languages and pkg.language not in self.languages:
            return False
        return True


@dataclass
class HandoffResult:
    outcome: HandoffOutcome
    call_id: str
    escalation_reason: str
    agent_id: Optional[str] = None
    ticket_id: Optional[str] = None
    bridged: bool = False
    transfer_mode: Optional[str] = None   # sip_refer | conference
    context_attempts: int = 0
    context_acked: bool = False
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        return d


class HandoffService:
    def __init__(self,
                 context_push: Optional[Callable[[str, HandoffPackage], bool]] = None,
                 bridge: Optional[Callable[[str, str, str], bool]] = None,
                 ticket_factory: Optional[Callable[[HandoffPackage, str], str]] = None,
                 max_context_retries: int = 3,
                 transfer_mode: str = "sip_refer"):
        self._push = context_push or (lambda agent_id, pkg: True)
        self._bridge = bridge or (lambda call_id, agent_id, mode: True)
        self._ticket_seq = itertools.count(1)
        self._ticket_factory = ticket_factory or self._default_ticket
        self.max_context_retries = max(1, int(max_context_retries))
        self.transfer_mode = transfer_mode
        self.agents: Dict[str, Agent] = {}
        self.sticky: Dict[str, str] = {}
        self.reason_counts: Dict[str, int] = {}
        self.results: List[HandoffResult] = []

    def _default_ticket(self, pkg: HandoffPackage, reason: str) -> str:
        return f"CB-{next(self._ticket_seq):06d}"

    # -- agent registry -------------------------------------------------------
    def register_agent(self, agent: Agent = None, **kwargs) -> Agent:
        if agent is None:
            agent = Agent(**kwargs)
        self.agents[agent.agent_id] = agent
        return agent

    add_agent = register_agent

    def set_availability(self, agent_id: str, available: bool = True,
                         on_shift: bool = True) -> None:
        a = self.agents[agent_id]
        a.available = available
        a.on_shift = on_shift

    def complete_call(self, agent_id: str) -> None:
        a = self.agents.get(agent_id)
        if a and a.active_calls > 0:
            a.active_calls -= 1

    # -- routing ----------------------------------------------------------------
    def _route(self, pkg: HandoffPackage) -> Optional[Agent]:
        eligible = [a for a in self.agents.values() if a.eligible(pkg)]
        if not eligible:
            return None
        # Sticky: previous agent for this customer, if still eligible.
        key = pkg.customer_id or pkg.phone
        if key and key in self.sticky:
            prev = self.agents.get(self.sticky[key])
            if prev is not None and prev in eligible:
                return prev
        # VIP: restrict to VIP-capable agents when any is eligible.
        if pkg.is_vip or pkg.priority in ("vip", "high"):
            vip = [a for a in eligible if a.vip_capable]
            if vip:
                eligible = vip
        # Least-loaded: lowest load ratio, then fewest active calls, then id.
        return min(eligible, key=lambda a: (a.load_ratio, a.active_calls, a.agent_id))

    # -- main entry ---------------------------------------------------------------
    def request_handoff(self, pkg: HandoffPackage = None, **kwargs) -> HandoffResult:
        if pkg is None:
            pkg = HandoffPackage(**kwargs)
        reason = _reason_value(pkg.escalation_reason)
        self.reason_counts[reason] = self.reason_counts.get(reason, 0) + 1

        agent = self._route(pkg)
        if agent is None:
            return self._callback(pkg, reason, detail="no_eligible_agent")

        # Push context with ACK + retry BEFORE bridging (no blind bridge).
        attempts = 0
        acked = False
        while attempts < self.max_context_retries and not acked:
            attempts += 1
            try:
                acked = bool(self._push(agent.agent_id, pkg))
            except Exception:
                acked = False
        if not acked:
            return self._callback(pkg, reason, detail="context_push_failed",
                                  attempts=attempts)

        # Warm bridge via SIP REFER / conference.
        try:
            bridged = bool(self._bridge(pkg.call_id, agent.agent_id,
                                        self.transfer_mode))
        except Exception:
            bridged = False
        if not bridged:
            return self._callback(pkg, reason, detail="bridge_failed",
                                  attempts=attempts, agent_id=agent.agent_id)

        agent.active_calls += 1
        key = pkg.customer_id or pkg.phone
        if key:
            self.sticky[key] = agent.agent_id
        result = HandoffResult(
            outcome=HandoffOutcome.WARM_TRANSFER, call_id=pkg.call_id,
            escalation_reason=reason, agent_id=agent.agent_id, bridged=True,
            transfer_mode=self.transfer_mode, context_attempts=attempts,
            context_acked=True, detail="ok")
        self.results.append(result)
        return result

    # Aliases
    handoff = request_handoff
    transfer = request_handoff

    def _callback(self, pkg: HandoffPackage, reason: str, detail: str,
                  attempts: int = 0, agent_id: Optional[str] = None) -> HandoffResult:
        ticket_id = self._ticket_factory(pkg, reason)
        result = HandoffResult(
            outcome=HandoffOutcome.CALLBACK, call_id=pkg.call_id,
            escalation_reason=reason, agent_id=agent_id, ticket_id=ticket_id,
            bridged=False, context_attempts=attempts,
            context_acked=False, detail=detail)
        self.results.append(result)
        return result


__all__ = [
    "EscalationReason", "HandoffOutcome", "HandoffStatus", "HandoffPackage",
    "ContextPackage", "Agent", "HandoffResult", "HandoffService",
]
