"""Vietnamese normalizer: 3 dialects, noise, slurred speech, entities.

fix/fix_rebase_remaining_algo_ml — approach_03, rebased to
``src/contracts.py`` v1.0.0.

Rebase verification (this module's contract surface is empty):
a grep over the pre-rebase file found NO mirrored contract
constant — no ``MAX_CLARIFICATIONS``, no escalation-reason
literal, no latency number (250/500/350/1200), no 72h window.
This module defines no shared constant, so there is nothing to
import except the version anchor: it imports ``CONTRACTS_VERSION``
and refuses to load against any other version, so the normalizer
is pinned to the contracts era it was verified against instead
of silently running under a drifted contract. It has no
dependency on ``data/golden/`` (also absent from ``main``): the
homophone dictionary below is embedded in this module so the
normalizer is usable and testable on its own. It is the same data
the golden collector (approach_21) is expected to emit as
``data/golden/homophones.json``; when that file lands, load it and
merge it over ``HOMOPHONES`` instead of editing this module.

What it does, in order
----------------------
1. Clean ASR text: lower-case, drop hesitations (``ừm``, ``à``...),
   collapse whitespace, strip punctuation that is not part of a code.
2. Restore diacritics for common undiacritized phrases/words
   (``don hang`` -> ``đơn hàng``) by longest-phrase match.
3. Map regional lexical / phonetic variants to a canonical form
   (North / Central / South), and correct common l/n, s/x, tr/ch,
   d/gi/r slurs using a dictionary — never by blind letter swap,
   which would corrupt correct words.
4. Extract entities spoken letter-by-letter or digit-by-digit:
   order codes (``đờ hát một hai ba`` -> ``DH123``) and phone
   numbers (``không chín không ...`` -> ``090...``).
5. Phonetic-weighted fuzzy matching for product / person / address
   names: two candidates with the same phonetic key score higher
   than two with the same spelling distance but different sound.
   When the top two candidates are close, the entity is ambiguous
   and the caller must do 2-step verification instead of guessing.
6. WER / CER measurement, always broken down by region and by
   noise level — a single overall WER hides exactly the failures
   that matter (South + high noise).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# --- Contracts version anchor: imported, never mirrored ---------------
# Two import forms cover both layouts: repo-root on sys.path
# (``src.contracts``, the layout on main) and ``src/`` on sys.path.
# This module defines no contract constant of its own; the anchor
# exists so a drifted contracts version breaks the import loudly
# instead of silently running under different shared definitions.
try:
    from src.contracts import CONTRACTS_VERSION  # type: ignore
except ImportError:  # pragma: no cover - alternate layout only
    from contracts import CONTRACTS_VERSION  # type: ignore

if CONTRACTS_VERSION != "1.0.0":
    raise RuntimeError(
        f"vietnamese_normalizer requires src/contracts.py v1.0.0, "
        f"got {CONTRACTS_VERSION!r}"
    )

__all__ = [
    "CONTRACTS_VERSION",
    "Region",
    "NoiseLevel",
    "HOMOPHONES",
    "DIALECT_MAP",
    "UNDIACRITICIZED_PHRASES",
    "normalize_text",
    "strip_diacritics",
    "phonetic_key",
    "levenshtein",
    "word_error_rate",
    "char_error_rate",
    "fuzzy_match",
    "MatchResult",
    "resolve_entity",
    "EntityResolution",
    "parse_spoken_order_code",
    "normalize_phone",
    "evaluate_wer",
    "VietnameseNormalizer",
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Region(str, Enum):
    NORTH = "north"      # Bắc
    CENTRAL = "central"  # Trung
    SOUTH = "south"      # Nam
    UNKNOWN = "unknown"


class NoiseLevel(str, Enum):
    CLEAN = "clean"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# Dictionaries (embedded golden data; see module docstring)
# ---------------------------------------------------------------------------

# Homophone / near-homophone groups: spoken form -> canonical form.
# Only entries that are genuinely confusable in ASR output are listed;
# a blind s/x or l/n swap would corrupt correct words, so correction
# is dictionary-driven, never rule-driven on arbitrary words.
HOMOPHONES: Dict[str, str] = {
    # s / x / sh confusions
    "xip": "ship",
    "síp": "ship",
    "sáu": "sáu",
    "xáu": "sáu",
    "xa": "sa",
    # tr / ch confusions
    "chả": "trả",
    "chả hàng": "trả hàng",
    "chuyển": "chuyển",
    # d / gi / r confusions
    "dá": "giá",
    "dá tiền": "giá tiền",
    "rẻ": "rẻ",
    "dẻ": "rẻ",
    # l / n slur (nói ngọng)
    "nói nộn": "nói lộn",
    "nộn": "lộn",
    "làm nũng": "làm nũng",
    # common ASR mis-hearings of domain words
    "đôn": "đơn",
    "đôn hàng": "đơn hàng",
    "đon": "đơn",
    "hàng hoá": "hàng hóa",
    "bảo hành": "bảo hành",
    "bảo hànhh": "bảo hành",
    "đổi chả": "đổi trả",
    "giao hàng": "giao hàng",
    "giao hang": "giao hàng",
    "sơ mi": "sơ mi",
    "sơ my": "sơ mi",
    "áo thun": "áo thun",
    "áo thung": "áo thun",
}

# Regional lexical variants -> canonical (Northern standard) form.
DIALECT_MAP: Dict[str, str] = {
    # South -> standard
    "tô": "bát",
    "ly": "cốc",
    "trái": "quả",
    "dô": "vào",
    "nè": "này",
    "hen": "nhé",
    "chớ": "chứ",
    # Central -> standard
    "mô": "đâu",
    "răng": "sao",
    "tê": "kia",
    "chi": "gì",
    "nớ": "đó",
    # North colloquial -> standard
    "này": "này",
}

# Undiacritized phrases, longest first at lookup time.
UNDIACRITICIZED_PHRASES: Dict[str, str] = {
    "don hang cua toi dau roi": "đơn hàng của tôi đâu rồi",
    "don hang": "đơn hàng",
    "tra don": "tra đơn",
    "ma don": "mã đơn",
    "giao hang": "giao hàng",
    "phi ship": "phí ship",
    "phi giao hang": "phí giao hàng",
    "doi tra": "đổi trả",
    "bao hanh": "bảo hành",
    "dat lich": "đặt lịch",
    "khieu nai": "khiếu nại",
    "boi thuong": "bồi thường",
    "ho ten": "họ tên",
    "dia chi": "địa chỉ",
    "so dien thoai": "số điện thoại",
    "ngay mai": "ngày mai",
    "hom nay": "hôm nay",
    "hom qua": "hôm qua",
    "xin chao": "xin chào",
    "cam on": "cảm ơn",
    "san pham": "sản phẩm",
    "ao so mi": "áo sơ mi",
    "ao thun": "áo thun",
    "gia tien": "giá tiền",
    "bao nhieu tien": "bao nhiêu tiền",
    "gap nhan vien": "gặp nhân viên",
    "gap nguoi": "gặp người",
    "huy don": "hủy đơn",
    "doi dia chi": "đổi địa chỉ",
}

UNDIACRITICIZED_WORDS: Dict[str, str] = {
    "don": "đơn",
    "hang": "hàng",
    "tra": "tra",
    "ma": "mã",
    "phi": "phí",
    "doi": "đổi",
    # NOTE: "bao" is deliberately NOT mapped word-by-word: "bao nhiêu"
    # (how much) vs "bảo hành" (warranty) are different words, and the
    # phrase table already handles "bao hanh" -> "bảo hành".
    "dat": "đặt",
    "lich": "lịch",
    "khieu": "khiếu",
    "nai": "nại",
    "boi": "bồi",
    "thu": "thứ",
    "ngay": "ngày",
    "hom": "hôm",
    "xin": "xin",
    "chao": "chào",
    "cam": "cảm",
    "on": "ơn",
    "san": "sản",
    "pham": "phẩm",
    "ao": "áo",
    "so": "sơ",
    "mi": "mi",
    "gia": "giá",
    "tien": "tiền",
    "huy": "hủy",
    "dia": "địa",
    "chi": "chỉ",
    "gap": "gặp",
    "nhan": "nhân",
    "vien": "viên",
    "nguoi": "người",
}

_HESITATIONS = {"ừm", "ừ", "à", "ờ", "ơ", "hmm", "ừm ừm", "a", "e"}

# Spoken Vietnamese letter names -> letter (ASR hears the name).
LETTER_NAMES: Dict[str, str] = {
    "a": "A", "bờ": "B", "bê": "B", "cờ": "C", "xê": "C",
    "dờ": "D", "đờ": "D", "e": "E", "ép": "F", "phờ": "F",
    "gờ": "G", "hờ": "H", "hát": "H", "i": "I", "gi": "G", "ka": "K",
    "lờ": "L", "mờ": "M", "nờ": "N", "o": "O", "pờ": "P",
    "quờ": "Q", "rờ": "R", "sờ": "S", "tờ": "T", "u": "U",
    "vờ": "V", "xờ": "X", "y": "Y", "dét": "Z", "zờ": "Z",
    # ASR often drops the trailing "ờ"
    "b": "B", "c": "C", "d": "D", "f": "F", "g": "G",
    "h": "H", "k": "K", "l": "L", "m": "M", "n": "N",
    "p": "P", "q": "Q", "r": "R", "s": "S", "t": "T",
    "v": "V", "x": "X", "z": "Z",
}

DIGIT_WORDS: Dict[str, str] = {
    "không": "0", "khong": "0", "một": "1", "mot": "1",
    "hai": "2", "ba": "3", "bốn": "4", "bon": "4",
    "năm": "5", "nam": "5", "sáu": "6", "sau": "6",
    "bảy": "7", "bay": "7", "tám": "8", "tam": "8",
    "chín": "9", "chin": "9",
}

# Phonetic normalisation for the phonetic key: consonant clusters
# that ASR confuses are collapsed to one symbol.
_PHONETIC_MAP = [
    # ch / tr must collapse to the SAME symbol (both are heard as
    # "t" by ASR); mapping ch->c first and c->k later would split
    # them again, so ch maps straight to "t" here.
    ("ph", "f"), ("th", "t"), ("kh", "k"), ("gh", "g"),
    ("ng", "n"), ("nh", "n"), ("ch", "t"), ("tr", "t"),
    ("gi", "z"), ("d", "z"), ("r", "z"), ("x", "s"),
    ("qu", "k"), ("c", "k"),
]


def strip_diacritics(text: str) -> str:
    """Remove tones / diacritics, keeping đ -> d."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _restore_diacritics(text: str) -> str:
    """Longest-phrase first, then word-by-word, undiacritized -> diacritics."""
    if any(ch in text for ch in "àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ"):
        return text  # already has diacritics; do not guess over them
    for phrase in sorted(UNDIACRITICIZED_PHRASES, key=len, reverse=True):
        if phrase in text:
            text = text.replace(phrase, UNDIACRITICIZED_PHRASES[phrase])
    words = text.split()
    words = [UNDIACRITICIZED_WORDS.get(w, w) for w in words]
    return " ".join(words)


def _apply_homophones_and_dialect(text: str) -> str:
    for phrase in sorted(HOMOPHONES, key=len, reverse=True):
        if phrase in text:
            text = text.replace(phrase, HOMOPHONES[phrase])
    words = [DIALECT_MAP.get(w, w) for w in text.split()]
    return " ".join(words)


def normalize_text(text: str, *, region: Region = Region.UNKNOWN) -> str:
    """Full normalisation pipeline. Idempotent on already-clean text."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    words = [w for w in text.split() if w not in _HESITATIONS]
    text = " ".join(words)
    text = _restore_diacritics(text)
    text = _apply_homophones_and_dialect(text)
    return re.sub(r"\s+", " ", text).strip()


def phonetic_key(text: str) -> str:
    """Sound-based key: confusable consonants collapse, tones dropped."""
    key = strip_diacritics(normalize_text(text)).lower()
    for src, dst in _PHONETIC_MAP:
        key = key.replace(src, dst)
    # Collapse double letters produced by the mapping.
    key = re.sub(r"(.)\1+", r"\1", key)
    return re.sub(r"\s+", "", key)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER = (S + D + I) / N_ref_words. 0.0 is perfect."""
    ref = reference.split()
    hyp = hypothesis.split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return _word_lev(ref, hyp) / len(ref)


def _word_lev(ref: List[str], hyp: List[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        cur = [i]
        for j in range(1, len(hyp) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ref[i - 1] != hyp[j - 1])))
        prev = cur
    return prev[-1]


def char_error_rate(reference: str, hypothesis: str) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return levenshtein(reference, hypothesis) / len(reference)


# ---------------------------------------------------------------------------
# Fuzzy matching (phonetic-weighted)
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    candidate: str
    score: float  # 0..1, higher is better
    phonetic_match: bool
    distance: int


def fuzzy_match(query: str, candidates: Sequence[str], *, threshold: float = 0.55) -> List[MatchResult]:
    """Rank candidates by phonetic-weighted similarity.

    Score = 0.6 * spelling similarity + 0.4 * phonetic similarity,
    where similarity is 1 - lev/max_len. A candidate whose sound
    matches the query exactly gets a phonetic bonus even when the
    spelling differs (s/x, tr/ch, d/gi/r), which is exactly the
    ASR confusion this module exists for.
    """
    q_norm = normalize_text(query)
    q_phon = phonetic_key(query)
    results: List[MatchResult] = []
    for cand in candidates:
        c_norm = normalize_text(cand)
        max_len = max(len(q_norm), len(c_norm), 1)
        spell_sim = 1.0 - levenshtein(q_norm, c_norm) / max_len
        c_phon = phonetic_key(cand)
        max_plen = max(len(q_phon), len(c_phon), 1)
        phon_sim = 1.0 - levenshtein(q_phon, c_phon) / max_plen
        score = 0.6 * spell_sim + 0.4 * phon_sim
        if q_phon and q_phon == c_phon:
            score = max(score, 0.85)
        if score >= threshold:
            results.append(MatchResult(
                candidate=cand, score=round(score, 4),
                phonetic_match=(q_phon == c_phon),
                distance=levenshtein(q_norm, c_norm),
            ))
    results.sort(key=lambda r: (-r.score, r.distance))
    return results


@dataclass
class EntityResolution:
    best: Optional[str]
    score: float
    needs_verification: bool
    alternatives: List[MatchResult] = field(default_factory=list)
    reason: str = ""


def resolve_entity(
    query: str,
    candidates: Sequence[str],
    *,
    threshold: float = 0.55,
    ambiguity_gap: float = 0.08,
) -> EntityResolution:
    """Resolve one entity, or flag it ambiguous for 2-step verification.

    Ambiguous when: no candidate clears the threshold, or the top two
    are within ``ambiguity_gap`` of each other. In both cases the
    caller must ask the customer to confirm (``Anh chị vừa nói ...,
    có phải ... không ạ?``) and must NOT guess — a wrong order code
    or product leaks another customer's data or ships the wrong item.
    """
    matches = fuzzy_match(query, candidates, threshold=threshold)
    if not matches:
        return EntityResolution(best=None, score=0.0, needs_verification=True,
                                reason="no_candidate_above_threshold")
    best = matches[0]
    if len(matches) > 1 and (best.score - matches[1].score) < ambiguity_gap:
        return EntityResolution(
            best=None, score=best.score, needs_verification=True,
            alternatives=matches[:3], reason="ambiguous_top_candidates")
    return EntityResolution(best=best.candidate, score=best.score,
                            needs_verification=False, alternatives=matches[:3])


# ---------------------------------------------------------------------------
# Spoken entities: order codes and phone numbers
# ---------------------------------------------------------------------------


def parse_spoken_order_code(text: str) -> Optional[str]:
    """Parse an order code spoken letter/digit by letter/digit.

    ``đờ hát một hai ba`` -> ``DH123``; ``DH123`` / ``dh 123`` also
    work. Returns None when no code-like sequence is found.
    """
    raw = normalize_text(text)
    tokens = raw.split()
    # Direct alphanumeric code, token by token — e.g. "dh123" in
    # "mã đơn là DH123", or "dh 123". A regex over the space-free
    # string would misread the tail of the preceding Vietnamese
    # words as part of the code ("...làdh123" -> "LADH123").
    for i, tok in enumerate(tokens):
        plain = strip_diacritics(tok)
        if re.fullmatch(r"[a-z]{1,4}\d{2,}", plain):
            return plain.upper()
        if (
            re.fullmatch(r"[a-z]{1,4}", plain)
            and i + 1 < len(tokens)
            and re.fullmatch(r"\d{2,}", strip_diacritics(tokens[i + 1]))
        ):
            return (plain + strip_diacritics(tokens[i + 1])).upper()
    out: List[str] = []
    for tok in tokens:
        plain = strip_diacritics(tok)
        if plain in DIGIT_WORDS:
            out.append(DIGIT_WORDS[plain])
        elif tok in LETTER_NAMES:
            out.append(LETTER_NAMES[tok])
        elif plain in LETTER_NAMES:
            out.append(LETTER_NAMES[plain])
        elif re.fullmatch(r"[a-z]\d+", plain):
            out.append(plain.upper())
    code = "".join(out)
    if re.fullmatch(r"[A-Z]{1,4}\d{2,}", code):
        return code
    return None


def normalize_phone(text: str) -> Optional[str]:
    """Normalise a spoken / typed phone number to 10-digit 0xxxxxxxxx.

    Handles spoken digits (``không chín không ...``), ``+84`` and
    spaces/dots/dashes. Returns None for anything that is not
    exactly 10 digits starting with 0 after normalisation — the
    caller must then ask for the number again, not guess.
    """
    tokens = normalize_text(text).split()
    digits: List[str] = []
    for tok in tokens:
        plain = strip_diacritics(tok)
        if plain in DIGIT_WORDS:
            digits.append(DIGIT_WORDS[plain])
        else:
            digits.extend(re.findall(r"\d", tok))
    joined = "".join(digits)
    if joined.startswith("84") and len(joined) == 11:
        joined = "0" + joined[2:]
    if re.fullmatch(r"0\d{9}", joined):
        return joined
    return None


# ---------------------------------------------------------------------------
# WER evaluation, broken down by region and noise (never one number)
# ---------------------------------------------------------------------------


@dataclass
class WerCase:
    reference: str
    hypothesis: str
    region: Region = Region.UNKNOWN
    noise: NoiseLevel = NoiseLevel.CLEAN


def evaluate_wer(cases: Sequence[WerCase]) -> Dict[Tuple[str, str], Dict[str, float]]:
    """WER per (region, noise) cell, plus the count behind each cell.

    The overall number is deliberately NOT the headline: a single
    WER hides South+high-noise failures. Callers must read the cells.
    """
    cells: Dict[Tuple[str, str], List[float]] = {}
    for case in cases:
        key = (case.region.value, case.noise.value)
        cells.setdefault(key, []).append(
            word_error_rate(case.reference, case.hypothesis))
    return {
        key: {
            "wer": round(sum(v) / len(v), 4) if v else 0.0,
            "count": float(len(v)),
        }
        for key, v in sorted(cells.items())
    }


class VietnameseNormalizer:
    """Convenience facade used by the dialogue plane."""

    def __init__(self, *, region: Region = Region.UNKNOWN):
        self.region = region

    def normalize(self, text: str) -> str:
        return normalize_text(text, region=self.region)

    def order_code(self, text: str) -> Optional[str]:
        return parse_spoken_order_code(text)

    def phone(self, text: str) -> Optional[str]:
        return normalize_phone(text)

    def match(self, query: str, candidates: Sequence[str], **kw) -> List[MatchResult]:
        return fuzzy_match(query, candidates, **kw)

    def resolve(self, query: str, candidates: Sequence[str], **kw) -> EntityResolution:
        return resolve_entity(query, candidates, **kw)

    def wer(self, cases: Sequence[WerCase]):
        return evaluate_wer(cases)
