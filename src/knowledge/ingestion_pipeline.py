"""Knowledge ingestion pipeline: versioned, approved, conflict-checked.

fix_missing_knowledge_pipeline — merged from expert/systems-arch-m3
(approach_13). Rules enforced here (all covered by tests):

- Sources: DB/API/Doc/PDF/Web/Sheet are all normalised by the caller into
  a KnowledgeDocument (raw text + source metadata); this pipeline owns
  chunking (Vietnamese structure-aware), metadata, versioning, approval,
  conflict detection, the golden regression gate and retrieval.
- A chunk is searchable ONLY when: status == published, approved by a
  named approver, and effective at query time
  (effective_from <= at <= effective_to). Expired / not-yet-effective /
  draft / unapproved chunks are never returned.
- Versioning: re-ingesting the same doc_id creates version n+1; older
  published versions are superseded on publish of the new one.
- Conflicts: two live chunks for the same tenant+topic whose concrete
  facts disagree (numbers/durations) or whose negation differs are both
  flagged CONFLICT; retrieval over a conflicted topic returns them with
  confidence halved and ``needs_escalation=True`` — the system must hand
  over to a human instead of picking one arbitrarily.
- Golden regression gate on publish: golden questions are answered with
  the currently published set and with the candidate set; if any golden
  answer changes and that question is not in the approved-change list,
  publish is BLOCKED and the candidate stays in draft/approved state.
- Retrieval: hybrid BM25 + vector (token-cosine) with rerank; every hit
  carries a citation (chunk_id, doc_id, version, source) for the
  grounding gateway.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

# Rebased onto contracts v1.0.0 (fix_rebase_remaining_fullstack): this
# module defines no contracts-locked constants of its own; the only
# contracts value it needs is the reason a knowledge CONFLICT hands over
# with — taken from contracts, not mirrored here.
from src.contracts import EscalationReason

CONFLICT_ESCALATION_REASON = EscalationReason.LOW_CONFIDENCE.value

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_PUBLISHED = "published"
STATUS_SUPERSEDED = "superseded"
FLAG_CONFLICT = "CONFLICT"
CONFLICT_CONFIDENCE_FACTOR = 0.5


def _to_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace("đ", "d")
    return re.sub(r"\s+", " ", t).strip()


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", _norm(text))


_NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_NEG_MARKERS = ("khong", "chua", "cam", "mien phi")  # normalised fragments


def _facts(text: str) -> set:
    return set(_NUM_RE.findall(_norm(text)))


def _neg_signature(text: str) -> frozenset:
    n = _norm(text)
    return frozenset(m for m in _NEG_MARKERS if m in n)


@dataclass
class KnowledgeDocument:
    doc_id: str
    title: str
    content: str
    topic: str
    tenant_id: str = "default"
    source_type: str = "doc"          # db|api|doc|pdf|web|sheet
    source_uri: str = ""
    channel: str = ""                 # "" = all channels
    region: str = ""                  # "" = all regions
    effective_from: Optional[Any] = None
    effective_to: Optional[Any] = None
    author: str = ""

    def __post_init__(self):
        self.effective_from = _to_date(self.effective_from)
        self.effective_to = _to_date(self.effective_to)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    topic: str
    text: str
    version: int
    tenant_id: str = "default"
    source_type: str = "doc"
    source_uri: str = ""
    channel: str = ""
    region: str = ""
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    status: str = STATUS_DRAFT
    approver: str = ""
    flags: List[str] = field(default_factory=list)

    def effective_at(self, at: Optional[date]) -> bool:
        at = _to_date(at) or date.today()
        if self.effective_from and at < self.effective_from:
            return False
        if self.effective_to and at > self.effective_to:
            return False
        return True

    def citation(self) -> Dict[str, Any]:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id,
                "version": self.version, "source_uri": self.source_uri,
                "source_type": self.source_type, "topic": self.topic}

    def to_dict(self):
        d = asdict(self)
        d["effective_from"] = str(self.effective_from) if self.effective_from else None
        d["effective_to"] = str(self.effective_to) if self.effective_to else None
        return d


@dataclass
class SearchHit:
    chunk: Chunk
    score: float
    confidence: float
    citation: Dict[str, Any]


@dataclass
class SearchResult:
    hits: List[SearchHit] = field(default_factory=list)
    conflict: bool = False
    needs_escalation: bool = False
    confidence: float = 0.0

    def top_text(self) -> str:
        return self.hits[0].chunk.text if self.hits else ""


@dataclass
class PublishResult:
    published: bool
    doc_id: str
    version: int = 0
    blocked_reasons: List[str] = field(default_factory=list)
    changed_golden: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)


@dataclass
class GoldenQuestion:
    question_id: str
    question: str
    expected_contains: str            # substring (normalised-insensitive)
    tenant_id: str = "default"


def chunk_text(content: str, max_chars: int = 500) -> List[str]:
    """Vietnamese structure-aware chunking: split on headings / blank
    lines first, then on sentence boundaries, respecting max_chars."""
    blocks: List[str] = []
    for para in re.split(r"\n\s*\n|(?=^(?:#|Điều|Muc|Mục)\s)", content or "",
                         flags=re.MULTILINE):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            blocks.append(para)
            continue
        buf = ""
        for sent in re.split(r"(?<=[.;])\s+", para):
            if len(buf) + len(sent) > max_chars and buf:
                blocks.append(buf.strip())
                buf = sent
            else:
                buf = f"{buf} {sent}".strip()
        if buf:
            blocks.append(buf.strip())
    return [b for b in blocks if b]


class KnowledgeIngestionPipeline:
    def __init__(self):
        self.chunks: Dict[str, Chunk] = {}
        self._versions: Dict[str, int] = {}
        self.conflicts: List[Dict[str, Any]] = []

    # -- ingestion ---------------------------------------------------------
    def ingest(self, doc: KnowledgeDocument) -> List[Chunk]:
        version = self._versions.get(doc.doc_id, 0) + 1
        self._versions[doc.doc_id] = version
        made: List[Chunk] = []
        for i, text in enumerate(chunk_text(doc.content)):
            chunk = Chunk(
                chunk_id=f"{doc.doc_id}:v{version}:{i}", doc_id=doc.doc_id,
                topic=doc.topic, text=text, version=version,
                tenant_id=doc.tenant_id, source_type=doc.source_type,
                source_uri=doc.source_uri, channel=doc.channel,
                region=doc.region, effective_from=doc.effective_from,
                effective_to=doc.effective_to)
            self.chunks[chunk.chunk_id] = chunk
            made.append(chunk)
        return made

    add_document = ingest

    def _doc_chunks(self, doc_id: str, version: Optional[int] = None) -> List[Chunk]:
        out = [c for c in self.chunks.values() if c.doc_id == doc_id]
        if version is not None:
            out = [c for c in out if c.version == version]
        return out

    # -- approval ------------------------------------------------------------
    def approve(self, doc_id: str, approver: str,
                version: Optional[int] = None) -> List[Chunk]:
        if not approver:
            raise ValueError("approver_required")
        version = version or self._versions.get(doc_id, 0)
        out = self._doc_chunks(doc_id, version)
        for c in out:
            if c.status == STATUS_DRAFT:
                c.status = STATUS_APPROVED
                c.approver = approver
        return out

    # -- conflict detection -----------------------------------------------------
    def detect_conflicts(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        live = [c for c in self.chunks.values()
                if c.status in (STATUS_APPROVED, STATUS_PUBLISHED)
                and (tenant_id is None or c.tenant_id == tenant_id)]
        found: List[Dict[str, Any]] = []
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if a.topic != b.topic or a.tenant_id != b.tenant_id:
                    continue
                if a.doc_id == b.doc_id and a.version == b.version:
                    continue
                facts_a, facts_b = _facts(a.text), _facts(b.text)
                numeric_clash = bool(facts_a and facts_b and
                                     not (facts_a & facts_b))
                neg_clash = _neg_signature(a.text) != _neg_signature(b.text) \
                    and len(_tokens(a.text)) and \
                    len(set(_tokens(a.text)) & set(_tokens(b.text))) >= 3
                if numeric_clash or neg_clash:
                    for c in (a, b):
                        if FLAG_CONFLICT not in c.flags:
                            c.flags.append(FLAG_CONFLICT)
                    entry = {"topic": a.topic, "tenant_id": a.tenant_id,
                             "chunks": [a.chunk_id, b.chunk_id],
                             "flag": FLAG_CONFLICT}
                    if entry not in self.conflicts:
                        self.conflicts.append(entry)
                    found.append(entry)
        return found

    # -- retrieval (hybrid BM25 + vector, reranked) ------------------------------
    def _live_chunks(self, tenant_id: str, channel: str, region: str,
                     at: Optional[date], extra_ids: Optional[set] = None,
                     include_ids: Optional[set] = None) -> List[Chunk]:
        out = []
        for c in self.chunks.values():
            if include_ids is not None:
                if c.chunk_id not in include_ids:
                    continue
            elif c.status != STATUS_PUBLISHED:
                continue
            if c.tenant_id != tenant_id:
                continue
            if c.channel and channel and c.channel != channel:
                continue
            if c.region and region and c.region != region:
                continue
            if not c.effective_at(at):
                continue
            out.append(c)
        return out

    def _score(self, query_tokens: Counter, chunk: Chunk,
               doc_freq: Counter, n_docs: int) -> float:
        ctoks = _tokens(chunk.text)
        ccount = Counter(ctoks)
        # BM25-lite
        bm25 = 0.0
        dl = max(1, len(ctoks))
        for tok, qf in query_tokens.items():
            if tok not in ccount:
                continue
            df = max(1, doc_freq.get(tok, 1))
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            tf = ccount[tok]
            bm25 += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * dl / 40.0))
        # Vector cosine over token counts
        dot = sum(query_tokens[t] * ccount.get(t, 0) for t in query_tokens)
        qn = math.sqrt(sum(v * v for v in query_tokens.values())) or 1.0
        cn = math.sqrt(sum(v * v for v in ccount.values())) or 1.0
        cosine = dot / (qn * cn)
        return 0.6 * bm25 + 0.4 * cosine * 5.0  # rerank blend

    def search(self, query: str, tenant_id: str = "default", channel: str = "",
               region: str = "", at=None, top_k: int = 3,
               _include_ids: Optional[set] = None) -> SearchResult:
        at = _to_date(at)
        pool = self._live_chunks(tenant_id, channel, region, at,
                                 include_ids=_include_ids)
        if not pool:
            return SearchResult()
        qtoks = Counter(_tokens(query))
        doc_freq: Counter = Counter()
        for c in pool:
            for tok in set(_tokens(c.text)):
                doc_freq[tok] += 1
        scored = []
        for c in pool:
            s = self._score(qtoks, c, doc_freq, len(pool))
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: (-x[0], x[1].chunk_id))
        hits: List[SearchHit] = []
        conflict = False
        max_score = scored[0][0] if scored else 1.0
        for s, c in scored[:top_k]:
            conf = min(1.0, s / max_score) if max_score else 0.0
            if FLAG_CONFLICT in c.flags:
                conflict = True
                conf *= CONFLICT_CONFIDENCE_FACTOR
            hits.append(SearchHit(chunk=c, score=s, confidence=conf,
                                  citation=c.citation()))
        return SearchResult(
            hits=hits, conflict=conflict, needs_escalation=conflict,
            confidence=hits[0].confidence if hits else 0.0)

    retrieve = search

    # -- publish with golden regression gate --------------------------------------
    def _golden_answers(self, golden: Sequence[GoldenQuestion],
                        include_ids: Optional[set] = None) -> Dict[str, str]:
        answers = {}
        for g in golden:
            r = self.search(g.question, tenant_id=g.tenant_id,
                            _include_ids=include_ids)
            answers[g.question_id] = _norm(r.top_text())
        return answers

    def publish(self, doc_id: str, version: Optional[int] = None,
                golden: Optional[Sequence[GoldenQuestion]] = None,
                approved_changes: Optional[Sequence[str]] = None) -> PublishResult:
        version = version or self._versions.get(doc_id, 0)
        candidates = self._doc_chunks(doc_id, version)
        if not candidates:
            return PublishResult(False, doc_id, version,
                                 blocked_reasons=["no_such_document_version"])
        if any(c.status == STATUS_DRAFT for c in candidates):
            return PublishResult(False, doc_id, version,
                                 blocked_reasons=["not_approved"])
        approved_changes = set(approved_changes or [])

        # Golden gate: compare answers before vs with-candidate-live.
        changed: List[str] = []
        if golden:
            before = self._golden_answers(golden)
            candidate_ids = {c.chunk_id for c in self.chunks.values()
                             if c.status == STATUS_PUBLISHED}
            # Candidate version replaces older versions of the same doc.
            candidate_ids = {cid for cid in candidate_ids
                             if self.chunks[cid].doc_id != doc_id}
            candidate_ids |= {c.chunk_id for c in candidates}
            after = self._golden_answers(golden, include_ids=candidate_ids)
            for g in golden:
                exp = _norm(g.expected_contains)
                was_ok = exp in before.get(g.question_id, "")
                is_ok = exp in after.get(g.question_id, "")
                if was_ok != is_ok or (was_ok and before[g.question_id] != after[g.question_id]):
                    changed.append(g.question_id)
            unapproved = [q for q in changed if q not in approved_changes]
            if unapproved:
                return PublishResult(
                    False, doc_id, version,
                    blocked_reasons=[f"golden_answer_changed_unapproved:{q}"
                                     for q in unapproved],
                    changed_golden=changed)

        # Supersede older published versions of this doc, publish candidate.
        for c in self.chunks.values():
            if c.doc_id == doc_id and c.version != version \
                    and c.status == STATUS_PUBLISHED:
                c.status = STATUS_SUPERSEDED
        for c in candidates:
            c.status = STATUS_PUBLISHED
        conflicts = self.detect_conflicts()
        return PublishResult(True, doc_id, version, changed_golden=changed,
                             conflicts=[f"{c['topic']}:{c['chunks']}"
                                        for c in conflicts])


# Alias matching the m3 naming.
IngestionPipeline = KnowledgeIngestionPipeline

__all__ = [
    "STATUS_DRAFT", "STATUS_APPROVED", "STATUS_PUBLISHED", "STATUS_SUPERSEDED",
    "FLAG_CONFLICT", "CONFLICT_ESCALATION_REASON", "KnowledgeDocument", "Chunk", "SearchHit", "SearchResult",
    "PublishResult", "GoldenQuestion", "chunk_text",
    "KnowledgeIngestionPipeline", "IngestionPipeline",
]
