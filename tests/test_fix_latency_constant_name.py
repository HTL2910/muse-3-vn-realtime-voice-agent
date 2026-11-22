"""Tests for fix_latency_constant_name — one SLO constant name, locked.

Branch: fix/fix_latency_constant_name. Target file: src/contracts.py.

New bug found by algo-ml in debate round #3 (never raised before):
two rebases used two different names for the same total SLO of
1200ms — media_gateway (systems-arch) imported TOTAL_TURN_P95_MS,
orchestrator (algo-ml) used TOTAL_SLO_P95_MS. If contracts defined
one name and a module imported the other, the merge would fail at
import time — exactly the dual-definition failure seen in the
multi-account project. Fix: contracts v1.0.0 locks ONE name,
TOTAL_SLO_P95_MS = 1200 (matching the "SLO p95" wording of the
problem statement). The old spelling is retired: it must not appear
anywhere in src/, and CI grep bans it plus any duplicate definition
of a latency constant outside contracts.py.

This branch submits ONLY src/contracts.py + this test file.
media_gateway.py and orchestrator.py are NOT resubmitted here; per
the agreed fix, any module importing the old name must be renamed
to TOTAL_SLO_P95_MS in its own rebase before it counts as merged.

Run:
    PYTHONPATH=. python3 -m pytest tests/test_fix_latency_constant_name.py -q
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.contracts as contracts  # noqa: E402
from src.contracts import (  # noqa: E402
    ASR_PARTIAL_MS, CONTRACTS_VERSION, LATENCY_BUFFER_MS,
    LATENCY_BUDGET_SUM_MS, LLM_FIRST_TOKEN_MS, TOTAL_SLO_P95_MS,
    TOOL_CALL_OFF_PATH_MS, TTS_FIRST_AUDIO_MS, CallMetrics,
    check_latency_budget,
)

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
CONTRACTS = SRC / "contracts.py"

LATENCY_CONSTANTS = (
    "ASR_PARTIAL_MS", "LLM_FIRST_TOKEN_MS", "TTS_FIRST_AUDIO_MS",
    "TOTAL_SLO_P95_MS", "TOOL_CALL_OFF_PATH_MS",
)
# The retired spelling, kept as a literal ONLY in this test file so
# the grep control can assert it never appears in src/.
RETIRED_NAME = "TOTAL_" + "TURN_P95_MS"


def test_single_slo_name_locked():
    assert CONTRACTS_VERSION == "1.0.0"
    assert TOTAL_SLO_P95_MS == 1200
    # The retired name must not exist as an attribute of contracts.
    assert not hasattr(contracts, RETIRED_NAME)


def test_slo_arithmetic_stages_plus_jitter_equals_slo():
    assert ASR_PARTIAL_MS == 250
    assert LLM_FIRST_TOKEN_MS == 500
    assert TTS_FIRST_AUDIO_MS == 350
    assert LATENCY_BUDGET_SUM_MS == 250 + 500 + 350 == 1100
    # 100 ms jitter/headroom: stages + jitter == SLO exactly.
    assert LATENCY_BUDGET_SUM_MS + 100 == TOTAL_SLO_P95_MS
    assert LATENCY_BUFFER_MS == 100
    assert check_latency_budget() is True


def test_tool_call_threshold_unchanged():
    assert TOOL_CALL_OFF_PATH_MS == 500


def test_call_metrics_latency_uses_locked_slo():
    ok = CallMetrics(call_id="C1", tenant_id="s",
                     asr_partial_ms=250, llm_first_token_ms=500,
                     tts_first_audio_ms=350, total_turn_ms=1100)
    assert ok.latency_within_budget() is True
    over = CallMetrics(call_id="C2", tenant_id="s",
                       asr_partial_ms=250, llm_first_token_ms=500,
                       tts_first_audio_ms=350, total_turn_ms=1201)
    assert over.latency_within_budget() is False


def test_ci_grep_bans_retired_name_in_src():
    """The retired name must not appear in any file under src/ —
    including contracts.py itself (its docstring must not spell it)."""
    hits = [str(p) for p in SRC.rglob("*.py")
            if RETIRED_NAME in p.read_text(encoding="utf-8")]
    assert hits == [], hits


def test_ci_grep_bans_duplicate_latency_constant_definitions():
    """No file in src/ other than contracts.py may define (= assign)
    a latency constant. Imports of the names are fine."""
    pattern = re.compile(
        r"^\s*(?:%s)\s*=" % "|".join(LATENCY_CONSTANTS), re.MULTILINE)
    hits = []
    for p in SRC.rglob("*.py"):
        if p.resolve() == CONTRACTS.resolve():
            continue
        if pattern.search(p.read_text(encoding="utf-8")):
            hits.append(str(p))
    assert hits == [], hits


def test_contracts_defines_each_latency_constant_exactly_once():
    text = CONTRACTS.read_text(encoding="utf-8")
    for name in LATENCY_CONSTANTS:
        assert len(re.findall(r"^%s\s*=" % name, text, re.MULTILINE)) == 1, name
