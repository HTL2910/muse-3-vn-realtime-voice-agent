"""Tests for fix/fix_rebase_remaining_algo_ml.

Verifies the rebase of the 5 remaining algo-ml modules to
src/contracts.py v1.0.0 (orchestrator was already rebased in
fix_rebase_algo_ml_to_contracts, 16 passed — not redone here).

Part A (always runs): the target file,
src/voice/vietnamese_normalizer.py — version anchor, no mirrored
constants in source, behaviour regression sample.
Part B (importorskip): the other 4 modules' contract binding —
they are verified here on the VM where the whole branch is
staged, and skipped (not failed) on a checkout where they have
not landed yet, so this test never blocks their own merge.
The full original suites (16 + 13 + 16 + 13 + 14 tests) run
separately in this branch and must all stay green.
"""

import inspect
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from src.contracts import CONTRACTS_VERSION, EscalationReason  # noqa: E402
from src.voice.vietnamese_normalizer import (  # noqa: E402
    CONTRACTS_VERSION as NORMALIZER_CONTRACTS_VERSION,
)
import src.voice.vietnamese_normalizer as normalizer_mod  # noqa: E402
from src.voice.vietnamese_normalizer import (  # noqa: E402
    HOMOPHONES,
    VietnameseNormalizer,
    fuzzy_match,
    normalize_phone,
    normalize_text,
    parse_spoken_order_code,
    phonetic_key,
    strip_diacritics,
)

PRODUCTS = ["áo sơ mi trắng", "áo thun đen", "giày thể thao", "túi xách da", "đồng hồ nam"]


# --- Part A: normalizer rebase ----------------------------------------------

def test_contracts_version_anchor_is_1_0_0():
    assert CONTRACTS_VERSION == "1.0.0"
    assert NORMALIZER_CONTRACTS_VERSION == CONTRACTS_VERSION


def test_no_mirrored_contract_constants_in_normalizer_source():
    # The pre-rebase grep found zero mirrors; this test pins that:
    # no literal MAX_CLARIFICATIONS, no literal escalation reason,
    # no literal reason-set, no old user_requested name anywhere
    # in the module source.
    source = inspect.getsource(normalizer_mod)
    for literal in (
        "MAX_CLARIFICATIONS = 1",
        "MAX_CLARIFICATIONS=1",
        '"out_of_scope"',
        '"low_confidence"',
        '"sensitive"',
        '"customer_request"',
        '"repeated_clarification"',
        '"repeated_failure"',
        "user_requested",
        "ESCALATION_REASONS = frozenset",
    ):
        assert literal not in source, f"mirrored literal still present: {literal}"


def test_normalizer_refuses_wrong_contracts_version(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).resolve().parents[1] / "src", root / "src")
    (root / "src" / "contracts.py").write_text(
        'CONTRACTS_VERSION = "9.9.9"\n'
    )
    proc = subprocess.run(
        [sys.executable, "-c", "import src.voice.vietnamese_normalizer"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode != 0
    assert "1.0.0" in proc.stderr


# --- Part A: behaviour regression sample (full suite runs separately) --------

def test_normalize_text_regression():
    assert normalize_text("ừm à đơn hàng của tôi đâu rồi") == "đơn hàng của tôi đâu rồi"
    assert normalize_text("don hang cua toi dau roi") == "đơn hàng của tôi đâu rồi"
    assert normalize_text("tra don") == "tra đơn"
    assert normalize_text("doi tra bao hanh") == "đổi trả bảo hành"
    assert normalize_text("") == ""


def test_dialect_and_homophone_regression():
    assert normalize_text("trái cây này bao nhiêu tiền") == "quả cây này bao nhiêu tiền"
    assert normalize_text("sáu giờ") == "sáu giờ"  # blind s->x swap must not corrupt it
    assert normalize_text("xip hàng") == "ship hàng"
    assert "đôn" in HOMOPHONES
    assert phonetic_key("sáu") == phonetic_key("xáu")
    assert phonetic_key("trả hàng") == phonetic_key("chả hàng")
    assert phonetic_key("áo sơ mi") != phonetic_key("áo thun đen")
    assert strip_diacritics("đơn hàng") == "don hang"


def test_spoken_entities_regression():
    assert parse_spoken_order_code("đờ hát một hai ba") == "DH123"
    assert parse_spoken_order_code("mã đơn là DH123") == "DH123"
    assert parse_spoken_order_code("xin chào") is None
    assert normalize_phone("không chín không một hai ba bốn năm sáu bảy") == "0901234567"
    assert normalize_phone("+84 901 234 567") == "0901234567"
    assert normalize_phone("12345") is None  # never guess


def test_fuzzy_match_regression():
    results = fuzzy_match("áo sơ my", PRODUCTS)
    assert results and results[0].candidate == "áo sơ mi trắng"
    assert fuzzy_match("máy bay phản lực", PRODUCTS, threshold=0.55) == []


def test_facade_still_works():
    from src.voice.vietnamese_normalizer import Region
    n = VietnameseNormalizer(region=Region.SOUTH)
    assert n.normalize("don hang") == "đơn hàng"
    assert n.order_code("đờ hát một hai ba") == "DH123"
    assert n.phone("không chín không một hai ba bốn năm sáu bảy") == "0901234567"
    assert n.resolve("áo sơ mi", PRODUCTS).best == "áo sơ mi trắng"


# --- Part B: the other 4 modules (importorskip) ------------------------------

def test_confidence_gate_rebased_to_contracts():
    gate_mod = pytest.importorskip("src.gating.confidence_gate")
    contracts = pytest.importorskip("src.contracts")
    assert gate_mod.CONTRACTS_VERSION == "1.0.0"
    assert gate_mod.MAX_CLARIFICATIONS == contracts.MAX_CLARIFICATIONS == 1
    assert gate_mod.ESCALATION_REASONS == {r.value for r in EscalationReason}
    assert "user_requested" not in gate_mod.ESCALATION_REASONS
    assert gate_mod.GateConfig().max_clarifications == 1
    # Clarification budget exhausted exactly once (MAX=1, not 2):
    # at 0.70 with 1 clarification already used -> escalate
    # with repeated_clarification from the contracts enum.
    gate = gate_mod.ConfidenceGate()
    signals = gate_mod.Signals(asr_confidence=0.7, intent_confidence_raw=0.7,
                               entity_match=0.7, evidence_completeness=0.7,
                               evidence_freshness=0.7, verifier_score=0.7,
                               has_evidence=True)
    d = gate.decide(signals, intent="track_order", clarifications_used=1)
    assert d.decision == gate_mod.Decision.ESCALATE
    assert d.escalation_reason == EscalationReason.REPEATED_CLARIFICATION.value


def test_grounded_answer_reasons_come_from_contracts_enum():
    mod = pytest.importorskip("src.grounding.grounded_answer")
    ev = mod.Evidence(source="oms.get_order", source_id="DH123", kind="order",
                      payload={"order_id": "DH123", "status": "đang giao"},
                      queried_at="2026-11-22T10:00:00+07:00")
    ans = mod.GroundedAnswerer()
    # Golden 1: no record -> UNKNOWN, out_of_scope (enum value).
    no_record = ans.answer_from_evidence("track_order", [])
    assert no_record.status == mod.AnswerStatus.UNKNOWN
    assert no_record.escalation_reason == EscalationReason.OUT_OF_SCOPE.value
    # Golden 2: contradictory records -> REJECTED, low_confidence.
    ev2 = mod.Evidence(source="oms.get_order", source_id="DH123", kind="order",
                       payload={"order_id": "DH123", "status": "đã giao"},
                       queried_at="2026-11-22T10:00:00+07:00")
    contra = ans.answer_from_evidence("track_order", [ev, ev2])
    assert contra.status == mod.AnswerStatus.REJECTED
    assert contra.escalation_reason == EscalationReason.LOW_CONFIDENCE.value
    # Blacklisted intent -> REJECTED, sensitive.
    blocked = ans.answer_from_evidence("compensation", [ev])
    assert blocked.status == mod.AnswerStatus.REJECTED
    assert blocked.escalation_reason == EscalationReason.SENSITIVE.value
    # Happy path still renders from evidence.
    ok = ans.answer_from_evidence("track_order", [ev])
    assert ok.status == mod.AnswerStatus.ANSWERED
    assert ok.speakable


def test_capacity_planner_keeps_erlang_a_not_erlang_c():
    mod = pytest.importorskip("src.queueing.capacity_planner")
    planner = mod.CapacityPlanner(containment=0.0)
    # c=1 still matches M/M/1 (the Erlang-A limit check).
    m = planner.erlang_c_metrics(0.2, 3.0, 1)
    assert m.prob_wait == pytest.approx(0.6)
    assert m.expected_wait_seconds == pytest.approx(270.0, rel=1e-6)
    # Overload under Erlang-A: finite wait (Erlang-C would be infinite).
    over = planner.metrics(10.0, 3.0, 5)
    assert over.overloaded
    assert over.prob_wait > 0.99
    assert math.isfinite(over.expected_wait_seconds) and over.expected_wait_seconds > 0


def test_model_cascade_keeps_session_scoped_order_cache():
    mod = pytest.importorskip("src.optimization.model_cascade")

    class FakeClock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = FakeClock()
    cascade = mod.ModelCascade(small_model=lambda t: None, large_model=lambda t: None,
                               clock=clock)
    cascade.set_order("session-a", "DH123", {"status": "đang giao"})
    assert cascade.get_order("session-a", "DH123") == {"status": "đang giao"}
    assert cascade.get_order("session-b", "DH123") is None  # never cross-session
    clock.advance(61)  # TTL 60s
    assert cascade.get_order("session-a", "DH123") is None
    # Voice cache still allowlist-only.
    assert not cascade.set_voice("Đơn DH123 đang giao.", b"audio")
