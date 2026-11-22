"""Model cascade, cache and cost/latency optimisation.

fix/fix_missing_model_cascade — approach_15 (P1: not on the core
call path, but required before go-live).

Self-contained, stdlib-only. No import from ``src.contracts``:
rebase verification (fix_rebase_remaining_algo_ml) found no
mirrored contract constant in this module — the only SLO number
is in prose — so there is nothing to import.

Design
------
* Small/fast model first: it handles known repeated questions and
  simple lookups. The large model is called only when the question
  is complex or needs multi-step reasoning, or when the small model
  returns low confidence / UNKNOWN — at most one fallback per turn,
  never a loop.
* Cache, with a hard safety rule: FAQ / policy results and *verified
  template answers* may be cached; order data may be cached only
  inside one session, for a short TTL, and must NEVER be served
  across sessions — serving another customer's order status is a
  data leak, not an optimisation.
* Cached voice: only opening / confirmation sentences (a fixed
  allowlist) have their TTS audio cached. Everything else is
  synthesised fresh, so a cached voice can never speak a wrong
  number or date.
* Spoken answers are shortened to one main idea per turn: the
  first sentence. A voice answer is not a web page.
* Cost is measured, not guessed: cost per AI minute and cost per
  contained call, and a Pareto frontier over (latency, cost) so a
  "cheaper" configuration that blows the p95 < 1200 ms SLO is
  visible as dominated, not as a saving.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "ModelTier",
    "TTLCache",
    "ModelResult",
    "CascadeDecision",
    "CostTracker",
    "ModelCascade",
    "complexity_score",
    "shorten_for_speech",
    "split_sentences",
    "pareto_frontier",
    "SIMPLE_INTENTS",
    "COMPLEX_INTENTS",
    "CACHED_VOICE_SENTENCES",
    "FAQ_TTL_SECONDS",
    "ORDER_TTL_SECONDS",
    "TEMPLATE_TTL_SECONDS",
]

SIMPLE_INTENTS = frozenset({
    "track_order", "check_fee", "check_inventory", "faq",
    "usage_guide", "confirm_info",
})

COMPLEX_INTENTS = frozenset({
    "complaint_severe", "return_policy", "warranty_policy",
    "book_appointment", "multi_step",
})

# Only these exact sentences may have cached TTS audio: they contain
# no numbers, dates, names or order data.
CACHED_VOICE_SENTENCES = frozenset({
    "Dạ, em nghe ạ.",
    "Dạ, em đang kiểm tra cho anh chị ạ.",
    "Cảm ơn anh chị đã gọi ạ.",
    "Dạ, em xin lỗi, em chưa xác minh được thông tin này ạ.",
})

FAQ_TTL_SECONDS = 300.0
ORDER_TTL_SECONDS = 60.0
TEMPLATE_TTL_SECONDS = 3600.0

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")
_MULTI_STEP_MARKERS = ("sau đó", "trước khi", "nếu", "giả sử", "tại sao",
                       "giải thích", "so sánh", "và", "hoặc")


def split_sentences(text: str) -> List[str]:
    return [m.group(0).strip() for m in _SENTENCE_RE.finditer(text) if m.group(0).strip()]


def shorten_for_speech(text: str) -> str:
    """One main idea per turn: keep the first sentence only.

    If the first sentence is very long, cut it at the first clause
    boundary after 120 characters — a caller cannot follow a
    200-character spoken sentence, and the rest can be offered as a
    follow-up ("Anh chị có muốn nghe thêm không ạ?").
    """
    sentences = split_sentences(text)
    if not sentences:
        return ""
    first = sentences[0]
    if len(first) <= 200:
        return first
    for sep in (", ", "; ", " - "):
        cut = first.find(sep, 100)
        if 100 < cut < 200:
            return first[:cut] + "."
    return first[:200].rsplit(" ", 1)[0] + "…"


def complexity_score(text: str, intent: str = "") -> float:
    """Rule-based complexity in [0, 1]. Deterministic and explainable.

    Long questions, multi-step markers, comparisons, explanations
    and multiple entities all push the score up; a short lookup
    question stays near 0. The cascade threshold (default 0.5) is
    applied by :class:`ModelCascade`, not here.
    """
    score = 0.0
    words = text.split()
    if len(words) > 25:
        score += 0.20
    elif len(words) > 15:
        score += 0.10
    lowered = text.lower()
    markers = sum(1 for m in _MULTI_STEP_MARKERS if m in lowered)
    score += min(0.30, 0.15 * markers)
    if len(re.findall(r"\d+", text)) >= 2:
        score += 0.15
    if "?" in text and text.count("?") >= 2:
        score += 0.15
    if intent.lower() in COMPLEX_INTENTS:
        score += 0.30
    return round(min(1.0, score), 4)


class ModelTier(str, Enum):
    SMALL = "small"
    LARGE = "large"


@dataclass
class ModelResult:
    text: str
    confidence: float
    tier: ModelTier
    latency_ms: float = 0.0
    tokens: int = 0


class TTLCache:
    """Bounded LRU cache with TTL, driven by an injectable clock.

    ``clock`` returns seconds (default ``time.monotonic``); tests
    inject a fake clock so expiry is deterministic.
    """

    def __init__(self, *, ttl_seconds: float, max_size: int = 512, clock=None):
        self.ttl_seconds = float(ttl_seconds)
        self.max_size = max_size
        self._clock = clock or time.monotonic
        self._data: "OrderedDict[str, Tuple[object, float]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def _now(self) -> float:
        return float(self._clock() if callable(self._clock) else self._clock.now())

    def get(self, key: str):
        entry = self._data.get(key)
        if entry is None:
            self.misses += 1
            return None
        value, expires = entry
        if self._now() >= expires:
            del self._data[key]
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: str, value: object) -> None:
        if key in self._data:
            del self._data[key]
        self._data[key] = (value, self._now() + self.ttl_seconds)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


@dataclass
class CascadeDecision:
    tier: ModelTier
    result: ModelResult
    from_cache: bool = False
    fallback_used: bool = False
    complexity: float = 0.0
    cost_usd: float = 0.0


@dataclass
class _CostEntry:
    tier: ModelTier
    latency_ms: float
    tokens: int
    cost_usd: float
    contained: bool


class CostTracker:
    """Cost per AI minute and per contained call.

    Prices are per-1k-tokens (USD): small 0.001, large 0.010 by
    default — override them per tenant; the tracker only measures,
    it never invents a price.
    """

    def __init__(self, *, small_price_per_1k: float = 0.001,
                 large_price_per_1k: float = 0.010):
        self.small_price_per_1k = small_price_per_1k
        self.large_price_per_1k = large_price_per_1k
        self._entries: List[_CostEntry] = []

    def price(self, tier: ModelTier, tokens: int) -> float:
        rate = self.small_price_per_1k if tier == ModelTier.SMALL else self.large_price_per_1k
        return tokens / 1000.0 * rate

    def record(self, tier: ModelTier, latency_ms: float, tokens: int,
               *, contained: bool) -> float:
        cost = self.price(tier, tokens)
        self._entries.append(_CostEntry(tier, latency_ms, tokens, cost, contained))
        return cost

    @property
    def total_cost_usd(self) -> float:
        return sum(e.cost_usd for e in self._entries)

    @property
    def total_minutes(self) -> float:
        return sum(e.latency_ms for e in self._entries) / 60000.0

    @property
    def cost_per_minute(self) -> Optional[float]:
        if self.total_minutes <= 0:
            return None
        return self.total_cost_usd / self.total_minutes

    @property
    def cost_per_contained_call(self) -> Optional[float]:
        contained = [e for e in self._entries if e.contained]
        if not contained:
            return None
        return self.total_cost_usd / len(contained)

    @property
    def small_share(self) -> float:
        if not self._entries:
            return 0.0
        return sum(1 for e in self._entries if e.tier == ModelTier.SMALL) / len(self._entries)


def pareto_frontier(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Non-dominated (latency_ms, cost_usd) points, sorted by latency.

    A point is dominated if another point is no worse on both axes
    and strictly better on one. Use it to choose a configuration:
    anything dominated is never the right choice, however cheap it
    looks on one axis alone.
    """
    pts = sorted(set(points))
    frontier: List[Tuple[float, float]] = []
    best_cost = float("inf")
    for latency, cost in pts:
        if cost < best_cost:
            frontier.append((latency, cost))
            best_cost = cost
    return frontier


class ModelCascade:
    """Route each turn to the cheapest tier that can answer it."""

    def __init__(self, *, small_model=None, large_model=None,
                 complexity_threshold: float = 0.5,
                 small_confidence_floor: float = 0.85,
                 clock=None, cost_tracker: Optional[CostTracker] = None):
        self.small_model = small_model
        self.large_model = large_model
        self.complexity_threshold = complexity_threshold
        self.small_confidence_floor = small_confidence_floor
        self.cost_tracker = cost_tracker or CostTracker()
        # Separate caches per data class, with separate TTLs.
        self.faq_cache = TTLCache(ttl_seconds=FAQ_TTL_SECONDS, clock=clock)
        self.template_cache = TTLCache(ttl_seconds=TEMPLATE_TTL_SECONDS, clock=clock)
        self.order_cache = TTLCache(ttl_seconds=ORDER_TTL_SECONDS, clock=clock)
        self.voice_cache = TTLCache(ttl_seconds=TEMPLATE_TTL_SECONDS, clock=clock)
        self.decision_log: List[CascadeDecision] = []

    # -- caches -------------------------------------------------------------
    def get_faq(self, key: str):
        return self.faq_cache.get(key)

    def set_faq(self, key: str, value: object) -> None:
        self.faq_cache.set(key, value)

    def get_template(self, intent: str, query: str):
        return self.template_cache.get(f"{intent}:{query.strip().lower()}")

    def set_template(self, intent: str, query: str, answer: str) -> None:
        """Cache a *verified* template answer only — never raw LLM text."""
        self.template_cache.set(f"{intent}:{query.strip().lower()}", answer)

    def get_order(self, session_id: str, order_id: str):
        """Order data is namespaced by session: another session's
        key can never hit. Callers must still clear on hang-up."""
        return self.order_cache.get(f"{session_id}:{order_id}")

    def set_order(self, session_id: str, order_id: str, value: object) -> None:
        self.order_cache.set(f"{session_id}:{order_id}", value)

    def clear_session(self, session_id: str) -> None:
        for key in list(self.order_cache._data):
            if key.startswith(f"{session_id}:"):
                self.order_cache.invalidate(key)

    def get_voice(self, sentence: str):
        if sentence not in CACHED_VOICE_SENTENCES:
            return None
        return self.voice_cache.get(sentence)

    def set_voice(self, sentence: str, audio: bytes) -> bool:
        if sentence not in CACHED_VOICE_SENTENCES:
            return False
        self.voice_cache.set(sentence, audio)
        return True

    # -- routing ---------------------------------------------------------------
    def route(self, text: str, intent: str = "") -> Tuple[ModelTier, float]:
        score = complexity_score(text, intent)
        if intent.lower() in COMPLEX_INTENTS or score >= self.complexity_threshold:
            return ModelTier.LARGE, score
        return ModelTier.SMALL, score

    def answer(self, text: str, *, intent: str = "", session_id: str = "",
               contained: bool = False) -> CascadeDecision:
        """Answer one turn, with at most one small -> large fallback."""
        cached = self.get_template(intent, text) if intent else None
        if cached is not None:
            result = ModelResult(text=str(cached), confidence=1.0,
                                 tier=ModelTier.SMALL, latency_ms=0.0, tokens=0)
            decision = CascadeDecision(ModelTier.SMALL, result, from_cache=True,
                                       complexity=complexity_score(text, intent),
                                       cost_usd=0.0)
            self.decision_log.append(decision)
            return decision

        tier, score = self.route(text, intent)
        model = self.small_model if tier == ModelTier.SMALL else self.large_model
        if model is None:
            raise ValueError(f"no model configured for tier {tier.value}")
        result = model(text)
        fallback = False
        if (tier == ModelTier.SMALL
                and (result.confidence < self.small_confidence_floor
                     or not result.text.strip()
                     or result.text.strip().upper() == "UNKNOWN")
                and self.large_model is not None):
            result = self.large_model(text)
            tier, fallback = ModelTier.LARGE, True
        cost = self.cost_tracker.record(tier, result.latency_ms, result.tokens,
                                        contained=contained)
        decision = CascadeDecision(tier, result, fallback_used=fallback,
                                   complexity=score, cost_usd=cost)
        self.decision_log.append(decision)
        return decision

    def speak(self, text: str) -> List[str]:
        """Sentences for streaming TTS, shortened to one main idea."""
        return split_sentences(shorten_for_speech(text))
