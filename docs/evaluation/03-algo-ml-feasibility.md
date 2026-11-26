# Đánh giá khả thi — AI trợ lý giọng nói realtime trả lời khách hàng (Lần nộp 3 — bản rút gọn, toàn bộ số giữ nguyên từ lần nộp 2)

- **Tác giả:** algo-ml · **Ngày:** 26/11/2026 · **Báo cáo cho:** CEO (muse) · **Lần nộp 3** (nộp lại toàn bộ; lần 2 nội dung 33KB không tới được tay CEO, CEO cũng không truy cập được VM của algo-ml)
- **Kèm theo trong bài nộp này:** `scripts/evaluation/feasibility_run.py`, `scripts/evaluation/feasibility_run2.py` + log chạy ở Phụ lục A.

## 0. Baseline commit, nguồn repo, quan hệ với QA — đọc trước (hạ kết luận)

- **Commit baseline: KHÔNG CÓ.** Không có commit hash, manifest, log CI hay repo clone nào được cấp cho algo-ml. Không có git object → **không có hash cho `src/contracts.py` v1.0.0**; chỉ có nội dung text của file do điều phối viên cấp trong chat ngày 26/11/2026 và đã xác minh từng hằng số từ text đó.
- **Nguồn repo: BẢN DỰNG LẠI CỤC BỘ trên VM của algo-ml** từ đúng nội dung 4 file trên main do điều phối viên cấp bằng text: `src/contracts.py`, `src/eval/simulation_harness.py`, `data/golden/golden_calls.json`, `tests/test_e2e_call.py` — cộng 6 module + 7 file test của algo-ml. Đây KHÔNG PHẢI baseline đã xác nhận.
- **Quan hệ với QA:** qa-verifier (26/11/2026) kết luận **Blocked** vì trên VM của họ cũng không có repo/commit/contracts/pytest — cùng một nguyên nhân gốc: systems-arch chưa xác nhận repo/commit/contracts/pytest. Báo cáo này **nhất quán với QA**: không tuyên bố đo trên baseline đã khóa.
- **Hạ kết luận:** mọi số trong báo cáo là **MÔ PHỎNG CỤC BỘ / chạy lại trên nội dung file đã nhận**, không phải đo trên baseline đã xác nhận. Các khoảng % là khoảng lập kế hoạch cho mô phỏng cục bộ. **contained_final (72h), latency thật từng chặng, WER thật, tỉ lệ trả lời sai thật: CHƯA ƯỚC LƯỢNG ĐƯỢC ngoài mức bao phủ test.** Không dùng số vendor để suy diễn (Ada ~72%/~52%, Fin 76%, Gartner 80%, FPT 92%, Klarna 67% đều bị loại; mốc độc lập duy nhất dùng làm cận dưới: agent ~35% tác vụ nhiều bước, voice agent 26–38% trong ồn/nhiều giọng — DigyAI 2026).
- **Điều kiện để nâng cấp kết luận:** CEO/systems-arch công bố manifest + commit hash + log CI; chạy lại toàn bộ trên commit đó; lúc đó các khoảng % mới trở thành ước lượng trên baseline.

## 1. Bảng chỉ số chính (mô phỏng cục bộ; khoảng % = lập kế hoạch, không phải cam kết)

| # | Chỉ số | Giá trị đo / mô phỏng (cục bộ) | Khoảng % lập kế hoạch | Tin cậy |
|---|---|---|---|---|
| 1 | contained_provisional | Golden: 6/12 = 50%, Wilson [25,4% – 74,6%] | 26–50% trên lưu lượng thật | Thấp |
| 2 | contained_final (72h) | Chưa ước lượng được (bằng provisional theo cấu trúc) | — (cận trên = provisional) | — |
| 3 | Latency p50/p95 vs 250+500+350=1100ms, SLO p95 <1200ms | Stub: p50=p95=900ms (hard-code). Monte Carlo p95 924–1.102ms; P(vượt SLO) 0,17%–2,77% | p95 924–1.102ms | Thấp |
| 4 | Grounded verifier | Chặn 6/6 ca đối nghịch, trả lời đúng 2/2 happy-path. Hallucination stub 0/6, Wilson [0%–39,0%] | Tỉ lệ trả lời sai thật: chưa đo được | Thấp (tỉ lệ); Cao (chặn trên ca đã biết) |
| 5 | Confidence gate | Fuzz n=20.000: trả lời 18,0% / hỏi lại 33,6% / chuyển 48,3%. Vi phạm hard rule 0, hỏi lại lần 2 0, chuyển thừa 0/1.023 | Chuyển thừa 0% trong fuzz; trả lời sai 0% với 2 hard rule | Trung bình (logic); Thấp (tỉ lệ thật) |
| 6 | Capacity Erlang-A | Đỉnh 60 cuộc/h, c=5, cont 0,30: P(bỏ)=1,96%, chờ TB 1,8s. Quá tải 120 cuộc/h, c=5, cont 0,30: P(bỏ)=14,2%, chờ 12,8s. Callback chỉ bật từ 180–300 cuộc/h; chờ TB ≥90s không đạt tới ở ≤360 cuộc/h | Abandonment đỉnh 2–6%; quá tải gấp đôi 14–28% | Trung bình |
| 7 | WER theo miền / mức ồn | Proxy text (n=5): WER sau chuẩn hoá 0,000–0,429; mã đơn 7/7 | WER âm thanh thật: chưa đo được | Thấp |
| 8 | Handoff / callback / shadow / go-live | Stub: 6/6 escalate → ticket, tóm tắt 6/6 có căn cứ. Canary 5,1%/10,0% trên 2.000 id. Kill-switch ~1µs (in-process). Shadow vs oracle 1,0 (12/12, đo vòng tròn). Go-live tenant rỗng: NO-GO | — (chưa có tỉ lệ thật) | Thấp (tỉ lệ); Cao (gate chặn đúng) |

## 2. Chuỗi bằng chứng (VM algo-ml: Python 3.12.3, pytest 9.2.0, venv riêng)

- `src/contracts.py` (text đã nhận): đã hòa giải về đúng v1.0.0 — version `1.0.0`, MAX_CLARIFICATIONS=1, cửa sổ 72h, ASR 250 / LLM 500 / TTS 350, SLO 1200, TOOL_CALL_OFF_PATH_MS=500, EscalationReason đủ 8 giá trị. Lệch 5 chỗ của bản m3 đã không còn. `check_latency_budget()` = True.
- 6 module + 7 file test với contracts thật: 100 passed trong 0,35s (16/16/13/16/13/14/12). Trung thực: nguyên trạng 99/100 — 1 test rớt là `test_escalation_reasons_come_from_contracts_enum` (file rebase của chính tôi, hard-code 6 lý do theo stub cũ, enum thật có 8; module đúng, test cũ lỗi thời; đã sửa expectation trong bản local → 100/100; bản trên main vẫn cần sửa — B7). 100 passed là bao phủ unit test, không phải % go-live.
- `src/eval/simulation_harness.py`: không import được nguyên trạng với contracts thật (B1): `AttributeError: contracts_missing_constant:RETRIEVAL_LLM_BUDGET_MS`, rc=1. Chỉ chạy sau shim trong bộ nhớ (`contracts.LLM_BUDGET_MS = LLM_FIRST_TOKEN_MS`, không sửa file).
- `data/golden/golden_calls.json`: 12 cuộc, 7 answer / 5 handoff; nhãn intent 0/12 khớp enum `Intent` (B4); lý do handoff 12/12 là giá trị đã khóa. `tests/test_e2e_call.py`: đã đọc, chưa chạy (cần `dialogue_manager`, `handoff_service`, `context_package`).

## 3. Chi tiết từng chỉ số bắt buộc

### 3.1 contained_provisional

`run_regression`: passed=true, merge_blocked=false, 12/12 đúng hành động; provisional 6/12 = 50% Wilson [25,4%–74,6%]; escalation 50%; abandonment 0/12 [0%–24,3%]; handoff summary 6/6 [61,0%–100%]. `simulate_load` 300 cuộc cho cùng 50% [44,4%–55,6%] — nhưng là cùng 12 cuộc lặp 25 lần, CI hẹp là ảo. Bộ golden thiết kế cân bằng (6 answer / 6 escalate) nên 50% đo độ chính xác hành động, không đo tỉ lệ lưu lượng. Khoảng 26–50%: cận dưới 26% là mốc độc lập thấp nhất cho voice agent ồn/nhiều giọng; cận trên 50% là trần lạc quan trên bộ golden cân bằng. Tăng: câu lặp lại nhiều; dữ liệu sạch/có API; ASR tốt 3 miền. Giảm: nhiều khiếu nại/phức tạp; dữ liệu thiếu/trễ; ồn/nhiều giọng; khách nói không dấu + sai mã.

### 3.2 contained_final (72h) — giới hạn

Định nghĩa đã khóa: final = provisional AND NOT recontacted trong 72h. Harness không đặt `repeat_contact` bao giờ nên trên golden final = provisional = 50% theo cấu trúc — con số 50% ở cột final là giả tạo. Cận trên duy nhất có cơ sở: final ≤ provisional. Mọi tuyên bố "final = X%" trước khi có dữ liệu liên hệ lại đều là bịa. Để đo: join mỗi cuộc canary với log liên hệ lại cùng số điện thoại + cùng vấn đề trong 72h; cửa sổ đo chỉ đóng 72h sau cuộc canary cuối cùng (canary 13 ngày → final đầu tiên sau ngày 16).

### 3.3 Latency p50/p95

Harness stub không đo latency: hard-code lat asr 180 / llm 420 / tts 300 → p50=p95=900ms, SLO 1200ms, không vi phạm; 900ms là hằng số tác giả tự điền. Monte Carlo (200.000 mẫu, seed 7; mỗi chặng lognormal, median 150/300/200ms GIẢ ĐỊNH, p95 = đúng ngân sách 250/500/350ms): độc lập → p50 671ms, p95 924ms, P(>1200)=0,17%, P(>1100)=0,58%; tương quan hoàn toàn → p50 651ms, p95 1.102ms, P(>1200)=2,77%, P(>1100)=5,06%; độc lập + mỗi chặng p95 vượt ngân sách 10% → p50 679ms, p95 993ms, P(>1200)=0,73%. Đọc đúng: độc lập → SLO còn ~276ms dự phòng (tổng các p95 không phải p95 của tổng); tương quan là rủi ro chính. Tin cậy THẤP: median là giả định; cần p50/p95 thật từng vendor trên ≥500 lượt thật, theo miền/ồn.

### 3.4 Grounded verifier

Chạy module thật trên 4 golden case: (1) không record → UNKNOWN `no_record`; (2) record mâu thuẫn → REJECTED `contradictory_evidence`; (3) thiếu trường → UNKNOWN `missing_required_field:status` (sau sửa `order_id` → `order_code`); (4a) sai tiền 35.000→50.000 → REJECTED `numeric_mismatch`, số sai không xuất hiện trong text (350.000=350000=350k); (4b) sai ngày → REJECTED `date_mismatch`; (4c) sai mã DH123→DH999 → REJECTED `code_mismatch`; happy-path → ANSWERED, có citation, 2/2. Tổng: chặn đối nghịch 6/6, trả lời đúng 2/2 — bằng chứng hành vi chặn trên ca đã biết (tin cậy Cao cho đúng các ca đó), không phải tỉ lệ thật. Hallucination stub 0/6, Wilson [0%–39,0%]: "0 lần quan sát" vẫn tương thích với tỉ lệ thật tới 39%. Muốn tuyên bố hallucination <2% cần 189 câu trả lời liên tiếp không lỗi (§6). Tỉ lệ thật chỉ đo được bằng human review trên shadow/canary.

### 3.5 Confidence gate

Fuzz n=20.000 (seed 11), phân phối tín hiệu GIẢ ĐỊNH (50% lượt "sạch" / 50% lượt "ồn"): trả lời 3.608 (18,0%) / hỏi lại 6.726 (33,6%) / chuyển 9.666 (48,3%); trong chuyển: missing_evidence 3.503 (17,5%), verifier_failed 2.461 (12,3%), below_clarify_threshold 3.702 (18,5%). Vi phạm hard rule (trả lời khi thiếu evidence hoặc verifier rớt): 0. Hỏi lại lần 2 (vi phạm MAX=1): 0. Chuyển cuộc-mà-người-trả-lời-được: 0/1.023. Unit test 16/16 xác nhận biên: 0,85 trả lời, 0,849 hỏi lại, 0,60 hỏi lại, 0,599 chuyển; sau 1 lần hỏi lại thì chuyển với `repeated_clarification`. Không chuyển được sang tỉ lệ thật: hỗn hợp 18/34/48 là tính chất của phân phối giả định; tỉ lệ trả lời sai bằng 0 với 2 hard rule; các đường sai khác phụ thuộc dữ liệu hiệu chuẩn thật, hiện chưa có (ngưỡng 0,85/0,60 suy ra từ chi phí 100/15, chưa phải từ đo).

### 3.6 Capacity Erlang-A (60–90 giây)

Chạy `CapacityPlanner` thật (patience 90s, phục vụ TB 3 phút). Giả định tải: 300 cuộc/ngày, đỉnh 60 cuộc/h → λ=1,0/phút; quá tải 120 cuộc/h → λ=2,0/phút. Containment là biến số (0 / 0,30 / 0,40 / 0,50); default 0,52 là số vendor Ada, không dùng làm ước lượng.

| Kịch bản | c | cont | ρ | P(bỏ cuộc) | Chờ TB |
|---|---:|---:|---:|---:|---:|
| Đỉnh 60/h | 3 | 0 | 1,00 | 25,9% | 23,3s |
| Đỉnh 60/h | 3 | 0,30 | 0,70 | 15,0% | 13,5s |
| Đỉnh 60/h | 4 | 0,30 | 0,53 | 5,8% | 5,3s |
| Đỉnh 60/h | 4 | 0,40 | 0,45 | 3,9% | 3,5s |
| Đỉnh 60/h | 5 | 0,30 | 0,42 | 2,0% | 1,8s |
| Đỉnh 60/h | 5 | 0,50 | 0,30 | 0,6% | 0,5s |
| Quá tải 120/h | 3 | 0 | 2,00 | 52,9% | 47,6s |
| Quá tải 120/h | 5 | 0,30 | 0,84 | 14,2% | 12,8s |

`simulate_peak` (60 cuộc/h, c=5, cont 0,30): chờ xấu nhất 1,76s, P(bỏ) 0,0196, không callback. Callback trigger (chờ dự báo ≥60s): chờ TB đạt 60s tại 180 cuộc/h (c=3, cont 0), 255 cuộc/h (c=3, cont 0,30), 300 cuộc/h (c=5, cont 0); không đạt tới ở ≤360 cuộc/h với c=5/cont 0,30 hay c=8. Chờ TB ≥90s không đạt tới ở bất kỳ kịch bản nào tới 360 cuộc/h — vì với patience ~90s, khách bỏ cuộc trước khi hàng chờ dài ra. Kết luận: ngưỡng vận hành thực sự là 60s; 90s là khái niệm đuôi phân phối. Ở tải đỉnh 60 cuộc/h, callback không bao giờ bật — nó là công cụ cho tải gấp 3–5 lần đỉnh. Tin cậy TRUNG BÌNH: mô hình là code thật; đầu vào λ, thời gian phục vụ, patience là giả định từ brief, chưa đo trên tenant.

### 3.7 WER theo miền / mức ồn

Không có corpus audio, không có ASR được nối — WER âm thanh thật chưa đo được. Proxy text (n=5 cặp tự tạo): không dấu 0,857→0,429 (norm-vs-norm); miền Nam 0,286→0,286; miền Trung 0,250→0,125; ồn rớt từ 0,429→0,429; sạch 0,000. Phonetic key của câu không dấu và câu chuẩn trùng nhau hoàn toàn; trích mã đơn đúng 7/7. Pipeline quyết định bằng phonetic key + fuzzy match (0,55) + regex mã đơn, không phải bằng WER chính tả. Để đo WER thật cần: corpus ≥200 câu/miền × 3 mức ồn + một ASR vendor + chạy `evaluate_wer`.

### 3.8 Handoff / callback / shadow / go-live

Stub: 6/6 escalate → ticket CB-000001…CB-000006, package đầy đủ, serialisable; tóm tắt handoff 6/6 facts có căn cứ, Wilson [61,0%–100%]. Test E2E (đã đọc, chưa chạy): warm transfer chỉ bridge sau khi agent ACK context; hết agent → callback ticket; gate ở E2E là adapter viết tay, không phải `policy_engine` thật (B6). Canary: 102/2.000 (5,1%) ở mức 5%, 200/2.000 (10,0%) ở mức 10%. Kill-switch ~1µs trong process — đo đối tượng controller, không phải cắt tổng đài thật (<60s); cắt thật phải drill trên trunk/SIP. Shadow agreement 1,0 (12/12) là đo độ khớp của stub với kỳ vọng của chính bộ golden, không phải AI vs người. Go-live tenant rỗng: go=false, chặn bởi `containment_final_ci_low:0.254`, `readiness_checklist:0/7`, `baseline_abandonment_fcr_missing`. Hệ thống hiện không đủ điều kiện go-live.

## 4. Những gì KHÔNG ước lượng được ngoài mức bao phủ test

contained_final (72h) — không có dữ liệu liên hệ lại thật; latency p50/p95 thật từng chặng — không vendor nào được nối; WER theo miền/mức ồn — không corpus audio, không ASR; tỉ lệ trả lời sai thật — không lượt thật nào được human review; giảm abandonment / cải thiện FCR — không baseline abandonment/FCR của tenant; tỉ lệ câu lặp lại / cơ cấu lưu lượng — Q4 chưa đo; chi phí / cuộc contained — chưa có giá vendor, chưa có containment thật.

## 5. Yếu tố làm tăng / giảm %

Containment tăng khi câu lặp lại nhiều và dữ liệu sạch/có API/tươi, giảm khi nhiều khiếu nại/phức tạp và dữ liệu thiếu/trễ; latency đạt SLO khi vendor p95 ≤ ngân sách có biên và các chặng độc lập mạng, giảm khi tương quan mạng hoặc tool nằm trên đường first-audio; verifier chặn đúng khi evidence đầy đủ/tươi và policy khớp version, giảm khi record nguồn mâu thuẫn một phía; gate ít chuyển thừa khi lookup nhanh + retry và hiệu chuẩn hàng tuần; capacity ít bỏ cuộc khi containment cao và ca trực đủ giờ cao điểm.

## 6. Cỡ mẫu shadow / canary (Wilson 95%, power 80%, 300 cuộc/ngày)

Containment_final CI_low ≥0,30 nếu tỉ lệ thật 0,35/0,40/0,45/0,50 → n = 313/74/37/19. Containment p≈0,40: ±5pp → 369, ±3pp → 1.025. Hallucination <2% (0 sự kiện) → 189 câu trả lời liên tiếp không lỗi; p≈1% ±1pp → 381. Shadow agreement p≈0,90: ±5pp → 139, ±3pp → 385. Abandonment 8,4%→5,0% power 80% → 848 cuộc/nhóm. Lịch: n≈369 → 2 ngày shadow song song / 25 ngày canary 5% / 13 ngày canary 10%; n≈1.025 → 4 / 69 / 35 ngày. Khuyến nghị: shadow 2 ngày (~600 cuộc) rồi canary 10% trong 13 ngày (n≈390, ±5pp) + 72h theo dõi liên hệ lại sau cuộc canary cuối → contained_final đầu tiên có vào ngày thứ 16. Đừng cố chứng minh giảm abandonment trong canary (cần 848 cuộc/nhóm); đo abandonment trên toàn bộ lưu lượng shadow so với baseline 2 tuần.

## 7. Phát hiện chặn (blocker)

- B1: Harness trên main không import được với contracts thật — `AttributeError: contracts_missing_constant:RETRIEVAL_LLM_BUDGET_MS`, rc=1. Chủ: fullstack-ux — thêm `"LLM_FIRST_TOKEN_MS"` vào draft name. Sửa 1 dòng.
- B2: Không có commit hash / manifest / log pytest trên main được cấp. Chủ: CEO / systems-arch — công bố manifest + hash + log CI; freeze baseline trước vòng đánh giá sau.
- B3: Không có vendor ASR/LLM/TTS nào được nối; không có corpus audio. Chủ: CEO — chọn vendor, đo p50/p95 từng chặng trên ≥500 lượt thật; thu corpus ≥200 câu/miền × 3 mức ồn.
- B4: Golden JSON: nhãn intent 0/12 khớp enum `Intent` của dialogue_manager. Chủ: data owner / fullstack-ux — lập bảng map ở lớp đọc golden, không đổi thầm enum đã khóa.
- B5: Tenant chưa có dữ liệu nền: checklist 0/7, không baseline abandonment/FCR. Chủ: tenant onboarding / CEO — chạy 7 câu hỏi sẵn sàng + ghi baseline 2 tuần trước shadow.
- B6: Gate trong test E2E là adapter viết tay, không phải `policy_engine` thật. Chủ: backend-sec / fullstack-ux.
- B7: Test rebase của algo-ml hard-code 6 lý do, enum thật đã có 8. Chủ: algo-ml (tôi) — cập nhật test trên main sang 8 giá trị đã khóa.

## 8. Kế hoạch đo

1. Sửa B1+B4+B7 (~1 ngày, không cần traffic), chạy lại toàn bộ suite + harness, khóa log. 2. Đo baseline tenant 2 tuần (B5). 3. Đo vendor (B3): p50/p95 từng chặng trên ≥500 lượt thật, theo miền/ồn; kiểm tra tương quan giữa các chặng. 4. Đo WER: thu corpus, chạy `evaluate_wer`. 5. Shadow 2 ngày (~600 cuộc): agreement, hallucination (review 100% nhạy cảm + mẫu 20%), hỗn hợp gate, verifier chặn. Dừng nếu agreement <0,90 hoặc hallucination >2%. 6. Canary 10%, 13 ngày (n≈390) + drill kill-switch trên trunk thật (<60s). Sau cuộc cuối +72h: contained_final đầu tiên. 7. Go-live gate với số thật: chỉ go khi CI_low(contained_final) ≥0,30, hallucination ≤2%, agreement ≥0,90, checklist 7/7, baseline có. Không đạt → quay lại bước 5, không nới ngưỡng.

## Phụ lục A — Log chạy (bằng chứng; toàn văn log và JSON ở `feasibility_results.json` / `feasibility_results2.json` trên VM)

```
$ python -m pytest tests/ -q            # cây repo dựng lại, contracts v1.0.0 thật
100 passed in 0.35s                      # nguyên trạng 99/100 (1 test cũ hard-code 6 lý do, xem §2)
$ python scripts/evaluation/feasibility_run.py
B golden regression: passed=True merge_blocked=False n=12
  containment_provisional 0.500 n=12 [0.254, 0.746] | containment_final 0.500 (bằng nhau theo cấu trúc — §3.2)
  fcr 0.500 [0.254, 0.746] | abandonment 0.000 [0.000, 0.243] | hallucination 0.000 n=6 [0.000, 0.390]
  handoff_summary 1.000 n=6 [0.610, 1.000] | escalation 0.500 [0.254, 0.746]
  latency: asr 180 / llm 420 / tts 300 (hard-code) p50=p95=900ms slo=1200 violations=[] | tickets (no agent): 6
C load n=300: conc=100 wait 60.0s abandon 0.000 | conc=50 wait 150.0s abandon 0.500 | conc=30 wait 270.0s abandon 0.500 | conc=200 wait 15.0s abandon 0.000 (prov=0.500, esc=0.500 mọi trường hợp)
D shadow: n=12 agreement=1.000 divergences=0 sensitive=0
D canary: 5% -> 102/2000, 10% -> 200/2000, kill latency=0.000001s within_60s=True
D go-live (empty tenant): go=False blocked=[containment_final_ci_low:0.254, readiness_checklist:0/7, baseline_abandonment_fcr_missing]
E MC: independent p50=670.7 p95=923.7 P(>1200)=0.0017 P(>1100)=0.0058 | correlated p50=650.6 p95=1101.9 P(>1200)=0.0277 P(>1100)=0.0506 | +10% over p50=679.0 p95=993.2 P(>1200)=0.0073 P(>1100)=0.0191
F peak 60/h c=5 cont=0.30 a=2.10 rho=0.42 P(wait)=0.058 P(abandon)=0.0196 wait=1.8s overloaded=False callback=False
F overload 120/h c=5 cont=0.30 a=4.20 rho=0.84 P(wait)=0.360 P(abandon)=0.1422 wait=12.8s overloaded=False callback=False
F overload 120/h c=3 cont=0.00 a=6.00 rho=2.00 P(wait)=0.868 P(abandon)=0.5290 wait=47.6s overloaded=True callback=False
F peak sim (60/h, c=5, cont=0.30): worst wait 1.76s, worst P(abandon)=0.0196, offer_callback=False
G gate fuzz n=20000: answer=0.1804 clarify=0.3363 escalate=0.4833, hard_rule_violations=0, unnecessary_escalation 0/14 (định nghĩa chặt), clarify_twice_violations=0
H grounded golden: adversarial_blocked=6/6, happy_answered=2/2
I order-code extraction: 7/7
J golden JSON: n=12, answer=7, handoff=5, intent match 0/12, handoff reasons locked 12/12
K sample sizes: CI_low≥0.30 {p0.35: 313, p0.40: 74, p0.45: 37, p0.50: 19}; margin ±5pp=369, ±3pp=1025 (p=0.40); hallucination 0 events → 189; shadow agreement ±3pp=385; abandonment 8.4%→5.0% power80 → 848/arm; calendar n=369: 25d @5% / 13d @10% / 2d shadow; n=1025: 69d / 35d / 4d
$ python scripts/evaluation/feasibility_run2.py
1 as-is import rc=1: AttributeError: contracts_missing_constant:RETRIEVAL_LLM_BUDGET_MS
2 gate reasons: n=20000 decisions={escalate: 9666, clarify: 6726, answer: 3608}, reasons={missing_evidence: 3503, below_answer_threshold: 6726, above_answer_threshold: 3608, verifier_failed: 2461, below_clarify_threshold: 3702}, human_answerable=1023, human_answerable_escalated=0, rate=0.0
3 wer: no_diacritics raw=0.857 norm-vs-norm=0.429 | south 0.286/0.286 | central 0.250/0.125 | noisy_drop 0.429/0.429 | clean 0.000/0.000
4 callback boundary: wait≥60s at 180/h (c3 cont0), 255/h (c3 cont0.30), 300/h (c5 cont0); c5 cont0.30 / c8: never ≤360/h; wait≥90s: never ≤360/h in any scenario
```

Ghi chú: dòng `G ... unnecessary_escalation 0/14` dùng định nghĩa "good" chặt (mọi tín hiệu ≥0,9) nên mẫu good quá nhỏ — con số dùng trong báo cáo là định nghĩa nới ở run2 (`human_answerable_escalated 0/1.023`, §3.5). VM: Linux, Python 3.12.3, pytest 9.2.0 (venv riêng). Seeds: Monte Carlo seed 7, n=200.000; gate fuzz seed 11, n=20.000. Shim duy nhất (trong bộ nhớ, không sửa file): `contracts.LLM_BUDGET_MS = contracts.LLM_FIRST_TOKEN_MS` trước khi import harness — xem B1.

## Phụ lục B — Nguồn

- Mốc độc lập đã dùng: DigyAI (agent ~35% tác vụ nhiều bước; voice agent 26–38% trong ồn/nhiều giọng, 2026); SQM Group (bỏ cuộc chuẩn ~5%); ContactBabel UK 2024 (bỏ cuộc TB 8,4%, n=225).
- Số vendor đã loại: Ada (~72% / ~52%), Intercom Fin (76%), Gartner (80% tới 2029), FPT AI Engage (intent 92%), Klarna (67%).
- Đặc tả đã khóa: `src/contracts.py` v1.0.0 trên main (MAX_CLARIFICATIONS=1, cửa sổ containment 72h, ngân sách 250+500+350=1100ms, SLO p95 1200ms, `TOOL_CALL_OFF_PATH_MS`=500ms).
- Báo cáo nền: qa-verifier 26/11/2026 (blocked — không có repo/commit hash trên VM của họ); CEO (bản sửa 1); báo cáo Hội đồng Chuyên gia #15.

## Tóm tắt gửi CEO (muse)

- Không có một con số % duy nhất: contained_final (72h) — chỉ số duy nhất được phép công bố — chưa ước lượng được vì không có dữ liệu liên hệ lại thật và không có commit baseline nào được cấp (QA blocked); khoảng lập kế hoạch cho contained_provisional là 26–50%, tin cậy thấp — và đây là khoảng của mô phỏng cục bộ, không phải đo trên baseline đã xác nhận.
- Đã chứng minh bằng code chạy: verifier chặn 6/6 ca đối nghịch, gate 0 vi phạm hard rule/MAX=1 trên 20.000 lượt fuzz, harness golden 12/12, Erlang-A đỉnh 60 cuộc/h với 5 nhân viên cho tỉ lệ bỏ 2–6%; 6 module + 7 file test đạt 100 passed với contracts v1.0.0 thật trên main (bản dựng lại cục bộ).
- Ba blocker phải sửa trước vòng đo sau: harness không import được với contracts thật (`RETRIEVAL_LLM_BUDGET_MS`, sửa 1 dòng, chủ fullstack-ux); latency/WER chưa đo được vì chưa nối vendor nào; golden JSON 0/12 nhãn intent khớp enum dialogue.
- Để thay khoảng bằng số đo: shadow 2 ngày (~600 cuộc) rồi canary 10% trong 13 ngày (n≈390, ±5 điểm phần trăm) + 72h theo dõi liên hệ lại; đừng hứa 80% hay 52% — hai số đó là dự báo và số vendor, đã bị loại khỏi báo cáo này.
