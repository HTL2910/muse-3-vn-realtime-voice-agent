"""Tests for fix/fix_missing_vietnamese_normalizer.

Stdlib-only (pytest). WER is asserted per (region, noise) cell —
never as one overall number — on a small noisy multi-voice set
built into this file, because data/golden/ is not on main yet.
Chưa chạy — kết quả thật do CI báo lại.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voice.vietnamese_normalizer import (  # noqa: E402
    HOMOPHONES,
    NoiseLevel,
    Region,
    VietnameseNormalizer,
    char_error_rate,
    evaluate_wer,
    fuzzy_match,
    normalize_phone,
    normalize_text,
    parse_spoken_order_code,
    phonetic_key,
    resolve_entity,
    strip_diacritics,
    word_error_rate,
    WerCase,
)

PRODUCTS = ["áo sơ mi trắng", "áo thun đen", "giày thể thao", "túi xách da", "đồng hồ nam"]


# --- cleaning / undiacritized -------------------------------------------

def test_normalize_text_is_idempotent_and_drops_hesitations():
    assert normalize_text("ừm à đơn hàng của tôi đâu rồi") == "đơn hàng của tôi đâu rồi"
    once = normalize_text("don hang cua toi dau roi")
    assert once == "đơn hàng của tôi đâu rồi"
    assert normalize_text(once) == once
    assert normalize_text("") == ""


def test_undiacritized_phrases_restored():
    assert normalize_text("tra don") == "tra đơn"
    assert normalize_text("doi tra bao hanh") == "đổi trả bảo hành"
    assert normalize_text("phi ship bao nhieu tien") == "phí ship bao nhiêu tiền"
    assert normalize_text("dat lich gap nhan vien") == "đặt lịch gặp nhân viên"


def test_strip_diacritics():
    assert strip_diacritics("đơn hàng") == "don hang"
    assert strip_diacritics("Nguyễn") == "Nguyen"


# --- dialects ------------------------------------------------------------

def test_dialect_variants_map_to_same_canonical_form():
    # South "trái", Central "mô/răng" must not become different intents.
    assert normalize_text("trái cây này bao nhiêu tiền") == "quả cây này bao nhiêu tiền"
    assert normalize_text("mô răng") == "đâu sao"
    assert normalize_text("tô này nè") == "bát này này"


def test_homophone_dictionary_is_dictionary_driven_not_blind_swap():
    # "sáu" (six) must survive: a blind s->x swap would corrupt it.
    assert normalize_text("sáu giờ") == "sáu giờ"
    assert normalize_text("xip hàng") == "ship hàng"
    assert normalize_text("đôn hàng") == "đơn hàng"
    assert "đôn" in HOMOPHONES


def test_phonetic_key_collapses_confusable_consonants():
    assert phonetic_key("sáu") == phonetic_key("xáu")
    assert phonetic_key("trả hàng") == phonetic_key("chả hàng")
    assert phonetic_key("giá tiền") == phonetic_key("dá tiền")
    assert phonetic_key("áo sơ mi") != phonetic_key("áo thun đen")


# --- spoken entities ------------------------------------------------------

def test_parse_spoken_order_code_letter_by_letter():
    assert parse_spoken_order_code("đờ hát một hai ba") == "DH123"
    assert parse_spoken_order_code("mã đơn là DH123") == "DH123"
    assert parse_spoken_order_code("dh 123") == "DH123"
    assert parse_spoken_order_code("xin chào") is None


def test_normalize_phone_spoken_and_plus84():
    assert normalize_phone("không chín không một hai ba bốn năm sáu bảy") == "0901234567"
    assert normalize_phone("+84 901 234 567") == "0901234567"
    assert normalize_phone("090-123-4567") == "0901234567"
    # Too short / wrong length: never guess.
    assert normalize_phone("không chín không") is None
    assert normalize_phone("12345") is None


# --- phonetic-weighted fuzzy matching + 2-step verification ---------------

def test_fuzzy_match_prefers_phonetic_match_over_spelling():
    results = fuzzy_match("áo sơ my", PRODUCTS)
    assert results and results[0].candidate == "áo sơ mi trắng"
    assert results[0].phonetic_match or results[0].score >= 0.55


def test_fuzzy_match_returns_empty_below_threshold():
    assert fuzzy_match("máy bay phản lực", PRODUCTS, threshold=0.55) == []


def test_resolve_entity_clear_case_needs_no_verification():
    res = resolve_entity("áo sơ mi", PRODUCTS)
    assert not res.needs_verification
    assert res.best == "áo sơ mi trắng"


def test_resolve_entity_ambiguous_triggers_two_step_verification():
    # Two near-identical candidates: guessing would ship the wrong item.
    res = resolve_entity("áo sơ mi", ["áo sơ mi trắng", "áo sơ mi đen", "giày thể thao"])
    assert res.needs_verification
    assert res.best is None
    assert res.reason == "ambiguous_top_candidates"
    assert len(res.alternatives) >= 2


def test_resolve_entity_no_candidate_triggers_verification():
    res = resolve_entity("máy bay", PRODUCTS)
    assert res.needs_verification
    assert res.best is None
    assert res.reason == "no_candidate_above_threshold"


# --- WER ------------------------------------------------------------------

def test_word_error_rate_known_values():
    assert word_error_rate("đơn hàng của tôi", "đơn hàng của tôi") == 0.0
    # 1 substitution in 4 words.
    assert word_error_rate("đơn hàng của tôi", "đơn hàng của anh") == 0.25
    # 1 deletion in 4 words.
    assert word_error_rate("đơn hàng của tôi", "đơn hàng tôi") == 0.25
    assert char_error_rate("abc", "abc") == 0.0


def test_wer_is_reported_per_region_and_noise_not_one_number():
    cases = [
        # North, clean: perfect.
        WerCase("đơn hàng của tôi đâu rồi", "đơn hàng của tôi đâu rồi",
                Region.NORTH, NoiseLevel.CLEAN),
        WerCase("tra đơn dh123", "tra đơn dh123",
                Region.NORTH, NoiseLevel.CLEAN),
        # North, high noise: 1 word wrong in 4.
        WerCase("đơn hàng của tôi", "đơn hàng của anh",
                Region.NORTH, NoiseLevel.HIGH),
        # South, clean: 1 word wrong in 5.
        WerCase("phí ship bao nhiêu tiền", "phí ship bao nhiêu tiên",
                Region.SOUTH, NoiseLevel.CLEAN),
        # South, high noise: 2 words wrong in 4.
        WerCase("đơn hàng của tôi", "đơn hàng của anh kia",
                Region.SOUTH, NoiseLevel.HIGH),
        # Central, medium noise: 1 word wrong in 4.
        WerCase("đổi trả bảo hành", "đổi trả bảo hànhh",
                Region.CENTRAL, NoiseLevel.MEDIUM),
    ]
    report = evaluate_wer(cases)
    # Every cell present, with its own count — no single headline WER.
    assert report[("north", "clean")] == {"wer": 0.0, "count": 2.0}
    assert report[("north", "high")] == {"wer": 0.25, "count": 1.0}
    assert report[("south", "clean")] == {"wer": 0.2, "count": 1.0}
    assert report[("south", "high")] == {"wer": 0.5, "count": 1.0}
    assert report[("central", "medium")] == {"wer": 0.25, "count": 1.0}
    # The breakdown exposes what one number would hide: South+high
    # noise is far worse than North+clean.
    assert report[("south", "high")]["wer"] > report[("north", "clean")]["wer"]


def test_facade_end_to_end():
    n = VietnameseNormalizer(region=Region.SOUTH)
    assert n.normalize("don hang") == "đơn hàng"
    assert n.order_code("đờ hát một hai ba") == "DH123"
    assert n.phone("không chín không một hai ba bốn năm sáu bảy") == "0901234567"
    assert n.resolve("áo sơ mi", PRODUCTS).best == "áo sơ mi trắng"
