"""Tests for fix_missing_eval_harness (approach_20).

Checks: golden set covers every required category; regression passes
with the reference end-to-end flow and BLOCKS the merge for a system
that answers sensitive cases / hallucinates; two-layer containment;
latency SLO fails on total even when stages pass; load simulation over
hundreds of calls; shadow agreement + sensitive human review; canary
5-10% + kill-switch; go-live gate rejects vendor numbers and requires
the tenant's own shadow/canary metrics + the 7-question baseline
checklist; end-to-end sensitive case -> handoff -> no agent -> durable
callback ticket.
Portable: repo root derived from this file, no hardcoded paths.
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "simulation_harness", ROOT / "src" / "eval" / "simulation_harness.py")
ev = importlib.util.module_from_spec(_spec)
sys.modules["simulation_harness"] = ev
_spec.loader.exec_module(ev)


def test_golden_set_covers_all_required_categories():
    cats = {c.category for c in ev.DEFAULT_GOLDEN_CALLS}
    required = {"order_tracking", "return", "complaint_sensitive",
                "out_of_scope", "barge_in", "no_diacritics", "dialect_south",
                "dialect_central", "noisy_low_asr", "wrong_order_code",
                "injection", "customer_request"}
    assert required <= cats
    dialects = {c.dialect for c in ev.DEFAULT_GOLDEN_CALLS}
    assert {"north", "central", "south"} <= dialects


def test_regression_passes_with_reference_flow():
    rep = ev.run_regression(ev.DEFAULT_GOLDEN_CALLS, ev.SimulatedCallFlow())
    assert rep.passed and not rep.merge_blocked, rep.failures
    assert rep.total == len(ev.DEFAULT_GOLDEN_CALLS)


def test_regression_blocks_system_that_answers_everything():
    def reckless(call):
        return ev.CallOutcome(
            action="answer", intent="order_tracking",
            answer_facts=["DH100001", "mien phi 999999"],
            evidence_facts=["DH100001"], resolved=True,
            stage_latencies_ms={"asr": 100, "llm": 200, "tts": 100})

    rep = ev.run_regression(ev.DEFAULT_GOLDEN_CALLS, reckless)
    assert not rep.passed and rep.merge_blocked
    assert rep.metrics["hallucination_rate"].value > 0


def test_containment_two_layers_final_below_provisional_on_repeat():
    outcomes = [
        ev.CallOutcome(action="answer", resolved=True),
        ev.CallOutcome(action="answer", resolved=True,
                       repeat_contact_within_window=True),
        ev.CallOutcome(action="escalate", reason="sensitive"),
        ev.CallOutcome(action="escalate", reason="out_of_scope"),
    ]
    m = ev.compute_metrics(outcomes)
    assert m["containment_provisional"].value == 0.5
    assert m["containment_final"].value == 0.25
    assert m["fcr"].value == 0.25


def test_metrics_carry_ci_definition_and_source():
    m = ev.compute_metrics([ev.CallOutcome(action="answer", resolved=True)],
                           source="tenant_shadow")
    c = m["containment_final"]
    assert c.ci_low <= c.value <= c.ci_high
    assert "72h" in c.definition and c.source == "tenant_shadow" and c.n == 1


def test_latency_total_slo_fails_even_if_stages_pass():
    # Each stage under its own budget (250/500/350) but the sum + work
    # makes the recorded total stages exceed 1200 at p95 via llm spikes.
    outcomes = [ev.CallOutcome(action="answer", resolved=True,
                               stage_latencies_ms={"asr": 250, "llm": 500,
                                                   "tts": 350})
                for _ in range(10)]
    outcomes.append(ev.CallOutcome(action="answer", resolved=True,
                                   stage_latencies_ms={"asr": 250, "llm": 900,
                                                       "tts": 350}))
    lat = ev.latency_report(outcomes)
    assert lat["total"]["p95"] > ev.TOTAL_LATENCY_SLO_MS
    assert not lat["passed"] and lat["violations"]


def test_latency_within_budget_passes():
    outcomes = [ev.CallOutcome(action="answer", resolved=True,
                               stage_latencies_ms={"asr": 180, "llm": 420,
                                                   "tts": 300})
                for _ in range(5)]
    lat = ev.latency_report(outcomes)
    assert lat["passed"] and lat["total"]["p95"] == 900


def test_load_simulation_hundreds_of_calls():
    out = ev.simulate_load(n_calls=300, concurrency=100)
    assert out["n_calls"] == 300
    assert "containment_final" in out["metrics"]
    assert out["metrics"]["containment_final"]["n"] == 300
    assert out["latency"]["total"]["p95"] <= 1200


def test_shadow_mode_agreement_and_sensitive_review():
    ai = ev.SimulatedCallFlow()
    rep = ev.run_shadow(ev.DEFAULT_GOLDEN_CALLS, ai, ai)
    assert rep.agreement_rate == 1.0 and rep.divergences == []

    def human_answers_sensitive(call):
        if call.category == "complaint_sensitive":
            return ev.CallOutcome(action="answer", resolved=True)
        return ai(call)

    rep2 = ev.run_shadow(ev.DEFAULT_GOLDEN_CALLS, ai, human_answers_sensitive)
    assert rep2.agreement_rate < 1.0
    assert rep2.sensitive_divergences
    j = ev.judge_transcript(ev.DEFAULT_GOLDEN_CALLS[2], ai(ev.DEFAULT_GOLDEN_CALLS[2]))
    assert j["requires_human_review"] is True


def test_canary_bounds_and_kill_switch():
    try:
        ev.CanaryController(20)
        raise AssertionError("canary >10% accepted")
    except ValueError:
        pass
    c = ev.CanaryController(10)
    routed = sum(1 for i in range(200) if c.route_to_ai(f"call-{i}"))
    assert 0 < routed < 60  # roughly 10%, deterministic by hash bucket
    out = c.kill_switch()
    assert out["within_budget"] and out["latency_s"] < 60
    assert all(not c.route_to_ai(f"call-{i}") for i in range(20))


def _ready_checklist():
    return ev.ReadinessChecklist(
        data_digitalised=True, cloud_pbx_with_api=True,
        calls_recorded_transcribed=True, repeat_question_rate_known=True,
        peak_and_abandonment_known=True, handoff_process_defined=True,
        baseline_metrics_recorded=True, baseline_abandonment=0.084,
        baseline_fcr=0.62)


def _good_shadow():
    return ev.ShadowReport(n=100, agreement_rate=0.95)


def _good_metrics():
    outcomes = [ev.CallOutcome(action="answer", resolved=True)
                for _ in range(80)] + \
               [ev.CallOutcome(action="escalate", reason="sensitive")
                for _ in range(20)]
    return ev.compute_metrics(outcomes, source="tenant_shadow_canary")


def test_go_live_passes_on_tenant_metrics_and_full_checklist():
    d = ev.evaluate_go_live(_good_shadow(), _good_metrics(), _ready_checklist())
    assert d.go and d.checklist_score == 7


def test_go_live_blocks_vendor_numbers():
    d = ev.evaluate_go_live(_good_shadow(), _good_metrics(), _ready_checklist(),
                            metrics_source="vendor_benchmark")
    assert not d.go
    assert "vendor_numbers_not_accepted_as_tenant_kpi" in d.blocked_reasons


def test_go_live_blocks_without_baseline():
    cl = _ready_checklist()
    cl.baseline_abandonment = None
    cl.baseline_metrics_recorded = False
    d = ev.evaluate_go_live(_good_shadow(), _good_metrics(), cl)
    assert not d.go and "baseline_abandonment_fcr_missing" in d.blocked_reasons


def test_end_to_end_sensitive_case_handoff_then_callback_ticket():
    flow = ev.SimulatedCallFlow(agents_available=False)
    call = [c for c in ev.DEFAULT_GOLDEN_CALLS
            if c.category == "complaint_sensitive"][0]
    o = flow(call)
    assert o.action == "escalate" and o.reason == "sensitive"
    assert o.department == "complaints"
    assert flow.ticket_store  # no agent -> durable callback ticket
    ticket = next(iter(flow.ticket_store.values()))
    assert ticket["status"] == "callback_pending"
    assert ticket["package"]["escalation_reason"] == "sensitive"


def test_end_to_end_grounded_answer_path():
    flow = ev.SimulatedCallFlow()
    call = ev.DEFAULT_GOLDEN_CALLS[0]
    o = flow(call)
    assert o.action == "answer"
    assert all(f in o.evidence_facts for f in o.answer_facts)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("PASS", fn.__name__)
    print(f"{len(fns)} passed")
