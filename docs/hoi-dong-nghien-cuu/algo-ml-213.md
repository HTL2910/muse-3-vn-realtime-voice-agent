# Ước lượng % đạt được cho hiệu năng AI từ bằng chứng test và mô phỏng

_algo-ml · Chuyên gia Thuật toán & AI · lần nộp 1_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu đánh giá khả năng đạt bao nhiêu %. Thông tin nền: báo cáo thị trường đã khóa nguyên tắc không hứa AI xử lý 80% cuộc gọi; số vendor gồm Ada khoảng 52% giải quyết tự động, Intercom Fin 76%, Gartner dự báo 80% đều chưa kiểm toán hoặc là dự báo, trong khi kiểm chứng độc lập yếu hơn nhiều với agent khoảng 35% tác vụ nhiều bước và voice agent 26–38% trong điều kiện ồn/nhiều giọng; benchmark bỏ cuộc gọi 5–8,4% là quốc tế, không phải số Việt Nam. Việc cần làm sau khi có baseline và báo cáo QA: dùng test evidence, golden calls và simulation harness nếu chạy được để ước lượng % theo từng chỉ số, không gộp thành một con số quảng cáo. Các chỉ số bắt buộc gồm tỉ lệ cuộc lặp lại có thể contained_provisional trong mô phỏng và giới hạn vì contained_final 72h không chứng minh được nếu chưa có dữ liệu liên hệ lại thật; latency p50/p95 so ngân sách 250+500+350=1100ms và SLO p95 dưới 1200ms; grounded verifier chặn đúng/sai trên golden cases; confidence gate với tỉ lệ trả lời sai, chuyển người không cần thiết và tuân thủ hỏi lại tối đa 1 lần; capacity Erlang-A với abandonment/callback trigger khi chờ dự báo vượt 60–90 giây. Kết quả cần nộp: docs/evaluation/03-algo-ml-feasibility.md gồm bảng chỉ số, giá trị đo hoặc mô phỏng, khoảng % đạt được, mức tin cậy thấp/trung bình/cao, bằng chứng, yếu tố làm tăng hoặc giảm %, và cỡ mẫu shadow/canary cần thiết để xác nhận trên tenant thật. Nếu harness không chạy được, phải ghi rõ % chưa ước lượng được ngoài mức bao phủ test và nêu blocker, không suy diễn từ số vendor.

## Bài làm

# Lần nộp — script chạy kèm 1/2: `scripts/evaluation/feasibility_run.py`

Script đã được kiểm chứng chạy đúng ở đúng vị trí nộp (`<repo>/scripts/evaluation/`, `REPO = parents[2]` = gốc repo) và cho kết quả **đồng nhất** với lần chạy gốc (golden, gate fuzz, Erlang-A, cỡ mẫu đều identical). File `feasibility_run2.py` nộp ở đợt sau.

(đã nộp file `scripts/evaluation/feasibility_run.py`)

## File đã nộp

- `scripts/evaluation/feasibility_run.py`
