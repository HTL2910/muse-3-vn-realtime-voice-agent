"""[approach_17] Horizontal scaling & fault tolerance.

Branch: fix/fix_missing_scaling_platform — MERGED from
expert/systems-arch-m3, not rewritten. Autoscaler / load shedding /
bulkhead / canary / cost tracking are the m3 implementation, re-verified
here against the locked contracts v1.0.0 (src/contracts.py): cost and
containment now use the locked two-layer containment definition
(provisional + no recontact in 72h = final), and replica placement is
explicitly multi-AZ.

Stateless workers: media gateway, orchestrator and LLM workers keep no
state in memory; session state lives in Redis, callback queues in Kafka
+ DB outbox, business data in a replicated DB. This module is the
pure decision logic for that platform (no cloud SDK needed to test it):

* autoscaling (HPA/KEDA-style): desired replicas from concurrent calls,
  CPU/GPU and queue latency, with min/max bounds, cooldown (no flapping)
  and scale-to-zero for auxiliary workers (callback dialler, ingestion)
  outside hours.
* load shedding by priority: in-progress calls are never dropped; new
  low-priority calls are shed to a callback message instead of crashing
  the whole system. Shedding is a deliberate, measured decision.
* bulkheads: inbound, outbound-callback and batch-ingestion run in
  separate bounded pools; a slow ingestion job cannot starve live calls.
* multi-AZ placement + blue/green & canary for prompt/policy releases,
  rollback by version; cost tracked as cost-per-contained-call so the
  team can see whether cost still grows linearly with calls.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

from src.contracts import (
    CONTAINMENT_WINDOW_HOURS, CallMetrics, Priority,
    ScalingDecision, ScalingMetrics,
)

CALLS_PER_REPLICA = 50          # one orchestrator replica handles ~50 calls
CPU_TARGET = 70.0               # scale up above this
QUEUE_LATENCY_TARGET_MS = 500.0
COOLDOWN_S = 120
SCALE_TO_ZERO_HOUR_START = 22   # auxiliary workers off 22:00-06:00
SCALE_TO_ZERO_HOUR_END = 6


@dataclass
class AutoscalerConfig:
    min_replicas: int = 2
    max_replicas: int = 40
    calls_per_replica: int = CALLS_PER_REPLICA
    cpu_target: float = CPU_TARGET
    queue_latency_target_ms: float = QUEUE_LATENCY_TARGET_MS
    cooldown_s: int = COOLDOWN_S
    scale_to_zero_aux: bool = True


@dataclass
class Bulkhead:
    """Bounded pool for one traffic class. ``try_acquire`` never blocks."""
    name: str
    limit: int
    used: int = 0

    def try_acquire(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    def release(self) -> None:
        self.used = max(0, self.used - 1)


class BulkheadManager:
    """Inbound / outbound-callback / batch-ingestion isolation."""

    def __init__(self, inbound: int = 200, outbound: int = 50, ingestion: int = 10):
        self.pools = {
            "inbound": Bulkhead("inbound", inbound),
            "outbound": Bulkhead("outbound", outbound),
            "ingestion": Bulkhead("ingestion", ingestion),
        }

    def acquire(self, pool: str) -> bool:
        return self.pools[pool].try_acquire()

    def release(self, pool: str) -> None:
        self.pools[pool].release()


@dataclass
class MultiAZPlacement:
    """Balanced replica placement across availability zones.

    No single AZ may hold all replicas: with >= 2 zones the max in
    any one zone is ceil(n / zones) and the min is floor(n / zones),
    so losing one AZ never takes the whole service down. Blue/green
    is handled by Release (canary + rollback by version); placement
    only decides *where* the desired replicas run.
    """
    zones: tuple[str, ...] = ("az-a", "az-b", "az-c")

    def place(self, replicas: int) -> dict[str, int]:
        if replicas <= 0 or not self.zones:
            return {z: 0 for z in self.zones}
        base, extra = divmod(replicas, len(self.zones))
        return {z: base + (1 if i < extra else 0)
                for i, z in enumerate(self.zones)}

    def max_in_one_zone(self, replicas: int) -> int:
        return max(self.place(replicas).values()) if replicas > 0 else 0


class Autoscaler:
    def __init__(self, config: Optional[AutoscalerConfig] = None,
                 now: Optional[callable] = None):
        self.config = config or AutoscalerConfig()
        self._now = now or time.time
        self._last_scale_at = 0.0
        self.current_replicas = self.config.min_replicas

    def decide(self, metrics: ScalingMetrics, hour: Optional[int] = None) -> ScalingDecision:
        cfg = self.config
        by_calls = math.ceil(metrics.concurrent_calls / cfg.calls_per_replica)
        by_cpu = math.ceil(self.current_replicas * metrics.cpu_percent / cfg.cpu_target) \
            if metrics.cpu_percent > cfg.cpu_target else self.current_replicas
        by_queue = self.current_replicas + 1 \
            if metrics.queue_latency_ms > cfg.queue_latency_target_ms else self.current_replicas
        desired = max(cfg.min_replicas, by_calls, by_cpu, by_queue)
        desired = min(cfg.max_replicas, desired)
        # Scale-to-zero only for auxiliary workers, never for live inbound.
        if cfg.scale_to_zero_aux and hour is not None and metrics.concurrent_calls == 0 \
                and (hour >= SCALE_TO_ZERO_HOUR_START or hour < SCALE_TO_ZERO_HOUR_END):
            return ScalingDecision(0, "scale_to_zero",
                                   "aux workers off outside hours")
        now = self._now()
        if desired == self.current_replicas:
            return ScalingDecision(desired, "hold", "within target")
        if now - self._last_scale_at < cfg.cooldown_s:
            return ScalingDecision(self.current_replicas, "hold",
                                   f"cooldown {cfg.cooldown_s}s")
        action = "scale_up" if desired > self.current_replicas else "scale_down"
        self._last_scale_at = now
        self.current_replicas = desired
        return ScalingDecision(desired, action,
                               f"calls={metrics.concurrent_calls} cpu={metrics.cpu_percent}% "
                               f"queue={metrics.queue_latency_ms}ms")


def shed_decision(concurrent_calls: int, capacity: int,
                  priority: Priority) -> ScalingDecision:
    """Load shedding: keep in-progress calls; shed NEW low-priority calls
    to a callback message. VIP / HIGH are never shed first."""
    if concurrent_calls < capacity:
        return ScalingDecision(0, "hold", "capacity available")
    if priority in (Priority.VIP, Priority.HIGH):
        return ScalingDecision(0, "hold", "high priority admitted despite load")
    return ScalingDecision(0, "shed", "over capacity: new call -> callback message",
                           shed_new_calls=True)


@dataclass
class Release:
    """Blue/green + canary release for a prompt/policy version."""
    version: str
    canary_percent: int = 5
    stable_version: str = ""

    def traffic_for_canary(self, call_id_hash: int) -> bool:
        return (call_id_hash % 100) < self.canary_percent

    def rollback(self) -> "Release":
        return Release(version=self.stable_version, canary_percent=0,
                       stable_version=self.stable_version)


@dataclass
class CostTracker:
    """Cost per contained call. Internal metric only -- never a vendor claim.

    Containment follows the locked contracts v1.0.0 definition, in
    two layers: ``record_call`` takes a CallMetrics record (or the
    provisional/final booleans) so provisional and final containment
    are never conflated. ``cost_per_contained_call`` is cost per
    CONTAINED-FINAL call (provisional + no recontact in
    CONTAINMENT_WINDOW_HOURS = 72h); ``cost_per_contained_provisional_call``
    is the provisional figure, for diagnosis only.
    """
    ai_cost_usd_per_minute: float = 0.08
    minutes_ai_handled: float = 0.0
    contained_calls: int = 0  # final contained calls (locked definition)
    contained_provisional_calls: int = 0
    total_calls: int = 0
    window_hours: int = CONTAINMENT_WINDOW_HOURS

    def record_call(self, minutes: float, contained: bool = False, *,
                    metrics: CallMetrics | None = None) -> None:
        """Record one call. Prefer passing ``metrics`` (a CallMetrics);
        the ``contained`` bool is kept for the m3 callers and means
        contained-PROVISIONAL when no metrics record is given."""
        self.total_calls += 1
        self.minutes_ai_handled += minutes
        if metrics is not None:
            if metrics.contained_provisional:
                self.contained_provisional_calls += 1
            if metrics.compute_contained_final():
                self.contained_calls += 1
        elif contained:
            self.contained_provisional_calls += 1
            # Without a metrics record there is no 72h window to check,
            # so a bare bool can never claim final containment.
            pass

    def record_metrics(self, minutes: float, metrics: CallMetrics) -> None:
        self.record_call(minutes, metrics=metrics)

    @property
    def cost_per_contained_call(self) -> Optional[float]:
        """Cost per contained-FINAL call; None when none are final."""
        if not self.contained_calls:
            return None
        return self.minutes_ai_handled * self.ai_cost_usd_per_minute / self.contained_calls

    @property
    def cost_per_contained_provisional_call(self) -> Optional[float]:
        if not self.contained_provisional_calls:
            return None
        return (self.minutes_ai_handled * self.ai_cost_usd_per_minute
                / self.contained_provisional_calls)

    @property
    def containment_rate(self) -> float:
        """Final containment rate (locked definition)."""
        return self.contained_calls / self.total_calls if self.total_calls else 0.0

    @property
    def provisional_containment_rate(self) -> float:
        return (self.contained_provisional_calls / self.total_calls
                if self.total_calls else 0.0)
