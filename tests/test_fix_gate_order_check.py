"""Tests for fix_gate_order_check — manifest gate enforces merge order.

Branch: fix/fix_gate_order_check. Target file:
scripts/verify_main_manifest.py (extends fix_merge_pipeline_gate,
no second gate).

New requirement from fullstack-ux (debate round #3, agreed by all
4 experts): rebased modules import hard from src.contracts and
fail-closed when contracts is absent — dialogue_manager proved it
with a test (missing contracts => import fails). If a rebased
module were merged before contracts, a correct patch would become
a repo-wide import error. The gate now fails (exit 1) when any
present src/ module imports src.contracts while src/contracts.py
is not in the same manifest, naming the violating modules.

The order check runs inside check_manifest(), alongside the
existing checks (21 approaches + contracts + scaffolding, SHA-256
hashes, compileall, pytest, --publish-evidence/--require-evidence).

Run:
    PYTHONPATH=. python3 -m pytest tests/test_fix_gate_order_check.py -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "verify_main_manifest.py"


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "verify_main_manifest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses in the script need the module registered first.
    sys.modules["verify_main_manifest"] = module
    spec.loader.exec_module(module)
    return module


gate = load_gate()

# A minimal rebased module: imports hard from contracts, fail-closed
# without it (mirrors dialogue_manager's behaviour).
DIALOGUE_MANAGER = '''"""Rebased dialogue manager (fixture)."""
from src.contracts import CONTRACTS_VERSION, EscalationReason

assert CONTRACTS_VERSION == "1.0.0"


def route(reason: EscalationReason) -> str:
    return "handoff" if reason else "answer"
'''

CONTRACTS = '''"""Locked contracts v1.0.0 (fixture)."""
CONTRACTS_VERSION = "1.0.0"
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_repo(root: Path, *, with_contracts: bool,
               importer_source: str = DIALOGUE_MANAGER) -> None:
    """A complete fake repo (every ALL_EXPECTED file present, valid
    Python, one passing test) — with or without src/contracts.py."""
    for rel in gate.ALL_EXPECTED:
        if rel == "src/contracts.py" and not with_contracts:
            continue
        if rel == "src/dialogue/dialogue_manager.py":
            _write(root / rel, importer_source)
        elif rel.endswith(".py"):
            _write(root / rel, '"""fixture module."""\nVALUE = 1\n')
        elif rel == "README.md":
            _write(root / rel, "# vn-realtime-voice-agent\n")
        elif rel == "pyproject.toml":
            _write(root / rel, '[project]\nname = "vn-realtime-voice-agent"\n')
        elif rel == ".gitignore":
            _write(root / rel, "__pycache__/\n")
    for d in gate.REQUIRED_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    _write(root / "tests" / "test_smoke.py",
           "def test_smoke():\n    assert True\n")
    if with_contracts:
        _write(root / "src" / "contracts.py", CONTRACTS)


def test_order_check_fails_when_importer_present_but_contracts_missing(tmp_path):
    _fake_repo(tmp_path, with_contracts=False)
    result = gate.check_manifest(tmp_path)
    assert result.order_violations == ["src/dialogue/dialogue_manager.py"]
    assert result.ok is False
    # The missing-contracts error is also reported as missing, but the
    # order violation is a separate, named failure.
    assert "src/contracts.py" in result.missing


def test_order_check_passes_when_contracts_added(tmp_path):
    _fake_repo(tmp_path, with_contracts=True)
    result = gate.check_manifest(tmp_path)
    assert result.order_violations == []
    assert result.ok is True


def test_full_verify_passes_with_contracts_and_fails_without(tmp_path):
    _fake_repo(tmp_path, with_contracts=True)
    assert gate.verify(tmp_path).ok is True
    # _fake_repo(with_contracts=False) only skips writing contracts.py;
    # it does not delete the file the first call created.
    (tmp_path / "src" / "contracts.py").unlink()
    assert gate.verify(tmp_path).ok is False


def test_cli_exit_codes(tmp_path):
    _fake_repo(tmp_path, with_contracts=False)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--skip-compile", "--skip-tests"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert "ORDER-VIOLATION" in proc.stdout
    assert "src/dialogue/dialogue_manager.py" in proc.stdout
    _fake_repo(tmp_path, with_contracts=True)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--skip-compile", "--skip-tests"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0


def test_import_spellings_detected():
    assert gate.imports_contracts("from src.contracts import X\n")
    assert gate.imports_contracts("import src.contracts\n")
    assert gate.imports_contracts("from src import contracts\n")
    assert gate.imports_contracts("from ..contracts import X\n")
    assert gate.imports_contracts("from .contracts import X\n")
    assert gate.imports_contracts("import src.contracts as c\n")


def test_comment_or_string_mention_is_not_an_import():
    assert not gate.imports_contracts('# from src.contracts import X\n')
    assert not gate.imports_contracts('"""see src.contracts for details"""\n')
    assert not gate.imports_contracts("x = 'from src.contracts import X'\n")
    assert not gate.imports_contracts("from src.contracts_v2 import X\n")
    assert not gate.imports_contracts("import os\n")


def test_unparseable_file_is_not_an_importer(tmp_path):
    assert not gate.imports_contracts("def broken(:\n")
    _fake_repo(tmp_path, with_contracts=False,
               importer_source="def broken(:\n")
    result = gate.check_manifest(tmp_path)
    # The syntax error is the compile check's job, not the order check's.
    assert result.order_violations == []


def test_no_importer_no_violation_even_without_contracts(tmp_path):
    _fake_repo(tmp_path, with_contracts=False,
               importer_source='"""no contracts import here."""\nVALUE = 1\n')
    result = gate.check_manifest(tmp_path)
    assert result.order_violations == []


def test_order_violations_in_json_dict(tmp_path):
    _fake_repo(tmp_path, with_contracts=False)
    d = gate.check_manifest(tmp_path).to_dict()
    assert d["order_violations"] == ["src/dialogue/dialogue_manager.py"]
    assert d["ok"] is False


def test_evidence_still_reports_gate_ok(tmp_path):
    _fake_repo(tmp_path, with_contracts=True)
    result = gate.verify(tmp_path)
    evidence = gate.collect_evidence(tmp_path, result)
    assert evidence["gate_ok"] is True
