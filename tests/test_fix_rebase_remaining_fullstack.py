"""Regression guard for fix_rebase_remaining_fullstack.

The 5 remaining fullstack-ux modules (handoff_service, context_package,
ingestion_pipeline, sme_onboarding_hub, simulation_harness) must take
every contracts-locked value from src/contracts.py v1.0.0 — no mirror
constants: no local EscalationReason class, no literal reason sets, no
literal latency budget / containment window. Verified by identity checks
against contracts, source scans, and behaviour spot-checks. Their own
suites (15+12+12+16+15 = 70 tests) must also stay green — run them
alongside this file.

Portable: repo root derived from this file, no hardcoded paths.
"""
import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import contracts  # noqa: E402


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


hs = _load("rb_handoff_service", "src/handoff/handoff_service.py")
cp = _load("rb_context_package", "src/handoff/context_package.py")
kb = _load("rb_ingestion_pipeline", "src/knowledge/ingestion_pipeline.py")
sme = _load("rb_sme_hub", "src/integrations/sme_onboarding_hub.py")
ev = _load("rb_simulation_harness", "src/eval/simulation_harness.py")

MODULE_FILES = [
    "src/handoff/handoff_service.py",
    "src/handoff/context_package.py",
    "src/knowledge/ingestion_pipeline.py",
    "src/integrations/sme_onboarding_hub.py",
    "src/eval/simulation_harness.py",
]
REASON_VALUES = {r.value for r in contracts.EscalationReason}


def test_no_mirror_definitions_in_any_module_source():
    for rel in MODULE_FILES:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "class EscalationReason" not in src, rel
        assert not re.search(r"^MAX_CLARIFICATIONS\s*=\s*\d", src, re.M), rel
        assert not re.search(r"^CONTAINMENT_WINDOW_HOURS\s*=\s*\d", src, re.M), rel
        assert not re.search(r"^TOTAL_LATENCY_SLO_MS\s*=\s*\d", src, re.M), rel
        assert '"out_of_scope", "low_confidence"' not in src, rel
        # legacy spellings as code tokens (quoted literals), not prose
        assert '"out-of-scope"' not in src and "'out-of-scope'" not in src, rel
        assert '"user_requested"' not in src and "'user_requested'" not in src, rel
        assert ("from src.contracts import" in src
                or "from src import contracts" in src), rel


def test_handoff_service_uses_contracts_reason_enum():
    assert hs.EscalationReason is contracts.EscalationReason
    svc = hs.HandoffService()
    svc.register_agent(agent_id="a1", skills=["general"])
    r = svc.request_handoff(hs.HandoffPackage(
        call_id="rb1", escalation_reason=contracts.EscalationReason.SENSITIVE))
    assert r.outcome is hs.HandoffOutcome.WARM_TRANSFER
    assert svc.reason_counts["sensitive"] == 1
    try:
        hs.HandoffPackage(call_id="rb2", escalation_reason="OUT_OF_SCOPE")
    except ValueError:
        pass
    else:
        raise AssertionError("legacy reason spelling must be rejected")


def test_context_package_reasons_derived_from_contracts():
    assert cp.VALID_REASONS == REASON_VALUES
    pkg = cp.ContextPackage(call_id="rb3", escalation_reason="sensitive")
    assert pkg.escalation_reason == "sensitive"


def test_ingestion_conflict_reason_comes_from_contracts():
    assert kb.CONFLICT_ESCALATION_REASON == \
        contracts.EscalationReason.LOW_CONFIDENCE.value == "low_confidence"


def test_sme_required_reasons_come_from_contracts():
    assert sme.REQUIRED_ESCALATION_REASONS == (
        contracts.EscalationReason.SENSITIVE.value,
        contracts.EscalationReason.CUSTOMER_REQUEST.value)


def test_eval_latency_and_containment_come_from_contracts():
    total = contracts.TOTAL_SLO_P95_MS
    assert ev.TOTAL_SLO_P95_MS == total == 1200
    assert ev.TOTAL_LATENCY_SLO_MS == total
    assert ev.STAGE_BUDGETS_MS == {"asr": 250, "llm": 500, "tts": 350}
    assert sum(ev.STAGE_BUDGETS_MS.values()) + ev.JITTER_BUFFER_MS == total
    assert ev.JITTER_BUFFER_MS == 100
    assert ev.CONTAINMENT_WINDOW_HOURS == contracts.CONTAINMENT_WINDOW_HOURS == 72


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
