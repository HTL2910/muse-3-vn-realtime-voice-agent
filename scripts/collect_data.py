#!/usr/bin/env python3
"""[approach_21] Collect / build the real datasets for the voice-AI system.

Branch: fix/fix_missing_data_golden — MERGED from
 expert/systems-arch-m3, not rewritten. Adapted to locked contracts
 v1.0.0: GC-10 handoff reason is "customer_request" (the m3 spelling
 was renamed in contracts v1.0.0 and must not recur in golden data).
 Every record now carries its own "source" field,
 and every market-benchmark record carries a reliability_class in
 {vendor, independent, forecast, benchmark} in addition to the
 detailed reliability label.

Runs on the council VM (8 GB RAM / 150 GB disk), stdlib only, fully
re-runnable and deterministic (``--seed``). It builds, under ``data/``:

1. data/golden/golden_calls.json -- Vietnamese golden calls: dialogue
   scripts by intent (tra don, phi ship, doi tra/bao hanh, dat lich,
   khieu nai, ngoai pham vi, nhay cam) with transcript, expected
   intent/slots and expected decision (answer / handoff + reason).
2. data/golden/golden_faq.json -- golden FAQ/policy QA for knowledge
   regression (question -> expected chunk / approved answer).
3. data/orders.json, data/inventory.json, data/appointments.json --
   synthetic but structurally real order / stock / appointment data
   (order codes, phone suffixes, SKUs, statuses) for the tool gateway
   and eval. NO real PII: names/phones are invented, phones use the
   090-xxx range with masked suffixes.
4. data/vietnamese_homophones.json -- homophone dictionary + entity
   patterns (order codes, product names, addresses) for the normalizer.
5. data/market_benchmarks.json -- the market figures quoted in the
   brief, stored structurally with source + reliability label, so no
   number is ever quoted without its provenance. Vendor figures are
   labelled vendor_self_reported; independent checks are labelled
   independent; forecasts are labelled forecast. No VN-specific
   abandonment rate exists -- that gap is recorded explicitly.

Usage:
    python3 scripts/collect_data.py --out data --seed 42
    python3 scripts/collect_data.py --out data --seed 42 --calls 24 --orders 60
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

# ------------------------------------------------------------------ data
GOLDEN_CALLS = [
    {"id": "GC-01", "intent": "tra_don", "skill": "order",
     "transcript": ["Khách: Cho tôi hỏi đơn hàng DH240101 thế nào rồi?",
                    "AI: Dạ, đơn DH240101 đang giao, dự kiến mai tới ạ."],
     "slots": {"order_code": "DH240101"}, "expected": "answer", "reason": ""},
    {"id": "GC-02", "intent": "phi_ship", "skill": "order",
     "transcript": ["Khách: Ship về Hà Nội bao nhiêu tiền?",
                    "AI: Dạ phí ship Hà Nội là 25 nghìn, miễn phí từ 500 nghìn ạ."],
     "slots": {}, "expected": "answer", "reason": ""},
    {"id": "GC-03", "intent": "doi_tra", "skill": "return_warranty",
     "transcript": ["Khách: Tôi muốn đổi size áo mua hôm qua được không?",
                    "AI: Dạ được ạ, trong 7 ngày, sản phẩm còn nguyên tem ạ."],
     "slots": {}, "expected": "answer", "reason": ""},
    {"id": "GC-04", "intent": "bao_hanh", "skill": "return_warranty",
     "transcript": ["Khách: Tai nghe mua 2 tháng bị rè, bảo hành thế nào?",
                    "AI: Dạ tai nghe bảo hành 12 tháng, anh mang ra cửa hàng để kiểm tra ạ."],
     "slots": {}, "expected": "answer", "reason": ""},
    {"id": "GC-05", "intent": "dat_lich", "skill": "booking",
     "transcript": ["Khách: Tôi muốn đặt lịch sửa máy giặt chiều mai.",
                    "AI: Dạ chiều mai còn 14 giờ và 16 giờ, anh chọn giờ nào ạ?"],
     "slots": {}, "expected": "answer", "reason": ""},
    {"id": "GC-06", "intent": "huong_dan_su_dung", "skill": "technical",
     "transcript": ["Khách: Nồi chiên không dầu dùng lần đầu cần làm gì?",
                    "AI: Dạ rửa khay, lau khô rồi chạy không tải 10 phút ạ."],
     "slots": {}, "expected": "answer", "reason": ""},
    {"id": "GC-07", "intent": "khieu_nai_gay_gat", "skill": "complaint",
     "transcript": ["Khách: Tôi khiếu nại, giao sai hàng 3 lần rồi, tôi muốn gặp quản lý!"],
     "slots": {}, "expected": "handoff", "reason": "sensitive"},
    {"id": "GC-08", "intent": "boi_thuong", "skill": "complaint",
     "transcript": ["Khách: Hàng hỏng làm tôi thiệt hại, các anh phải bồi thường!"],
     "slots": {}, "expected": "handoff", "reason": "sensitive"},
    {"id": "GC-09", "intent": "ngoai_pham_vi", "skill": "general",
     "transcript": ["Khách: Giá cổ phiếu công ty anh mai lên hay xuống?",
                    "AI: Dạ câu này ngoài phạm vi hỗ trợ, để em chuyển nhân viên ạ."],
     "slots": {}, "expected": "handoff", "reason": "out_of_scope"},
    {"id": "GC-10", "intent": "yeu_cau_gap_nguoi", "skill": "general",
     "transcript": ["Khách: Tôi không muốn nói với máy, cho gặp người đi."],
     "slots": {}, "expected": "handoff", "reason": "customer_request"},
    {"id": "GC-11", "intent": "tra_don_khong_chac", "skill": "order",
     "transcript": ["Khách: Đơn của tôi... mã gì đó... tôi không nhớ rõ."],
     "slots": {}, "expected": "handoff", "reason": "low_confidence"},
    {"id": "GC-12", "intent": "ton_kho", "skill": "order",
     "transcript": ["Khách: Mẫu giày XYZ size 42 còn hàng không?",
                    "AI: Dạ còn 3 đôi ở kho Hà Nội ạ."],
     "slots": {"sku": "XYZ-42"}, "expected": "answer", "reason": ""},
]

GOLDEN_FAQ = [
    {"id": "FAQ-01", "question": "Đổi trả trong bao lâu?",
     "expected_chunk_id": "policy-return-c0001",
     "answer": "Đổi trả trong 7 ngày, sản phẩm còn nguyên tem."},
    {"id": "FAQ-02", "question": "Phí ship về Hà Nội là bao nhiêu?",
     "expected_chunk_id": "policy-shipping-c0002",
     "answer": "Phí ship Hà Nội 25.000đ, miễn phí từ 500.000đ."},
    {"id": "FAQ-03", "question": "Tai nghe bảo hành bao lâu?",
     "expected_chunk_id": "policy-warranty-c0003",
     "answer": "Tai nghe bảo hành 12 tháng."},
    {"id": "FAQ-04", "question": "Tra cứu đơn hàng cần gì?",
     "expected_chunk_id": "policy-order-c0004",
     "answer": "Cần mã đơn và 3 số cuối số điện thoại đặt hàng."},
]

HOMOPHONES = {
    "source": "synthetic dictionary built for the normalizer; not a linguistic corpus",
    "license": "synthetic, CC0",
    "pairs": [
        {"a": "đơn", "b": "đờn", "note": "homophone in fast speech"},
        {"a": "ship", "b": "síp", "note": "loanword spelling variant"},
        {"a": "size", "b": "sai", "note": "loanword / Vietnamese word collision"},
        {"a": "mã đơn", "b": "má đơn", "note": "tone confusion"},
        {"a": "bảo hành", "b": "bảo hànhh", "note": "ASR duplication"},
    ],
    "entity_patterns": {
        "order_code": r"DH\d{6}",
        "phone": r"0\d{9}",
        "sku": r"[A-Z]{2,4}-\d{2,3}",
    },
}

MARKET_BENCHMARKS = {
    "note": "Figures quoted in the brief, with source + reliability label. "
            "Use the range, never a single absolute number, when presenting externally.",
    "records": [
        {"metric": "vietnam_cloud_contact_center_2025_usd_m", "value": 192.9,
         "to_2034_usd_m": 855.3, "cagr": 0.1745,
         "source": "IMARC Group — Vietnam Cloud Based Contact Center Market",
         "reliability": "research_firm_forecast", "reliability_class": "forecast"},
        {"metric": "call_abandonment_avg_pct", "value": 8.4,
         "source": "ContactBabel UK 2024 (n=225), via Ainora",
         "reliability": "benchmark_international_not_vn", "reliability_class": "benchmark",
         "gap": "No Vietnam-specific abandonment rate was found."},
        {"metric": "call_abandonment_industry_standard_pct", "value": 5.0,
         "source": "SQM Group, via Ringly 2026", "reliability": "benchmark_international_not_vn", "reliability_class": "benchmark"},
        {"metric": "voice_ai_global_2025_usd_b", "value": 2.54, "to_2033_usd_b": 35.24,
         "cagr": 0.39, "source": "Grand View Research, via RaftLabs",
         "reliability": "research_firm_forecast_range", "reliability_class": "forecast"},
        {"metric": "klarna_ai_containment_pct", "value": 67,
         "source": "Klarna / Twig case study", "reliability": "vendor_case_study", "reliability_class": "vendor",
         "lesson": "AI answered easy cases at scale, then had to re-hire humans for complex cases."},
        {"metric": "ada_auto_resolution_pct", "value": 52,
         "source": "Ada (550+ deployments)", "reliability": "vendor_self_reported", "reliability_class": "vendor"},
        {"metric": "independent_voice_agent_multistep_pct_range", "value": [26, 38],
         "source": "DigyAI 2026 synthesis", "reliability": "independent", "reliability_class": "independent"},
        {"metric": "vietnam_bpo_2024_usd_b", "value": 2.5, "to_2028_usd_b": 3.6,
         "source": "Ken Research 2024, via StealthAgents", "reliability": "research_firm_forecast", "reliability_class": "forecast"},
    ],
}


def build_orders(rng: random.Random, n: int) -> list[dict]:
    statuses = ["dang_giao", "da_giao", "dang_chuan_bi", "da_huy"]
    orders = []
    for i in range(n):
        code = f"DH{240101 + i}"
        orders.append({
            "order_code": code,
            "phone_suffix": f"{rng.randint(100, 999)}",
            "phone_masked": f"090***{rng.randint(100, 999)}",
            "status": rng.choice(statuses),
            "total_vnd": rng.choice([199000, 350000, 499000, 1290000]),
            "updated_at": "2026-11-22T10:00:00+07:00",
            "source": "synthetic",
        })
    return orders


def build_inventory(rng: random.Random) -> list[dict]:
    items = []
    for sku in ["XYZ-42", "XYZ-43", "ABC-38", "DEF-01", "GHI-10"]:
        items.append({"sku": sku, "qty": rng.randint(0, 20),
                      "warehouse": rng.choice(["HN", "HCM"]),
                      "updated_at": "2026-11-22T10:00:00+07:00", "source": "synthetic"})
    return items


def build_appointments(rng: random.Random, n: int = 20) -> list[dict]:
    return [{"appointment_id": f"AP{1000 + i}",
             "slot": f"2026-11-{23 + i % 5:02d}T{14 + i % 3}:00:00+07:00",
             "service": rng.choice(["sua_may_giat", "bao_hanh", "tu_van"]),
             "status": "confirmed", "source": "synthetic"} for i in range(n)]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--calls", type=int, default=12)
    ap.add_argument("--orders", type=int, default=60)
    args = ap.parse_args()
    out = Path(args.out)
    rng = random.Random(args.seed)
    calls = [{**c, "source": "synthetic"} for c in GOLDEN_CALLS[: args.calls]]
    qa = [{**q, "source": "synthetic"} for q in GOLDEN_FAQ]
    write_json(out / "golden" / "golden_calls.json",
               {"source": "synthetic scripts by council, no real PII",
                "license": "synthetic, CC0", "calls": calls})
    write_json(out / "golden" / "golden_faq.json",
               {"source": "synthetic, approved answers in this file",
                "license": "synthetic, CC0", "qa": qa})
    write_json(out / "orders.json", build_orders(rng, args.orders))
    write_json(out / "inventory.json", build_inventory(rng))
    write_json(out / "appointments.json", build_appointments(rng))
    write_json(out / "vietnamese_homophones.json", HOMOPHONES)
    write_json(out / "market_benchmarks.json", MARKET_BENCHMARKS)
    print(f"wrote datasets to {out} (seed={args.seed}, "
          f"calls={min(args.calls, len(GOLDEN_CALLS))}, orders={args.orders})")


if __name__ == "__main__":
    main()
