"""Tests for fix_missing_handoff_service.

End-to-end checks agreed by the council:
- no eligible agent -> CALLBACK with a ticket_id (never a dead end);
- context push failing after retries -> NOT bridged (no blind bridge),
  falls back to CALLBACK;
- reason_counts records the exact snake_case escalation reason;
- routing is least-loaded, sticky and VIP-aware, respecting skill,
  department, language, shift and capacity.
Portable: repo root derived from this file, no hardcoded paths.
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "handoff_service", ROOT / "src" / "handoff" / "handoff_service.py")
hs = importlib.util.module_from_spec(_spec)
sys.modules["handoff_service"] = hs
_spec.loader.exec_module(hs)

HandoffService = hs.HandoffService
HandoffPackage = hs.HandoffPackage
Agent = hs.Agent
Outcome = hs.HandoffOutcome


def pkg(**over):
    base = dict(call_id="call-1", escalation_reason="sensitive",
                customer_id="cust-1", phone="0901234567",
                intent="complaint", summary="Khách khiếu nại đơn DH123456",
                required_skill="complaints", language="vi")
    base.update(over)
    return HandoffPackage(**base)


def test_no_agent_at_all_gives_callback_with_ticket():
    svc = HandoffService()
    r = svc.request_handoff(pkg())
    assert r.outcome is Outcome.CALLBACK
    assert r.ticket_id and r.ticket_id.startswith("CB-")
    assert r.bridged is False


def test_all_agents_off_shift_gives_callback():
    svc = HandoffService()
    svc.register_agent(Agent("a1", skills=["complaints"], on_shift=False))
    r = svc.request_handoff(pkg())
    assert r.outcome is Outcome.CALLBACK and r.ticket_id


def test_warm_transfer_pushes_context_before_bridge():
    events = []

    def push(agent_id, p):
        events.append(("push", agent_id)); return True

    def bridge(call_id, agent_id, mode):
        events.append(("bridge", agent_id, mode)); return True

    svc = HandoffService(context_push=push, bridge=bridge)
    svc.register_agent(Agent("a1", skills=["complaints"]))
    r = svc.request_handoff(pkg())
    assert r.outcome is Outcome.WARM_TRANSFER
    assert r.bridged is True and r.context_acked is True
    assert r.agent_id == "a1" and r.transfer_mode == "sip_refer"
    assert [e[0] for e in events] == ["push", "bridge"]  # context first


def test_context_push_failure_never_bridges_blind():
    bridged = []

    def bridge(call_id, agent_id, mode):
        bridged.append(True); return True

    svc = HandoffService(context_push=lambda a, p: False, bridge=bridge,
                         max_context_retries=3)
    svc.register_agent(Agent("a1", skills=["complaints"]))
    r = svc.request_handoff(pkg())
    assert r.outcome is Outcome.CALLBACK and r.ticket_id
    assert r.bridged is False and bridged == []  # bridge never attempted
    assert r.context_attempts == 3 and r.detail == "context_push_failed"


def test_context_push_retries_then_succeeds():
    calls = {"n": 0}

    def flaky(agent_id, p):
        calls["n"] += 1
        return calls["n"] >= 2

    svc = HandoffService(context_push=flaky, max_context_retries=3)
    svc.register_agent(Agent("a1", skills=["complaints"]))
    r = svc.request_handoff(pkg())
    assert r.outcome is Outcome.WARM_TRANSFER and r.context_attempts == 2


def test_bridge_failure_falls_back_to_callback():
    svc = HandoffService(bridge=lambda c, a, m: False)
    svc.register_agent(Agent("a1", skills=["complaints"]))
    r = svc.request_handoff(pkg())
    assert r.outcome is Outcome.CALLBACK and r.ticket_id
    assert r.detail == "bridge_failed"


def test_reason_counts_use_exact_snake_case():
    svc = HandoffService()
    svc.register_agent(Agent("a1", skills=["complaints", "general"]))
    svc.request_handoff(pkg(escalation_reason="sensitive"))
    svc.request_handoff(pkg(call_id="call-2", escalation_reason="customer_request"))
    svc.request_handoff(pkg(call_id="call-3", escalation_reason="sensitive"))
    assert svc.reason_counts == {"sensitive": 2, "customer_request": 1}


def test_invalid_reason_is_rejected():
    try:
        pkg(escalation_reason="OUT_OF_SCOPE")  # not the locked snake_case value
        raise AssertionError("invalid reason accepted")
    except ValueError:
        pass
    try:
        pkg(escalation_reason="out-of-scope")
        raise AssertionError("invalid reason accepted")
    except ValueError:
        pass


def test_least_loaded_routing():
    svc = HandoffService()
    svc.register_agent(Agent("busy", skills=["complaints"], capacity=4, active_calls=3))
    svc.register_agent(Agent("free", skills=["complaints"], capacity=4, active_calls=0))
    r = svc.request_handoff(pkg())
    assert r.agent_id == "free"


def test_capacity_full_agent_is_skipped_to_callback():
    svc = HandoffService()
    svc.register_agent(Agent("a1", skills=["complaints"], capacity=1, active_calls=1))
    r = svc.request_handoff(pkg())
    assert r.outcome is Outcome.CALLBACK and r.ticket_id


def test_skill_and_language_mismatch_not_routed():
    svc = HandoffService()
    svc.register_agent(Agent("a1", skills=["sales"], languages=["en"]))
    r = svc.request_handoff(pkg())  # needs complaints + vi
    assert r.outcome is Outcome.CALLBACK


def test_sticky_routing_returns_same_agent():
    svc = HandoffService()
    svc.register_agent(Agent("a1", skills=["complaints"], capacity=10))
    svc.register_agent(Agent("a2", skills=["complaints"], capacity=10))
    r1 = svc.request_handoff(pkg())
    r2 = svc.request_handoff(pkg(call_id="call-2"))
    assert r1.agent_id == r2.agent_id


def test_vip_customer_prefers_vip_capable_agent():
    svc = HandoffService()
    svc.register_agent(Agent("plain", skills=["complaints"], capacity=10))
    svc.register_agent(Agent("vipdesk", skills=["complaints"], capacity=10,
                             vip_capable=True, active_calls=1))
    r = svc.request_handoff(pkg(is_vip=True, priority="vip"))
    assert r.agent_id == "vipdesk"


def test_successful_transfer_consumes_capacity_and_complete_releases():
    svc = HandoffService()
    a = svc.register_agent(Agent("a1", skills=["complaints"], capacity=1))
    r = svc.request_handoff(pkg())
    assert r.outcome is Outcome.WARM_TRANSFER and a.active_calls == 1
    r2 = svc.request_handoff(pkg(call_id="call-2", customer_id="cust-2"))
    assert r2.outcome is Outcome.CALLBACK  # agent now full
    svc.complete_call("a1")
    assert a.active_calls == 0


def test_package_to_dict_keeps_reason_and_summary():
    p = pkg(transcript=[{"role": "customer", "text": "tôi rất bực"}])
    d = p.to_dict()
    assert d["escalation_reason"] == "sensitive"
    assert d["summary"] and d["transcript"][0]["text"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("PASS", fn.__name__)
    print(f"{len(fns)} passed")
