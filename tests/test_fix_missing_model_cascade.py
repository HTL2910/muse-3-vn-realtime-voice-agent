"""Tests for fix/fix_missing_model_cascade.

Stdlib-only (pytest). Routing, TTL expiry, the no-cross-session
order-cache rule, speech shortening, and cost / Pareto measurement.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from optimization.model_cascade import (  # noqa: E402
    CACHED_VOICE_SENTENCES,
    CostTracker,
    ModelCascade,
    ModelResult,
    ModelTier,
    TTLCache,
    complexity_score,
    pareto_frontier,
    shorten_for_speech,
    split_sentences,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def small_model(text):
    return ModelResult(text="Đơn DH123 đang giao.", confidence=0.95,
                       tier=ModelTier.SMALL, latency_ms=200.0, tokens=50)


def unsure_small_model(text):
    return ModelResult(text="UNKNOWN", confidence=0.30,
                       tier=ModelTier.SMALL, latency_ms=200.0, tokens=50)


def large_model(text):
    return ModelResult(text="Đơn DH123 đang giao, dự kiến ngày mai.",
                       confidence=0.97, tier=ModelTier.LARGE,
                       latency_ms=900.0, tokens=200)


# --- routing -----------------------------------------------------------------

def test_simple_lookup_goes_small_complex_goes_large():
    cascade = ModelCascade(small_model=small_model, large_model=large_model)
    tier, score = cascade.route("đơn của tôi đâu rồi", "track_order")
    assert tier == ModelTier.SMALL and score < 0.5
    tier2, score2 = cascade.route(
        "tại sao đơn của tôi bị trả lại và sau đó tôi phải làm gì để được bồi thường",
        "complaint_severe")
    assert tier2 == ModelTier.LARGE and score2 >= 0.5


def test_complexity_score_orders_simple_below_complex():
    assert complexity_score("tra đơn") < complexity_score(
        "tại sao đơn bị trả lại và sau đó tôi phải làm gì nếu không đồng ý")
    assert 0.0 <= complexity_score("tra đơn") <= 1.0


def test_low_confidence_small_falls_back_to_large_once():
    cascade = ModelCascade(small_model=unsure_small_model, large_model=large_model)
    d = cascade.answer("câu khó", intent="track_order")
    assert d.tier == ModelTier.LARGE
    assert d.fallback_used
    assert d.result.confidence == 0.97
    assert len(cascade.decision_log) == 1  # one decision, not a loop


def test_verified_template_answer_served_from_cache_without_a_model_call():
    calls = {"n": 0}

    def counting_small(text):
        calls["n"] += 1
        return small_model(text)

    cascade = ModelCascade(small_model=counting_small, large_model=large_model)
    cascade.set_template("faq", "phí ship bao nhiêu", "Phí ship là 35000 đồng.")
    d = cascade.answer("phí ship bao nhiêu", intent="faq")
    assert d.from_cache and d.cost_usd == 0.0
    assert calls["n"] == 0
    assert d.result.text == "Phí ship là 35000 đồng."


# --- caches -------------------------------------------------------------------

def test_ttl_cache_expires_and_evicts_lru():
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60.0, max_size=2, clock=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    clock.advance(61)
    assert cache.get("a") is None  # expired
    assert cache.get("b") is None
    cache.set("x", 1)
    cache.set("y", 2)
    cache.set("z", 3)  # max_size=2: oldest evicted
    assert cache.get("x") is None
    assert cache.get("z") == 3


def test_faq_cache_hit_and_expiry():
    clock = FakeClock()
    cascade = ModelCascade(small_model=small_model, large_model=large_model, clock=clock)
    cascade.set_faq("return-policy", "Đổi trả trong 7 ngày.")
    assert cascade.get_faq("return-policy") == "Đổi trả trong 7 ngày."
    clock.advance(301)
    assert cascade.get_faq("return-policy") is None


def test_order_cache_never_served_across_sessions():
    clock = FakeClock()
    cascade = ModelCascade(small_model=small_model, large_model=large_model, clock=clock)
    cascade.set_order("session-a", "DH123", {"status": "đang giao"})
    assert cascade.get_order("session-a", "DH123") == {"status": "đang giao"}
    # Another session / another customer must never hit this entry.
    assert cascade.get_order("session-b", "DH123") is None
    assert cascade.get_order("session-a", "DH999") is None
    clock.advance(61)  # short TTL: order data goes stale fast
    assert cascade.get_order("session-a", "DH123") is None


def test_clear_session_removes_only_that_sessions_orders():
    cascade = ModelCascade(small_model=small_model, large_model=large_model)
    cascade.set_order("s1", "DH1", {"status": "a"})
    cascade.set_order("s2", "DH2", {"status": "b"})
    cascade.clear_session("s1")
    assert cascade.get_order("s1", "DH1") is None
    assert cascade.get_order("s2", "DH2") == {"status": "b"}


def test_voice_cache_only_for_allowlisted_sentences():
    cascade = ModelCascade(small_model=small_model, large_model=large_model)
    opening = "Dạ, em nghe ạ."
    assert opening in CACHED_VOICE_SENTENCES
    assert cascade.set_voice(opening, b"audio-opening")
    assert cascade.get_voice(opening) == b"audio-opening"
    # A sentence with order data must never be cached as voice.
    assert not cascade.set_voice("Đơn DH123 đang giao.", b"audio-order")
    assert cascade.get_voice("Đơn DH123 đang giao.") is None


# --- speech shortening ----------------------------------------------------------

def test_shorten_for_speech_keeps_one_main_idea():
    text = ("Đơn DH123 đang giao. Dự kiến ngày mai anh nhận được. "
            "Nếu anh không có nhà, shipper sẽ gọi lại.")
    assert shorten_for_speech(text) == "Đơn DH123 đang giao."
    assert split_sentences("Một câu. Hai câu!") == ["Một câu.", "Hai câu!"]
    cascade = ModelCascade(small_model=small_model, large_model=large_model)
    assert cascade.speak(text) == ["Đơn DH123 đang giao."]


# --- cost / Pareto ---------------------------------------------------------------

def test_cost_per_minute_and_per_contained_call():
    tracker = CostTracker()
    tracker.record(ModelTier.SMALL, latency_ms=12000.0, tokens=1000, contained=True)
    tracker.record(ModelTier.LARGE, latency_ms=48000.0, tokens=1000, contained=True)
    tracker.record(ModelTier.SMALL, latency_ms=12000.0, tokens=1000, contained=False)
    # Costs: small 0.001 + large 0.010 + small 0.001 = 0.012 USD.
    assert tracker.total_cost_usd == pytest.approx(0.012)
    # Total time 72 s = 1.2 min -> 0.012 / 1.2 = 0.01 USD/min.
    assert tracker.cost_per_minute == pytest.approx(0.01)
    # 0.012 USD over 2 contained calls.
    assert tracker.cost_per_contained_call == pytest.approx(0.006)
    assert tracker.small_share == pytest.approx(2 / 3)


def test_cost_per_contained_call_is_none_without_contained_calls():
    tracker = CostTracker()
    tracker.record(ModelTier.SMALL, latency_ms=1000.0, tokens=10, contained=False)
    assert tracker.cost_per_contained_call is None


def test_pareto_frontier_drops_dominated_points():
    points = [(200.0, 0.010), (400.0, 0.005), (600.0, 0.008), (800.0, 0.002)]
    # (600, 0.008) is dominated by (400, 0.005): slower AND dearer.
    assert pareto_frontier(points) == [(200.0, 0.010), (400.0, 0.005), (800.0, 0.002)]


def test_cascade_records_cost_and_small_share():
    cascade = ModelCascade(small_model=small_model, large_model=large_model)
    cascade.answer("tra đơn", intent="track_order", contained=True)
    cascade.answer("tra đơn", intent="track_order", contained=True)
    assert cascade.cost_tracker.small_share == 1.0
    assert cascade.cost_tracker.cost_per_contained_call is not None
    assert cascade.cost_tracker.cost_per_contained_call > 0
