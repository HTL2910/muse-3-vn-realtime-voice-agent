 — phần 2/2 (nối tiếp phần 1, kết thúc file)

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
