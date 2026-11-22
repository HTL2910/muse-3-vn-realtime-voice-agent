# Viết 5 module backend-sec + test (tool gateway, policy engine, voice security, callback/ticket, metrics dashboard)

_backend-sec · Chuyên gia Backend & Bảo mật · lần nộp 1_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu tạo repo thật — các module dưới đây chưa từng có mặt trên main, phải viết/nộp lại đầy đủ dưới dạng file thật theo đúng đặc tả đã khóa (chép lại dưới đây vì bạn không có báo cáo cuối). File cần nộp: (1) src/grounding/tool_gateway.py — API gateway nội bộ duy nhất, tool schema chặt (get_order_status, get_inventory, get_appointment, get_policy, create_callback_ticket); AI không truy cập DB trực tiếp; tenant_id/shop_id lấy từ phiên đã xác thực, KHÔNG từ prompt/transcript; ownership check mã đơn + hậu tố SĐT; timeout 800–1500ms; kết quả kèm source_id/record_id/updated_at/evidence; kèm test xâm nhập (tool lạ bị rejected, thiếu tenant bị rejected, sai hậu tố SĐT không trả dữ liệu, cross-tenant bị từ chối). (2) src/dialog/policy_engine.py — rule + classifier chạy song song LLM, bảng quyết định cấu hình theo tenant (khiếu nại gay gắt, bồi thường, pháp lý, sức khoẻ/tài chính nhạy cảm, tự hại/bạo lực, khách yêu cầu gặp người, vượt MAX_CLARIFICATIONS, sentiment âm mạnh); hard-rule LUÔN thắng confidence gate; cấm LLM thương lượng bồi thường hay đưa cam kết pháp lý; mọi quyết định ghi audit log. LƯU Ý: dùng EscalationReason snake_case 6 giá trị và MAX_CLARIFICATIONS=1 — bản nộp cũ từng mang MAX=2 đã bị hội đồng bác. (3) src/security/voice_security_policy.py — transcript là dữ liệu KHÔNG tin cậy: tách system instruction/evidence/transcript, chặn tool-call bất thường; xác minh theo mức rủi ro (mã đơn cho tra cứu cơ bản, OTP cho đổi/hủy/bồi thường); mask PII theo vai trò; mã hoá at-rest theo tenant (KMS), TLS 1.3, retention tự xóa, audit log bất biến; thông báo ghi âm + cơ chế từ chối; rate limit chống toll fraud/spam call. (4) src/callback/callback_ticket_service.py — outbox pattern (ghi nguyên tử DB + outbox event, worker đẩy CRM/helpdesk, retry exponential backoff + dead-letter queue); idempotency-key, dedup theo SĐT + intent + cửa sổ thời gian và theo call_id + phone; SLA theo mức ưu tiên; scheduler tôn trọng khung giờ khách chọn và capacity đội trực; khách gọi lại được nối tiếp ticket cũ; xác nhận SMS/Zalo/email kèm mã phiếu. (5) src/observability/metrics_dashboard.py — sự kiện chuẩn mọi cuộc gọi với trace_id xuyên suốt; containment 2 lớp (provisional tại cuộc gọi bằng evidence đã xác thực; final = provisional + không liên hệ lại cùng vấn đề trong 72h CỐ ĐỊNH — LƯU Ý: bản nộp cũ từng mang window 48h đã bị bác); KPI cam kết chỉ dùng contained_final, cost-per-contained tính trên FINAL; tỉ lệ/lý do chuyển theo EscalationReason, abandonment, thời gian chờ, FCR, AHT, CSAT, độ trễ p50/p95, tỉ lệ verifier chặn; dashboard tách số đo nội bộ khỏi benchmark vendor; redaction PII trước phân tích. Quy tắc chung: import hằng số/enum từ src.contracts, không định nghĩa mirror. Kèm test cho từng file trong tests/ (số test cũ trên nhánh — tool gateway 12, policy 22 gồm rebase, security 14, callback 13, metrics 12 — chỉ để tham chiếu; số nộp lần này tính theo test thực chạy).

## Bài làm

Ghi rõ theo quy tắc nhiệm vụ này: **chưa chạy** build/test/lint (không có máy trong nhiệm vụ này) — cách chạy kiểm chứng ở cuối bài, kết quả thật do CI của repo báo lại. Một điểm phải báo trước: tài liệu #14 cho thấy bản contracts trên nhánh systems-arch-m3 là bản *đề xuất* (`CONTRACTS_VERSION = "1.0.0-m3"`, dùng `HandoffReason`/`user_requested`, chưa có `EscalationReason`/`MAX_CLARIFICATIONS`) — khác với bản khóa v1.0.0 mà cấp trên giao (EscalationReason snake_case 6 giá trị, MAX_CLARIFICATIONS=1, containment 72h). Cả 5 module dưới đây import theo **bản khóa v1.0.0** như được giao, không định nghĩa mirror; vì vậy `src/contracts.py` bản khóa phải lên main trước, nếu không import sẽ fail-closed — đúng thiết kế.

(đã nộp file `src/grounding/tool_gateway.py`)

(đã nộp file `src/dialog/policy_engine.py`)

(đã nộp file `src/security/voice_security_policy.py`)

(đã nộp file `src/callback/callback_ticket_service.py`)

(đã nộp file `src/observability/metrics_dashboard.py`)

(đã nộp file `tests/test_tool_gateway.py`)

(đã nộp file `tests/test_policy_engine.py`)

(đã nộp file `tests/test_voice_security_policy.py`)

(đã nộp file `tests/test_callback_ticket_service.py`)

(đã nộp file `tests/test_metrics_dashboard.py`)

**Trạng thái kiểm thử:** Chưa chạy build/test/lint trong nhiệm vụ này (theo quy tắc KHÔNG_CHẠY_LỆNH của phiếu giao). Cách chạy sau khi merge đủ `src/contracts.py` bản khóa v1.0.0 lên main: `python -m compileall src` rồi `python -m pytest tests/test_tool_gateway.py tests/test_policy_engine.py tests/test_voice_security_policy.py tests/test_callback_ticket_service.py tests/test_metrics_dashboard.py -q`. Lưu ý phụ thuộc thứ tự: cả 5 module import cứng từ `src.contracts` nên CI sẽ fail ở bước import nếu contracts chưa có trên main — đó là hành vi fail-closed có chủ đích, không phải lỗi của các module này.

## Tóm tắt gửi CEO (muse)
Đã nộp đủ 5 file thật kèm 5 file test: tool_gateway mới (allowlist 5 tool, schema chặt, tenant chỉ từ phiên, ownership mã đơn + hậu tố SĐT, timeout 800–1500ms, evidence bắt buộc, test xâm nhập), policy_engine (hard-rule thắng gate, MAX_CLARIFICATIONS=1), voice_security_policy, callback_ticket_service (outbox nguyên tử, idempotency/dedup, SLA), metrics_dashboard (containment 2 lớp, window 72h cố định, KPI và cost-per-contained chỉ trên FINAL).
Cả 5 module import hằng số/enum từ `src.contracts` bản khóa v1.0.0, không còn hằng số mirror nào (đã loại bỏ hẳn các fallback từng mang MAX=2 và window 48h).
Cần CEO xử lý một xung đột tài liệu trước khi merge: bản contracts trong tài liệu #14 là bản đề xuất m3 (`1.0.0-m3`, `HandoffReason`/`user_requested`) — phải công bố bản khóa v1.0.0 làm `src/contracts.py` chính thức và merge nó TRƯỚC 5 file này.
Trạng thái kiểm thử: chưa chạy trong nhiệm vụ này; lệnh chạy và điều kiện tiên quyết đã ghi rõ ở cuối bài để CI của repo kiểm chứng.

## File đã nộp

- `src/grounding/tool_gateway.py`
- `src/dialog/policy_engine.py`
- `src/security/voice_security_policy.py`
- `src/callback/callback_ticket_service.py`
- `src/observability/metrics_dashboard.py`
- `tests/test_tool_gateway.py`
- `tests/test_policy_engine.py`
- `tests/test_voice_security_policy.py`
- `tests/test_callback_ticket_service.py`
- `tests/test_metrics_dashboard.py`
