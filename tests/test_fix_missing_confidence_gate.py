"""Tests for fix/fix_missing_confidence_gate.

Stdlib-only (pytest). Threshold boundaries are asserted exactly
(0.85 answers, 0.60 clarifies), calibration is asserted on labelled
data, and missing evidence is asserted to escalate whatever the
other signals say.
Chưa chạy — kết quả thật do CI báo lại.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from gating.confidence_gate import (  # noqa: E402
    MAX_CLARIFICATIONS,
    ConfidenceGate,
    Decision,
    GateConfig,
    IsotonicCalibrator,
    Signals,
    TemperatureCalibrator,
)


def signals_at(value: float, **overrides):
    """All components equal to `value`, so the weighted aggregate is `value`."""
    kw = dict(asr_confidence=value, intent_confidence_raw=value,
              entity_match=value, evidence_completeness=value,
              evidence_freshness=value, verifier_score=value,
              has_evidence=True)
    kw.update(overrides)
    return Signals(**kw)


# --- thresholds 0.85 / 0.60 -------------------------------------------------

def test_exactly_085_answers():
    gate = ConfidenceGate()
    d = gate.decide(signals_at(0.85), intent="track_order")
    assert d.decision == Decision.ANSWER
    assert d.confidence == 0.85
    assert d.zone == "answer"
    assert d.escalation_reason is None


def test_just_below_085_clarifies():
    gate = ConfidenceGate()
    d = gate.decide(signals_at(0.849), intent="track_order")
    assert d.decision == Decision.CLARIFY
    assert d.zone == "clarify"


def test_exactly_060_clarifies():
    gate = ConfidenceGate()
    d = gate.decide(signals_at(0.60), intent="track_order")
    assert d.decision == Decision.CLARIFY


def test_just_below_060_escalates():
    gate = ConfidenceGate()
    d = gate.decide(signals_at(0.599), intent="track_order")
    assert d.decision == Decision.ESCALATE
    assert d.escalation_reason == "low_confidence"
    assert d.reason == "below_clarify_threshold"


def test_high_confidence_still_escalates_after_one_clarification():
    # MAX_CLARIFICATIONS = 1: a second turn in the clarify zone must
    # escalate, not ask again forever.
    assert MAX_CLARIFICATIONS == 1
    gate = ConfidenceGate()
    d = gate.decide(signals_at(0.70), intent="track_order", clarifications_used=1)
    assert d.decision == Decision.ESCALATE
    assert d.escalation_reason == "repeated_clarification"


# --- missing evidence / verifier ---------------------------------------------

def test_missing_evidence_escalates_even_at_099():
    gate = ConfidenceGate()
    d = gate.decide(signals_at(0.99, has_evidence=False), intent="track_order")
    assert d.decision == Decision.ESCALATE
    assert d.reason == "missing_evidence"
    assert d.escalation_reason == "low_confidence"


def test_failed_verifier_escalates_even_at_099():
    gate = ConfidenceGate()
    d = gate.decide(signals_at(0.99, verifier_score=0.0), intent="track_order")
    assert d.decision == Decision.ESCALATE
    assert d.reason == "verifier_failed"


def test_competing_intents_clarify_once_then_escalate():
    gate = ConfidenceGate()
    top = [("track_order", 0.70), ("check_fee", 0.68)]  # gap 0.02 < 0.08
    d = gate.decide(signals_at(0.90), intent="track_order", top_intents=top)
    assert d.decision == Decision.CLARIFY
    assert d.reason == "competing_intents"
    d2 = gate.decide(signals_at(0.90), intent="track_order",
                     clarifications_used=1, top_intents=top)
    assert d2.decision == Decision.ESCALATE
    assert d2.escalation_reason == "repeated_clarification"


def test_wide_intent_gap_does_not_force_clarify():
    gate = ConfidenceGate()
    top = [("track_order", 0.90), ("check_fee", 0.40)]
    d = gate.decide(signals_at(0.90), intent="track_order", top_intents=top)
    assert d.decision == Decision.ANSWER


# --- calibration ---------------------------------------------------------------

def test_temperature_calibrator_shrinks_overconfident_probabilities():
    # Model says 0.9 but is right only half the time: calibrated must
    # drop well below the raw value, so it no longer clears 0.85.
    pairs = [(0.9, True), (0.9, False)] * 10 + [(0.6, True), (0.6, False)] * 5
    cal = TemperatureCalibrator().fit(pairs)
    assert cal.temperature > 1.0
    assert cal.calibrate(0.9) < 0.85
    assert cal.calibrate(0.5) == pytest.approx(0.5, abs=0.05)


def test_calibrated_gate_blocks_overconfident_raw_090():
    pairs = [(0.9, True), (0.9, False)] * 10
    cal = TemperatureCalibrator().fit(pairs)
    gate = ConfidenceGate(calibrator=cal)
    d = gate.decide(signals_at(0.90), intent="track_order")
    # Raw 0.90 would answer; calibrated must not.
    assert d.calibrated_intent_confidence < 0.85
    assert d.decision != Decision.ANSWER


def test_isotonic_calibrator_is_monotone():
    pairs = [(0.9, True), (0.9, False), (0.9, True), (0.9, False),
             (0.6, False), (0.6, False), (0.6, True),
             (0.3, False), (0.3, False)]
    cal = IsotonicCalibrator().fit(pairs)
    vals = [cal.calibrate(p) for p in (0.3, 0.6, 0.9)]
    assert vals == sorted(vals)
    assert cal.calibrate(0.9) < 0.9  # overconfident at 0.9, shrunk


# --- cost-sensitive thresholds / config / logging --------------------------------

def test_threshold_derived_from_costs_matches_default_085():
    cfg = GateConfig.from_costs(cost_wrong_answer=100, cost_escalate=15)
    assert cfg.answer_threshold == 0.85
    assert cfg.optimal_answer_threshold() == pytest.approx(0.85)
    # Cheaper escalation -> higher threshold (answer less often).
    cfg2 = GateConfig.from_costs(cost_wrong_answer=100, cost_escalate=5)
    assert cfg2.answer_threshold == 0.95


def test_invalid_thresholds_and_weights_rejected():
    with pytest.raises(ValueError):
        GateConfig(answer_threshold=0.5, clarify_threshold=0.6)
    with pytest.raises(ValueError):
        GateConfig(weights={"asr": 0.5, "intent": 0.5, "entity": 0.5,
                            "evidence": 0.5, "verifier": 0.5})


def test_per_tenant_config_override():
    strict = GateConfig(answer_threshold=0.95, clarify_threshold=0.80)
    gate = ConfidenceGate(configs={"tenant-b:track_order": strict})
    d = gate.decide(signals_at(0.90), intent="track_order", tenant_id="tenant-b")
    assert d.decision == Decision.CLARIFY  # 0.90 clears default 0.85, not 0.95
    d2 = gate.decide(signals_at(0.90), intent="track_order", tenant_id="tenant-a")
    assert d2.decision == Decision.ANSWER


def test_every_decision_is_logged_with_confidence_and_reason():
    gate = ConfidenceGate()
    gate.decide(signals_at(0.90), intent="track_order", tenant_id="t1")
    gate.decide(signals_at(0.40), intent="check_fee", tenant_id="t1")
    assert len(gate.decision_log) == 2
    first, second = gate.decision_log
    assert first["decision"] == "answer" and first["confidence"] == 0.90
    assert first["tenant_id"] == "t1" and first["intent"] == "track_order"
    assert second["decision"] == "escalate"
    assert second["escalation_reason"] == "low_confidence"
    # Outcomes feed weekly recalibration.
    gate.record_outcome(0.90, True)
    gate.record_outcome(0.90, False)
    assert gate.calibration_data() == [(0.90, True), (0.90, False)]
