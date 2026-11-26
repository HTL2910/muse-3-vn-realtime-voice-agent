# 02 — QA Test Report — vn-realtime-voice-agent (qa-verifier, 26/11/2026)

Trạng thái tổng: **BLOCKED — chưa có baseline commit khả kiểm.**
Chi tiết đầy đủ, ma trận bao phủ 5 yêu cầu cốt lõi, đặc tả 13 nhóm test mục tiêu,
2 lỗi Sev-2 (lệch CONTRACTS_VERSION 1.0.0-m3 vs 1.0.0; lệch enum HandoffReason 7
giá trị vs EscalationReason 6 giá trị) và 1 Blocker Sev-1 (không có repo/commit
hash/manifest/log pytest trên main) được trình bày trong báo cáo QA nộp CEO
ngày 26/11/2026 của qa-verifier. Môi trường: Python 3.12.3, git 2.43.0,
pytest not found, ~/workspace/vn-realtime-voice-agent: No such file or directory.
Không báo cáo % pass / % coverage / % go-live vì mẫu số không tồn tại.
Điều kiện gỡ Blocked: URL repo + commit hash 40 ký tự + evidence/manifest
SHA-256 + log pytest thô; sau đó chạy `pip install -e .` và
`python -m pytest -q` cùng `python -m pytest tests/evaluation/ -q`.
