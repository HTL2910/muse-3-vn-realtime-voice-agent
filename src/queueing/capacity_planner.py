"""Capacity planner: Erlang-A queueing, load forecast, callback policy.

fix/fix_missing_capacity_planner — approach_12.

Self-contained, stdlib-only. No import from ``src.contracts``:
rebase verification (fix_rebase_remaining_algo_ml) found no
mirrored contract constant in this module — the only numbers are
the 90 s patience benchmark, the 60/90 s callback band and
internal loop bounds — so there is nothing to import.

Why Erlang-A, not Erlang-C
--------------------------
Erlang-C (M/M/c) assumes customers wait forever. That is false here:
the brief's benchmark is that customers hang up after ~90 s on
average (60% within 1 minute, >90% by 5 minutes). A pure Erlang-C
planner therefore *understates* abandonment and *overstates* the
queue: it predicts an ever-growing line where the real system loses
callers. Erlang-A (M/M/c+M) adds abandonment: each waiting caller
abandons at rate theta = 1 / mean patience. With theta > 0 the
system is stable even when offered load a >= c, because the queue
is capped by callers leaving — but the price is paid in
abandonment, which is exactly the metric the business cares about.

When theta == 0 the model reduces exactly to Erlang-C (and for
c == 1, to M/M/1); when a >= c and theta == 0 the queue is
unstable and the planner returns ``overloaded=True`` with
``prob_wait = 1`` and infinite expected wait, never a negative
number or NaN.

Architecture modelled
---------------------
AI is the first server layer: it resolves a fraction
``containment`` of calls (default 0.52, the Ada vendor figure —
labelled as such, never a promise). Only
``lambda * (1 - containment)`` reaches the human queue, which is
priority-ordered by urgency and by time already waited. The
planner answers three questions: how many human agents (and AI
sessions) are needed for a target wait / abandonment, when the
forecast wait crosses 60-90 s so a callback should be offered
proactively, and which hours need extra shifts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = [
    "QueueMetrics",
    "HourlyPlan",
    "CapacityPlanner",
    "erlang_b",
    "erlang_c_probability_wait",
    "DEFAULT_HOURLY_PROFILE",
    "DEFAULT_PATIENCE_SECONDS",
]

DEFAULT_PATIENCE_SECONDS = 90.0  # benchmark: mean hang-up time ~90 s

# Hourly load multipliers (relative to the daily base rate).
# Peak 9-11h and 14-16h, quiet overnight. Tenants override this.
DEFAULT_HOURLY_PROFILE: Dict[int, float] = {
    0: 0.05, 1: 0.03, 2: 0.02, 3: 0.02, 4: 0.03, 5: 0.10,
    6: 0.30, 7: 0.60, 8: 0.90, 9: 1.40, 10: 1.60, 11: 1.50,
    12: 1.00, 13: 1.10, 14: 1.50, 15: 1.60, 16: 1.30, 17: 1.00,
    18: 0.80, 19: 0.70, 20: 0.60, 21: 0.40, 22: 0.20, 23: 0.10,
}

# Day-of-week multipliers (Mon=0). Weekends are quieter for B2B,
# busier for B2C retail — the default is the retail shape.
DEFAULT_DOW_PROFILE: Dict[int, float] = {
    0: 1.0, 1: 1.05, 2: 1.05, 3: 1.0, 4: 1.0, 5: 1.20, 6: 1.10,
}


def erlang_b(servers: int, offered_load: float) -> float:
    """Erlang-B blocking probability, computed by stable recurrence."""
    if servers <= 0:
        return 1.0
    if offered_load <= 0:
        return 0.0
    b = 1.0
    for k in range(1, servers + 1):
        b = offered_load * b / (k + offered_load * b)
    return b


def erlang_c_probability_wait(servers: int, offered_load: float) -> float:
    """Erlang-C P(wait > 0). For a >= c the queue is unstable -> 1.0."""
    if servers <= 0:
        return 1.0
    if offered_load <= 0:
        return 0.0
    if offered_load >= servers:
        return 1.0
    b = erlang_b(servers, offered_load)
    return servers * b / (servers - offered_load + offered_load * b)


@dataclass
class QueueMetrics:
    lambda_per_min: float
    service_time_min: float
    servers: int
    patience_seconds: float
    containment: float
    offered_load: float        # a = lambda_human / mu
    utilization: float         # rho = a / c (may exceed 1 under overload)
    prob_wait: float
    prob_abandon: float
    expected_wait_seconds: float   # mean wait, all arrivals (incl. abandoned)
    expected_wait_served_seconds: float
    expected_queue_length: float
    overloaded: bool

    def to_dict(self) -> Dict[str, float]:
        return {
            "lambda_per_min": self.lambda_per_min,
            "servers": float(self.servers),
            "offered_load": self.offered_load,
            "utilization": self.utilization,
            "prob_wait": self.prob_wait,
            "prob_abandon": self.prob_abandon,
            "expected_wait_seconds": self.expected_wait_seconds,
            "expected_wait_served_seconds": self.expected_wait_served_seconds,
            "expected_queue_length": self.expected_queue_length,
            "overloaded": float(self.overloaded),
        }


@dataclass
class HourlyPlan:
    hour: int
    lambda_per_min: float
    servers_needed: int
    metrics: QueueMetrics
    offer_callback: bool


class CapacityPlanner:
    """Erlang-A planner with an AI front layer and a load forecast."""

    def __init__(self, *, patience_seconds: float = DEFAULT_PATIENCE_SECONDS,
                 containment: float = 0.52,
                 hourly_profile: Optional[Dict[int, float]] = None,
                 dow_profile: Optional[Dict[int, float]] = None):
        if not 0.0 <= containment < 1.0:
            raise ValueError("containment must be in [0, 1)")
        if patience_seconds <= 0:
            raise ValueError("patience_seconds must be > 0")
        self.patience_seconds = float(patience_seconds)
        self.containment = float(containment)
        self.hourly_profile = dict(hourly_profile or DEFAULT_HOURLY_PROFILE)
        self.dow_profile = dict(dow_profile or DEFAULT_DOW_PROFILE)

    # -- Erlang-A core ------------------------------------------------------
    def metrics(self, lambda_per_min: float, service_time_min: float,
                servers: int, *, patience_seconds: Optional[float] = None,
                containment: Optional[float] = None) -> QueueMetrics:
        """Erlang-A metrics for the human queue after the AI layer."""
        if lambda_per_min < 0 or service_time_min <= 0:
            raise ValueError("lambda_per_min >= 0 and service_time_min > 0 required")
        if servers <= 0:
            raise ValueError("servers must be >= 1")
        patience = self.patience_seconds if patience_seconds is None else patience_seconds
        cont = self.containment if containment is None else containment
        if not 0.0 <= cont < 1.0:
            raise ValueError("containment must be in [0, 1)")
        if patience <= 0:
            raise ValueError("patience_seconds must be > 0")

        lam_human = lambda_per_min * (1.0 - cont)
        mu = 1.0 / service_time_min            # per minute
        theta = 60.0 / patience                # abandonments per minute
        a = lam_human / mu
        rho = a / servers
        overloaded = a >= servers

        if lam_human == 0:
            return QueueMetrics(lambda_per_min, service_time_min, servers,
                                patience, cont, a, rho, 0.0, 0.0, 0.0, 0.0, 0.0, False)

        # theta == 0 is the Erlang-C limit (used only for the c=1 / M/M/1
        # edge test and as a degenerate check — production always has
        # a finite patience, because real callers hang up).
        if theta == 0.0:  # pragma: no cover - patience is validated > 0
            raise ValueError("patience_seconds must be > 0")

        # Birth-death steady state for M/M/c+M, truncated when the
        # tail probability is negligible. Death rate in state n:
        #   n <= c: n * mu
        #   n >  c: c * mu + (n - c) * theta
        probs: List[float] = [1.0]
        n = 1
        while n <= 5000:
            death = n * mu if n <= servers else servers * mu + (n - servers) * theta
            probs.append(probs[-1] * lam_human / death)
            if n > servers and probs[-1] < 1e-14 and sum(probs[-100:]) < 1e-12:
                break
            n += 1
        total = sum(probs)
        probs = [p / total for p in probs]

        prob_wait = sum(probs[servers:])
        lq = sum((i - servers) * p for i, p in enumerate(probs) if i > servers)
        # Abandonment rate = theta * Lq; P(abandon) = that / lambda.
        prob_abandon = min(1.0, max(0.0, theta * lq / lam_human)) if lam_human else 0.0
        lam_eff = lam_human * (1.0 - prob_abandon)
        expected_wait = (lq / lam_human) * 60.0 if lam_human else 0.0
        expected_wait_served = (lq / lam_eff) * 60.0 if lam_eff > 0 else expected_wait
        # Guard against any numerical pathology: never return NaN/negative.
        for v in (prob_wait, prob_abandon, expected_wait, expected_wait_served, lq):
            if not math.isfinite(v) or v < 0:
                raise ArithmeticError("non-finite queue metric computed")
        return QueueMetrics(
            lambda_per_min=lambda_per_min,
            service_time_min=service_time_min,
            servers=servers,
            patience_seconds=patience,
            containment=cont,
            offered_load=a,
            utilization=rho,
            prob_wait=min(1.0, max(0.0, prob_wait)),
            prob_abandon=prob_abandon,
            expected_wait_seconds=expected_wait,
            expected_wait_served_seconds=expected_wait_served,
            expected_queue_length=lq,
            overloaded=overloaded,
        )

    def erlang_c_metrics(self, lambda_per_min: float, service_time_min: float,
                         servers: int) -> QueueMetrics:
        """Pure Erlang-C (theta = 0) — for the c=1 / M/M/1 edge test only.

        Returns overloaded=True, prob_wait=1 and infinite wait when
        a >= c, instead of a negative number or NaN.
        """
        if servers <= 0 or service_time_min <= 0:
            raise ValueError("servers >= 1 and service_time_min > 0 required")
        mu = 1.0 / service_time_min
        a = lambda_per_min / mu
        rho = a / servers
        if a >= servers:
            return QueueMetrics(lambda_per_min, service_time_min, servers,
                                float("inf"), 0.0, a, rho, 1.0, 0.0,
                                float("inf"), float("inf"), float("inf"), True)
        pw = erlang_c_probability_wait(servers, a)
        wait_min = pw / (servers * mu - lambda_per_min)
        return QueueMetrics(lambda_per_min, service_time_min, servers,
                            float("inf"), 0.0, a, rho, pw, 0.0,
                            wait_min * 60.0, wait_min * 60.0,
                            wait_min * lambda_per_min, False)

    # -- staffing ------------------------------------------------------------
    def servers_needed(self, lambda_per_min: float, service_time_min: float,
                       *, target_wait_seconds: float = 60.0,
                       target_abandon: float = 0.05,
                       max_servers: int = 200,
                       containment: Optional[float] = None) -> int:
        """Smallest c meeting both targets, or max_servers if unreachable."""
        for c in range(1, max_servers + 1):
            m = self.metrics(lambda_per_min, service_time_min, c, containment=containment)
            if (m.expected_wait_seconds <= target_wait_seconds
                    and m.prob_abandon <= target_abandon):
                return c
        return max_servers

    def ai_sessions_needed(self, lambda_per_min: float, ai_service_time_min: float,
                           *, target_wait_seconds: float = 30.0,
                           max_sessions: int = 500) -> int:
        """AI sessions are the first layer: they see the full lambda
        (containment applies only after they answer). Same Erlang-A
        maths, with the AI layer's own (shorter) patience — a caller
        will not wait 90 s for an AI greeting either, so use 30 s."""
        for c in range(1, max_sessions + 1):
            m = self.metrics(lambda_per_min, ai_service_time_min, c,
                             patience_seconds=30.0, containment=0.0)
            if m.expected_wait_seconds <= target_wait_seconds:
                return c
        return max_sessions

    # -- forecast --------------------------------------------------------------
    def forecast_lambda(self, base_lambda_per_min: float, *, hour: int,
                        day_of_week: int = 0, campaign_factor: float = 1.0) -> float:
        """Forecast arrivals for one hour: base x hour profile x dow x campaign."""
        if hour not in self.hourly_profile:
            raise ValueError(f"hour must be 0-23, got {hour}")
        return (base_lambda_per_min
                * self.hourly_profile[hour]
                * self.dow_profile.get(day_of_week, 1.0)
                * campaign_factor)

    def plan_day(self, base_lambda_per_min: float, service_time_min: float,
                 *, day_of_week: int = 0, campaign_factor: float = 1.0,
                 target_wait_seconds: float = 60.0,
                 target_abandon: float = 0.05) -> List[HourlyPlan]:
        """One staffing plan per hour: servers needed + callback flag."""
        plan: List[HourlyPlan] = []
        for hour in range(24):
            lam = self.forecast_lambda(base_lambda_per_min, hour=hour,
                                       day_of_week=day_of_week,
                                       campaign_factor=campaign_factor)
            c = self.servers_needed(lam, service_time_min,
                                    target_wait_seconds=target_wait_seconds,
                                    target_abandon=target_abandon)
            m = self.metrics(lam, service_time_min, c)
            plan.append(HourlyPlan(hour=hour, lambda_per_min=lam,
                                   servers_needed=c, metrics=m,
                                   offer_callback=self.should_offer_callback(
                                       m.expected_wait_seconds)))
        return plan

    # -- callback policy ---------------------------------------------------------
    @staticmethod
    def should_offer_callback(expected_wait_seconds: float,
                              *, low_seconds: float = 60.0,
                              high_seconds: float = 90.0) -> bool:
        """Offer a callback (record + book a slot) once the forecast
        wait crosses 60 s; above 90 s it is no longer optional in
        practice — the caller will hang up first."""
        return expected_wait_seconds >= low_seconds

    def callback_slots(self, expected_wait_seconds: float, *,
                       slot_minutes: int = 15, slots: int = 4) -> List[str]:
        """Next free callback slots, as offsets from now. Empty when
        no callback is needed — do not offer what is not needed."""
        if not self.should_offer_callback(expected_wait_seconds):
            return []
        return [f"+{slot_minutes * (i + 1)}min" for i in range(slots)]

    # -- peak simulation -----------------------------------------------------------
    def simulate_peak(self, lambda_per_min: float, service_time_min: float,
                      servers: int, *, hours: int = 2,
                      containment: Optional[float] = None) -> Dict:
        """Deterministic peak-load simulation: the same Erlang-A
        metrics evaluated hour by hour at a sustained peak rate.
        Returns the worst hour and whether a callback must be offered.
        """
        worst = None
        for _ in range(hours):
            m = self.metrics(lambda_per_min, service_time_min, servers,
                             containment=containment)
            if worst is None or m.expected_wait_seconds > worst.expected_wait_seconds:
                worst = m
        assert worst is not None
        return {
            "lambda_per_min": lambda_per_min,
            "servers": servers,
            "worst_expected_wait_seconds": round(worst.expected_wait_seconds, 2),
            "worst_prob_abandon": round(worst.prob_abandon, 4),
            "worst_prob_wait": round(worst.prob_wait, 4),
            "overloaded": worst.overloaded,
            "offer_callback": self.should_offer_callback(worst.expected_wait_seconds),
        }
