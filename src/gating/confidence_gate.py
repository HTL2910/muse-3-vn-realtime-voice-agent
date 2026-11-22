"""Confidence gate: calibrated, cost-sensitive answer / clarify / escalate.

fix/fix_missing_confidence_gate — approach_07 (P0, business-critical).

Self-contained, stdlib-only. No import from ``src.contracts`` (there
is no contracts file on ``main`` yet). The locked values mirror the
contract agreed in COUNCIL_BUG_DEBATE (move verbatim into
``src/contracts.py`` v1.0.0):

* ``MAX_CLARIFICATIONS = 1`` — one clarification, then escalate.
* Escalation reasons are snake_case: ``out_of_scope``,
  ``low_confidence``, ``sensitive``, ``customer_request``,
  ``repeated_clarification``, ``repeated_failure``.
* Default zones: >= 0.85 answer, 0.60-0.85 clarify, < 0.60 escalate.

Why this module is P0
----------------------
Without a gate the system is a chatbot that answers every call
(Klarna, May 2025): it answers confidently when it is wrong. The
gate is the only place that may say "answer", and it may only do so
from *calibrated* confidence — a raw LLM probability of 0.9 that is
right only half the time must not clear 0.85.

Signals aggregated (weights sum to 1, configurable per tenant/intent)
----------------------------------------------------------------------
* ASR confidence (0.15) — how sure the transcription is.
* Calibrated intent confidence (0.35) — raw intent probability
  passed through temperature scaling or isotonic regression fitted
  on real labelled data, never the raw probability.
* Entity match (0.15) — how well the extracted slots match a real
  record (order code / SKU / phone).
* Evidence completeness + freshness (0.20) — the tool data exists,
  has the required fields, and is fresh. Missing evidence is a
  hard escalate, whatever the other signals say.
* Verifier score (0.15) — the grounded-answer verifier's score
  (1.0 = every number/date/code in the answer matches evidence).

Cost-sensitive thresholds
-------------------------
Answering wrong costs far more than escalating: with
``cost_wrong_answer = 100`` and ``cost_escalate = 15``, answering
is only cheaper when ``(1 - p) * 100 < 15``, i.e. ``p > 0.85`` —
exactly the default answer threshold. ``GateConfig.from_costs``
derives the threshold from the tenant's own costs instead of
hard-coding it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "Decision",
    "GateConfig",
    "GateDecision",
    "Signals",
    "TemperatureCalibrator",
    "IsotonicCalibrator",
    "ConfidenceGate",
    "MAX_CLARIFICATIONS",
    "ESCALATION_REASONS",
    "DEFAULT_WEIGHTS",
]

MAX_CLARIFICATIONS = 1

ESCALATION_REASONS = frozenset({
    "out_of_scope",
    "low_confidence",
    "sensitive",
    "customer_request",
    "repeated_clarification",
    "repeated_failure",
})

DEFAULT_WEIGHTS: Dict[str, float] = {
    "asr": 0.15,
    "intent": 0.35,
    "entity": 0.15,
    "evidence": 0.20,
    "verifier": 0.15,
}


def _clamp(p: float) -> float:
    return min(0.999, max(0.001, float(p)))


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _logit(p: float) -> float:
    p = _clamp(p)
    return math.log(p / (1.0 - p))


# ---------------------------------------------------------------------------
# Calibration (fit on real labelled data, never on raw probabilities)
# ---------------------------------------------------------------------------


class TemperatureCalibrator:
    """Temperature scaling: p_cal = sigmoid(logit(p) / T).

    T is fitted by grid search minimising log-loss on labelled
    (probability, correct) pairs. T > 1 shrinks overconfident
    probabilities towards 0.5; T < 1 sharpens underconfident ones.
    """

    def __init__(self, temperature: float = 1.0):
        self.temperature = float(temperature)

    def fit(self, pairs: Sequence[Tuple[float, bool]]) -> "TemperatureCalibrator":
        best_t, best_loss = 1.0, float("inf")
        t = 0.2
        while t <= 5.0:
            loss = 0.0
            for p, correct in pairs:
                q = _sigmoid(_logit(p) / t)
                loss -= math.log(q if correct else 1.0 - q)
            if loss < best_loss:
                best_loss, best_t = loss, t
            t += 0.05
        self.temperature = round(best_t, 2)
        return self

    def calibrate(self, p: float) -> float:
        return _sigmoid(_logit(p) / self.temperature)


class IsotonicCalibrator:
    """Isotonic regression (PAVA) on labelled (probability, correct) pairs.

    Produces a non-decreasing stepwise mapping. Use when the
    miscalibration is not a simple temperature (e.g. the model is
    overconfident at 0.9 but underconfident at 0.6).
    """

    def __init__(self):
        self.breakpoints: List[Tuple[float, float]] = [(0.0, 0.0), (1.0, 1.0)]

    def fit(self, pairs: Sequence[Tuple[float, bool]]) -> "IsotonicCalibrator":
        # Group by distinct probability FIRST: all labels at the same
        # p belong to one initial block (their mean). Running PAVA on
        # individual points sorted by (p, label) would pool across
        # a probability boundary for an arbitrary within-tie order
        # and return a non-isotonic-looking step function.
        grouped: Dict[float, List[float]] = {}
        for p, c in pairs:
            grouped.setdefault(float(p), []).append(1.0 if c else 0.0)
        if not grouped:
            return self
        # PAVA: pool adjacent violators until the values are non-decreasing.
        blocks: List[List[float]] = []  # [sum, count, max_prob]
        for p in sorted(grouped):
            ys = grouped[p]
            blocks.append([sum(ys), float(len(ys)), p])
            while len(blocks) >= 2 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
                b2 = blocks.pop()
                b1 = blocks.pop()
                blocks.append([b1[0] + b2[0], b1[1] + b2[1], b2[2]])
        self.breakpoints = [(0.0, blocks[0][0] / blocks[0][1])]
        for total, count, max_p in blocks:
            self.breakpoints.append((max_p, total / count))
        self.breakpoints.append((1.0, blocks[-1][0] / blocks[-1][1]))
        return self

    def calibrate(self, p: float) -> float:
        p = _clamp(p)
        value = self.breakpoints[0][1]
        for prob, val in self.breakpoints:
            if p >= prob:
                value = val
            else:
                break
        return float(value)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class Decision(str, Enum):
    ANSWER = "answer"
    CLARIFY = "clarify"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Signals:
    asr_confidence: float = 0.0
    intent_confidence_raw: float = 0.0
    entity_match: float = 0.0
    evidence_completeness: float = 0.0
    evidence_freshness: float = 0.0
    verifier_score: float = 0.0
    has_evidence: bool = True

    def evidence_score(self) -> float:
        return (self.evidence_completeness + self.evidence_freshness) / 2.0


@dataclass(frozen=True)
class GateConfig:
    answer_threshold: float = 0.85
    clarify_threshold: float = 0.60
    max_clarifications: int = MAX_CLARIFICATIONS
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    cost_wrong_answer: float = 100.0
    cost_escalate: float = 15.0
    cost_clarify: float = 5.0
    competing_intent_gap: float = 0.08

    def __post_init__(self):
        if not 0.0 < self.clarify_threshold < self.answer_threshold < 1.0:
            raise ValueError("thresholds must satisfy 0 < clarify < answer < 1")
        if abs(sum(self.weights.values()) - 1.0) > 1e-6:
            raise ValueError("weights must sum to 1")

    @classmethod
    def from_costs(cls, *, cost_wrong_answer: float, cost_escalate: float,
                   cost_clarify: float = 5.0, clarify_threshold: float = 0.60,
                   **kw) -> "GateConfig":
        """Derive the answer threshold from costs.

        Answer iff (1 - p) * cost_wrong < cost_escalate, i.e.
        p > 1 - cost_escalate / cost_wrong. With the defaults
        (100, 15) that is exactly 0.85.
        """
        threshold = 1.0 - cost_escalate / cost_wrong_answer
        return cls(answer_threshold=round(threshold, 4),
                   clarify_threshold=clarify_threshold,
                   cost_wrong_answer=cost_wrong_answer,
                   cost_escalate=cost_escalate,
                   cost_clarify=cost_clarify, **kw)

    def optimal_answer_threshold(self) -> float:
        return 1.0 - self.cost_escalate / self.cost_wrong_answer


@dataclass
class GateDecision:
    decision: Decision
    confidence: float
    calibrated_intent_confidence: float
    reason: str
    escalation_reason: Optional[str] = None
    zone: str = ""

    def log_record(self, *, tenant_id: str, intent: str, signals: Signals) -> Dict:
        return {
            "tenant_id": tenant_id,
            "intent": intent,
            "decision": self.decision.value,
            "confidence": round(self.confidence, 4),
            "calibrated_intent_confidence": round(self.calibrated_intent_confidence, 4),
            "reason": self.reason,
            "escalation_reason": self.escalation_reason,
            "zone": self.zone,
            "signals": {
                "asr_confidence": signals.asr_confidence,
                "intent_confidence_raw": signals.intent_confidence_raw,
                "entity_match": signals.entity_match,
                "evidence_completeness": signals.evidence_completeness,
                "evidence_freshness": signals.evidence_freshness,
                "verifier_score": signals.verifier_score,
                "has_evidence": signals.has_evidence,
            },
        }


class ConfidenceGate:
    """Aggregate calibrated signals and decide answer / clarify / escalate.

    Every decision is appended to ``self.decision_log`` with its
    confidence and escalation reason, so thresholds can be
    re-calibrated weekly from real outcomes (see ``record_outcome``).
    """

    def __init__(self, *, config: Optional[GateConfig] = None,
                 calibrator=None, configs: Optional[Dict[str, GateConfig]] = None):
        self.config = config if config is not None else GateConfig()
        self.calibrator = calibrator  # TemperatureCalibrator | IsotonicCalibrator | None
        self.configs = configs or {}  # "tenant:intent" -> GateConfig override
        self.decision_log: List[Dict] = []
        self._outcomes: List[Tuple[float, bool]] = []

    def config_for(self, tenant_id: str = "", intent: str = "") -> GateConfig:
        return self.configs.get(f"{tenant_id}:{intent}",
                                self.configs.get(intent, self.config))

    def aggregate(self, signals: Signals, config: Optional[GateConfig] = None) -> Tuple[float, float]:
        calibrated = (self.calibrator.calibrate(signals.intent_confidence_raw)
                      if self.calibrator is not None
                      else float(signals.intent_confidence_raw))
        w = (config if config is not None else self.config).weights
        total = (
            w["asr"] * signals.asr_confidence
            + w["intent"] * calibrated
            + w["entity"] * signals.entity_match
            + w["evidence"] * signals.evidence_score()
            + w["verifier"] * signals.verifier_score
        )
        return round(total, 4), round(calibrated, 4)

    def decide(self, signals: Signals, *, intent: str, tenant_id: str = "",
               clarifications_used: int = 0,
               top_intents: Optional[Sequence[Tuple[str, float]]] = None) -> GateDecision:
        cfg = self.config_for(tenant_id, intent)
        confidence, calibrated = self.aggregate(signals, cfg)

        def _decide(decision: Decision, reason: str, escalation: Optional[str],
                    zone: str) -> GateDecision:
            d = GateDecision(decision, confidence, calibrated, reason, escalation, zone)
            self.decision_log.append(d.log_record(tenant_id=tenant_id, intent=intent, signals=signals))
            return d

        # Hard rule: no evidence -> escalate, whatever the other signals say.
        # Answering without verified data is exactly the Klarna failure.
        if not signals.has_evidence:
            return _decide(Decision.ESCALATE, "missing_evidence", "low_confidence", "escalate")
        # Hard rule: a failed verifier (score < 0.5) blocks answering.
        if signals.verifier_score < 0.5:
            return _decide(Decision.ESCALATE, "verifier_failed", "low_confidence", "escalate")

        # Two competing intents close together: clarify once, then escalate.
        if top_intents and len(top_intents) >= 2:
            gap = abs(top_intents[0][1] - top_intents[1][1])
            if gap < cfg.competing_intent_gap:
                if clarifications_used < cfg.max_clarifications:
                    return _decide(Decision.CLARIFY, "competing_intents", None, "clarify")
                return _decide(Decision.ESCALATE, "competing_intents_after_clarify",
                               "repeated_clarification", "escalate")

        if confidence >= cfg.answer_threshold:
            return _decide(Decision.ANSWER, "above_answer_threshold", None, "answer")
        if confidence >= cfg.clarify_threshold:
            if clarifications_used < cfg.max_clarifications:
                return _decide(Decision.CLARIFY, "below_answer_threshold", None, "clarify")
            return _decide(Decision.ESCALATE, "clarification_budget_exhausted",
                           "repeated_clarification", "escalate")
        return _decide(Decision.ESCALATE, "below_clarify_threshold", "low_confidence", "escalate")

    def record_outcome(self, confidence: float, correct: bool) -> None:
        """Record whether an answered turn was actually right.

        Feed these pairs back into a calibrator weekly; a gate whose
        0.9-confidence answers are right only 60% of the time is
        miscalibrated, however green its unit tests are.
        """
        self._outcomes.append((float(confidence), bool(correct)))

    def calibration_data(self) -> List[Tuple[float, bool]]:
        return list(self._outcomes)
