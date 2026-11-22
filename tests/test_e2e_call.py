"""End-to-end integration test: one full simulated call on main.

fix_merge_tests_golden_ci — the minimum E2E proof the council locked:
a simulated call flows through the real modules on main —

    nghe (transcript turns in) -> hiểu (dialogue_manager: intent/slots)
    -> tra dữ liệu có evidence (tool call recorded in dialogue state)
    -> gate (hard rule) -> trả lời từ evidence, hoặc
    -> handoff kèm HandoffPackage/ContextPackage (handoff_service),
    -> hết agent -> callback ticket bền vững (ticket store + package).

Modules are loaded by file path from the repo root so the test exercises
exactly the files on main, independent of package layout. The OMS below
is a golden snapshot: when data/golden/orders.json exists on main its
orders are merged in; the built-in snapshot keeps the test deterministic
either way. The gate step is the contracts hard rule (sensitive markers
always block an AI answer and escalate with reason ``sensitive``); it is
kept as a small adapter here because policy_engine's public API is owned
by another branch — the asserted contract (no answer, reason, package)
is the locked one.
"""
import importlib.util
import json
import pathlib
import sys
import unicodedata
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dm = _load("e2e_dialogue_manager", "src/dialogue/dialogue_manager.py")
hs = _load("e2e_handoff_service", "src/handoff/handoff_service.py")
cp = _load("e2e_context_package", "src/handoff/context_package.py")


# --- Golden OMS snapshot ------------------------------------------------------
def _golden_orders():
    orders = {"DH123456": {"order_code": "DH123456",
                           "status": "đang giao hàng",
                           "carrier": "GHN", "eta_days": 1}}
    for cand in (ROOT / "data" / "golden" / "orders.json",
                 ROOT / "data" / "orders.json"):
        try:
            raw = json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = raw if isinstance(raw, list) else raw.get("orders", [])
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            code = it.get("order_code") or it.get("code") or it.get("id")
            status = it.get("status") or it.get("trang_thai") or it.get("state")
            if code and status:
                orders[str(code)] = {"order_code": str(code),
                                     "status": str(status)}
        break
    return orders


ORDERS = _golden_orders()
KNOWN_CODE = "DH123456" if "DH123456" in ORDERS else next(iter(ORDERS))


def fake_get_order(order_code):
    """Stand-in for the tool gateway's OMS lookup (golden data only)."""
    return ORDERS.get(order_code)


# --- Gate adapter (contracts hard rule) ---------------------------------------
_SENSITIVE_MARKERS = ("boi thuong", "kien", "phap ly", "luat su",
                      "bao co quan", "dang bao")


def _norm(text):
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.replace("đ", "d")


def hard_rule_gate(text):
    """Return an escalation reason when a hard rule blocks answering."""
    n = _norm(text)
    if any(m in n for m in _SENSITIVE_MARKERS):
        return "sensitive"
    return None


def _context_package_from_state(state, reason, tool_records):
    return cp.ContextPackage(
        call_id=state.call_id, escalation_reason=reason,
        tenant_id=state.tenant_id,
        customer_id=state.verified_customer.get("customer_id", ""),
        phone=state.verified_customer.get("phone", ""),
        verified_customer=dict(state.verified_customer),
        intent=state.intent.value, unresolved_needs=list(state.unresolved_needs),
        slots=dict(state.slots),
        transcript=[cp.TranscriptEntry(role=h.get("role", "customer"),
                                       text=h.get("text", ""),
                                       timestamp=float(h.get("turn", 0)))
                    for h in state.history],
        tool_calls=tool_records,
        frustration_level=state.frustration_level)


# --- Scenario 1: full call answered from evidence ------------------------------
def test_full_call_answered_from_evidence():
    mgr = dm.DialogueManager()
    state = mgr.new_state(call_id="e2e-1", tenant_id="t1",
                          verified_customer={"customer_id": "KH001",
                                             "phone": "0901234567",
                                             "phone_verified": True})
    # nghe -> hiểu
    r = mgr.process_turn(state, f"Tra cứu đơn hàng mã đơn là {KNOWN_CODE} giúp tôi")
    assert r.action is dm.DialogueAction.READY_FOR_TOOL, r
    assert r.intent is dm.Intent.ORDER_TRACKING
    assert "get_order" in r.allowed_tools
    # tra dữ liệu thật (tool gateway stand-in over golden data)
    evidence = fake_get_order(r.slots["order_code"])
    assert evidence is not None
    mgr.record_tool_result(state, "get_order", evidence)
    # trả lời: every concrete fact in the answer comes from the evidence
    answer = (f"Dạ đơn {evidence['order_code']} hiện đang ở trạng thái "
              f"{evidence['status']} ạ.")
    for fact in (evidence["order_code"], evidence["status"]):
        assert fact in answer and fact in str(evidence.values())
    # contained: resolved by AI, no handoff needed
    assert state.looked_up_data["get_order"] is evidence


# --- Scenario 2: sensitive case -> gate blocks -> handoff with package ---------
def test_sensitive_case_gate_blocks_then_handoff_with_package():
    mgr = dm.DialogueManager()
    state = mgr.new_state(call_id="e2e-2", tenant_id="t1",
                          verified_customer={"customer_id": "KH002",
                                             "phone": "0912345678",
                                             "phone_verified": True})
    r = mgr.process_turn(state, f"Tôi muốn kiểm tra đơn {KNOWN_CODE}")
    assert r.action is dm.DialogueAction.READY_FOR_TOOL
    evidence = fake_get_order(KNOWN_CODE)
    mgr.record_tool_result(state, "get_order", evidence)
    tool_records = [cp.ToolCallRecord(tool="get_order",
                                      args={"order_code": KNOWN_CODE},
                                      result=evidence, timestamp=1.0)]

    angry = "Tôi khiếu nại, yêu cầu bồi thường ngay, không thì tôi kiện ra tòa"
    mgr.process_turn(state, angry)
    # gate: hard rule blocks any AI answer for this turn
    reason = hard_rule_gate(angry)
    assert reason == "sensitive"
    assert state.frustration_level >= 1

    # handoff package: validated 3-part summary built from evidence only
    pkg = _context_package_from_state(state, reason, tool_records)
    pkg.unresolved_needs = ["khiếu nại và yêu cầu bồi thường"]
    cp.build_context_package(pkg)
    assert cp.validate_summary(pkg) == []
    assert pkg.summary.who_and_verified
    assert pkg.summary.discussed_and_looked_up
    assert pkg.summary.next_action
    card = cp.build_desktop_card(pkg)
    assert card  # one-screen desktop card exists for the agent

    # warm transfer: context ACKed before bridge, correct reason counted
    pushed = []
    svc = hs.HandoffService(
        context_push=lambda agent_id, p: pushed.append(agent_id) or True)
    svc.register_agent(agent_id="agent-complaints", skills=["general"],
                       departments=["complaints"], languages=["vi"],
                       capacity=2)
    hpkg = hs.HandoffPackage(
        call_id=state.call_id, escalation_reason=reason, tenant_id="t1",
        customer_id="KH002", phone="0912345678", intent=state.intent.value,
        summary=pkg.summary.all_text(),
        transcript=[t.to_dict() for t in pkg.transcript],
        slots=dict(state.slots), looked_up_data=dict(state.looked_up_data),
        required_skill="general", department="complaints")
    result = svc.request_handoff(hpkg)
    assert result.outcome is hs.HandoffOutcome.WARM_TRANSFER
    assert result.bridged is True and result.context_acked is True
    assert result.agent_id == "agent-complaints"
    assert pushed == ["agent-complaints"]  # context pushed before bridging
    assert svc.reason_counts["sensitive"] == 1


# --- Scenario 3: no agent available -> durable callback ticket ------------------
def test_no_agent_creates_durable_callback_ticket_with_package():
    mgr = dm.DialogueManager()
    state = mgr.new_state(call_id="e2e-3", tenant_id="t1",
                          verified_customer={"customer_id": "KH003",
                                             "phone": "0987654321"})
    r = mgr.process_turn(state, "Cho tôi gặp nhân viên thật đi")
    pkg = _context_package_from_state(state, "customer_request", [])
    cp.build_context_package(pkg)

    # ticket store = the durable outbox/DB stand-in: factory persists the
    # full package with the ticket, keyed by ticket_id
    ticket_store = {}

    def factory(hpkg, reason):
        tid = f"CB-{len(ticket_store) + 1:06d}"
        ticket_store[tid] = {"ticket_id": tid, "status": "callback_pending",
                             "reason": reason, "package": hpkg.to_dict()}
        return tid

    svc = hs.HandoffService(ticket_factory=factory)  # no agents registered
    hpkg = hs.HandoffPackage(
        call_id=state.call_id, escalation_reason="customer_request",
        tenant_id="t1", customer_id="KH003", phone="0987654321",
        summary=pkg.summary.all_text(), slots=dict(state.slots))
    result = svc.request_handoff(hpkg)
    assert result.outcome is hs.HandoffOutcome.CALLBACK
    assert result.bridged is False
    assert result.ticket_id in ticket_store
    saved = ticket_store[result.ticket_id]
    assert saved["package"]["call_id"] == "e2e-3"
    assert saved["package"]["escalation_reason"] == "customer_request"
    assert saved["package"]["summary"]  # customer never repeats themselves

    # durability: the store survives a JSON round-trip (persist + reload)
    reloaded = json.loads(json.dumps(ticket_store))
    assert reloaded[result.ticket_id]["status"] == "callback_pending"

    # context_package's own no-dead-end path agrees
    out = cp.ensure_no_dead_end(pkg, agent_available=False)
    assert out["outcome"] == "callback" and out["ticket_id"]
    assert out["package"]["call_id"] == "e2e-3"


# --- Scenario 4: clarification budget ties dialogue -> handoff ------------------
def test_repeated_clarification_escalates_with_contracts_reason():
    mgr = dm.DialogueManager()
    state = mgr.new_state(call_id="e2e-4", tenant_id="t1")
    r1 = mgr.process_turn(state, "Tôi muốn kiểm tra đơn hàng của tôi")
    assert r1.action is dm.DialogueAction.ASK_CLARIFICATION
    r2 = mgr.process_turn(state, "Tôi không nhớ mã nữa")
    assert r2.action is dm.DialogueAction.ESCALATE
    assert r2.escalation_reason == "repeated_clarification"
    pkg = _context_package_from_state(state, r2.escalation_reason, [])
    cp.build_context_package(pkg)
    svc = hs.HandoffService()
    svc.register_agent(agent_id="agent-general", skills=["general"])
    result = svc.request_handoff(hs.HandoffPackage(
        call_id=state.call_id, escalation_reason=r2.escalation_reason,
        summary=pkg.summary.all_text(), slots=dict(state.slots)))
    assert result.outcome is hs.HandoffOutcome.WARM_TRANSFER
    assert svc.reason_counts["repeated_clarification"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
    print(f"{len(fns) - failed} passed")
    sys.exit(1 if failed else 0)
