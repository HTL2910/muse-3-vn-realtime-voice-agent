# Viết 6 module algo-ml + test (orchestrator, normalizer, grounded answer, confidence gate, capacity planner, model cascade)

_algo-ml · Chuyên gia Thuật toán & AI · lần nộp 1_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu tạo repo thật — các module dưới đây chưa từng có mặt trên main, phải viết/nộp lại đầy đủ dưới dạng file thật theo đúng đặc tả đã khóa (chép lại dưới đây vì bạn không có báo cáo cuối). File cần nộp: (1) src/realtime/orchestrator.py — pipeline ASR-LLM-TTS streaming, máy trạng thái lượt nói (listening/thinking/speaking/interrupted/confirming/handing-off), backpressure, timeout từng chặng, câu đệm đã duyệt khi tra cứu chậm, fallback bán-duplex khi mạng xấu, session store Redis, idempotency-key cho thao tác ghi, LatencyTracker đo p50/p95 từng chặng; import từ src.contracts và fail-closed khi CONTRACTS_VERSION != 1.0.0. (2) src/voice/vietnamese_normalizer.py — phương ngữ 3 miền Bắc/Trung/Nam, nói nhanh/ngọng, nhiễu nền, không dấu; mã đơn đọc theo chữ cái/số; từ điển đồng âm + fuzzy matching trọng số âm vị; xác minh 2 bước khi thực thể mơ hồ; đo WER theo miền và mức ồn. (3) src/grounding/grounded_answer.py — LLM chỉ diễn đạt lại dữ liệu tool đã trả về kèm trích dẫn nguồn; verifier hậu kiểm chặn phát khi đáp án không suy ra 100% từ evidence; validator so khớp số liệu/số tiền/ngày tháng với payload; thiếu/mâu thuẫn evidence → UNKNOWN/REJECTED; whitelist intent, blacklist chủ đề nhạy cảm. (4) src/gating/confidence_gate.py — tổng hợp ASR confidence, intent confidence đã hiệu chuẩn, độ khớp entity, độ đầy đủ/tươi của dữ liệu và verifier score; 3 vùng ngưỡng mặc định ≥0.85 trả lời, 0.60–0.85 hỏi lại, <0.60 chuyển người; tuân thủ MAX_CLARIFICATIONS=1 lần hỏi lại; log mọi quyết định kèm confidence. (5) src/queueing/capacity_planner.py — mô hình Erlang-A (M/M/c + abandonment, patience ~90s), CẤM dùng Erlang-C vì giả định khách chờ vô hạn; dự báo tải theo giờ/ngày/chiến dịch; chủ động đề nghị callback khi chờ dự báo vượt 60–90 giây; test biên c=1 khớp M/M/1, tải ≥ server → quá tải với wait hữu hạn, không số âm/NaN. (6) src/optimization/model_cascade.py — mô hình nhỏ/nhanh cho câu lặp lại, mô hình lớn chỉ khi phức tạp; cache FAQ/chính sách/trạng thái đơn TTL ngắn; cache đơn hàng theo phiên TTL 60s, KHÔNG cache chéo phiên; TTS theo câu; đo chi phí/phút và chi phí/cuộc xử lý trọn vẹn. Quy tắc chung: import hằng số/enum từ src.contracts (đặc tả đã khóa: EscalationReason snake_case 6 giá trị, MAX_CLARIFICATIONS=1, TOTAL_SLO_P95_MS=1200, TOOL_CALL_OFF_PATH_MS=500), không định nghĩa mirror. Kèm test cho từng file trong tests/ (số test cũ trên nhánh — orchestrator 16, normalizer 16, grounded 13, gate 16, capacity 13, cascade 14 — chỉ để tham chiếu; số nộp lần này tính theo test thực chạy).

## Bài làm

# Nộp 6 module algo-ml + test — repo thật

**Chưa chạy** — theo quy định của turn này, tôi không chạy build/test/lint hay kiểm thử tay; toàn bộ số test dưới đây là **số hàm test có trong file, không phải kết quả chạy**. Kết quả thật do CI của repo báo lại sau khi chạy lệnh ở mục "Cách chạy" bên dưới.

## Phát hiện quan trọng nhất: `src/contracts.py` m3 LỆCH với đặc tả khóa — phải đối chiếu trước khi merge

Tôi đã đọc tài liệu #14 (nhánh systems-arch-m3). File contracts đó **không khớp** đặc tả khóa trong đề bài giao:

| Đặc tả khóa (đề bài) | File m3 nhận được (DOC #14) |
|---|---|
| `CONTRACTS_VERSION = "1.0.0"` | `"1.0.0-m3"` |
| Enum `EscalationReason`, 6 giá trị snake_case | Enum tên `HandoffReason` |
| `customer_request` | `USER_REQUESTED = "user_requested"` |
| Có `repeated_clarification` | Không có; thừa `NO_AGENT`, `SYSTEM_ERROR` |
| `MAX_CLARIFICATIONS = 1` | Không thấy trong phần nhận được |
| `TOTAL_SLO_P95_MS = 1200`, `TOOL_CALL_OFF_PATH_MS = 500` | Không thấy trong phần nhận được (file bị cắt bớt) |

6 module dưới đây import đúng **tên đã khóa** (`EscalationReason`, `MAX_CLARIFICATIONS`, `TOTAL_SLO_P95_MS`, `TOOL_CALL_OFF_PATH_MS`, `CONTRACTS_VERSION == "1.0.0"`), và fail-closed khi version khác 1.0.0. Hệ quả cố ý: **nếu merge file m3 nguyên văn, cả 6 module sẽ fail ngay ở bước import** — đó là hành vi đúng (thà không chạy còn hơn chạy với mã lý do sai), và thông báo lỗi sẽ chỉ thẳng vào version/enum lệch. Việc cần làm trước mọi module: systems-arch đối chiếu (diff) file m3 với đặc tả khóa — đổi `HandoffReason` → `EscalationReason`, `user_requested` → `customer_request`, thêm `repeated_clarification`, thêm 4 hằng số, version `1.0.0` — rồi mới merge contracts lên main. Tôi **không** nộp `src/contracts.py` vì đó là file của systems-arch, không phải phạm vi của tôi.

## Nội dung nộp

| # | File | Nội dung chính | Test kèm theo (số hàm test trong file) |
|---|---|---|---|
| 1 | `src/realtime/orchestrator.py` | Streaming ASR→LLM→TTS theo câu, máy trạng thái 6 trạng thái, barge-in, backpressure → bán-duplex, timeout từng chặng, câu đệm đã duyệt khi tra cứu chậm, session store (Redis + fallback bộ nhớ), idempotency-key, LatencyTracker p50/p95, `check()` ngân sách từ hằng số contracts | `tests/test_fix_rebase_algo_ml_to_contracts.py` (16) |
| 2 | `src/voice/vietnamese_normalizer.py` | Phương ngữ 3 miền, từ điển đồng âm, khôi phục dấu, mã đơn đọc theo chữ cái/số, số điện thoại, fuzzy matching trọng số âm vị, xác minh 2 bước khi mơ hồ, WER theo miền × mức ồn | `tests/test_fix_missing_vietnamese_normalizer.py` (16) + `tests/test_fix_rebase_remaining_algo_ml.py` (12, kiểm tra rebase cả 5 module) |
| 3 | `src/grounding/grounded_answer.py` | Fail-closed: blacklist/sensitive → whitelist → không bản ghi UNKNOWN → mâu thuẫn REJECTED → thiếu trường UNKNOWN → policy hết hạn REJECTED → verifier số/tiền/ngày/mã; chỉ render từ payload, đáp án sai bị thay bằng câu xin lỗi + chuyển người cố định | `tests/test_fix_missing_grounded_answer.py` (13, đủ golden 4 ca) |
| 4 | `src/gating/confidence_gate.py` | Tổng hợp 5 tín hiệu (ASR 0.15 / intent đã hiệu chuẩn 0.35 / entity 0.15 / evidence 0.20 / verifier 0.15); vùng ≥0.85 trả lời, 0.60–0.85 hỏi lại, <0.60 chuyển người; `MAX_CLARIFICATIONS=1`; hard rule (không evidence, verifier <0.5) luôn chuyển người; hiệu chuẩn temperature + isotonic (PAVA); log mọi quyết định | `tests/test_fix_missing_confidence_gate.py` (16) |
| 5 | `src/queueing/capacity_planner.py` | **Erlang-A (M/M/c+M), patience ~90s — cấm Erlang-C**; AI là tầng đầu (containment mặc định 0.52, ghi rõ là số vendor Ada, không phải cam kết); dự báo theo giờ/ngày/chiến dịch; đề nghị callback khi chờ dự báo ≥60s; quá tải trả `overloaded=True`, wait hữu hạn, không âm/NaN | `tests/test_fix_missing_capacity_planner.py` (13) |
| 6 | `src/optimization/model_cascade.py` | Mô hình nhỏ trước, lớn chỉ khi phức tạp hoặc nhỏ thiếu tự tin (fallback tối đa 1 lần); cache FAQ 300s / template đã kiểm chứng 3600s / đơn hàng **theo phiên TTL 60s, không cache chéo phiên** / giọng chỉ cho câu mở đầu-xác nhận trong allowlist; rút gọn câu trả lời còn 1 ý chính; đo chi phí/phút AI và chi phí/cuộc xử lý trọn vẹn + Pareto latency-cost | `tests/test_fix_missing_model_cascade.py` (14) |

Tổng: **6 module + 7 file test = 100 hàm test**. Thứ tự merge bắt buộc: contracts đã đối chiếu (1.0.0) → 6 module theo thứ tự phụ thuộc (grounded/gate trước orchestrator) → test. Không merge module nào trước contracts, vì các module import cứng từ contracts và sẽ fail-closed.

## Cách chạy (CI / máy本地)

```bash
# 0. Điều kiện tiên quyết: src/contracts.py v1.0.0 đã đối chiếu phải có trên main trước.
#    Nếu chưa có, mọi module import từ contracts sẽ fail-closed đúng như thiết kế.
python -m py_compile src/contracts.py src/realtime/orchestrator.py src/voice/vietnamese_normalizer.py src/grounding/grounded_answer.py src/gating/confidence_gate.py src/queueing/capacity_planner.py src/optimization/model_cascade.py
python -m pytest tests/ -q
```

(đã nộp file `src/realtime/orchestrator.py`)

(đã nộp file `src/voice/vietnamese_normalizer.py`)

(đã nộp file `src/grounding/grounded_answer.py`)

(đã nộp file `src/gating/confidence_gate.py`)

(đã nộp file `src/queueing/capacity_planner.py`)

(đã nộp file `src/optimization/model_cascade.py`)

(đã nộp file `tests/test_fix_rebase_algo_ml_to_contracts.py`)

(đã nộp file `tests/test_fix_missing_vietnamese_normalizer.py`)

(đã nộp file `tests/test_fix_missing_grounded_answer.py`)

(đã nộp file `tests/test_fix_missing_confidence_gate.py`)

(đã nộp file `tests/test_fix_missing_capacity_planner.py`)

(đã nộp file `tests/test_fix_missing_model_cascade.py`)

(đã nộp file `tests/test_fix_rebase_remaining_algo_ml.py`)

## Tóm tắt gửi CEO (muse)

- Nộp đủ 6 module algo-ml + 7 file test (100 hàm test), toàn bộ import hằng số/enum từ `src.contracts` theo đặc tả khóa, không mirror; **chưa chạy** — CI chạy `python -m pytest tests/ -q` sẽ báo kết quả thật.
- Phát hiện chặn merge: contracts m3 (DOC #14) lệch đặc tả khóa ở 5 điểm (`1.0.0-m3`, `HandoffReason`, `user_requested`, thiếu `repeated_clarification`, thiếu 4 hằng số) — cần systems-arch đối chiếu và sửa trước khi merge contracts, nếu không cả 6 module sẽ fail-closed ngay ở bước import.
- Thứ tự merge bắt buộc: contracts đã đối chiếu (1.0.0) trước, rồi 6 module, rồi CI xanh mới tính là xong; 2 quyết định đã khóa lại trong code: capacity giữ Erlang-A (bác Erlang-C) và cache đơn hàng chỉ theo phiên TTL 60s, không cache chéo phiên.

## File đã nộp

- `src/realtime/orchestrator.py`
- `src/voice/vietnamese_normalizer.py`
- `src/grounding/grounded_answer.py`
- `src/gating/confidence_gate.py`
- `src/queueing/capacity_planner.py`
- `src/optimization/model_cascade.py`
- `tests/test_fix_rebase_algo_ml_to_contracts.py`
- `tests/test_fix_missing_vietnamese_normalizer.py`
- `tests/test_fix_missing_grounded_answer.py`
- `tests/test_fix_missing_confidence_gate.py`
- `tests/test_fix_missing_capacity_planner.py`
- `tests/test_fix_missing_model_cascade.py`
- `tests/test_fix_rebase_remaining_algo_ml.py`
