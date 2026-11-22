"""Tests for expert/systems-arch-m3 (6 approaches). Stdlib only; run:
    PYTHONPATH=. python3 -m pytest tests/test_systems_arch_m3.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.contracts import (  # noqa: E402
    CallSession, CallerInfo, Decision, DegradationMode, HandoffReason,
    KnowledgeStatus, Priority, Skill, TenantContext, TranscriptTurn,
)
from src.telephony.media_gateway import (  # noqa: E402
    AudioFrame, GatewayConfig, JitterBuffer, MediaGateway,
    VoiceActivityDetector,
)
from src.grounding.tool_gateway import (  # noqa: E402
    InMemoryInventoryAdapter, InMemoryOrderAdapter, ToolGateway,
)
from src.handoff.handoff_service import Agent, HandoffService, build_context_package  # noqa: E402
from src.knowledge.ingestion_pipeline import (  # noqa: E402
    HybridRetriever, KnowledgeDoc, KnowledgeStore, chunk_text,
    run_regression,
)
from src.platform.scaling import (  # noqa: E402
    Autoscaler, BulkheadManager, CostTracker, Release, ScalingMetrics,
    shed_decision,
)


def _session(call_id="C1", skill=Skill.ORDER):
    return CallSession(call_id=call_id, tenant=TenantContext("shop-1", "shop-1"),
                       caller=CallerInfo(phone="0901234567"),
                       transcript=[TranscriptTurn("caller", "Cho tôi hỏi đơn DH240101")],
                       slots={"intent": "tra_don", "order_code": "DH240101"},
                       skill=skill)


def _loud_frame(seq, ts):
    return AudioFrame(seq, ts, samples=[0.5] * 160)


# --- 01 media gateway ---
def test_barge_in_stops_tts_within_150ms():
    stopped = []
    class FakeTTS:
        def stop(self, cid): stopped.append(cid)
        def play(self, cid, text): pass
    gw = MediaGateway(GatewayConfig(), tts=FakeTTS(), now=lambda: 1000)
    gw.create_session(_session())
    gw.start_tts("C1", "Xin chào")
    gw.feed_audio("C1", _loud_frame(1, 1050))
    gw.feed_audio("C1", _loud_frame(2, 1100))
    assert stopped == ["C1"]
    assert gw._sessions["C1"].barge_in_count == 1


def test_admission_control_queues_on_overload():
    gw = MediaGateway(GatewayConfig(max_concurrent_calls=2))
    d = gw.admit(TenantContext("s"), concurrent_calls=2, cpu_percent=10.0)
    assert not d.admitted and d.mode == DegradationMode.QUEUED and d.queue_eta_seconds > 0


def test_jitter_buffer_reorders_and_drops_duplicates():
    jb = JitterBuffer()
    assert jb.push(AudioFrame(2, 20, [])) == []
    out = jb.push(AudioFrame(1, 0, []))
    assert [f.seq for f in out] == [1, 2]
    assert jb.push(AudioFrame(1, 0, [])) == [] and jb.duplicates == 1


def test_janitor_reaps_orphan():
    gw = MediaGateway(now=lambda: 0)
    gw.create_session(_session())
    assert gw.sweep_orphans(now_ms=31_000) == ["C1"]
    assert gw.active_calls() == 0


def test_vad_silence():
    vad = VoiceActivityDetector()
    assert not vad.is_speech(AudioFrame(1, 0, samples=[0.001] * 160))
    assert vad.is_speech(_loud_frame(1, 0))


# --- 05 tool gateway ---
def _gateway():
    orders = {"DH240101": {"order_code": "DH240101", "phone_suffix": "567",
                           "status": "dang_giao", "updated_at": "2026-11-22T10:00:00+07:00"}}
    return ToolGateway({ "get_order_status": InMemoryOrderAdapter(orders),
                         "get_inventory": InMemoryInventoryAdapter(
                             {"XYZ-42": {"sku": "XYZ-42", "qty": 3, "updated_at": "2026-11-22T10:00:00+07:00"}})})


def test_tool_gateway_returns_evidence_with_ownership():
    gw = _gateway()
    r = gw.call_tool(TenantContext("shop-1"), "get_order_status",
                     {"order_code": "DH240101", "phone_suffix": "567"},
                     caller_phone="0901234567")
    assert r.ok and r.evidence and r.evidence[0].source_id == "oms"


def test_tool_gateway_rejects_without_ownership_and_unknown_tool():
    gw = _gateway()
    r = gw.call_tool(TenantContext("shop-1"), "get_order_status",
                     {"order_code": "DH240101", "phone_suffix": "999"},
                     caller_phone="0901234567")
    assert not r.ok and r.status == "rejected" and not r.data
    r2 = gw.call_tool(TenantContext("shop-1"), "drop_table", {})
    assert r2.status == "rejected"


def test_tool_gateway_ticket_idempotent():
    gw = _gateway()
    a = gw.call_tool(TenantContext("shop-1"), "create_callback_ticket",
                     {"phone": "0901234567", "summary": "goi lai"}, idempotency_key="k1")
    b = gw.call_tool(TenantContext("shop-1"), "create_callback_ticket",
                     {"phone": "0901234567", "summary": "goi lai"}, idempotency_key="k1")
    assert a.data["ticket_id"] == b.data["ticket_id"]


# --- 09 handoff ---
def test_handoff_routes_least_loaded_and_warm():
    agents = [Agent("a1", "An", {Skill.ORDER}, active_calls=1),
              Agent("a2", "Binh", {Skill.ORDER}, active_calls=0)]
    svc = HandoffService(agents)
    out = svc.handoff(_session(), HandoffReason.LOW_CONFIDENCE, warm=True)
    assert out.decision == Decision.HANDOFF and out.agent_id == "a2"
    assert out.context_ack and out.transfer_type == "warm"


def test_handoff_no_agent_falls_back_to_callback():
    svc = HandoffService([])
    out = svc.handoff(_session(), HandoffReason.SENSITIVE)
    assert out.decision == Decision.CALLBACK and out.ticket_id.startswith("TKT-")


def test_context_package_contains_transcript_and_no_reask():
    pkg = build_context_package(_session(), HandoffReason.OUT_OF_SCOPE)
    assert pkg.transcript and "DH240101" in pkg.summary


# --- 13 knowledge ---
def _store():
    s = KnowledgeStore()
    s.ingest(KnowledgeDoc("policy-return", "Đổi trả",
                          "Đổi trả trong 7 ngày, sản phẩm còn nguyên tem.",
                          "policy.pdf", version=1), KnowledgeStatus.PUBLISHED)
    s.ingest(KnowledgeDoc("policy-shipping", "Phí ship",
                          "Phí ship Hà Nội 25.000đ, miễn phí từ 500.000đ.",
                          "policy.pdf", version=1), KnowledgeStatus.PUBLISHED)
    return s


def test_chunking_never_splits_mid_sentence():
    chunks = chunk_text("Câu một. Câu hai rất dài " + "x" * 700 + ". Câu ba.")
    assert all(c.endswith(".") for c in chunks)


def test_hybrid_retrieval_returns_cited_chunk():
    hits = HybridRetriever(_store()).search("Đổi trả trong bao lâu?")
    assert hits and hits[0].chunk.doc_id == "policy-return"


def test_regression_blocks_unapproved_change():
    s = _store()
    ret = [c for c in s.published() if c.doc_id == "policy-return"][0]
    golden = [{"question": "Đổi trả trong bao lâu?", "expected_chunk_id": ret.chunk_id}]
    assert run_regression(s, golden).passed


def test_conflict_detection_flags_contradiction():
    s = _store()
    s.ingest(KnowledgeDoc("policy-return", "Đổi trả",
                          "Đổi trả trong 30 ngày, không cần tem.",
                          "policy-v2.pdf", version=2), KnowledgeStatus.PUBLISHED)
    assert s.detect_conflicts()


# --- 17 scaling ---
def test_autoscaler_scales_up_on_calls():
    sc = Autoscaler(now=lambda: 1000.0)
    d = sc.decide(ScalingMetrics(concurrent_calls=300, cpu_percent=50.0,
                                 queue_latency_ms=100.0))
    assert d.action == "scale_up" and d.desired_replicas >= 6


def test_load_shedding_sheds_low_priority_only():
    assert shed_decision(250, 200, Priority.LOW).shed_new_calls
    assert not shed_decision(250, 200, Priority.VIP).shed_new_calls


def test_bulkhead_isolates_ingestion_from_inbound():
    bm = BulkheadManager(inbound=1, ingestion=1)
    assert bm.acquire("ingestion") and bm.acquire("inbound")
    assert not bm.acquire("inbound")
    bm.release("inbound"); assert bm.acquire("inbound")


def test_cost_per_contained_call():
    ct = CostTracker()
    ct.record_call(3.0, contained=True); ct.record_call(3.0, contained=False)
    assert ct.containment_rate == 0.5
    assert abs(ct.cost_per_contained_call - 0.48) < 1e-9


def test_canary_and_rollback():
    rel = Release(version="v2", canary_percent=10, stable_version="v1")
    assert rel.traffic_for_canary(5) and not rel.traffic_for_canary(50)
    assert rel.rollback().version == "v1"
