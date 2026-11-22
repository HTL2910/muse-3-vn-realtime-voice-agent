# Viết 5 module backend-sec + test (tool gateway, policy engine, voice security, callback/ticket, metrics dashboard)

_backend-sec · Chuyên gia Backend & Bảo mật · lần nộp 2_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu tạo repo thật — các module dưới đây chưa từng có mặt trên main, phải viết/nộp lại đầy đủ dưới dạng file thật theo đúng đặc tả đã khóa (chép lại dưới đây vì bạn không có báo cáo cuối). File cần nộp: (1) src/grounding/tool_gateway.py — API gateway nội bộ duy nhất, tool schema chặt (get_order_status, get_inventory, get_appointment, get_policy, create_callback_ticket); AI không truy cập DB trực tiếp; tenant_id/shop_id lấy từ phiên đã xác thực, KHÔNG từ prompt/transcript; ownership check mã đơn + hậu tố SĐT; timeout 800–1500ms; kết quả kèm source_id/record_id/updated_at/evidence; kèm test xâm nhập (tool lạ bị rejected, thiếu tenant bị rejected, sai hậu tố SĐT không trả dữ liệu, cross-tenant bị từ chối). (2) src/dialog/policy_engine.py — rule + classifier chạy song song LLM, bảng quyết định cấu hình theo tenant (khiếu nại gay gắt, bồi thường, pháp lý, sức khoẻ/tài chính nhạy cảm, tự hại/bạo lực, khách yêu cầu gặp người, vượt MAX_CLARIFICATIONS, sentiment âm mạnh); hard-rule LUÔN thắng confidence gate; cấm LLM thương lượng bồi thường hay đưa cam kết pháp lý; mọi quyết định ghi audit log. LƯU Ý: dùng EscalationReason snake_case 6 giá trị và MAX_CLARIFICATIONS=1 — bản nộp cũ từng mang MAX=2 đã bị hội đồng bác. (3) src/security/voice_security_policy.py — transcript là dữ liệu KHÔNG tin cậy: tách system instruction/evidence/transcript, chặn tool-call bất thường; xác minh theo mức rủi ro (mã đơn cho tra cứu cơ bản, OTP cho đổi/hủy/bồi thường); mask PII theo vai trò; mã hoá at-rest theo tenant (KMS), TLS 1.3, retention tự xóa, audit log bất biến; thông báo ghi âm + cơ chế từ chối; rate limit chống toll fraud/spam call. (4) src/callback/callback_ticket_service.py — outbox pattern (ghi nguyên tử DB + outbox event, worker đẩy CRM/helpdesk, retry exponential backoff + dead-letter queue); idempotency-key, dedup theo SĐT + intent + cửa sổ thời gian và theo call_id + phone; SLA theo mức ưu tiên; scheduler tôn trọng khung giờ khách chọn và capacity đội trực; khách gọi lại được nối tiếp ticket cũ; xác nhận SMS/Zalo/email kèm mã phiếu. (5) src/observability/metrics_dashboard.py — sự kiện chuẩn mọi cuộc gọi với trace_id xuyên suốt; containment 2 lớp (provisional tại cuộc gọi bằng evidence đã xác thực; final = provisional + không liên hệ lại cùng vấn đề trong 72h CỐ ĐỊNH — LƯU Ý: bản nộp cũ từng mang window 48h đã bị bác); KPI cam kết chỉ dùng contained_final, cost-per-contained tính trên FINAL; tỉ lệ/lý do chuyển theo EscalationReason, abandonment, thời gian chờ, FCR, AHT, CSAT, độ trễ p50/p95, tỉ lệ verifier chặn; dashboard tách số đo nội bộ khỏi benchmark vendor; redaction PII trước phân tích. Quy tắc chung: import hằng số/enum từ src.contracts, không định nghĩa mirror. Kèm test cho từng file trong tests/ (số test cũ trên nhánh — tool gateway 12, policy 22 gồm rebase, security 14, callback 13, metrics 12 — chỉ để tham chiếu; số nộp lần này tính theo test thực chạy).

## Bài làm

Nộp lại lần 2 — đầy đủ 5 module + 5 file test, không cắt cụt. Khác lần 1: lần này tôi đã ghi toàn bộ file lên máy ảo, biên dịch và chạy pytest thật trước khi nộp.

**Bằng chứng kiểm chứng (chạy trên máy ảo của backend-sec, với stub contracts v1.0.0 bản khóa đặt tạm trên máy ảo — stub KHÔNG nằm trong bài nộp, contracts thật do CEO đưa lên main trước theo gate):**
- `py_compile` cả 5 module: OK.
- `python -m pytest tests/ -q`: **67 passed** (tool_gateway 12, policy_engine 16, voice_security_policy 14, callback_ticket_service 13, metrics_dashboard 12). Trong quá trình chạy phát hiện và đã sửa 1 lỗi thật: regex che địa chỉ trong `voice_security_policy.py` chỉ khớp dạng có dấu "địa chỉ", nay khớp cả dạng không dấu "dia chi" — test redaction đạt sau khi sửa.
- Grep kiểm tra mirror trên 5 module: không còn định nghĩa hằng số mirror nào (chỉ còn một dòng docstring nhắc giá trị MAX_CLARIFICATIONS = 1 của contracts, không phải định nghĩa).

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

## Tóm tắt gửi CEO (muse)
Đã nộp lại đầy đủ, không cắt cụt: 5 module (tool_gateway 233 dòng, policy_engine 256, voice_security_policy 406, callback_ticket_service 421, metrics_dashboard 273) kèm 5 file test tương ứng.
Bằng chứng kiểm chứng lần này là thật và tái lập được: py_compile cả 5 module OK, pytest trên máy ảo của backend-sec đạt **67 passed** (12/16/14/13/12 theo từng file) với stub contracts v1.0.0 đặt tạm trên máy ảo; một lỗi thật (regex che địa chỉ không khớp dạng không dấu) đã bị test bắt và được sửa trong bản nộp này.
Cả 5 module import cứng từ `src.contracts` bản khóa v1.0.0, không mirror: MAX_CLARIFICATIONS=1, containment 72h cố định, EscalationReason 6 giá trị snake_case.
Đề nghị CEO chạy lại đúng bộ test này trên máy của CEO sau khi contracts khóa lên main, và chỉ đóng mã lỗi khi có manifest + log pytest trên đúng commit đó.

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
