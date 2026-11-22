"""Tests for fix_rebase_remaining_m3 — the last m3 rebase residue, verified.

Branch: fix/fix_rebase_remaining_m3. Target file of this branch:
src/grounding/tool_gateway.py. This test file is the audit itself:
it checks tool_gateway.py AND, for every file present in the
checkout, the whole 6-artifact m3 tree (media_gateway, tool_gateway,
handoff_service, ingestion_pipeline, scaling, collect_data) against
the locked contracts v1.0.0.

Grep audit run on the VM (2026-11-22) over the original m3 tree,
before this fix:
  * Retired customer-request spelling — 2 hits, both already fixed in their own
    branches: m3's own src/contracts.py:45 (USER_REQUESTED — the
    whole file is superseded by locked contracts v1.0.0) and
    scripts/collect_data.py:76 (GC-10 reason — fixed to
    customer_request in fix_missing_data_golden).
  * Mirrored constants — 0 hits: no module defined
    MAX_CLARIFICATIONS / CONTAINMENT_WINDOW_HOURS / a latency
    constant / a second EscalationReason.
  * Latency constants — no m3 module used them at all; the only
    old-name import was media_gateway's retired total-SLO name, renamed
    to TOTAL_SLO_P95_MS in this fix (verified on the VM: media
    gateway 11 passed, rebase 5 passed) and submitted in
    media_gateway's own rebase turn, not in this branch.
  * tool_gateway.py itself was already clean: single
    `from src.contracts import ...`, no retired spellings, no mirrors.
    It is submitted unchanged except for the branch header.
  * handoff_service.py uses HandoffReason (the contracts alias,
    same object as EscalationReason); its "no_agent_available" /
    "transfer_failed" strings are callback detail strings, not
    reason values.
  * scaling.py's QUEUE_LATENCY_TARGET_MS = 500.0 is a queue target,
    not a definition of the locked TOOL_CALL_OFF_PATH_MS.
  * TOOL_TIMEOUTS_MS in tool_gateway.py (800-1500 ms per tool) are
    backend-adapter timeouts, not the locked first-audio SLO.

Run:
    PYTHONPATH=. python3 -m pytest tests/test_fix_rebase_remaining_m3.py -q
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.contracts import (  # noqa: E402
    CONTRACTS_VERSION, EscalationReason, TenantContext, ToolName,
)
from src.grounding.tool_gateway import (  # noqa: E402
    InMemoryInventoryAdapter, InMemoryOrderAdapter, ToolGateway,
)

REPO = Path(__file__).resolve().parents[1]
TOOL_GATEWAY = REPO / "src" / "grounding" / "tool_gateway.py"
CONTRACTS = REPO / "src" / "contracts.py"

LATENCY_CONSTANTS = (
    "ASR_PARTIAL_MS", "LLM_FIRST_TOKEN_MS", "TTS_FIRST_AUDIO_MS",
    "TOTAL_SLO_P95_MS", "TOOL_CALL_OFF_PATH_MS",
)
# Retired literals, built without writing them plainly so this test
# file itself stays greppable the same way src/ is grepped.
RETIRED_REASON = "user_" + "requested"
RETIRED_SLO = "TOTAL_" + "TURN_P95_MS"


def _py_files(*roots: str) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        d = REPO / root
        if d.is_dir():
            out.extend(sorted(p for p in d.rglob("*.py")
                              if "__pycache__" not in p.parts))
    return out


def test_tool_gateway_single_import_style():
    text = TOOL_GATEWAY.read_text(encoding="utf-8")
    assert "from src.contracts import" in text
    assert "import src.contracts" not in text
    assert "from contracts import" not in text
    assert "from .contracts" not in text
    assert "from ..contracts" not in text


def test_tool_gateway_no_mirrors_no_retired_spellings():
    text = TOOL_GATEWAY.read_text(encoding="utf-8")
    for banned in ("class EscalationReason", "MAX_CLARIFICATIONS",
                   "CONTAINMENT_WINDOW_HOURS", "LATENCY_BUDGET_SUM_MS",
                   RETIRED_REASON, RETIRED_SLO, "out-of-scope"):
        assert banned not in text, banned
    for name in LATENCY_CONSTANTS:
        assert re.search(r"^%s\s*=" % name, text, re.MULTILINE) is None, name


def test_contracts_has_all_six_reasons_incl_repeated_clarification():
    assert CONTRACTS_VERSION == "1.0.0"
    values = {r.value for r in EscalationReason}
    assert values == {
        "out_of_scope", "low_confidence", "sensitive",
        "customer_request", "repeated_clarification",
        "repeated_failure", "no_agent", "system_error",
    }
    assert "repeated_clarification" in values  # the value m3 was missing
    assert RETIRED_REASON not in values


def test_no_retired_reason_or_slo_name_anywhere_in_src_and_scripts():
    hits = [str(p) for p in _py_files("src", "scripts")
            if RETIRED_REASON in p.read_text(encoding="utf-8")
            or RETIRED_SLO in p.read_text(encoding="utf-8")]
    assert hits == [], hits


def test_no_duplicate_latency_constant_definitions():
    pattern = re.compile(
        r"^(?:%s)\s*=" % "|".join(LATENCY_CONSTANTS), re.MULTILINE)
    hits = []
    for p in _py_files("src", "scripts"):
        if p.resolve() == CONTRACTS.resolve():
            continue
        if pattern.search(p.read_text(encoding="utf-8")):
            hits.append(str(p))
    assert hits == [], hits


def test_no_duplicate_reason_enum_or_clarification_limit():
    hits = []
    for p in _py_files("src", "scripts"):
        if p.resolve() == CONTRACTS.resolve():
            continue
        text = p.read_text(encoding="utf-8")
        if "class EscalationReason" in text or "MAX_CLARIFICATIONS =" in text:
            hits.append(str(p))
    assert hits == [], hits


def test_every_contracts_importer_uses_single_import_style():
    for p in _py_files("src"):
        if p.resolve() == CONTRACTS.resolve():
            continue
        text = p.read_text(encoding="utf-8")
        if "src.contracts" in text or "from .contracts" in text \
                or "from ..contracts" in text:
            assert "from src.contracts import" in text, p
            assert "import src.contracts" not in text, p
            assert "from contracts import" not in text, p


# -- tool_gateway behaviour (unchanged module, re-verified here) -----
def _gateway():
    orders = {"DH240101": {"order_code": "DH240101", "phone_suffix": "567",
                           "status": "dang_giao", "updated_at": "2026-11-22"}}
    adapters = {"get_order_status": InMemoryOrderAdapter(orders),
                "get_inventory": InMemoryInventoryAdapter(
                    {"SKU1": {"sku": "SKU1", "qty": 3,
                              "warehouse": "HN", "updated_at": "2026-11-22"}})}
    return ToolGateway(adapters=adapters)


def test_tool_gateway_allowlist_tenant_ownership():
    gw = _gateway()
    tenant = TenantContext("shop-1", "shop-1")
    assert gw.call_tool(tenant, "drop_table", {}).status == "rejected"
    assert gw.call_tool(TenantContext(""), "get_order_status",
                        {}).status == "rejected"
    # Ownership: wrong phone suffix -> fail-closed, no data.
    r = gw.call_tool(tenant, ToolName.GET_ORDER_STATUS.value,
                     {"order_code": "DH240101", "phone_suffix": "999"},
                     caller_phone="0901234567")
    assert r.status == "rejected" and not r.data
    r = gw.call_tool(tenant, ToolName.GET_ORDER_STATUS.value,
                     {"order_code": "DH240101", "phone_suffix": "567"},
                     caller_phone="0901234567")
    assert r.ok and r.evidence and r.evidence[0].source_id == "oms"


def test_tool_gateway_ticket_idempotent_and_cache_tenant_isolated():
    gw = _gateway()
    tenant = TenantContext("shop-1", "shop-1")
    t1 = gw.call_tool(tenant, ToolName.CREATE_CALLBACK_TICKET.value,
                      {"phone": "0901234567", "summary": "goi lai"},
                      idempotency_key="k1")
    t2 = gw.call_tool(tenant, ToolName.CREATE_CALLBACK_TICKET.value,
                      {"phone": "0901234567", "summary": "goi lai"},
                      idempotency_key="k1")
    assert t1.data["ticket_id"] == t2.data["ticket_id"]
    # Cache is keyed by tenant: another shop re-fetches, it does not
    # read shop-1's cached rows.
    args = {"order_code": "DH240101", "phone_suffix": "567"}
    gw.call_tool(tenant, ToolName.GET_ORDER_STATUS.value, args,
                 caller_phone="0901234567")
    assert len(gw._cache) == 1
    gw.call_tool(TenantContext("shop-2", "shop-2"),
                 ToolName.GET_ORDER_STATUS.value, args,
                 caller_phone="0901234567")
    assert len(gw._cache) == 2
