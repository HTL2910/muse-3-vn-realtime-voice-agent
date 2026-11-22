"""Tests for fix_merge_pipeline_gate — scripts/verify_main_manifest.py.

Supersedes tests/test_fix_missing_repo_main_empty.py: same gate
(12 earlier tests, kept here in condensed form) plus the new
3-evidence publication that audit round #3 requires before it opens:
commit hash + git ls-files/SHA-256 per file + pytest log, on ONE
commit. Evidence is COMPLETE only when all three are present.

Run:
    python3 -m pytest tests/test_fix_merge_pipeline_gate.py -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_main_manifest.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("verify_main_manifest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations via sys.modules[__name__];
    # register the module BEFORE exec_module or @dataclass fails.
    sys.modules["verify_main_manifest"] = module
    spec.loader.exec_module(module)
    return module


gate = load_gate()
STUB = "x = 1\n"


def make_complete_repo(root: Path) -> Path:
    for rel in gate.ALL_EXPECTED:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".py"):
            path.write_text(STUB, encoding="utf-8")
        elif rel == "pyproject.toml":
            path.write_text('[project]\nname = "vn-realtime-voice-agent"\n',
                            encoding="utf-8")
        elif rel == "README.md":
            path.write_text("# vn-realtime-voice-agent\n", encoding="utf-8")
        elif rel == ".gitignore":
            path.write_text("__pycache__/\n", encoding="utf-8")
        else:
            path.write_text("stub\n", encoding="utf-8")
    for d in gate.REQUIRED_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def make_git_repo(root: Path) -> str:
    make_complete_repo(root)
    assert _git(root, "init", "-q").returncode == 0
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "commit", "-qm", "init").returncode == 0
    return _git(root, "rev-parse", "HEAD").stdout.strip()


# --- gate core (condensed from the earlier 12-test file) ---------------

def test_expected_table_covers_all_approaches_01_to_21():
    assert sorted(gate.EXPECTED_FILES) == [f"approach_{i:02d}" for i in range(1, 22)]
    assert len(set(gate.EXPECTED_FILES.values())) == 21
    assert "src/contracts.py" in gate.REQUIRED_CORE_FILES


def test_complete_repo_passes_and_empty_repo_fails(tmp_path):
    make_complete_repo(tmp_path)
    assert gate.check_manifest(tmp_path).ok
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "README.md").write_text("# repo\n", encoding="utf-8")
    result = gate.check_manifest(empty)
    assert not result.ok
    assert "src/contracts.py" in result.missing
    assert len(result.missing) == len(gate.ALL_EXPECTED) - 1


def test_one_missing_file_and_hash_mismatch_fail(tmp_path):
    make_complete_repo(tmp_path)
    (tmp_path / "src/telephony/media_gateway.py").unlink()
    result = gate.check_manifest(tmp_path)
    assert not result.ok and result.missing == ["src/telephony/media_gateway.py"]
    make_complete_repo(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    gate.write_manifest(tmp_path, manifest_path)
    (tmp_path / "src/contracts.py").write_text("x = 2\n", encoding="utf-8")
    hashes = gate.load_manifest(manifest_path)
    result = gate.check_manifest(tmp_path, expected_hashes=hashes)
    assert not result.ok and result.hash_mismatches == ["src/contracts.py"]


def test_compile_failure_and_red_pytest_fail_gate(tmp_path, monkeypatch):
    make_complete_repo(tmp_path)
    (tmp_path / "src/gating/confidence_gate.py").write_text("def broken(:\n")
    ok, errors = gate.run_compile(tmp_path)
    assert not ok and any("confidence_gate.py" in e for e in errors)
    monkeypatch.setattr(gate, "run_tests", lambda root: (False, "1 failed"))
    result = gate.verify(tmp_path)
    assert not result.ok and result.tests_ok is False


def test_verify_passes_when_all_checks_pass(tmp_path, monkeypatch):
    make_complete_repo(tmp_path)
    monkeypatch.setattr(gate, "run_tests", lambda root: (True, "1 passed"))
    result = gate.verify(tmp_path)
    assert result.ok and result.compile_ok is True and result.tests_ok is True


def test_cli_exit_codes(tmp_path):
    make_complete_repo(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--skip-compile", "--skip-tests"], capture_output=True, text=True)
    assert proc.returncode == 0 and "PASS" in proc.stdout
    (tmp_path / "src/eval/simulation_harness.py").unlink()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--skip-compile", "--skip-tests"], capture_output=True, text=True)
    assert proc.returncode == 1
    assert "src/eval/simulation_harness.py" in proc.stdout


# --- 3-evidence publication (new in this fix) --------------------------

def test_evidence_complete_in_a_committed_git_repo(tmp_path, monkeypatch):
    commit = make_git_repo(tmp_path)
    monkeypatch.setattr(gate, "run_tests", lambda root: (True, "1 passed"))
    result = gate.verify(tmp_path)
    assert result.ok
    evidence = gate.collect_evidence(tmp_path, result)
    assert evidence["commit_hash"] == commit
    assert evidence["file_source"] == "git ls-files"
    assert evidence["files"]["src/contracts.py"] == gate.sha256_file(
        tmp_path / "src/contracts.py")
    assert evidence["tests_ok"] is True
    assert "1 passed" in evidence["pytest_log"]
    assert evidence["complete"] is True


def test_evidence_incomplete_without_a_commit(tmp_path, monkeypatch):
    make_complete_repo(tmp_path)  # no .git at all: the audit #2 state
    monkeypatch.setattr(gate, "run_tests", lambda root: (True, "1 passed"))
    result = gate.verify(tmp_path)
    evidence = gate.collect_evidence(tmp_path, result)
    assert evidence["commit_hash"] is None
    assert evidence["complete"] is False


def test_evidence_incomplete_when_pytest_did_not_run(tmp_path, monkeypatch):
    make_git_repo(tmp_path)
    result = gate.verify(tmp_path, skip_tests=True)
    evidence = gate.collect_evidence(tmp_path, result)
    assert evidence["tests_ok"] is None
    assert evidence["complete"] is False


def test_cli_publish_evidence_and_require_evidence(tmp_path, monkeypatch):
    make_git_repo(tmp_path)
    monkeypatch.setattr(gate, "run_tests", lambda root: (True, "1 passed"))
    out = tmp_path / "evidence.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--publish-evidence", str(out), "--require-evidence"],
        capture_output=True, text=True)
    # verify() inside the CLI runs the real pytest on the fake repo,
    # which has no tests/ -> pytest exits 5, so the gate itself fails;
    # but the EVIDENCE is complete (commit + files + a pytest log
    # that ran) — completeness and gate_ok are separate fields, and
    # the exit code 1 here comes from the gate, not the evidence.
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["commit_hash"]
    assert data["files"]
    assert data["complete"] is True
    assert data["gate_ok"] is False
    assert data["tests_ok"] is False
    assert proc.returncode == 1
    assert "evidence" in proc.stdout.lower()


def test_cli_require_evidence_blocks_when_no_commit(tmp_path):
    make_complete_repo(tmp_path)
    out = tmp_path / "evidence.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--skip-compile", "--skip-tests",
         "--publish-evidence", str(out), "--require-evidence"],
        capture_output=True, text=True)
    assert proc.returncode == 1
    assert "INCOMPLETE" in proc.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["commit_hash"] is None and data["complete"] is False
