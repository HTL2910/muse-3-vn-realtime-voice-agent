# Ước lượng % đạt được cho hiệu năng AI từ bằng chứng test và mô phỏng

_algo-ml · Chuyên gia Thuật toán & AI · lần nộp 3_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu đánh giá khả năng đạt bao nhiêu %. Thông tin nền: báo cáo thị trường đã khóa nguyên tắc không hứa AI xử lý 80% cuộc gọi; số vendor gồm Ada khoảng 52% giải quyết tự động, Intercom Fin 76%, Gartner dự báo 80% đều chưa kiểm toán hoặc là dự báo, trong khi kiểm chứng độc lập yếu hơn nhiều với agent khoảng 35% tác vụ nhiều bước và voice agent 26–38% trong điều kiện ồn/nhiều giọng; benchmark bỏ cuộc gọi 5–8,4% là quốc tế, không phải số Việt Nam. Việc cần làm sau khi có baseline và báo cáo QA: dùng test evidence, golden calls và simulation harness nếu chạy được để ước lượng % theo từng chỉ số, không gộp thành một con số quảng cáo. Các chỉ số bắt buộc gồm tỉ lệ cuộc lặp lại có thể contained_provisional trong mô phỏng và giới hạn vì contained_final 72h không chứng minh được nếu chưa có dữ liệu liên hệ lại thật; latency p50/p95 so ngân sách 250+500+350=1100ms và SLO p95 dưới 1200ms; grounded verifier chặn đúng/sai trên golden cases; confidence gate với tỉ lệ trả lời sai, chuyển người không cần thiết và tuân thủ hỏi lại tối đa 1 lần; capacity Erlang-A với abandonment/callback trigger khi chờ dự báo vượt 60–90 giây. Kết quả cần nộp: docs/evaluation/03-algo-ml-feasibility.md gồm bảng chỉ số, giá trị đo hoặc mô phỏng, khoảng % đạt được, mức tin cậy thấp/trung bình/cao, bằng chứng, yếu tố làm tăng hoặc giảm %, và cỡ mẫu shadow/canary cần thiết để xác nhận trên tenant thật. Nếu harness không chạy được, phải ghi rõ % chưa ước lượng được ngoài mức bao phủ test và nêu blocker, không suy diễn từ số vendor.

## Bài làm

# Lần nộp 3 — Báo cáo khả thi đầy đủ + cả 2 script + log (nộp lại toàn bộ)

**Baseline / nguồn / QA (ghi rõ theo yêu cầu):** Không có commit baseline nào được cấp — không có commit hash, manifest, log CI hay repo clone. Repo dùng để chạy số chỉ là **bản dựng lại cục bộ** trên VM của algo-ml từ đúng nội dung 4 file trên main do điều phối viên cấp bằng text trong chat ngày 26/11/2026 (`src/contracts.py`, `src/eval/simulation_harness.py`, `data/golden/golden_calls.json`, `tests/test_e2e_call.py`); không có git object nên **không có hash cho contracts v1.0.0** (chỉ có nội dung text đã đọc và xác minh từng hằng số). **Nhất quán với QA:** qa-verifier (26/11/2026) kết luận Blocked vì trên VM của họ cũng không có repo/commit/contracts/pytest — cùng một nguyên nhân gốc (systems-arch chưa xác nhận repo/commit/contracts/pytest). **Hạ kết luận:** mọi số trong báo cáo là **mô phỏng cục bộ / chạy lại trên nội dung file đã nhận**, không phải đo trên baseline đã xác nhận; contained_final (72h), latency thật, WER thật, tỉ lệ trả lời sai thật đều **chưa ước lượng được ngoài mức bao phủ test**; không dùng số vendor để suy diễn. Điều kiện nâng cấp: CEO/systems-arch công bố manifest + commit hash + log CI, chạy lại toàn bộ trên commit đó.

**Kết quả chính (mô phỏng cục bộ):** contained_provisional 26–50% (tin cậy thấp); latency p95 924–1.102ms mô phỏng (thấp); verifier chặn 6/6 ca đối nghịch; gate 0 vi phạm hard rule/MAX=1 trên 20.000 lượt fuzz; Erlang-A đỉnh 60 cuộc/h với 5 nhân viên cho tỉ lệ bỏ 2–6% (trung bình); 6 module + 7 file test 100 passed với contracts v1.0.0 thật (nguyên trạng 99/100, 1 test cũ hard-code 6 lý do so với enum thật 8 giá trị — B7). Chi tiết đầy đủ, bảng chỉ số, cỡ mẫu shadow/canary và log chạy ở báo cáo bên dưới (bản rút gọn của lần nộp 2, toàn bộ số giữ nguyên).

(đã nộp file `docs/evaluation/03-algo-ml-feasibility.md`)

(đã nộp file `scripts/evaluation/feasibility_run.py`)

(đã nộp file `scripts/evaluation/feasibility_run2.py`)

## File đã nộp

- `docs/evaluation/03-algo-ml-feasibility.md`
- `scripts/evaluation/feasibility_run.py`
- `scripts/evaluation/feasibility_run2.py`
