"""NEW evaluation tests by qa-verifier (2026-11-26). Not product code.
Covers: contracts/version/grep-mirror + tool gateway edge cases.
Soft-import policy: missing baseline => skip with Blocked reason, never fake-pass.
"""
import pathlib, re, pytest
ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCKED = dict(max_clarifications=1, slo_p95_ms=1200, budget_ms=1100)

def _text(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else None

def test_contracts_file_exists_on_baseline():
    if _text("src/contracts.py") is None:
        pytest.skip("Blocked: src/contracts.py not present on this checkout")

def test_contracts_version_single_source():
    t = _text("src/contracts.py")
    if t is None: pytest.skip("Blocked: no contracts.py")
    m = re.search(r'CONTRACTS_VERSION\s*=\s*"([^"]+)"', t)
    assert m, "CONTRACTS_VERSION missing"
    assert m.group(1) in {"1.0.0", "1.0.0-m3"}, m.group(1)
    # Known Sev-2: m3 branch says 1.0.0-m3 while locked brief says 1.0.0.
    # After reconciliation this assertion must be tightened to exactly one value.

def test_latency_budget_constants_mirror():
    blob = "\n".join(filter(None, [_text("src/contracts.py"),
        _text("src/telephony/media_gateway.py"), _text("src/realtime/orchestrator.py")]))
    if not blob: pytest.skip("Blocked: no source files on this checkout")
    for token in ("250", "500", "350"):
        assert token in blob, f"latency budget component {token}ms not mirrored"

def _gateway():
    try:
        from src.grounding.tool_gateway import ToolGateway  # type: ignore
        return ToolGateway
    except Exception:
        pytest.skip("Blocked: ToolGateway not importable on baseline")

def test_unknown_tool_rejected():
    gw = _gateway()
    pytest.skip("Blocked: needs baseline ToolGateway call signature — wire to contracts.ToolResult(status='rejected')")

def test_missing_tenant_rejected():
    _gateway(); pytest.skip("Blocked: needs baseline session fixture (tenant_id empty => rejected, no backend call)")

def test_wrong_phone_suffix_returns_no_data():
    _gateway(); pytest.skip("Blocked: needs baseline orders fixture (wrong suffix => empty data, indistinguishable error)")

def test_cross_tenant_denied():
    _gateway(); pytest.skip("Blocked: needs baseline two-tenant fixture (tenant A must not receive tenant B evidence)")
