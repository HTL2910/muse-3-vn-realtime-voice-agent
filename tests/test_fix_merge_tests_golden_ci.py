"""Regression guard for fix_merge_tests_golden_ci.

This branch's deliverable is tests/test_e2e_call.py. The guard checks:
- the E2E test exists, loads the three real modules from main and covers
  the three locked scenarios (answered-from-evidence call, sensitive
  case blocked by the gate then handed off with a package, no-agent ->
  durable callback ticket);
- when the merged golden data / collect script / CI config from the
  sibling triage branches are present on main, they match the locked
  shape (12 golden calls, seedable collect_data.py, CI runs pytest).
  Presence-dependent checks only hard-fail when the artifact is present
  but wrong — merging those artifacts belongs to their own branches.
"""
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
E2E = ROOT / "tests" / "test_e2e_call.py"


def test_e2e_file_exists_and_loads_real_modules():
    assert E2E.exists()
    src = E2E.read_text(encoding="utf-8")
    for rel in ("src/dialogue/dialogue_manager.py",
                "src/handoff/handoff_service.py",
                "src/handoff/context_package.py"):
        assert rel in src, rel
        assert (ROOT / rel).exists(), rel


def test_e2e_covers_the_three_locked_scenarios():
    src = E2E.read_text(encoding="utf-8")
    assert "test_full_call_answered_from_evidence" in src
    assert "test_sensitive_case_gate_blocks_then_handoff_with_package" in src
    assert "test_no_agent_creates_durable_callback_ticket_with_package" in src
    # the locked vocabulary of the flow must appear, snake_case only
    for token in ("sensitive", "customer_request", "repeated_clarification",
                  "WARM_TRANSFER", "CALLBACK", "READY_FOR_TOOL"):
        assert token in src, token
    assert "out-of-scope" not in src and "user_requested" not in src


def test_e2e_module_imports_and_defines_tests():
    spec = importlib.util.spec_from_file_location("test_e2e_call_guard", E2E)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["test_e2e_call_guard"] = mod
    spec.loader.exec_module(mod)
    fns = [k for k in vars(mod) if k.startswith("test_")]
    assert len(fns) >= 3


def test_golden_data_shape_when_present():
    golden_dir = ROOT / "data" / "golden"
    calls_file = golden_dir / "golden_calls.json"
    if not calls_file.exists():
        return  # merged by the data branch; nothing to validate yet
    calls = json.loads(calls_file.read_text(encoding="utf-8"))
    if isinstance(calls, dict):
        calls = calls.get("calls", [])
    assert len(calls) == 12
    cats = {c.get("category", "") for c in calls if isinstance(c, dict)}
    for required in ("complaint_sensitive", "out_of_scope", "injection"):
        assert required in cats, required


def test_collect_data_seedable_when_present():
    script = ROOT / "scripts" / "collect_data.py"
    if not script.exists():
        return
    src = script.read_text(encoding="utf-8")
    assert "seed" in src  # must support --seed 42 regeneration on main


def test_ci_config_runs_pytest_when_present():
    workflows = ROOT / ".github" / "workflows"
    if not workflows.exists():
        return
    texts = [p.read_text(encoding="utf-8", errors="ignore")
             for p in workflows.glob("*.y*ml")]
    assert any("pytest" in t for t in texts)


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
