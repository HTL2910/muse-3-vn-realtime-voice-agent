"""Feasibility follow-ups: gate reason breakdown, corrected normalizer WER
proxy (standard references, norm-vs-norm), callback wait boundary, and a
clean subprocess reproduction of the harness as-is import failure.

See feasibility_run.py for the shim disclosure and the vendor-number ban.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import src.contracts as contracts  # noqa: E402

# --- SHIM (in-memory only) ---
contracts.LLM_BUDGET_MS = contracts.LLM_FIRST_TOKEN_MS

import random  # noqa: E402
from src.gating.confidence_gate import ConfidenceGate, Signals  # noqa: E402
from src.queueing.capacity_planner import CapacityPlanner  # noqa: E402
from src.voice.vietnamese_normalizer import VietnameseNormalizer, word_error_rate  # noqa: E402

OUT: dict = {}

# --- 1. Harness as-is import failure, reproduced in a subprocess ----------
code = (
    "import sys; sys.path.insert(0, %r); "
    "import src.eval.simulation_harness" % str(REPO)
)
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
OUT["harness_import_as_is_subprocess"] = {
    "returncode": r.returncode,
    "stderr_tail": r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "",
}
print("1 as-is import rc=%d: %s" % (r.returncode, OUT["harness_import_as_is_subprocess"]["stderr_tail"]))

# --- 2. Gate fuzz with reason breakdown -------------------------------------
rng = random.Random(11)
gate = ConfidenceGate()
N = 20_000
reasons = Counter()
decisions = Counter()
# "Human-answerable": evidence exists, verifier high, intent/entity solid.
# An escalation here is unnecessary (the human would have answered).
human_answerable = 0
human_answerable_escalated = 0
human_answerable_by_reason = Counter()
for _ in range(N):
    noisy = rng.random() < 0.5
    if noisy:
        s = Signals(asr_confidence=rng.betavariate(2, 3),
                    intent_confidence_raw=rng.betavariate(3, 3),
                    entity_match=rng.betavariate(3, 3),
                    evidence_completeness=rng.betavariate(4, 3),
                    evidence_freshness=rng.betavariate(4, 3),
                    verifier_score=rng.betavariate(4, 3),
                    has_evidence=rng.random() < 0.70)
    else:
        s = Signals(asr_confidence=rng.betavariate(9, 1),
                    intent_confidence_raw=rng.betavariate(8, 2),
                    entity_match=rng.betavariate(8, 2),
                    evidence_completeness=rng.betavariate(8, 2),
                    evidence_freshness=rng.betavariate(8, 2),
                    verifier_score=rng.betavariate(9, 1),
                    has_evidence=rng.random() < 0.95)
    d = gate.decide(s, intent="order_tracking")
    decisions[d.decision.value] += 1
    reasons[d.reason] += 1
    answerable = (s.has_evidence and s.verifier_score >= 0.9
                  and s.intent_confidence_raw >= 0.8 and s.entity_match >= 0.8
                  and s.evidence_completeness >= 0.8)
    if answerable:
        human_answerable += 1
        if d.decision.value == "escalate":
            human_answerable_escalated += 1
            human_answerable_by_reason[d.reason] += 1
OUT["gate_fuzz_reasons"] = {
    "n": N, "decisions": dict(decisions), "reasons": dict(reasons),
    "human_answerable": human_answerable,
    "human_answerable_escalated": human_answerable_escalated,
    "human_answerable_escalation_rate":
        round(human_answerable_escalated / human_answerable, 4) if human_answerable else None,
    "human_answerable_escalated_by_reason": dict(human_answerable_by_reason),
}
print("2 gate reasons:", json.dumps(OUT["gate_fuzz_reasons"], ensure_ascii=False))

# --- 3. Normalizer WER proxy, corrected --------------------------------------
# References are STANDARD Vietnamese; hypotheses are the degraded forms.
# Both sides go through normalize() before WER, because canonicalisation
# (lowercase, diacritic handling) is the normalizer's job — a raw
# case/diacritic-sensitive WER penalises it for doing its job.
norm = VietnameseNormalizer()
pairs = [
    ("Tra cứu đơn hàng DH100001 giúp tôi", "tra cuu don hang DH100001 giup toi", "no_diacritics"),
    ("Đơn DH100001 của tôi tới đâu rồi", "Đơn DH100001 của tui tới đâu rồi dạ", "south"),
    ("Đơn DH100001 của mình sao chưa tới nơi", "Đơn DH100001 của miềng răng chưa tới nơi", "central"),
    ("Tra cứu đơn hàng DH100001 giúp tôi", "đơn DH100001 giúp tôi", "noisy_drop"),
    ("Tra cứu đơn hàng DH100001 giúp tôi", "Tra cứu đơn hàng DH100001 giúp tôi", "clean"),
]
rows = []
for ref, hyp, kind in pairs:
    rows.append({"kind": kind,
                 "wer_raw_vs_ref": round(word_error_rate(ref, hyp), 3),
                 "wer_norm_vs_norm": round(word_error_rate(norm.normalize(ref), norm.normalize(hyp)), 3),
                 "norm_hyp": norm.normalize(hyp)})
OUT["normalizer_wer_proxy_corrected"] = rows
for row in rows:
    print("3 wer %-14s raw=%.3f norm-vs-norm=%.3f | %s"
          % (row["kind"], row["wer_raw_vs_ref"], row["wer_norm_vs_norm"], row["norm_hyp"]))

# --- 4. Callback wait boundary (Erlang-A) ------------------------------------
planner = CapacityPlanner()
boundary = {}
for c in (3, 5, 8):
    for cont in (0.0, 0.30):
        lam60 = lam90 = None
        lam = 0.1
        while lam <= 6.0:
            w = planner.metrics(lam, 3.0, c, containment=cont).expected_wait_seconds
            if lam60 is None and w >= 60.0:
                lam60 = round(lam, 2)
            if lam90 is None and w >= 90.0:
                lam90 = round(lam, 2)
            lam += 0.05
        boundary[f"c{c}_cont{cont}"] = {"lambda_per_min_wait_ge_60s": lam60,
                                        "calls_per_hour": round(lam60 * 60) if lam60 else None,
                                        "lambda_per_min_wait_ge_90s": lam90}
OUT["callback_wait_boundary"] = boundary
print("4 callback boundary:", json.dumps(boundary))

(Path(__file__).resolve().parents[2] / "feasibility_results2.json").write_text(
    json.dumps(OUT, indent=2, ensure_ascii=False), encoding="utf-8")
print("WROTE feasibility_results2.json")
