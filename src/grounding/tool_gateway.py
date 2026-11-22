"""
Tool gateway - the ONLY path from AI to business data. Fail-closed:
  * AI never touches a DB directly; only the 5 allowlisted tools below,
    each with a strict schema (required + allowed fields).
  * tenant_id / shop_id come ONLY from the authenticated call session.
    A different tenant claim inside params (from prompt/transcript) is
    rejected as an override attempt.
  * Ownership check for order data: order_code + caller phone suffix must
    match the record owner; on mismatch NO data is returned at all.
  * Cross-tenant: an adapter record whose tenant differs from the
    session tenant is rejected and its data is dropped.
  * Per-tool timeout is configurable only inside 800-1500ms; transient
    adapter errors are retried at most max_retries times, other errors
    are never retried.
  * Every successful result carries evidence (source_id / record_id /
    updated_at). A result without evidence becomes an error.
  * Read-only tools (policy / inventory / appointment) may be cached per
    tenant for a short TTL; order status is never cached.
  * create_callback_ticket is the only write tool and requires an
    idempotency_key; a repeated key returns the same ticket.

CONTRACTS_VERSION is imported from src.contracts (locked v1.0.0);
this module defines no mirror of any contracts constant. Stdlib only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.contracts import CONTRACTS_VERSION  # type: ignore


class TransientError(Exception):
    """Adapter error that is safe to retry (timeouts, 502/503 upstream)."""


@dataclass
class AuthenticatedSession:
    """Tenant binding from the telephony layer, NOT from the caller."""
    session_id: str
    tenant_id: str
    shop_id: str = ""
    caller_phone: str = ""
    authenticated: bool = True


@dataclass
class ToolResult:
    tool: str
    ok: bool
    status: str = "ok"          # ok|not_found|rejected|timeout|error
    data: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    error: str = ""
    latency_ms: float = 0.0
    deduplicated: bool = False
    contracts_version: str = CONTRACTS_VERSION


# tool -> schema dict
TOOL_SCHEMAS: dict[str, dict] = {
    "get_order_status": {
        "required": {"order_code", "phone_suffix"},
        "allowed": {"order_code", "phone_suffix"},
        "timeout_ms": 1000, "read_only": True, "cacheable": False},
    "get_inventory": {
        "required": {"sku"},
        "allowed": {"sku", "warehouse_id"},
        "timeout_ms": 800, "read_only": True, "cacheable": True},
    "get_appointment": {
        "required": {"appointment_id"},
        "allowed": {"appointment_id", "phone_suffix"},
        "timeout_ms": 800, "read_only": True, "cacheable": True},
    "get_policy": {
        "required": {"topic"}, "allowed": {"topic"},
        "timeout_ms": 800, "read_only": True, "cacheable": True},
    "create_callback_ticket": {
        "required": {"phone", "summary", "idempotency_key"},
        "allowed": {"phone", "summary", "idempotency_key", "intent",
                    "priority", "window_start", "window_end"},
        "timeout_ms": 1500, "read_only": False, "cacheable": False},
}
ALLOWED_TOOLS = frozenset(TOOL_SCHEMAS)

_FORBIDDEN_PARAM_MARKERS = ("select ", "union select", "drop table",
                            "delete from", "http://", "https://", "../")


def _phone_suffix_match(phone: str, suffix: str) -> bool:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    sfx = "".join(c for c in (suffix or "") if c.isdigit())
    return len(sfx) >= 3 and digits.endswith(sfx)


class ToolGateway:
    """Adapters: callable(tenant_id, shop_id, **params) -> dict with keys
    data (dict), source_id, record_id, updated_at, and for order records
    also owner_phone and record_tenant_id. Adapters are the ONLY place
    that knows about OMS/WMS/CRM/knowledge stores."""

    def __init__(self, adapters: Optional[dict[str, Callable]] = None,
                 timeouts_ms: Optional[dict[str, int]] = None,
                 max_retries: int = 1, cache_ttl_s: float = 60.0):
        self.adapters = dict(adapters or {})
        self.max_retries = int(max_retries)
        self.cache_ttl_s = float(cache_ttl_s)
        self._timeouts = {}
        for tool, schema in TOOL_SCHEMAS.items():
            t = int((timeouts_ms or {}).get(tool, schema["timeout_ms"]))
            if not (800 <= t <= 1500):
                raise ValueError(
                    f"timeout for {tool} must be within 800-1500ms, got {t}")
            self._timeouts[tool] = t
        self._cache: dict[tuple, tuple[float, ToolResult]] = {}
        self._tickets_by_key: dict[str, ToolResult] = {}

    def register_adapter(self, tool: str, fn: Callable) -> None:
        if tool not in TOOL_SCHEMAS:
            raise ValueError(f"unknown tool {tool}")
        self.adapters[tool] = fn

    def call(self, session: Optional[AuthenticatedSession], tool: str,
             params: Optional[dict] = None, transcript: str = "") -> ToolResult:
        params = dict(params or {})
        start = time.monotonic()

        def done(result: ToolResult) -> ToolResult:
            result.latency_ms = round((time.monotonic() - start) * 1000, 3)
            return result

        def rejected(error: str) -> ToolResult:
            return done(ToolResult(tool=tool, ok=False, status="rejected",
                                   error=error))

        # 1) Session / tenant - tenant NEVER comes from params or speech
        if session is None or not session.authenticated or not session.tenant_id:
            return rejected("missing_tenant")
        for claim_key in ("tenant_id", "shop_id"):
            if claim_key in params:
                claimed = params.pop(claim_key)
                expected = (session.tenant_id if claim_key == "tenant_id"
                            else session.shop_id)
                if expected and claimed != expected:
                    return rejected("tenant_override_attempt")

        # 2) Allowlist + strict schema
        if tool not in TOOL_SCHEMAS:
            return rejected("unknown_tool")
        schema = TOOL_SCHEMAS[tool]
        extra = set(params) - schema["allowed"]
        if extra:
            return rejected(f"schema_violation_extra:{sorted(extra)}")
        missing = schema["required"] - set(params)
        if missing:
            return rejected(f"schema_violation_missing:{sorted(missing)}")
        blob = " ".join(str(v).lower() for v in params.values())
        if any(m in blob for m in _FORBIDDEN_PARAM_MARKERS):
            return rejected("suspicious_params")

        # 3) Idempotent write path
        if tool == "create_callback_ticket":
            key = params["idempotency_key"]
            if key in self._tickets_by_key:
                prev = self._tickets_by_key[key]
                prev.deduplicated = True
                return prev

        # 4) Cache (read-only, per tenant, short TTL; never order status)
        cache_key = None
        if schema["cacheable"]:
            cache_key = (session.tenant_id, tool,
                         tuple(sorted(params.items())))
            hit = self._cache.get(cache_key)
            if hit and time.monotonic() - hit[0] < self.cache_ttl_s:
                return hit[1]

        # 5) Adapter execution, bounded retry on transient errors only
        adapter = self.adapters.get(tool)
        if adapter is None:
            return done(ToolResult(tool=tool, ok=False, status="error",
                                   error="no_adapter_registered"))
        raw, timed_out = None, False
        attempts = 0
        while True:
            attempts += 1
            try:
                raw = adapter(session.tenant_id, session.shop_id, **params)
                break
            except TransientError:
                if attempts > self.max_retries:
                    timed_out = True
                    break
            except Exception as exc:  # non-transient: never retry
                return done(ToolResult(tool=tool, ok=False, status="error",
                                       error=f"adapter_error:{type(exc).__name__}"))
        elapsed_ms = (time.monotonic() - start) * 1000
        if timed_out or elapsed_ms > self._timeouts[tool]:
            return done(ToolResult(tool=tool, ok=False, status="timeout",
                                   error="adapter_timeout"))
        if raw is None:
            return done(ToolResult(tool=tool, ok=False, status="not_found"))

        # 6) Cross-tenant guard on the returned record
        record_tenant = raw.get("record_tenant_id") or raw.get("tenant_id")
        if record_tenant and record_tenant != session.tenant_id:
            return rejected("cross_tenant_record")

        # 7) Ownership check for order / appointment data
        if tool in ("get_order_status", "get_appointment"):
            owner_phone = raw.get("owner_phone", "")
            suffix = params.get("phone_suffix", "")
            if tool == "get_order_status" or suffix:
                if not owner_phone or not _phone_suffix_match(owner_phone, suffix):
                    return rejected("ownership_check_failed")

        # 8) Evidence is mandatory
        if not (raw.get("source_id") and raw.get("record_id")
                and raw.get("updated_at")):
            return done(ToolResult(tool=tool, ok=False, status="error",
                                   error="missing_evidence"))
        evidence = [{"source_id": raw["source_id"],
                     "record_id": raw["record_id"],
                     "updated_at": raw["updated_at"]}]
        result = ToolResult(tool=tool, ok=True, status="ok",
                            data=dict(raw.get("data") or {}),
                            evidence=evidence)
        result = done(result)
        if cache_key is not None:
            self._cache[cache_key] = (time.monotonic(), result)
        if tool == "create_callback_ticket":
            self._tickets_by_key[params["idempotency_key"]] = result
        return result
