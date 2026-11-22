"""Tests for fix_missing_data_golden — scripts/collect_data.py.

Merged from expert/systems-arch-m3 (not rewritten) and adapted to
locked contracts v1.0.0 (GC-10 reason is "customer_request").
Run:
    PYTHONPATH=. python3 -m pytest tests/test_fix_missing_data_golden.py -q

The tests run the script itself (subprocess, --seed 42) into a
temporary directory and check the regenerated data, so they verify
the script re-runs and the data matches the seed — not a checked-in
copy of the data.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "collect_data.py"

ALLOWED_REASONS = {
    "", "out_of_scope", "low_confidence", "sensitive",
    "customer_request", "repeated_clarification", "repeated_failure",
    "no_agent", "system_error",
}
ALLOWED_BENCHMARK_CLASSES = {"vendor", "independent", "forecast", "benchmark"}


def _run(out: Path, seed: int = 42) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out), "--seed", str(seed)],
        capture_output=True, text=True, cwd=REPO)


def _load(out: Path, rel: str):
    return json.loads((out / rel).read_text(encoding="utf-8"))


def test_script_regenerates_exact_counts(tmp_path):
    out = tmp_path / "data"
    result = _run(out)
    assert result.returncode == 0, result.stderr
    assert len(_load(out, "golden/golden_calls.json")["calls"]) == 12
    assert len(_load(out, "golden/golden_faq.json")["qa"]) == 4
    assert len(_load(out, "orders.json")) == 60
    assert len(_load(out, "inventory.json")) == 5
    assert len(_load(out, "appointments.json")) == 20
    assert len(_load(out, "market_benchmarks.json")["records"]) == 8
    assert len(_load(out, "vietnamese_homophones.json")["pairs"]) == 5


def test_regeneration_is_deterministic_for_seed_42(tmp_path):
    out1, out2 = tmp_path / "a" / "data", tmp_path / "b" / "data"
    assert _run(out1).returncode == 0
    assert _run(out2).returncode == 0
    for rel in ("golden/golden_calls.json", "golden/golden_faq.json",
                "orders.json", "inventory.json", "appointments.json",
                "vietnamese_homophones.json", "market_benchmarks.json"):
        assert (out1 / rel).read_bytes() == (out2 / rel).read_bytes(), rel
    # A different seed changes the synthetic orders (rng is seeded).
    out3 = tmp_path / "c" / "data"
    assert _run(out3, seed=7).returncode == 0
    assert (out1 / "orders.json").read_bytes() != (out3 / "orders.json").read_bytes()


def test_golden_calls_have_intent_slots_and_expected_decision(tmp_path):
    out = tmp_path / "data"
    assert _run(out).returncode == 0
    calls = _load(out, "golden/golden_calls.json")["calls"]
    ids = {c["id"] for c in calls}
    assert ids == {f"GC-{i:02d}" for i in range(1, 13)}
    for c in calls:
        assert c["intent"] and c["transcript"] and c["source"] == "synthetic"
        assert c["expected"] in ("answer", "handoff")
        assert c["reason"] in ALLOWED_REASONS, c
        if c["expected"] == "answer":
            assert c["reason"] == "", c
        else:
            assert c["reason"] != "", c
    # Spot checks: sensitive complaint and out-of-scope hand off,
    # customer-request handoff uses the locked contracts spelling.
    by_id = {c["id"]: c for c in calls}
    assert by_id["GC-07"]["expected"] == "handoff" and by_id["GC-07"]["reason"] == "sensitive"
    assert by_id["GC-09"]["expected"] == "handoff" and by_id["GC-09"]["reason"] == "out_of_scope"
    assert by_id["GC-10"]["reason"] == "customer_request"
    assert "user_requested" not in json.dumps(calls)
    assert by_id["GC-01"]["slots"] == {"order_code": "DH240101"}


def test_golden_faq_has_expected_chunk_and_answer(tmp_path):
    out = tmp_path / "data"
    assert _run(out).returncode == 0
    for q in _load(out, "golden/golden_faq.json")["qa"]:
        assert q["question"] and q["expected_chunk_id"] and q["answer"]
        assert q["source"] == "synthetic"


def test_market_benchmarks_have_source_and_reliability_label(tmp_path):
    out = tmp_path / "data"
    assert _run(out).returncode == 0
    records = _load(out, "market_benchmarks.json")["records"]
    for r in records:
        assert r["source"] and r["reliability"], r
        assert r["reliability_class"] in ALLOWED_BENCHMARK_CLASSES, r
    by_metric = {r["metric"]: r for r in records}
    assert by_metric["klarna_ai_containment_pct"]["reliability_class"] == "vendor"
    assert by_metric["ada_auto_resolution_pct"]["reliability_class"] == "vendor"
    assert by_metric["independent_voice_agent_multistep_pct_range"]["reliability_class"] == "independent"
    assert by_metric["vietnam_cloud_contact_center_2025_usd_m"]["reliability_class"] == "forecast"
    assert "IMARC" in by_metric["vietnam_cloud_contact_center_2025_usd_m"]["source"]
    assert "ContactBabel" in by_metric["call_abandonment_avg_pct"]["source"]
    assert "Klarna" in by_metric["klarna_ai_containment_pct"]["source"]
    assert "Ada" in by_metric["ada_auto_resolution_pct"]["source"]


def test_no_real_pii_and_every_record_has_source(tmp_path):
    out = tmp_path / "data"
    assert _run(out).returncode == 0
    orders = _load(out, "orders.json")
    for o in orders:
        assert o["source"] == "synthetic"
        assert "***" in o["phone_masked"]  # masked, never a full real number
        assert o["order_code"].startswith("DH")
    for rel in ("inventory.json", "appointments.json"):
        for rec in _load(out, rel):
            assert rec["source"] == "synthetic", (rel, rec)
    # No full 10-digit phone number anywhere in the generated data.
    import re
    for path in out.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b0\d{9}\b", text), path
    # Homophone dictionary carries its own source + license.
    homo = _load(out, "vietnamese_homophones.json")
    assert homo["source"] and homo["license"]
