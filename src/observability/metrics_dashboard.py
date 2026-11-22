 — phần 1/2
"""
Metrics & dashboard - honest containment measurement.

Containment, two locked layers (contracts v1.0.0):
  * provisional: call ended, AI handled it, no escalation, not abandoned,
    AND the answer was backed by verified evidence.
  * final (THE KPI - the only containment number that may be committed):
    provisional AND the same customer did not call back about the same
    issue within CONTAINMENT_WINDOW_HOURS imported from src.contracts -
    FIXED at 72h, not a local option. Cost-per-contained is always
    computed on the FINAL layer.

Every call carries one trace_id across media-dialog-data-handoff.
Transcripts are PII-redacted BEFORE analytics storage. Internal
measurements are always reported separately from international/vendor
benchmarks - benchmarks are never merged into internal KPIs, and this
module never claims an 80% resolution rate.

EscalationReason / CONTAINMENT_WINDOW_HOURS / TOTAL_SLO_P95_MS /
CONTRACTS_VERSION are imported from src.contracts; NO mirror is defined.
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.contracts import (  # type: ignore
    EscalationReason, CONTAINMENT_WINDOW_HOURS, TOTAL_SLO_P95_MS,
    CONTRACTS_VERSION)


_PHONE_RE = re.compile(r"\b0\d{9}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_ID_RE = re.compile(r"\b\d{9}(\d{3})?\b")


def redact_pii(text: str) -> str:
    if not text:
        return text or ""
    out = _EMAIL_RE.sub("[EMAIL]", text)
    out = _PHONE_RE.sub(
        lambda m: m.group(0)[:2] + "******" + m.group(0)[-2:], out)
    out = _ID_RE.sub("[ID]", out)
    return out


def percentile(values: list, pct: float) -> float:
    """Nearest-rank percentile; 0.0 for empty input."""
    if not values:
        return 0.0
    vals = sorted(values)
    rank = math.ceil(pct / 100.0 * len(vals))
    return float(vals[max(0, min(rank, len(vals)) - 1)])


@dataclass
class CallRecord:
    trace_id: str
    call_id: str = ""
    tenant_id: str = ""
    phone: str = ""
    intent: str = ""
    department: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    wait_s: float = 0.0
    duration_s: float = 0.0
    handled_by_ai: bool = False
    evidence_verified: bool = False
    escalated: bool = False
    escalation_reason: Any = None        # EscalationReason | str | None
    correct_department: Optional[bool] = None
    abandoned: bool = False
    resolved_first_contact: bool = False
    csat: Optional[float] = None        # 1..5
    cost: float = 0.0
    ai_minutes: float = 0.0
    latencies_ms: dict = field(default_factory=dict)
    barge_in_count: int = 0
    provider_errors: dict = field(default_factory=dict)
    verifier_attempts: int = 0
    verifier_blocked: int = 0
    transcript: str = ""                 # stored REDACTED only
    recording_ref: str = ""
    repeat_same_issue: bool = False

    @property
    def provisional_contained(self) -> bool:
        return bool(self.handled_by_ai and self.evidence_verified
                    and not self.escalated and not self.abandoned)


class MetricsDashboard:
    def __init__(self, window_hours: float = CONTAINMENT_WINDOW_HOURS,
                 retention_days: int = 90):
        if float(window_hours) != float(CONTAINMENT_WINDOW_HOURS):
            raise ValueError(
                "containment window is FIXED by contracts v1.0.0 at "
                f"{CONTAINMENT_WINDOW_HOURS}h; got {window_hours}")
        self.window_hours = float(CONTAINMENT_WINDOW_HOURS)
        self.retention_days = int(retention_days)
        self._lock = threading.RLock()
        self._calls: list[CallRecord] = []
        self.benchmarks: dict = {}

    def record_call(self, record: CallRecord | dict, **kw) -> CallRecord:
        if isinstance(record, dict):
            data = {**record, **kw}
            record = CallRecord(**{k: v for k, v in data.items()
                                   if k in CallRecord.__dataclass_fields__})
        elif kw:
            for k, v in kw.items():
                setattr(record, k, v)
        if isinstance(record.escalation_reason, Enum):
            record.escalation_reason = record.escalation_reason.value
        record.transcript = redact_pii(record.transcript)
        with self._lock:
            window_s = self.window_hours * 3600
            for prev in self._calls:
                if prev.phone and prev.phone == record.phone \
                        and prev.intent == record.intent \
                        and 0 <= record.started_at - prev.started_at <= window_s:
                    prev.repeat_same_issue = True
            self._calls.append(record)
        return record

    record = record_call
    add_call = record_call

    def set_benchmarks(self, benchmarks: dict) -> None:
        """International/vendor benchmarks, stored apart from internal."""
        self.benchmarks = dict(benchmarks or {})

    def _final_contained(self, c: CallRecord) -> bool:
        return c.provisional_contained and not c.repeat_same_issue



[[FILE src/observability/metrics_dashboard.py]] — phần 2/2 (nối tiếp, kết thúc file)

    def compute(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else float(now)
        with self._lock:
            calls = list(self._calls)
        total = len(calls)

        def rate(n, d=total):
            return round(n / d, 4) if d else 0.0

        prov = sum(1 for c in calls if c.provisional_contained)
        final = sum(1 for c in calls if self._final_contained(c))
        mature = sum(1 for c in calls if c.started_at
                     and now - c.started_at >= self.window_hours * 3600)
        escalated = [c for c in calls if c.escalated]
        reasons = Counter(str(c.escalation_reason) for c in escalated
                          if c.escalation_reason)
        dept_known = [c for c in escalated if c.correct_department is not None]
        dept_ok = sum(1 for c in dept_known if c.correct_department)
        total_cost = sum(c.cost for c in calls)
        total_minutes = sum(c.ai_minutes for c in calls)
        lat = {}
        for stage in ("asr", "llm", "tts", "total"):
            vals = [float(c.latencies_ms[stage]) for c in calls
                    if stage in c.latencies_ms]
            if vals:
                lat[stage] = {"p50": percentile(vals, 50),
                              "p95": percentile(vals, 95), "n": len(vals)}
        provider_errors = Counter()
        for c in calls:
            provider_errors.update(c.provider_errors or {})
        v_attempts = sum(c.verifier_attempts for c in calls)
        v_blocked = sum(c.verifier_blocked for c in calls)
        csats = [c.csat for c in calls if c.csat is not None]

        return {
            "source": "internal_measured",
            "total_calls": total,
            "contracts_version": CONTRACTS_VERSION,
            "containment_window_hours": self.window_hours,
            "containment_provisional_rate": rate(prov),
            "containment_final_rate": rate(final),
            "contained_final": final,
            "containment_final_count": final,
            "containment_mature_calls": mature,
            "kpi_containment": rate(final),
            "escalation_rate": rate(len(escalated)),
            "escalation_by_reason": dict(reasons),
            "escalation_reason_rates": {k: rate(v) for k, v in reasons.items()},
            "correct_department_rate": round(dept_ok / len(dept_known), 4) if dept_known else 0.0,
            "abandonment_rate": rate(sum(1 for c in calls if c.abandoned)),
            "avg_wait_s": round(sum(c.wait_s for c in calls) / total, 3) if total else 0.0,
            "fcr_rate": rate(sum(1 for c in calls if c.resolved_first_contact)),
            "aht_s": round(sum(c.duration_s for c in calls) / total, 3) if total else 0.0,
            "csat_avg": round(sum(csats) / len(csats), 3) if csats else None,
            "latency_ms": lat,
            "latency_slo_p95_ms": TOTAL_SLO_P95_MS,
            "latency_slo_breached": bool(
                lat.get("total") and lat["total"]["p95"] > TOTAL_SLO_P95_MS),
            "barge_in_rate": rate(sum(1 for c in calls if c.barge_in_count > 0)),
            "provider_errors": dict(provider_errors),
            "provider_error_calls_rate": rate(
                sum(1 for c in calls if c.provider_errors)),
            "verifier_block_rate": round(v_blocked / v_attempts, 4) if v_attempts else 0.0,
            "verifier_blocked_count": v_blocked,
            "cost_per_ai_minute": round(total_cost / total_minutes, 6) if total_minutes else 0.0,
            "cost_per_contained_call": round(total_cost / final, 6) if final else None,
            "total_cost": round(total_cost, 4),
            "by_intent": self._breakdown(calls, "intent"),
            "by_department": self._breakdown(calls, "department"),
            "by_hour": self._by_hour(calls),
            "benchmarks_external": self.benchmarks,
            "benchmarks_mixed_into_kpi": False,
            "claimed_resolution_rate": None,  # never promise 80%
        }

    snapshot = compute
    dashboard = compute

    def _breakdown(self, calls: list, attr: str) -> dict:
        groups = defaultdict(list)
        for c in calls:
            groups[getattr(c, attr) or "unknown"].append(c)
        out = {}
        for key, items in groups.items():
            n = len(items)
            out[key] = {
                "total": n,
                "containment_final_rate": round(
                    sum(1 for c in items if self._final_contained(c)) / n, 4) if n else 0.0,
                "escalation_rate": round(
                    sum(1 for c in items if c.escalated) / n, 4) if n else 0.0,
                "abandonment_rate": round(
                    sum(1 for c in items if c.abandoned) / n, 4) if n else 0.0,
            }
        return out

    def _by_hour(self, calls: list) -> dict:
        groups = defaultdict(list)
        for c in calls:
            if c.started_at:
                hour = time.strftime("%H", time.localtime(c.started_at))
                groups[hour].append(c)
        return {h: {"total": len(v),
                    "abandonment_rate": round(
                        sum(1 for c in v if c.abandoned) / len(v), 4)}
                for h, v in sorted(groups.items())}

    def purge_expired(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else float(now)
        cutoff = now - self.retention_days * 86400
        with self._lock:
            before = len(self._calls)
            self._calls = [c for c in self._calls
                           if not c.started_at or c.started_at >= cutoff]
            return before - len(self._calls)

    def analytics_transcripts(self) -> list:
        with self._lock:
            return [{"trace_id": c.trace_id, "transcript": c.transcript}
                    for c in self._calls]

    def render_text(self, now: Optional[float] = None) -> str:
        s = self.compute(now)
        return (f"Calls: {s['total_calls']} | Containment (final, "
                f"{self.window_hours:.0f}h): {s['containment_final_rate']:.1%} | "
                f"Provisional: {s['containment_provisional_rate']:.1%} | "
                f"Escalation: {s['escalation_rate']:.1%} "
                f"{s['escalation_by_reason']} | Abandonment: "
                f"{s['abandonment_rate']:.1%} | FCR: {s['fcr_rate']:.1%} | "
                f"AHT: {s['aht_s']}s | Cost/contained: "
                f"{s['cost_per_contained_call']}")
