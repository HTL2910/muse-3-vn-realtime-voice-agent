#!/usr/bin/env python3
"""Post-merge manifest gate — fix_merge_pipeline_gate.

Branch: fix/fix_gate_order_check (extends fix_merge_pipeline_gate;
 same script, plus the order check that debate round #3 required).
Order check: a module that imports from src.contracts only counts
as merged when src/contracts.py is present in the same manifest —
rebased modules (dialogue_manager proved it by test) fail-closed
on a missing contracts, so merging them first would turn a correct
patch into a repo-wide import error.
Repo: vn-realtime-voice-agent.

Problem it closes: the council declared branches "merged into main"
while main was in fact empty (only README.md). Tests that passed on a
private branch then looked green while main could not run anything —
the same lost-fix-on-merge failure seen in the multi-account project.

What this gate does, in order, on a checkout of ``main``:
  1. Manifest check — every approach_01..21 target file, plus the
     locked ``src/contracts.py`` and repo scaffolding (README.md,
     pyproject.toml, .gitignore), must exist. A missing target file
     means the merge did not happen, whatever the merge message said.
  1b. Order check — every .py under src/ that imports from
     ``src.contracts`` (``from src.contracts import ...``,
     ``import src.contracts``, ``from src import contracts``, or a
     relative ``from ..contracts import ...``) only counts as
     merged when ``src/contracts.py`` is present in the same
     manifest. A rebased module merged before contracts is an
     ORDER-VIOLATION and fails the gate (exit 1), even if every
     other check passes — the module would fail at import time.
  2. Hash check — when a frozen manifest (``manifest.json``, written
     with ``--write-manifest`` from the approved commit) is supplied,
     every listed file's SHA-256 must match. A silent overwrite or a
     file replaced by a stub is caught, not just an absence.
  3. Compile check — ``python -m compileall src`` must succeed.
  4. Test check — ``python -m pytest -q`` must pass (exit 0).
  5. Evidence publication — ``--publish-evidence evidence.json``
     writes the 3 evidences audit round #3 requires on ONE commit:
     (a) commit hash (``git rev-parse HEAD``), (b) ``git ls-files``
     + SHA-256 per file, (c) the pytest log on that exact commit.
     Evidence is COMPLETE only when all three are present; audit 3
     is blocked (not merely failed) while any one is missing.

Exit code is 0 only if ALL checks pass. Any missing file, hash
mismatch, compile error or red pytest run makes the merge count as
"not happened" (exit 1). Extra files never fail the gate — other
experts may add files; only the expected set is mandatory.

Usage (CI post-merge, from the repo root):
    python3 scripts/verify_main_manifest.py
    python3 scripts/verify_main_manifest.py --root /path/to/checkout
    python3 scripts/verify_main_manifest.py --manifest manifest.json
    python3 scripts/verify_main_manifest.py --write-manifest manifest.json
    # fast manifest-only check (no compile / no pytest):
    python3 scripts/verify_main_manifest.py --skip-compile --skip-tests
    # publish the 3 audit evidences for this exact commit:
    python3 scripts/verify_main_manifest.py --publish-evidence evidence.json
    python3 scripts/verify_main_manifest.py --publish-evidence evidence.json --require-evidence

Only the standard library is used. ``git ls-files`` is used when the
checkout is a git repo; otherwise the filesystem is walked (excluding
.git, __pycache__, .venv, .pytest_cache).
"""
from __future__ import annotations

import argparse
import ast
import compileall
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ------------------------------------------------------------------
# Expected files, locked by the council DEDUP (approach_01..21).
# Keys are approach ids; values are repo-relative paths.
# ------------------------------------------------------------------
EXPECTED_FILES: dict[str, str] = {
    "approach_01": "src/telephony/media_gateway.py",
    "approach_02": "src/realtime/orchestrator.py",
    "approach_03": "src/voice/vietnamese_normalizer.py",
    "approach_04": "src/dialogue/dialogue_manager.py",
    "approach_05": "src/grounding/tool_gateway.py",
    "approach_06": "src/grounding/grounded_answer.py",
    "approach_07": "src/gating/confidence_gate.py",
    "approach_08": "src/dialog/policy_engine.py",
    "approach_09": "src/handoff/handoff_service.py",
    "approach_10": "src/handoff/context_package.py",
    "approach_11": "src/callback/callback_ticket_service.py",
    "approach_12": "src/queueing/capacity_planner.py",
    "approach_13": "src/knowledge/ingestion_pipeline.py",
    "approach_14": "src/integrations/sme_onboarding_hub.py",
    "approach_15": "src/optimization/model_cascade.py",
    "approach_16": "src/realtime/resilience_controller.py",
    "approach_17": "src/platform/scaling.py",
    "approach_18": "src/security/voice_security_policy.py",
    "approach_19": "src/observability/metrics_dashboard.py",
    "approach_20": "src/eval/simulation_harness.py",
    "approach_21": "scripts/collect_data.py",
}

# Files that are not one approach but are mandatory for the repo to
# be a repo at all (locked contracts + scaffolding).
REQUIRED_CORE_FILES: list[str] = [
    "src/contracts.py",
    "README.md",
    "pyproject.toml",
    ".gitignore",
]

# Directories from the approved COUNCIL_DEDUP tree. A missing
# directory is reported, but it is the files above that fail the gate;
# an empty directory alone is a warning, not a failure, because git
# does not track empty directories.
REQUIRED_DIRS: list[str] = [
    "src/telephony", "src/realtime", "src/voice", "src/dialogue",
    "src/nlu", "src/grounding", "src/gating", "src/dialog",
    "src/handoff", "src/callback", "src/queueing", "src/knowledge",
    "src/integrations", "src/optimization", "src/platform",
    "src/security", "src/observability", "src/eval", "src/api",
    "src/web", "scripts", "data", "data/golden", "tests", "docs",
    "docker",
]

EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", ".pytest_cache",
                ".mypy_cache", "node_modules"}

# The file every rebased module imports from. The order check
# (check_order) requires it to be present in the same manifest
# as any module that imports it.
CONTRACTS_PATH = "src/contracts.py"


def _clean_key(key: str) -> str:
    return key.strip()


# Normalise the table above (guards against a stray space in a key).
EXPECTED_FILES = {_clean_key(k): v for k, v in EXPECTED_FILES.items()}

ALL_EXPECTED: list[str] = sorted(
    list(EXPECTED_FILES.values()) + REQUIRED_CORE_FILES)


@dataclass
class VerificationResult:
    ok: bool
    missing: list[str] = field(default_factory=list)
    order_violations: list[str] = field(default_factory=list)
    hash_mismatches: list[str] = field(default_factory=list)
    empty_files: list[str] = field(default_factory=list)
    missing_dirs: list[str] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)
    compile_ok: bool | None = None
    compile_errors: list[str] = field(default_factory=list)
    tests_ok: bool | None = None
    tests_output: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "missing": self.missing,
            "order_violations": self.order_violations,
            "hash_mismatches": self.hash_mismatches,
            "empty_files": self.empty_files,
            "missing_dirs": self.missing_dirs,
            "extra_files": self.extra_files,
            "compile_ok": self.compile_ok,
            "compile_errors": self.compile_errors,
            "tests_ok": self.tests_ok,
            "tests_output": self.tests_output,
        }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def list_files_git(root: Path) -> list[str] | None:
    """Return `git ls-files` output, or None if this is not a git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line.strip()]


def list_files_walk(root: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        out.append(path.relative_to(root).as_posix())
    return out


def list_repo_files(root: Path) -> list[str]:
    """Prefer git ls-files (the frozen, committed truth); fall back to walk."""
    git_files = list_files_git(root)
    return git_files if git_files is not None else list_files_walk(root)


def commit_hash(root: Path) -> str | None:
    """Commit hash of the checkout, or None if not a git repo / no commit."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def collect_evidence(root: Path, result: VerificationResult) -> dict:
    """The 3 evidences audit round #3 requires, on ONE commit.

    Returns a dict with ``complete`` True only when (a) a commit hash
    exists, (b) the file list (git ls-files preferred) is non-empty
    with a SHA-256 per file, and (c) pytest actually ran on this
    checkout (tests_ok is not None) with its log attached.
    """
    files = list_repo_files(root)
    hashes: dict[str, str] = {}
    for rel in files:
        full = root / rel
        if full.is_file():
            hashes[rel] = sha256_file(full)
    evidence = {
        "commit_hash": commit_hash(root),
        "file_source": "git ls-files" if list_files_git(root) is not None else "filesystem walk",
        "files": hashes,
        "tests_ok": result.tests_ok,
        "pytest_log": result.tests_output,
        "gate_ok": result.ok,
    }
    evidence["complete"] = bool(
        evidence["commit_hash"] and hashes and result.tests_ok is not None)
    return evidence


def write_manifest(root: Path, manifest_path: Path) -> dict:
    """Freeze the current checkout: path -> sha256 for every repo file."""
    files = list_repo_files(root)
    manifest = {
        "root": str(root),
        "files": {},
    }
    for rel in files:
        full = root / rel
        if full.is_file():
            manifest["files"][rel] = sha256_file(full)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    return manifest


def load_manifest(manifest_path: Path) -> dict:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "files" in data:
        return data["files"]
    if isinstance(data, dict):
        return data
    raise ValueError(f"unrecognised manifest format in {manifest_path}")


def imports_contracts(source: str) -> bool:
    """True iff this .py source imports from src.contracts.

    AST-based, so a mention in a comment or a string literal does
    not count. Covers the single locked import style plus its
    equivalent spellings: ``from src.contracts import ...``,
    ``import src.contracts``, ``from src import contracts``, and a
    relative import (``from .contracts import ...`` /
    ``from ..contracts import ...``) from a module under src/.
    A file that does not parse is NOT an importer here — the compile
    check reports its syntax error separately.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "src.contracts":
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "src.contracts":
                return True
            if node.module == "src" and any(
                    alias.name == "contracts" for alias in node.names):
                return True
            if node.level > 0 and node.module == "contracts":
                return True
    return False


def find_contracts_importers(root: Path,
                             actual_files: list[str]) -> list[str]:
    """Repo-relative .py files under src/ that import src.contracts.

    contracts.py itself is never an importer (it defines the module).
    Only files actually present in the checkout are scanned.
    """
    importers: list[str] = []
    for rel in actual_files:
        if rel == CONTRACTS_PATH:
            continue
        if not rel.startswith("src/") or not rel.endswith(".py"):
            continue
        full = root / rel
        if not full.is_file():
            continue
        try:
            source = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if imports_contracts(source):
            importers.append(rel)
    return sorted(importers)


def check_order(root: Path, actual_files: list[str]) -> list[str]:
    """Order violations: importers of src.contracts with no contracts
    in the same manifest. Returns the violating module paths (empty
    when contracts.py is present, or when nothing imports it)."""
    if CONTRACTS_PATH in set(actual_files):
        return []
    return find_contracts_importers(root, actual_files)


def check_manifest(root: Path, expected_hashes: dict[str, str] | None = None,
                   actual_files: list[str] | None = None) -> VerificationResult:
    """Manifest-only check: existence, non-emptiness, hashes, dirs."""
    actual = actual_files if actual_files is not None else list_repo_files(root)
    actual_set = set(actual)
    missing = [p for p in ALL_EXPECTED if p not in actual_set]
    empty: list[str] = []
    for rel in ALL_EXPECTED:
        full = root / rel
        if full.is_file() and full.stat().st_size == 0:
            empty.append(rel)
    mismatches: list[str] = []
    if expected_hashes:
        for rel, expected in expected_hashes.items():
            full = root / rel
            if not full.is_file():
                continue  # already reported as missing
            if sha256_file(full) != expected:
                mismatches.append(rel)
    missing_dirs = [d for d in REQUIRED_DIRS if not (root / d).is_dir()]
    extra = sorted(actual_set - set(ALL_EXPECTED))
    order_violations = check_order(root, actual)
    ok = not missing and not mismatches and not empty and not order_violations
    return VerificationResult(
        ok=ok, missing=missing, hash_mismatches=mismatches,
        empty_files=empty, missing_dirs=missing_dirs, extra_files=extra,
        order_violations=order_violations)


def run_compile(root: Path) -> tuple[bool, list[str]]:
    """Compile every .py under src/. Returns (ok, errors)."""
    src = root / "src"
    if not src.is_dir():
        return False, ["src/ directory missing"]
    # compileall returns False on any failure; capture via quiet=False
    # is noisy, so compile file-by-file for a clean error list.
    errors: list[str] = []
    py_files = sorted(src.rglob("*.py"))
    if not py_files:
        return False, ["no .py files under src/"]
    for path in py_files:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except Exception as exc:  # SyntaxError, UnicodeDecodeError, ...
            errors.append(f"{path.relative_to(root)}: {exc}")
    return (not errors), errors


def run_tests(root: Path) -> tuple[bool, str]:
    """Run `python -m pytest -q` in root. Returns (ok, combined output)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(root), capture_output=True, text=True, timeout=600)
    except FileNotFoundError as exc:
        return False, f"pytest not runnable: {exc}"
    except subprocess.TimeoutExpired:
        return False, "pytest timed out after 600s"
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output


def verify(root: Path, manifest_path: Path | None = None,
           skip_compile: bool = False, skip_tests: bool = False) -> VerificationResult:
    expected_hashes = load_manifest(manifest_path) if manifest_path else None
    result = check_manifest(root, expected_hashes)
    if skip_compile:
        result.compile_ok = None
    else:
        ok, errors = run_compile(root)
        result.compile_ok = ok
        result.compile_errors = errors
        if not ok:
            result.ok = False
    if skip_tests:
        result.tests_ok = None
    else:
        ok, output = run_tests(root)
        result.tests_ok = ok
        result.tests_output = output
        if not ok:
            result.ok = False
    return result


def report(result: VerificationResult) -> str:
    lines: list[str] = []
    lines.append("verify_main_manifest: "
                 + ("PASS — merge verified" if result.ok else "FAIL — merge NOT verified"))
    if result.missing:
        lines.append(f"missing files ({len(result.missing)}):")
        for p in result.missing:
            lines.append(f"  MISSING {p}")
    if result.order_violations:
        lines.append(f"order violations ({len(result.order_violations)}): "
                     "module(s) import src.contracts but src/contracts.py "
                     "is not in this manifest — merge contracts FIRST:")
        for p in result.order_violations:
            lines.append(f"  ORDER-VIOLATION {p} imports src.contracts, "
                         "src/contracts.py missing")
    if result.hash_mismatches:
        lines.append(f"hash mismatches ({len(result.hash_mismatches)}):")
        for p in result.hash_mismatches:
            lines.append(f"  HASH-MISMATCH {p}")
    if result.empty_files:
        lines.append(f"empty files ({len(result.empty_files)}):")
        for p in result.empty_files:
            lines.append(f"  EMPTY {p}")
    if result.missing_dirs:
        lines.append(f"missing dirs (warning): {', '.join(result.missing_dirs)}")
    if result.compile_ok is False:
        lines.append("compile FAILED:")
        for e in result.compile_errors:
            lines.append(f"  {e}")
    elif result.compile_ok is True:
        lines.append("compile: ok")
    if result.tests_ok is False:
        lines.append("pytest FAILED (see output below):")
        lines.append(result.tests_output)
    elif result.tests_ok is True:
        lines.append("pytest: ok")
    if result.ok:
        lines.append(f"extra files (ignored): {len(result.extra_files)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo checkout to verify")
    parser.add_argument("--manifest", default=None,
                        help="frozen manifest.json to check hashes against")
    parser.add_argument("--write-manifest", default=None,
                        help="write a frozen manifest.json and exit 0")
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--publish-evidence", default=None,
                        help="write the 3 audit evidences (commit hash + "
                             "ls-files/hashes + pytest log) to this JSON file")
    parser.add_argument("--require-evidence", action="store_true",
                        help="exit 1 when the published evidence is incomplete "
                             "(no commit hash, no files, or pytest did not run)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.write_manifest:
        manifest = write_manifest(root, Path(args.write_manifest))
        print(f"wrote manifest with {len(manifest['files'])} files "
              f"to {args.write_manifest}")
        return 0

    manifest_path = Path(args.manifest) if args.manifest else None
    result = verify(root, manifest_path,
                    skip_compile=args.skip_compile, skip_tests=args.skip_tests)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(report(result))
    if args.publish_evidence:
        evidence = collect_evidence(root, result)
        out = Path(args.publish_evidence)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(f"evidence: commit={evidence['commit_hash']} "
              f"files={len(evidence['files'])} "
              f"tests_ok={evidence['tests_ok']} "
              f"complete={evidence['complete']} -> {args.publish_evidence}")
        if args.require_evidence and not evidence["complete"]:
            print("evidence INCOMPLETE — audit round #3 is blocked, "
                  "not merely failed: publish all 3 evidences on one commit.")
            return 1
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
