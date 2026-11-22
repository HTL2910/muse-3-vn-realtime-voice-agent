"""Tests for fix_missing_knowledge_pipeline (approach_13).

Checks agreed by the council:
- draft / unapproved knowledge is never searchable; approval requires a
  named approver; publish supersedes older versions;
- expired and not-yet-effective chunks are never returned;
- two live chunks on the same topic with disagreeing facts are flagged
  CONFLICT, retrieval confidence is halved and needs_escalation is set;
- the golden regression gate blocks publish when a golden answer changes
  outside the approved-change list, and allows it when approved;
- hybrid retrieval returns the right chunk with a citation; tenants are
  isolated.
Portable: repo root derived from this file, no hardcoded paths.
"""
import importlib.util
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ingestion_pipeline", ROOT / "src" / "knowledge" / "ingestion_pipeline.py")
kb = importlib.util.module_from_spec(_spec)
sys.modules["ingestion_pipeline"] = kb
_spec.loader.exec_module(kb)

Doc = kb.KnowledgeDocument
Golden = kb.GoldenQuestion


def pipe_with(doc, approver="truong-nhom"):
    p = kb.KnowledgeIngestionPipeline()
    p.ingest(doc)
    p.approve(doc.doc_id, approver)
    return p


def test_draft_is_not_searchable_until_published():
    p = kb.KnowledgeIngestionPipeline()
    p.ingest(Doc("faq1", "Đổi trả", "Khách được đổi trả trong 7 ngày.",
                 topic="return_policy"))
    assert p.search("đổi trả bao nhiêu ngày").hits == []
    p.approve("faq1", "lead")
    assert p.search("đổi trả bao nhiêu ngày").hits == []  # approved != published
    r = p.publish("faq1")
    assert r.published
    hits = p.search("đổi trả bao nhiêu ngày").hits
    assert hits and "7 ngày" in hits[0].chunk.text


def test_approval_requires_named_approver():
    p = kb.KnowledgeIngestionPipeline()
    p.ingest(Doc("faq1", "t", "Nội dung chính sách đổi trả.", topic="x"))
    try:
        p.approve("faq1", "")
        raise AssertionError("anonymous approval accepted")
    except ValueError:
        pass


def test_publish_unapproved_is_blocked():
    p = kb.KnowledgeIngestionPipeline()
    p.ingest(Doc("faq1", "t", "Chính sách bảo hành 12 tháng.", topic="warranty"))
    r = p.publish("faq1")
    assert not r.published and "not_approved" in r.blocked_reasons


def test_expired_chunk_is_never_returned():
    p = pipe_with(Doc("old", "Chính sách cũ",
                      "Phí giao hàng là 20000 đồng cho mọi đơn.",
                      topic="shipping_fee",
                      effective_from="2024-01-01", effective_to="2024-12-31"))
    p.publish("old")
    assert p.search("phí giao hàng bao nhiêu", at=date(2024, 6, 1)).hits
    assert p.search("phí giao hàng bao nhiêu", at=date(2026, 1, 1)).hits == []


def test_not_yet_effective_chunk_is_not_returned():
    p = pipe_with(Doc("future", "Chính sách mới",
                      "Phí giao hàng là 30000 đồng từ năm sau.",
                      topic="shipping_fee", effective_from="2027-01-01"))
    p.publish("future")
    assert p.search("phí giao hàng", at=date(2026, 6, 1)).hits == []
    assert p.search("phí giao hàng", at=date(2027, 2, 1)).hits


def test_conflicting_chunks_flagged_and_confidence_lowered():
    p = kb.KnowledgeIngestionPipeline()
    p.ingest(Doc("v1", "Đổi trả A", "Khách được đổi trả trong 7 ngày kể từ khi nhận hàng.",
                 topic="return_policy"))
    p.approve("v1", "lead"); p.publish("v1")
    base = p.search("đổi trả trong bao nhiêu ngày")
    base_conf = base.confidence
    assert not base.conflict

    p.ingest(Doc("v2", "Đổi trả B", "Khách được đổi trả trong 30 ngày kể từ khi nhận hàng.",
                 topic="return_policy"))
    p.approve("v2", "lead"); p.publish("v2")
    conflicts = p.detect_conflicts()
    assert conflicts and conflicts[0]["flag"] == "CONFLICT"
    r = p.search("đổi trả trong bao nhiêu ngày")
    assert r.conflict and r.needs_escalation
    assert r.confidence < base_conf


def test_versioning_supersedes_old_version():
    p = pipe_with(Doc("pol", "Bảo hành", "Bảo hành 12 tháng cho sản phẩm.",
                      topic="warranty"))
    p.publish("pol")
    p.ingest(Doc("pol", "Bảo hành", "Bảo hành 24 tháng cho sản phẩm.",
                 topic="warranty"))
    p.approve("pol", "lead", version=2)
    r = p.publish("pol", version=2)
    assert r.published and r.version == 2
    hits = p.search("bảo hành bao nhiêu tháng").hits
    assert hits and hits[0].chunk.version == 2
    assert all(h.chunk.status == "published" for h in hits)


def test_golden_gate_blocks_unapproved_answer_change():
    p = pipe_with(Doc("pol", "Đổi trả", "Khách được đổi trả trong 7 ngày.",
                      topic="return_policy"))
    p.publish("pol")
    golden = [Golden("g1", "đổi trả trong bao nhiêu ngày", "7 ngày")]
    p.ingest(Doc("pol", "Đổi trả", "Khách được đổi trả trong 15 ngày.",
                 topic="return_policy"))
    p.approve("pol", "lead", version=2)
    r = p.publish("pol", version=2, golden=golden)
    assert not r.published
    assert "g1" in r.changed_golden
    assert any("golden_answer_changed_unapproved" in b for b in r.blocked_reasons)
    # Blocked publish must leave the old answer live.
    assert "7 ngày" in p.search("đổi trả trong bao nhiêu ngày").top_text()


def test_golden_gate_allows_approved_change():
    p = pipe_with(Doc("pol", "Đổi trả", "Khách được đổi trả trong 7 ngày.",
                      topic="return_policy"))
    p.publish("pol")
    golden = [Golden("g1", "đổi trả trong bao nhiêu ngày", "15 ngày")]
    p.ingest(Doc("pol", "Đổi trả", "Khách được đổi trả trong 15 ngày.",
                 topic="return_policy"))
    p.approve("pol", "lead", version=2)
    r = p.publish("pol", version=2, golden=golden, approved_changes=["g1"])
    assert r.published
    assert "15 ngày" in p.search("đổi trả trong bao nhiêu ngày").top_text()


def test_hybrid_search_returns_citation():
    p = pipe_with(Doc("ship", "Ship", "Phí giao hàng nội thành là 25000 đồng, giao trong 2 ngày.",
                      topic="shipping_fee", source_uri="sheet://fees"))
    p.publish("ship")
    hit = p.search("phí giao hàng nội thành bao nhiêu").hits[0]
    assert hit.citation["doc_id"] == "ship"
    assert hit.citation["source_uri"] == "sheet://fees"
    assert hit.citation["version"] == 1


def test_tenant_isolation():
    p = pipe_with(Doc("a", "t", "Chính sách riêng của shop A về đổi trả 7 ngày.",
                      topic="return_policy", tenant_id="shopA"))
    p.publish("a")
    assert p.search("đổi trả", tenant_id="shopB").hits == []
    assert p.search("đổi trả", tenant_id="shopA").hits


def test_chunking_splits_long_document():
    long_text = ". ".join(f"Câu số {i} về chính sách giao hàng và đổi trả"
                          for i in range(60)) + "."
    chunks = kb.chunk_text(long_text, max_chars=300)
    assert len(chunks) > 3
    assert all(len(c) <= 320 for c in chunks)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("PASS", fn.__name__)
    print(f"{len(fns)} passed")
