"""Regression guard for fix_rebase_fullstack_to_contracts.

The dialogue manager must take every locked value (MAX_CLARIFICATIONS,
escalation reasons) from src/contracts.py v1.0.0 — no mirror constants —
and must count clarifications exactly as contracts defines: the counter
counts clarification *questions asked* for the current intent; with the
locked limit of 1, the first missing-slot detection asks once and a still
-missing slot on the next turn escalates ``repeated_clarification``
without asking again.

Portable: repo root derived from this file, no hardcoded paths.
"""
import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import tempfile

_CLEAN_ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import contracts  # noqa: E402

DM_PATH = ROOT / "src" / "dialogue" / "dialogue_manager.py"
_spec = importlib.util.spec_from_file_location("dialogue_manager_rebased", DM_PATH)
dm = importlib.util.module_from_spec(_spec)
sys.modules["dialogue_manager_rebased"] = dm
_spec.loader.exec_module(dm)


def test_module_imports_locked_values_from_contracts():
    assert dm.CONTRACTS_VERSION == contracts.CONTRACTS_VERSION == "1.0.0"
    assert dm.MAX_CLARIFICATIONS == contracts.MAX_CLARIFICATIONS == 1
    assert dm.EscalationReason is contracts.EscalationReason


def test_reason_strings_are_contracts_enum_values():
    assert dm.REASON_REPEATED_CLARIFICATION == \
        contracts.EscalationReason.REPEATED_CLARIFICATION.value \
        == "repeated_clarification"
    assert dm.REASON_OUT_OF_SCOPE == \
        contracts.EscalationReason.OUT_OF_SCOPE.value == "out_of_scope"
    assert dm.REASON_LOW_CONFIDENCE == \
        contracts.EscalationReason.LOW_CONFIDENCE.value == "low_confidence"
    # locked snake_case member from the debate must exist (not user_requested)
    assert contracts.EscalationReason.CUSTOMER_REQUEST.value == "customer_request"


def test_no_mirror_constants_left_in_source():
    src = DM_PATH.read_text(encoding="utf-8")
    assert "from src.contracts import" in src
    # no literal re-definition of the locked limit or reason strings
    assert not re.search(r"^MAX_CLARIFICATIONS\s*=\s*\d", src, re.M)
    assert 'REASON_REPEATED_CLARIFICATION = "repeated_clarification"' not in src
    assert 'REASON_OUT_OF_SCOPE = "out_of_scope"' not in src
    # forbidden legacy spellings anywhere in the module
    assert "out-of-scope" not in src
    assert "OUT_OF_SCOPE" not in src.replace(
        "REASON_OUT_OF_SCOPE", "").replace('_reason("OUT_OF_SCOPE")', "")
    assert "user_requested" not in src
    # no fallback import of a bare top-level contracts module
    assert "from contracts import" not in src


def test_exactly_one_clarification_question_then_escalate():
    """Contracts counting definition: 1 question asked, then escalate."""
    m = dm.DialogueManager()
    s = m.new_state(call_id="c-rebase-1")
    r1 = m.process_turn(s, "Tôi muốn kiểm tra đơn hàng của tôi")
    assert r1.action is dm.DialogueAction.ASK_CLARIFICATION
    assert s.clarification_count == 1
    r2 = m.process_turn(s, "Tôi không nhớ mã nữa")
    assert r2.action is dm.DialogueAction.ESCALATE
    assert r2.escalation_reason == \
        contracts.EscalationReason.REPEATED_CLARIFICATION.value
    # no second question was asked: count stays at the locked limit
    assert s.clarification_count == 1


def test_behavior_follows_contracts_value_not_a_mirror():
    """With a contracts stub whose MAX_CLARIFICATIONS=0 in a clean
    subprocess, the manager must escalate immediately — proving the value
    is read from contracts, not mirrored in the module."""
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "src" / "dialogue").mkdir(parents=True)
        (root / "src" / "contracts.py").write_text(
            "from enum import Enum\n"
            "CONTRACTS_VERSION = '1.0.0'\n"
            "MAX_CLARIFICATIONS = 0\n"
            "class EscalationReason(str, Enum):\n"
            "    OUT_OF_SCOPE = 'out_of_scope'\n"
            "    LOW_CONFIDENCE = 'low_confidence'\n"
            "    SENSITIVE = 'sensitive'\n"
            "    CUSTOMER_REQUEST = 'customer_request'\n"
            "    REPEATED_CLARIFICATION = 'repeated_clarification'\n"
            "    REPEATED_FAILURE = 'repeated_failure'\n",
            encoding="utf-8")
        (root / "src" / "dialogue" / "dialogue_manager.py").write_bytes(
            DM_PATH.read_bytes())
        probe = root / "probe.py"
        probe.write_text(
            "import importlib.util, sys\n"
            f"sys.path.insert(0, r'{root}')\n"
            "spec = importlib.util.spec_from_file_location(\n"
            "    'dm_probe', r'" + str(root / "src" / "dialogue" / "dialogue_manager.py") + "')\n"
            "dm = importlib.util.module_from_spec(spec)\n"
            "sys.modules['dm_probe'] = dm\n"
            "spec.loader.exec_module(dm)\n"
            "assert dm.MAX_CLARIFICATIONS == 0, dm.MAX_CLARIFICATIONS\n"
            "m = dm.DialogueManager()\n"
            "assert m.max_clarifications == 0, m.max_clarifications\n"
            "s = m.new_state(call_id='probe')\n"
            "m.process_turn(s, 'Tôi muốn kiểm tra đơn hàng của tôi')\n"
            "r = m.process_turn(s, 'Tôi không nhớ mã nữa')\n"
            "assert r.action is dm.DialogueAction.ESCALATE, r.action\n"
            "assert r.escalation_reason == 'repeated_clarification'\n"
            "print('PROBE_OK')\n",
            encoding="utf-8")
        out = subprocess.run([sys.executable, str(probe)],
                             capture_output=True, text=True, timeout=60, env=_CLEAN_ENV)
        assert out.returncode == 0, out.stderr
        assert "PROBE_OK" in out.stdout


def test_rebased_manager_still_handles_core_flows():
    m = dm.DialogueManager()
    s = m.new_state(call_id="c-rebase-2")
    r = m.process_turn(s, "Tra cứu đơn hàng mã đơn là DH123456 giúp tôi")
    assert r.action is dm.DialogueAction.READY_FOR_TOOL
    assert r.slots["order_code"] == "DH123456"
    # a phone number is never mistaken for an order code
    s2 = m.new_state(call_id="c-rebase-3")
    r2 = m.process_turn(s2, "Xác nhận thông tin cho số 0901234567")
    assert r2.slots.get("phone") == "0901234567"
    assert "order_code" not in r2.slots


def test_missing_contracts_fails_loudly_not_silently():
    """Importing the manager without src/contracts.py must fail (no
    silent mirror fallback) — contract drift surfaces immediately."""
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "src" / "dialogue").mkdir(parents=True)
        (root / "src" / "dialogue" / "dialogue_manager.py").write_bytes(
            DM_PATH.read_bytes())
        probe = root / "probe.py"
        probe.write_text(
            "import importlib.util, sys\n"
            f"sys.path.insert(0, r'{root}')\n"
            "spec = importlib.util.spec_from_file_location(\n"
            "    'dm_probe2', r'" + str(root / "src" / "dialogue" / "dialogue_manager.py") + "')\n"
            "dm = importlib.util.module_from_spec(spec)\n"
            "sys.modules['dm_probe2'] = dm\n"
            "try:\n"
            "    spec.loader.exec_module(dm)\n"
            "except Exception:\n"
            "    print('IMPORT_FAILED_AS_EXPECTED')\n"
            "else:\n"
            "    print('IMPORTED_WITHOUT_CONTRACTS')\n",
            encoding="utf-8")
        out = subprocess.run([sys.executable, str(probe)],
                             capture_output=True, text=True, timeout=60, env=_CLEAN_ENV)
        assert "IMPORT_FAILED_AS_EXPECTED" in out.stdout, out.stdout + out.stderr


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
