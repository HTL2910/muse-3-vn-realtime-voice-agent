"""Dialogue manager: intent, slot-filling and dialogue state tracking.

fix_missing_dialogue_manager (approach_04), rebased onto contracts v1.0.0
by fix_rebase_fullstack_to_contracts — branch fix/fix_rebase_fullstack_to_contracts

Design (council-agreed):
- State machine + constrained (optional, injected) LLM classifier. The LLM
  may only *suggest* an intent; it can never invent slots, skip required
  slots, or override the clarification limit.
- Vietnamese intents, each with a versioned playbook: required slots,
  allowed tools, answer template, exit conditions.
- Clarification budget comes ONLY from contracts v1.0.0
  (``MAX_CLARIFICATIONS``); this module defines no mirror constants.
  Counting definition (contracts): the counter counts clarification
  *questions asked* for the current intent — the first detection of a
  missing required slot asks the single allowed question; if the slot is
  still missing on the next turn for the same intent, the manager does
  NOT ask again, it escalates with ``EscalationReason.REPEATED_CLARIFICATION``.
- Escalation reasons are ``src.contracts.EscalationReason`` values
  (snake_case); no local reason literals exist in this module.
- Structured per-turn state: verified customer info, intent, filled slots,
  looked-up data, steps tried, unresolved needs, frustration level.
- Slot correction, follow-up questions and returning to a previous topic
  (topic stack) are handled explicitly.
- Intent/slot/state schemas are versioned below (local schema versions,
  not contracts constants).

Fail-closed on contract drift: if contracts lacks a locked name this
module imports, the import fails loudly instead of silently falling back
to a mirrored value.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

# --- Contracts v1.0.0: single source of truth (single import style) --------
from src.contracts import (  # noqa: F401  (re-exported for callers/tests)
    CONTRACTS_VERSION,
    MAX_CLARIFICATIONS,
    EscalationReason,
)

INTENT_SCHEMA_VERSION = "1.0.0"
SLOT_SCHEMA_VERSION = "1.0.0"
STATE_SCHEMA_VERSION = "1.0.0"


def _reason(member: str) -> str:
    """Value of a contracts EscalationReason member (snake_case string)."""
    m = getattr(EscalationReason, member)  # AttributeError == contract drift
    return str(getattr(m, "value", m))


REASON_REPEATED_CLARIFICATION = _reason("REPEATED_CLARIFICATION")
REASON_OUT_OF_SCOPE = _reason("OUT_OF_SCOPE")
REASON_LOW_CONFIDENCE = _reason("LOW_CONFIDENCE")


class Intent(str, Enum):
    ORDER_TRACKING = "order_tracking"        # tra cứu đơn hàng
    SHIPPING_FEE = "shipping_fee"            # phí / thời gian giao
    RETURN_EXCHANGE = "return_exchange"      # đổi trả
    WARRANTY = "warranty"                    # bảo hành
    BOOK_APPOINTMENT = "book_appointment"    # đặt lịch / hẹn
    CONFIRM_INFO = "confirm_info"            # xác nhận thông tin
    UNKNOWN = "unknown"


# Convenient aliases
TRACK_ORDER = Intent.ORDER_TRACKING
RETURN_OR_WARRANTY = Intent.RETURN_EXCHANGE


class DialogueAction(str, Enum):
    ASK_CLARIFICATION = "ask_clarification"
    READY_FOR_TOOL = "ready_for_tool"        # all required slots present
    ANSWER_FROM_STATE = "answer_from_state"
    ESCALATE = "escalate"
    CONTINUE = "continue"


@dataclass(frozen=True)
class Playbook:
    intent: Intent
    required_slots: tuple
    optional_slots: tuple
    allowed_tools: tuple
    answer_template: str
    exit_conditions: tuple
    slot_prompts: Dict[str, str]


SLOT_PROMPTS_VI = {
    "order_code": "Anh/chị cho em xin mã đơn hàng ạ?",
    "phone": "Anh/chị cho em xin số điện thoại đặt hàng ạ?",
    "customer_name": "Anh/chị cho em xin họ tên người đặt ạ?",
    "product": "Anh/chị cho em xin tên sản phẩm ạ?",
    "appointment_time": "Anh/chị muốn đặt lịch vào ngày giờ nào ạ?",
    "address": "Anh/chị cho em xin địa chỉ ạ?",
}

# --- Tool gateway allowlist (locked by the tool gateway) -------------------
# The gateway accepts EXACTLY these 5 tool names and rejects anything else.
# Playbook ``allowed_tools`` below therefore use gateway names only. The
# mapping keeps the older semantic names used in playbook drafts traceable
# to the gateway name that actually executes them.
GATEWAY_TOOLS = frozenset({
    "get_order_status", "get_inventory", "get_appointment",
    "get_policy", "create_callback_ticket",
})

TOOL_GATEWAY_MAP = {
    "get_order": "get_order_status",
    "get_delivery_status": "get_order_status",
    "get_customer": "get_order_status",
    "get_shipping_fee": "get_policy",
    "get_return_policy": "get_policy",
    "get_warranty_policy": "get_policy",
    "get_delivery_eta": "get_order_status",
    "get_schedule": "get_appointment",
    "book_appointment": "get_appointment",
    "get_inventory": "get_inventory",
    "get_order_status": "get_order_status",
    "get_policy": "get_policy",
    "get_appointment": "get_appointment",
    "create_callback_ticket": "create_callback_ticket",
}


def gateway_tool(name: str) -> str:
    """Resolve a playbook/semantic tool name to its gateway tool name.
    Raises ValueError for any name the gateway would reject."""
    resolved = TOOL_GATEWAY_MAP.get(name)
    if resolved is None or resolved not in GATEWAY_TOOLS:
        raise ValueError(f"tool_not_allowed_by_gateway:{name}")
    return resolved


PLAYBOOKS: Dict[Intent, Playbook] = {
    Intent.ORDER_TRACKING: Playbook(
        Intent.ORDER_TRACKING, ("order_code",), ("phone",),
        ("get_order_status",),
        "Đơn {order_code} hiện đang ở trạng thái theo dữ liệu hệ thống.",
        ("tool_result_received", "customer_satisfied"), SLOT_PROMPTS_VI),
    Intent.SHIPPING_FEE: Playbook(
        Intent.SHIPPING_FEE, ("address",), ("order_code", "product"),
        ("get_policy", "get_order_status"),
        "Phí và thời gian giao tới {address} theo dữ liệu hệ thống.",
        ("tool_result_received",), SLOT_PROMPTS_VI),
    Intent.RETURN_EXCHANGE: Playbook(
        Intent.RETURN_EXCHANGE, ("order_code",), ("product", "phone"),
        ("get_order_status", "get_policy"),
        "Thông tin đổi trả cho đơn {order_code} theo chính sách hiện hành.",
        ("tool_result_received", "policy_escalation"), SLOT_PROMPTS_VI),
    Intent.WARRANTY: Playbook(
        Intent.WARRANTY, ("order_code",), ("product", "phone"),
        ("get_order_status", "get_policy"),
        "Thông tin bảo hành cho đơn {order_code} theo chính sách hiện hành.",
        ("tool_result_received", "policy_escalation"), SLOT_PROMPTS_VI),
    Intent.BOOK_APPOINTMENT: Playbook(
        Intent.BOOK_APPOINTMENT, ("appointment_time", "phone"),
        ("customer_name", "product"),
        ("get_appointment", "create_callback_ticket"),
        "Lịch hẹn {appointment_time} cho số {phone}.",
        ("tool_result_received", "slot_unavailable"), SLOT_PROMPTS_VI),
    Intent.CONFIRM_INFO: Playbook(
        Intent.CONFIRM_INFO, ("phone",), ("order_code", "customer_name"),
        ("get_order_status", "get_inventory"),
        "Thông tin xác nhận cho số {phone} theo dữ liệu hệ thống.",
        ("tool_result_received",), SLOT_PROMPTS_VI),
    Intent.UNKNOWN: Playbook(
        Intent.UNKNOWN, (), (), (),
        "", ("clarified", "escalated"), SLOT_PROMPTS_VI),
}


def get_playbook(intent) -> Playbook:
    return PLAYBOOKS[Intent(intent)]


# --- Text normalisation / extraction ---------------------------------------
def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"\s+", " ", t).strip()


_INTENT_KEYWORDS = [
    (Intent.WARRANTY, ["bao hanh", "kich hoat bao hanh", "trung tam bao hanh"]),
    (Intent.RETURN_EXCHANGE, ["doi tra", "tra hang", "hoan tien", "doi san pham",
                               "san pham loi", "hang loi", "muon tra"]),
    (Intent.BOOK_APPOINTMENT, ["dat lich", "hen lich", "dat hen", "lich hen",
                                "muon hen", "dat cuoc hen"]),
    (Intent.SHIPPING_FEE, ["phi ship", "phi giao", "phi van chuyen", "ship bao nhieu",
                           "giao bao lau", "thoi gian giao", "khi nao giao",
                           "bao lau thi nhan", "phi gui"]),
    (Intent.CONFIRM_INFO, ["xac nhan thong tin", "xac nhan don", "xac nhan dia chi",
                           "kiem tra thong tin cua toi", "xac nhan lai"]),
    (Intent.ORDER_TRACKING, ["tra cuu don", "kiem tra don", "tinh trang don",
                             "don hang cua toi", "don cua toi", "ma don",
                             "don hang dang o dau", "theo doi don"]),
]

_ORDER_RE = re.compile(r"\b(?:DH|ORD|VN|SPX)?\d{6,14}\b", re.IGNORECASE)
_ORDER_LABELLED_RE = re.compile(
    r"(?:mã đơn|ma don|mã vận đơn|order)\s*(?:là|:)?\s*([A-Za-z0-9]{6,20})",
    re.IGNORECASE)
_PHONE_RE = re.compile(r"\b0\d{9}\b")
_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")
_TIME_RE = re.compile(r"\b(\d{1,2})\s*(?:giờ|h|g)\s*(\d{2})?\b", re.IGNORECASE)
_REL_DAYS = {"hom nay": "today", "ngay mai": "tomorrow", "ngay kia": "day_after_tomorrow"}


def detect_intent(text: str, llm_classifier: Optional[Callable] = None) -> Intent:
    """Keyword scoring on diacritic-stripped Vietnamese; an injected LLM
    classifier may only break a tie / confirm, never override a clear
    keyword hit (constrained LLM)."""
    n = _norm(text)
    scores: Dict[Intent, int] = {}
    for intent, kws in _INTENT_KEYWORDS:
        s = sum(1 for kw in kws if kw in n)
        if s:
            scores[intent] = s
    if "don" in n and _ORDER_RE.search(text or "") and not scores:
        scores[Intent.ORDER_TRACKING] = 1
    if scores:
        best = max(scores.items(), key=lambda kv: kv[1])
        return best[0]
    if llm_classifier is not None:
        try:
            suggested = llm_classifier(text)
            if suggested is not None:
                intent = Intent(str(suggested))
                if intent is not Intent.UNKNOWN:
                    return intent
        except Exception:
            pass  # a failing classifier must never crash the dialogue
    return Intent.UNKNOWN


def extract_slots(text: str, intent: Optional[Intent] = None) -> Dict[str, str]:
    slots: Dict[str, str] = {}
    if not text:
        return slots
    m = _ORDER_LABELLED_RE.search(text)
    if m:
        slots["order_code"] = m.group(1).upper()
    else:
        codes = _ORDER_RE.findall(text)
        # A bare long digit run that is a phone number is not an order code.
        phones = _PHONE_RE.findall(text)
        for c in codes:
            if c not in phones:
                slots["order_code"] = c.upper()
                break
    phones = _PHONE_RE.findall(text)
    if phones:
        slots["phone"] = phones[0]
    dm = _DATE_RE.search(text)
    tm = _TIME_RE.search(text)
    n = _norm(text)
    rel = next((v for k, v in _REL_DAYS.items() if k in n), None)
    if dm or tm or rel:
        parts = []
        if rel:
            parts.append(rel)
        if dm:
            parts.append(dm.group(0))
        if tm:
            parts.append(tm.group(0))
        slots["appointment_time"] = " ".join(parts)
    # Address heuristic for shipping-fee intent: text after "tới/đến/giao tới"
    am = re.search(r"(?:giao tới|giao đến|tới|đến)\s+(.+)$", text, re.IGNORECASE)
    if am and (intent is Intent.SHIPPING_FEE or intent is None):
        addr = am.group(1).strip(" .?")
        if len(addr) >= 3:
            slots["address"] = addr
    return slots


# --- State -------------------------------------------------------------------
@dataclass
class DialogueState:
    call_id: str = ""
    tenant_id: str = ""
    schema_version: str = STATE_SCHEMA_VERSION
    intent_schema_version: str = INTENT_SCHEMA_VERSION
    slot_schema_version: str = SLOT_SCHEMA_VERSION
    verified_customer: Dict[str, Any] = field(default_factory=dict)
    intent: Intent = Intent.UNKNOWN
    slots: Dict[str, str] = field(default_factory=dict)
    looked_up_data: Dict[str, Any] = field(default_factory=dict)
    steps_tried: List[str] = field(default_factory=list)
    unresolved_needs: List[str] = field(default_factory=list)
    frustration_level: int = 0  # 0 calm .. 3 very frustrated
    clarification_count: int = 0
    clarification_intent: Optional[Intent] = None
    topic_stack: List[Dict[str, Any]] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    turn_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["intent"] = self.intent.value
        d["clarification_intent"] = (
            self.clarification_intent.value if self.clarification_intent else None)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DialogueState":
        d = dict(d or {})
        if isinstance(d.get("intent"), str):
            d["intent"] = Intent(d["intent"])
        ci = d.get("clarification_intent")
        if isinstance(ci, str):
            d["clarification_intent"] = Intent(ci)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class DialogueResult:
    action: DialogueAction
    intent: Intent
    slots: Dict[str, str] = field(default_factory=dict)
    missing_slots: List[str] = field(default_factory=list)
    prompt: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    escalation_reason: Optional[str] = None
    state: Optional[DialogueState] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["action"] = self.action.value
        d["intent"] = self.intent.value
        d["state"] = self.state.to_dict() if self.state else None
        return d


# Backwards/forwards-compatible alias
TurnResult = DialogueResult

_FRUSTRATION_WORDS = ["buc", "tuc", "qua lau", "lua dao", "te qua", "kem",
                      "khieu nai", "khong hai long", "do lua"]
_CORRECTION_MARKERS = ["khong phai", "sua thanh", "doi thanh", "nham",
                       "sua lai", "doi sang", "chinh xac la"]
_BACK_MARKERS = ["quay lai", "tro lai", "viec truoc", "chuyen truoc"]


class DialogueManager:
    def __init__(self, llm_classifier: Optional[Callable] = None,
                 max_clarifications: Optional[int] = None):
        self.llm_classifier = llm_classifier
        self.max_clarifications = (
            int(MAX_CLARIFICATIONS) if max_clarifications is None
            else int(max_clarifications))

    def new_state(self, call_id: str = "", tenant_id: str = "",
                  verified_customer: Optional[Dict[str, Any]] = None) -> DialogueState:
        return DialogueState(call_id=call_id, tenant_id=tenant_id,
                             verified_customer=dict(verified_customer or {}))

    create_state = new_state
    start_session = new_state

    # -- internals -----------------------------------------------------------
    def _update_frustration(self, state: DialogueState, norm_text: str) -> None:
        hits = sum(1 for w in _FRUSTRATION_WORDS if w in norm_text)
        if hits:
            state.frustration_level = min(3, state.frustration_level + hits)

    def _missing(self, state: DialogueState) -> List[str]:
        pb = get_playbook(state.intent)
        return [s for s in pb.required_slots if not state.slots.get(s)]

    def _clarify_or_escalate(self, state: DialogueState,
                             missing: List[str]) -> DialogueResult:
        same_context = state.clarification_intent == state.intent
        if same_context and state.clarification_count >= self.max_clarifications:
            state.unresolved_needs = list(missing) or [state.intent.value]
            return DialogueResult(
                action=DialogueAction.ESCALATE, intent=state.intent,
                slots=dict(state.slots), missing_slots=list(missing),
                escalation_reason=REASON_REPEATED_CLARIFICATION, state=state)
        state.clarification_count = (
            state.clarification_count + 1 if same_context else 1)
        state.clarification_intent = state.intent
        pb = get_playbook(state.intent)
        if missing:
            prompt = " ".join(pb.slot_prompts.get(s, f"Cho em xin {s}?")
                               for s in missing)
        else:
            prompt = ("Anh/chị có thể nói rõ hơn nhu cầu của mình được không ạ? "
                      "Ví dụ tra cứu đơn hàng, phí giao hàng, đổi trả, bảo hành, "
                      "đặt lịch hoặc xác nhận thông tin.")
        return DialogueResult(
            action=DialogueAction.ASK_CLARIFICATION, intent=state.intent,
            slots=dict(state.slots), missing_slots=list(missing),
            prompt=prompt, state=state)

    # -- main entry ------------------------------------------------------------
    def process_turn(self, state: DialogueState, text: str) -> DialogueResult:
        if state is None:
            state = self.new_state()
        state.turn_index += 1
        state.history.append({"turn": state.turn_index, "role": "customer",
                              "text": text})
        n = _norm(text)
        self._update_frustration(state, n)

        # 1) Return to previous topic
        if any(m in n for m in _BACK_MARKERS) and state.topic_stack:
            prev = state.topic_stack.pop()
            state.intent = Intent(prev["intent"])
            for k, v in prev.get("slots", {}).items():
                state.slots.setdefault(k, v)
            state.clarification_count = 0
            state.clarification_intent = None
            state.steps_tried.append("return_to_previous_topic")
            missing = self._missing(state)
            if missing:
                return self._clarify_or_escalate(state, missing)
            return self._ready(state)

        # 2) Slot correction: override, never append a second value
        is_correction = any(m in n for m in _CORRECTION_MARKERS)
        new_slots = extract_slots(text, state.intent)
        if is_correction and new_slots:
            state.slots.update(new_slots)
            state.steps_tried.append("slot_correction")
            state.clarification_count = 0
            state.clarification_intent = None
            missing = self._missing(state)
            if missing:
                return self._clarify_or_escalate(state, missing)
            return self._ready(state)

        # 3) Intent detection (follow-up utterances keep current intent)
        detected = detect_intent(text, self.llm_classifier)
        is_followup = n.startswith(("the con", "con ", "the ", "roi sao", "tiep"))
        if detected is not Intent.UNKNOWN and detected != state.intent:
            if state.intent is not Intent.UNKNOWN:
                state.topic_stack.append(
                    {"intent": state.intent.value, "slots": dict(state.slots)})
                state.steps_tried.append("topic_switch")
            state.intent = detected
            state.clarification_count = 0
            state.clarification_intent = None
        elif detected is Intent.UNKNOWN and state.intent is Intent.UNKNOWN:
            return self._clarify_or_escalate(state, [])
        # follow-up / same intent: keep state.intent

        # 4) Fill slots (explicit values win over stored ones)
        if new_slots:
            state.slots.update(new_slots)
        state.steps_tried.append(f"turn:{state.intent.value}")

        # 5) Playbook gate: required slots or clarify/escalate
        missing = self._missing(state)
        if missing:
            return self._clarify_or_escalate(state, missing)
        return self._ready(state)

    handle_turn = process_turn
    process = process_turn

    def _ready(self, state: DialogueState) -> DialogueResult:
        pb = get_playbook(state.intent)
        state.unresolved_needs = []
        return DialogueResult(
            action=DialogueAction.READY_FOR_TOOL, intent=state.intent,
            slots=dict(state.slots), missing_slots=[],
            allowed_tools=list(pb.allowed_tools), state=state)

    def record_tool_result(self, state: DialogueState, tool: str,
                           data: Dict[str, Any]) -> DialogueState:
        """Store looked-up data in state; only data recorded here may be
        used to answer (grounding is enforced by the caller/verifier)."""
        pb = get_playbook(state.intent)
        tool = gateway_tool(tool)  # legacy semantic names resolve here
        if tool not in pb.allowed_tools:
            raise ValueError(f"tool_not_allowed_for_intent:{tool}")
        state.looked_up_data[tool] = data
        state.steps_tried.append(f"tool:{tool}")
        return state


__all__ = [
    "CONTRACTS_VERSION", "EscalationReason",
    "REASON_REPEATED_CLARIFICATION", "REASON_OUT_OF_SCOPE",
    "REASON_LOW_CONFIDENCE",
    "MAX_CLARIFICATIONS", "INTENT_SCHEMA_VERSION", "SLOT_SCHEMA_VERSION",
    "STATE_SCHEMA_VERSION", "GATEWAY_TOOLS", "TOOL_GATEWAY_MAP",
    "gateway_tool", "Intent", "DialogueAction", "Playbook",
    "PLAYBOOKS", "SLOT_PROMPTS_VI", "get_playbook", "detect_intent",
    "extract_slots", "DialogueState", "DialogueResult", "TurnResult",
    "DialogueManager",
]
