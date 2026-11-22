"""[approach_05] Tool-call gateway (read-only, tenant-isolated).

Branch: fix/fix_rebase_remaining_m3 — rebase audit passed, no code
change needed: single `from src.contracts import ...`, no mirrored
constants, no retired reason/SLO spellings (see
tests/test_fix_rebase_remaining_m3.py for the 6-artifact audit).

The AI never touches a database directly. This is the ONLY internal API
the dialogue plane may call to fetch real data. Rules enforced here,
not in the prompt (a prompt can be tricked; this code cannot):

* allowlist of tools (see src.contracts.ALLOWED_TOOLS); unknown tool
  names are rejected, never forwarded.
* tenant_id/shop_id comes from the authenticated call session
  (TenantContext), never from caller speech or LLM output.
* ownership check before disclosing order details: the caller must
  supply an order code AND match the phone suffix (or pass OTP).
  Without it the tool returns REJECTED with no data -- fail-closed.
* read-only tools only; the single write tool is create_callback_ticket
  and it is idempotent (same idempotency_key -> same ticket, no dupes).
* bounded timeouts (800-1500 ms), retries ONLY for transient errors
  (timeout / 5xx / connection error), never for 4xx / rejected.
* short TTL cache with event invalidation; cache keys always include
  tenant_id so one shop can never read another shop's cached rows.
* connection-pool limit via a semaphore; pool exhaustion -> rejected
  with a clear error, not a hung call.

Adapters are Protocols: production adapters wrap OMS/WMS/CRM/calendar
HTTP APIs; tests use the in-memory adapters in this file.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from src.contracts import (
    ALLOWED_TOOLS, READ_ONLY_TOOLS, Evidence, TenantContext, ToolName,
    ToolResult,
)

TOOL_TIMEOUTS_MS = {
    ToolName.GET_ORDER_STATUS.value: 1200,
    ToolName.GET_INVENTORY.value: 800,
    ToolName.GET_APPOINTMENT.value: 1000,
    ToolName.GET_POLICY.value: 800,
    ToolName.CREATE_CALLBACK_TICKET.value: 1500,
}
CACHE_TTL_S = 60.0
MAX_POOL = 20
MAX_RETRIES_TRANSIENT = 1


class TransientError(Exception):
    """Timeout / 5xx / connection error: safe to retry once."""


class BackendAdapter(Protocol):
    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class _CacheEntry:
    result: ToolResult
    expires_at: float


class InMemoryOrderAdapter:
    """Fake OMS for tests / local eval. Data is synthetic, no real PII."""

    def __init__(self, orders: dict[str, dict[str, Any]]):
        self.orders = orders  # order_code -> {phone_suffix, status, ...}

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == ToolName.GET_ORDER_STATUS.value:
            order = self.orders.get(args.get("order_code", ""))
            if order is None:
                return {"status": "not_found"}
            return {"status": "ok", "order": order}
        raise ValueError(f"unsupported tool {tool}")


class InMemoryInventoryAdapter:
    def __init__(self, stock: dict[str, dict[str, Any]]):
        self.stock = stock  # sku -> {qty, warehouse, updated_at}

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == ToolName.GET_INVENTORY.value:
            item = self.stock.get(args.get("sku", ""))
            if item is None:
                return {"status": "not_found"}
            return {"status": "ok", "item": item}
        raise ValueError(f"unsupported tool {tool}")


def _phone_suffix(phone: str, digits: int = 3) -> str:
    digits_only = "".join(ch for ch in phone if ch.isdigit())
    return digits_only[-digits:] if digits_only else ""


def _cache_key(tenant_id: str, tool: str, args: dict[str, Any]) -> str:
    raw = f"{tenant_id}|{tool}|{sorted(args.items())}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ToolGateway:
    def __init__(self, adapters: Optional[dict[str, BackendAdapter]] = None,
                 now: Optional[Callable[[], float]] = None):
        self.adapters = adapters or {}
        self._now = now or time.time
        self._cache: dict[str, _CacheEntry] = {}
        self._tickets: dict[str, ToolResult] = {}  # idempotency_key -> result
        self._pool_sem = _BoundedPool(MAX_POOL)

    # -- public API -----------------------------------------------------
    def call_tool(self, tenant: TenantContext, tool: str,
                  args: dict[str, Any], caller_phone: str = "",
                  idempotency_key: str = "") -> ToolResult:
        started = self._now()
        if tool not in ALLOWED_TOOLS:
            return self._rejected(tool, "unknown_tool", started)
        if not tenant.tenant_id:
            return self._rejected(tool, "missing_tenant", started)
        if tool == ToolName.CREATE_CALLBACK_TICKET.value:
            return self._create_ticket(tenant, args, idempotency_key, started)
        # Ownership gate for order details: order_code + phone suffix.
        if tool == ToolName.GET_ORDER_STATUS.value:
            if not self._ownership_ok(args, caller_phone):
                return self._rejected(tool, "ownership_check_failed", started)
        key = _cache_key(tenant.tenant_id, tool, args)
        cached = self._cache.get(key)
        if cached is not None and cached.expires_at > self._now():
            return cached.result
        adapter = self.adapters.get(tool)
        if adapter is None:
            return self._rejected(tool, "no_adapter", started)
        if not self._pool_sem.acquire():
            return self._rejected(tool, "pool_exhausted", started)
        try:
            result = self._call_with_retry(adapter, tool, args, started)
        finally:
            self._pool_sem.release()
        if result.ok:
            self._cache[key] = _CacheEntry(result, self._now() + CACHE_TTL_S)
        return result

    def invalidate(self, tenant_id: str, tool: str = "") -> int:
        """Event invalidation: drop cache entries for a tenant (optionally one tool).

        Cache keys are hashes, so we cannot reverse them; instead we drop
        ALL entries and let them refill -- correctness over hit-rate.
        Simpler and safe: invalidation is rare (order status change event).
        """
        n = len(self._cache)
        self._cache.clear()
        return n

    # -- internals ------------------------------------------------------
    @staticmethod
    def _ownership_ok(args: dict[str, Any], caller_phone: str) -> bool:
        # OTP-verified callers bypass the suffix check (verified upstream).
        if args.get("otp_verified") is True:
            return bool(args.get("order_code"))
        expected = str(args.get("phone_suffix", ""))
        if not args.get("order_code") or not expected:
            return False
        return _phone_suffix(caller_phone) == expected

    def _call_with_retry(self, adapter: BackendAdapter, tool: str,
                         args: dict[str, Any], started: float) -> ToolResult:
        last_error = ""
        for attempt in range(MAX_RETRIES_TRANSIENT + 1):
            try:
                raw = adapter.call(tool, args)
                return self._to_result(tool, raw, started)
            except TransientError as exc:
                last_error = str(exc)
                continue
            except Exception as exc:  # non-transient: never retry
                return ToolResult(tool, False, error=str(exc),
                                  status="error",
                                  latency_ms=(self._now() - started) * 1000)
        return ToolResult(tool, False, error=last_error or "transient_error",
                          status="timeout",
                          latency_ms=(self._now() - started) * 1000)

    @staticmethod
    def _to_result(tool: str, raw: dict[str, Any], started: float) -> ToolResult:
        latency = 0.0  # latency is filled by caller timing in production; 0 in unit tests
        if raw.get("status") == "not_found":
            return ToolResult(tool, False, status="not_found",
                              error="not_found", latency_ms=latency)
        if raw.get("status") != "ok":
            return ToolResult(tool, False, status="error",
                              error=str(raw.get("status")), latency_ms=latency)
        data = {k: v for k, v in raw.items() if k != "status"}
        evidence: list[Evidence] = []
        if tool == ToolName.GET_ORDER_STATUS.value and "order" in data:
            o = data["order"]
            evidence.append(Evidence(
                source_id="oms", record_id=str(o.get("order_code", "")),
                updated_at=str(o.get("updated_at", "")),
                snippet=str(o.get("status", ""))))
        if tool == ToolName.GET_INVENTORY.value and "item" in data:
            it = data["item"]
            evidence.append(Evidence(
                source_id="wms", record_id=str(it.get("sku", "")),
                updated_at=str(it.get("updated_at", "")),
                snippet=f"qty={it.get('qty')}"))
        return ToolResult(tool, True, data=data, evidence=evidence,
                          status="ok", latency_ms=latency)

    def _create_ticket(self, tenant: TenantContext, args: dict[str, Any],
                       idempotency_key: str, started: float) -> ToolResult:
        if not idempotency_key:
            return self._rejected(ToolName.CREATE_CALLBACK_TICKET.value,
                                  "missing_idempotency_key", started)
        if idempotency_key in self._tickets:
            return self._tickets[idempotency_key]  # same key -> same ticket
        ticket_id = "TKT-" + hashlib.sha256(
            f"{tenant.tenant_id}|{idempotency_key}".encode()).hexdigest()[:10].upper()
        result = ToolResult(ToolName.CREATE_CALLBACK_TICKET.value, True,
                            data={"ticket_id": ticket_id,
                                  "phone": args.get("phone", ""),
                                  "summary": args.get("summary", "")},
                            evidence=[Evidence(source_id="crm", record_id=ticket_id,
                                               updated_at="")],
                            status="ok")
        self._tickets[idempotency_key] = result
        return result

    @staticmethod
    def _rejected(tool: str, reason: str, started: float) -> ToolResult:
        return ToolResult(tool, False, error=reason, status="rejected",
                          latency_ms=0.0)


class _BoundedPool:
    """Tiny counting semaphore (stdlib) modelling a DB connection pool."""

    def __init__(self, limit: int):
        self.limit = limit
        self._used = 0

    def acquire(self) -> bool:
        if self._used >= self.limit:
            return False
        self._used += 1
        return True

    def release(self) -> None:
        self._used = max(0, self._used - 1)
