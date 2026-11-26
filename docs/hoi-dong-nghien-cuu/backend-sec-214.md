# Đánh giá % sẵn sàng an toàn dữ liệu và vận hành backend

_backend-sec · Chuyên gia Backend & Bảo mật · lần nộp 3_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu đánh giá % đạt được và test thử; phần của backend-sec là xác định hệ thống có đủ an toàn để pilot hay chưa. Thông tin nền: tool gateway là đường duy nhất từ AI tới dữ liệu nghiệp vụ với 5 tool get_order_status, get_inventory, get_appointment, get_policy, create_callback_ticket; tenant_id/shop_id chỉ lấy từ phiên đã xác thực, không lấy từ prompt/transcript; ownership check dùng mã đơn và hậu tố SĐT; timeout tool 800–1500ms; mọi kết quả thành công phải có source_id/record_id/updated_at/evidence; policy hard-rule luôn thắng confidence gate; transcript là dữ liệu không tin cậy; callback dùng outbox, idempotency-key, dedup và SLA; metrics phải redaction PII trước phân tích và containment final cố định 72h. Việc cần làm trên commit baseline: kiểm tra và chạy hoặc đối chiếu test âm tính cho cross-tenant, thiếu tenant, sai hậu tố SĐT, tool lạ, injection trong transcript không thành tool-call, ca bồi thường/pháp lý dù confidence cao vẫn chuyển người, log sau redaction không còn SĐT/địa chỉ thô, callback không tạo trùng khi retry, hết agent vẫn tạo ticket. Đồng thời đánh giá các blocker vận hành như adapter OMS/WMS/CRM thật, KMS/TLS/retention/audit log, rate limit chống toll fraud/spam call và khả năng chạy tải. Kết quả cần nộp: docs/evaluation/04-backend-security-readiness.md gồm % sẵn sàng an toàn cho pilot theo từng nhóm kiểm soát, bằng chứng test hoặc lý do chưa test được, blocker nào làm trần % bị hạ, và điều kiện tối thiểu trước khi chạm dữ liệu thật. Không kết luận an toàn chỉ từ việc code tồn tại.

## Bài làm

You've reached your usage limit. Upgrade now or invite friends to get more Muse tokens. Your full weekly usage will reset at ⁨10:52 PM⁩ on ⁨Thursday, November 26⁩.
