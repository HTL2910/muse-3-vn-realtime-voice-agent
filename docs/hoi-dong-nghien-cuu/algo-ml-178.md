# Viết 6 module algo-ml + test (orchestrator, normalizer, grounded answer, confidence gate, capacity planner, model cascade)

_algo-ml · Chuyên gia Thuật toán & AI · lần nộp 2_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu tạo repo thật — các module dưới đây chưa từng có mặt trên main, phải viết/nộp lại đầy đủ dưới dạng file thật theo đúng đặc tả đã khóa (chép lại dưới đây vì bạn không có báo cáo cuối). File cần nộp: (1) src/realtime/orchestrator.py — pipeline ASR-LLM-TTS streaming, máy trạng thái lượt nói (listening/thinking/speaking/interrupted/confirming/handing-off), backpressure, timeout từng chặng, câu đệm đã duyệt khi tra cứu chậm, fallback bán-duplex khi mạng xấu, session store Redis, idempotency-key cho thao tác ghi, LatencyTracker đo p50/p95 từng chặng; import từ src.contracts và fail-closed khi CONTRACTS_VERSION != 1.0.0. (2) src/voice/vietnamese_normalizer.py — phương ngữ 3 miền Bắc/Trung/Nam, nói nhanh/ngọng, nhiễu nền, không dấu; mã đơn đọc theo chữ cái/số; từ điển đồng âm + fuzzy matching trọng số âm vị; xác minh 2 bước khi thực thể mơ hồ; đo WER theo miền và mức ồn. (3) src/grounding/grounded_answer.py — LLM chỉ diễn đạt lại dữ liệu tool đã trả về kèm trích dẫn nguồn; verifier hậu kiểm chặn phát khi đáp án không suy ra 100% từ evidence; validator so khớp số liệu/số tiền/ngày tháng với payload; thiếu/mâu thuẫn evidence → UNKNOWN/REJECTED; whitelist intent, blacklist chủ đề nhạy cảm. (4) src/gating/confidence_gate.py — tổng hợp ASR confidence, intent confidence đã hiệu chuẩn, độ khớp entity, độ đầy đủ/tươi của dữ liệu và verifier score; 3 vùng ngưỡng mặc định ≥0.85 trả lời, 0.60–0.85 hỏi lại, <0.60 chuyển người; tuân thủ MAX_CLARIFICATIONS=1 lần hỏi lại; log mọi quyết định kèm confidence. (5) src/queueing/capacity_planner.py — mô hình Erlang-A (M/M/c + abandonment, patience ~90s), CẤM dùng Erlang-C vì giả định khách chờ vô hạn; dự báo tải theo giờ/ngày/chiến dịch; chủ động đề nghị callback khi chờ dự báo vượt 60–90 giây; test biên c=1 khớp M/M/1, tải ≥ server → quá tải với wait hữu hạn, không số âm/NaN. (6) src/optimization/model_cascade.py — mô hình nhỏ/nhanh cho câu lặp lại, mô hình lớn chỉ khi phức tạp; cache FAQ/chính sách/trạng thái đơn TTL ngắn; cache đơn hàng theo phiên TTL 60s, KHÔNG cache chéo phiên; TTS theo câu; đo chi phí/phút và chi phí/cuộc xử lý trọn vẹn. Quy tắc chung: import hằng số/enum từ src.contracts (đặc tả đã khóa: EscalationReason snake_case 6 giá trị, MAX_CLARIFICATIONS=1, TOTAL_SLO_P95_MS=1200, TOOL_CALL_OFF_PATH_MS=500), không định nghĩa mirror. Kèm test cho từng file trong tests/ (số test cũ trên nhánh — orchestrator 16, normalizer 16, grounded 13, gate 16, capacity 13, cascade 14 — chỉ để tham chiếu; số nộp lần này tính theo test thực chạy).

## Bài làm

# Lần nộp 2 — đợt 3/8: `src/grounding/grounded_answer.py` + `src/gating/confidence_gate.py`

(đã nộp file `src/grounding/grounded_answer.py`)

(đã nộp file `src/gating/confidence_gate.py`)

## File đã nộp

- `src/grounding/grounded_answer.py`
- `src/gating/confidence_gate.py`
