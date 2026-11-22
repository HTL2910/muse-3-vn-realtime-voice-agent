"""Tests for fix_missing_repo_main_empty — scripts/verify_main_manifest.py.

Run from the repo root (or any directory; the script is loaded by path):
    python3 -m pytest tests/test_fix_missing_repo_main_empty.py -q

The gate itself is exercised on synthetic checkouts in tmp_path, so
these tests do NOT depend on the real main repo existing, and they do
not run the real pytest suite except in one explicitly mocked case.
Negative controls are mandatory here: a gate that cannot fail is
worse than no gate (it creates the false-green merge the bug is about).
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

# Every expected file gets a tiny valid stub, so a "complete" fake
# checkout compiles and would pass pytest (with a trivial test file).
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


def test_expected_table_covers_all_approaches_01_to_21():
    ids = sorted(gate.EXPECTED_FILES)
    assert ids == [f"approach_{i:02d}" for i in range(1, 22)]
    assert len(set(gate.EXPECTED_FILES.values())) == 21
    assert "src/contracts.py" in gate.REQUIRED_CORE_FILES


def test_complete_repo_passes_manifest_check(tmp_path):
    make_complete_repo(tmp_path)
    result = gate.check_manifest(tmp_path)
    assert result.ok, result
    assert result.missing == []
    assert result.empty_files == []


def test_empty_repo_fails_with_all_files_missing(tmp_path):
    # This is the exact state main was in at audit time: only README.md.
    (tmp_path / "README.md").write_text("# repo\n", encoding="utf-8")
    result = gate.check_manifest(tmp_path)
    assert not result.ok
    assert "src/contracts.py" in result.missing
    assert "src/telephony/media_gateway.py" in result.missing
    assert "scripts/collect_data.py" in result.missing
    assert len(result.missing) == len(gate.ALL_EXPECTED) - 1  # README present


def test_one_missing_file_fails(tmp_path):
    make_complete_repo(tmp_path)
    (tmp_path / "src/telephony/media_gateway.py").unlink()
    result = gate.check_manifest(tmp_path)
    assert not result.ok
    assert result.missing == ["src/telephony/media_gateway.py"]


def test_empty_file_fails(tmp_path):
    make_complete_repo(tmp_path)
    (tmp_path / "src/contracts.py").write_text("", encoding="utf-8")
    result = gate.check_manifest(tmp_path)
    assert not result.ok
    assert result.empty_files == ["src/contracts.py"]


def test_extra_file_does_not_fail(tmp_path):
    make_complete_repo(tmp_path)
    (tmp_path / "src/telephony/extra_experiment.py").write_text(STUB)
    result = gate.check_manifest(tmp_path)
    assert result.ok
    assert "src/telephony/extra_experiment.py" in result.extra_files


def test_write_manifest_then_hash_mismatch_fails(tmp_path):
    make_complete_repo(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    gate.write_manifest(tmp_path, manifest_path)
    # Tamper with one file after freezing (stub replaced by other content).
    (tmp_path / "src/contracts.py").write_text("x = 2\n", encoding="utf-8")
    hashes = gate.load_manifest(manifest_path)
    result = gate.check_manifest(tmp_path, expected_hashes=hashes)
    assert not result.ok
    assert result.hash_mismatches == ["src/contracts.py"]
    # And the untampered manifest passes.
    (tmp_path / "src/contracts.py").write_text(STUB, encoding="utf-8")
    assert gate.check_manifest(tmp_path, expected_hashes=hashes).ok


def test_compile_failure_is_caught(tmp_path):
    make_complete_repo(tmp_path)
    (tmp_path / "src/gating/confidence_gate.py").write_text(
        "def broken(:\n", encoding="utf-8")
    ok, errors = gate.run_compile(tmp_path)
    assert not ok
    assert any("confidence_gate.py" in e for e in errors)
    result = gate.verify(tmp_path, skip_tests=True)
    assert not result.ok and result.compile_ok is False


def test_verify_fails_when_pytest_fails(tmp_path, monkeypatch):
    make_complete_repo(tmp_path)
    # Mock the test runner: a red pytest must fail the gate even when
    # the manifest and compile checks pass.
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
    # Complete repo, manifest-only: exit 0.
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--skip-compile", "--skip-tests"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout
    assert "PASS" in proc.stdout
    # Remove one file: exit 1, names the file.
    (tmp_path / "src/eval/simulation_harness.py").unlink()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--skip-compile", "--skip-tests"],
        capture_output=True, text=True)
    assert proc.returncode == 1
    assert "src/eval/simulation_harness.py" in proc.stdout


def test_cli_write_manifest_roundtrip(tmp_path):
    make_complete_repo(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--write-manifest", str(manifest_path)],
        capture_output=True, text=True)
    assert proc.returncode == 0
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["files"]["src/contracts.py"] == gate.sha256_file(
        tmp_path / "src/contracts.py")
    # Checking against the frozen manifest passes.
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--manifest", str(manifest_path),
         "--skip-compile", "--skip-tests"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout
