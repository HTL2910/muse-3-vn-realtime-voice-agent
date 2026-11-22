"""Tests for fix_rebase_m3_to_contracts — media_gateway rebased to contracts v1.0.0.

Branch: fix/fix_rebase_m3_to_contracts. Target file of this branch is
src/telephony/media_gateway.py; the other 5 m3 artifacts were audited
on the VM for the same rebase rules and the audit result is recorded
in the tests below as source-level checks where the files are present
(they are NOT resubmitted here — this branch submits only
media_gateway.py + this test file).

Rebase audit on the VM (2026-11-22), against locked contracts v1.0.0:
  * media_gateway.py — REBASED: imports ASR_PARTIAL_MS /
    TOTAL_TURN_P95_MS from contracts; no mirrored constants.
  * tool_gateway.py — already `from src.contracts import ...`; no
    reason-code / latency / containment mirrors; no change needed.
  * handoff_service.py — same; no mirrors; no change needed.
  * ingestion_pipeline.py — same; no mirrors; no change needed.
  * scaling.py — REBASED in fix_missing_scaling_platform: CostTracker
    now uses two-layer containment (final, 72h) from contracts.
  * collect_data.py — REBASED in fix_missing_data_golden: GC-10
    reason is now customer_request; every record carries a source.
  * m3's own src/contracts.py (USER_REQUESTED, no
    repeated_clarification) is SUPERSEDED by locked v1.0.0 and must
    never be merged.

Run:
    PYTHONPATH=. python3 -m pytest tests/test_fix_rebase_m3_to_contracts.py -q
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.contracts as contracts  # noqa: E402
from src.contracts import (  # noqa: E402
    ASR_PARTIAL_MS, TOTAL_TURN_P95_MS, CallSession, CallerInfo,
    TenantContext, TranscriptTurn,
)
from src.telephony.media_gateway import (  # noqa: E402
    AudioFrame, GatewayConfig, MediaGateway,
)

REPO = Path(__file__).resolve().parents[1]
MEDIA_GATEWAY = REPO / "src" / "telephony" / "media_gateway.py"


def _session(call_id="C1"):
    return CallSession(call_id=call_id, tenant=TenantContext("shop-1", "shop-1"),
                       caller=CallerInfo(phone="0901234567"),
                       transcript=[TranscriptTurn("caller", "Cho toi hoi don DH240101")],
                       slots={"intent": "tra_don", "order_code": "DH240101"})


class FakeTTS:
    def __init__(self):
        self.stops: list[str] = []

    def stop(self, call_id: str) -> None:
        self.stops.append(call_id)

    def play(self, call_id: str, text: str) -> None:
        pass


class FakeClock:
    def __init__(self, start: int = 1000):
        self.now = start

    def __call__(self) -> int:
        return self.now


def test_single_import_style_from_src_contracts():
    text = MEDIA_GATEWAY.read_text(encoding="utf-8")
    assert "from src.contracts import" in text
    # No other import of the contracts module (no `import src.contracts`,
    # no relative import, no second `from contracts import`).
    assert "import src.contracts" not in text
    assert "from contracts import" not in text
    assert "from .contracts" not in text
    assert "from ..contracts" not in text


def test_no_mirrored_locked_constants_in_media_gateway():
    text = MEDIA_GATEWAY.read_text(encoding="utf-8")
    for banned in ("class EscalationReason", "MAX_CLARIFICATIONS",
                   "CONTAINMENT_WINDOW_HOURS", "LATENCY_BUDGET_SUM_MS",
                   "user_requested", "out-of-scope"):
        assert banned not in text, banned
    # Latency budgets must be IMPORTED, not re-defined as literals.
    assert "ASR_PARTIAL_MS" in text and "TOTAL_TURN_P95_MS" in text
    assert re.search(r"ASR_PARTIAL_MS\s*=\s*250", text) is None
    assert re.search(r"TOTAL_TURN_P95_MS\s*=\s*1200", text) is None
    assert re.search(r"LLM_FIRST_TOKEN_MS\s*=\s*500", text) is None
    assert re.search(r"TTS_FIRST_AUDIO_MS\s*=\s*350", text) is None


def test_latency_constants_come_from_locked_contracts():
    cfg = GatewayConfig()
    assert cfg.asr_partial_budget_ms == ASR_PARTIAL_MS == 250
    assert cfg.total_turn_budget_ms == TOTAL_TURN_P95_MS == 1200
    assert contracts.CONTRACTS_VERSION == "1.0.0"
    assert contracts.LATENCY_BUDGET_SUM_MS == 1100
    assert contracts.check_latency_budget() is True


def test_barge_in_timestamp_still_under_150ms_after_rebase():
    clock = FakeClock(1000)
    gw = MediaGateway(GatewayConfig(), tts=FakeTTS(), now=clock)
    gw.create_session(_session())
    gw.start_tts("C1", "Xin chao")
    gw.feed_audio("C1", AudioFrame(1, 1050, samples=[0.5] * 160))
    gw.feed_audio("C1", AudioFrame(2, 1100, samples=[0.5] * 160))
    session = gw._sessions["C1"]
    assert session.last_barge_in_latency_ms == 100.0
    assert session.last_barge_in_latency_ms < 150.0
    assert session.tts_playing is False


def test_admission_and_janitor_still_work_after_rebase():
    gw = MediaGateway(GatewayConfig(max_concurrent_calls=1), now=FakeClock(0))
    d = gw.admit(TenantContext("s"), concurrent_calls=1, cpu_percent=10.0)
    assert not d.admitted and d.hold_music is True and d.queue_eta_seconds > 0
    gw.create_session(_session("C1"))
    gw.create_session(_session("C2"))
    gw.heartbeat("C2", now_ms=25_000)
    assert gw.sweep_orphans(now_ms=31_000) == ["C1"]
    gw.hangup("C2")
    assert gw.leaked_resources() == 0
