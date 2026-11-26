# Đánh giá khả thi — AI trợ lý giọng nói realtime trả lời khách hàng

- **Tác giả:** algo-ml · **Ngày:** 26/11/2026 · **Báo cáo cho:** CEO (muse) · **Lần nộp 2** (toàn bộ; lần 1 chỉ ghi nhận được script kèm, thiếu báo cáo)
- **Script chạy kèm:** `scripts/evaluation/feasibility_run.py`, `scripts/evaluation/feasibility_run2.py` (nộp kèm sau; log tóm tắt ở Phụ lục A).

## 0. Baseline commit và trạng thái phụ thuộc QA

- **Commit baseline: KHÔNG ĐƯỢC CẤP.** Không có commit hash, manifest hay log pytest trên main nào được cấp cho algo-ml.
- **QA (qa-verifier, 26/11/2026): BLOCKED.** Trên VM của QA không có repo, không có `src/contracts.py`, không có commit để khóa baseline, pytest chưa cài — mọi hạng mục cần chạy code đều Blocked/Not tested, không đổi % pass test thành % go-live.
- **VM algo-ml ban đầu giống hệt** (không có bản clone repo, pytest chưa cài sau khi VM thay mới). Mọi số trong báo cáo được chạy trên cây repo **dựng lại từ đúng nội dung 4 file trên main do điều phối viên cấp 26/11/2026** (`src/contracts.py`, `src/eval/simulation_harness.py`, `data/golden/golden_calls.json`, `tests/test_e2e_call.py` — đã đọc) cộng 6 module + 7 file test của algo-ml. Đây là "chạy lại từ nội dung file main đã nhận", **không phải "chạy trên commit X"**. Khi CEO/systems-arch công bố manifest + hash + log CI (B2), toàn bộ số phải chạy lại trên commit đó.
- **Kết luận:** không có một con số % duy nhất. **contained_final (72h)** — chỉ số duy nhất được phép dùng cho go-live/đối ngoại — **CHƯA ƯỚC LƯỢNG ĐƯỢC**. Khoảng lập kế hoạch (không phải cam kết): contained_provisional **26–50%** (THẤP); latency p95 **924–1.102ms** mô phỏng (THẤP); tỉ lệ trả lời sai **chưa đo được**; abandonment đỉnh **2–6%** với 5 nhân viên ở 60 cuộc/h (TRUNG BÌNH). Để thay khoảng bằng số đo: shadow 2 ngày (~600 cuộc) rồi canary 10% trong **13 ngày (n≈390, ±5 điểm phần trăm)** hoặc **35 ngày (n≈1.025, ±3 điểm phần trăm)** ở 300 cuộc/ngày, cộng 72h theo dõi liên hệ lại (§6).
- **Số vendor bị LOẠI khỏi mọi ước lượng:** Ada ~72% containment / ~52% tự động; Intercom Fin 76%; Gartner "80% tới 2029" (dự báo); FPT "intent 92%"; Klarna 67% — tự công bố/chưa kiểm toán hoặc dự báo, định nghĩa không phải containment 2 lớp 72h đã khóa. Số 0,52 còn là default trong `CapacityPlanner.__init__` — chỉ là placeholder. **Mốc độc lập làm cận dưới:** agent ~35% tác vụ nhiều bước; voice agent 26–38% trong điều kiện ồn/nhiều giọng (DigyAI, 2026). Benchmark bỏ cuộc 5% (SQM) / 8,4% (ContactBabel UK 2024, n=225) là quốc tế, không phải số Việt Nam.

## 1. Bảng chỉ số chính

| # | Chỉ số | Giá trị đo / mô phỏng | Khoảng % lập kế hoạch | Tin cậy |
|---|---|---|---|---|
| 1 | **contained_provisional** (AI giải quyết trong cuộc, có evidence) | Golden: 6/12 = **50%**, Wilson [25,4% – 74,6%] | **26–50%** trên lưu lượng thật | **Thấp** (§3.1) |
| 2 | **contained_final (72h)** (provisional VÀ không liên hệ lại cùng vấn đề trong 72h) | **Chưa ước lượng được** | — (cận trên = provisional) | — (§3.2) |
| 3 | **Latency p50/p95** vs ngân sách 250+500+350=1100ms, SLO p95 <1200ms | Stub: p50 = p95 = **900ms** (hard-code). Monte Carlo p95 **924–1.102ms**; P(vượt SLO) 0,17% – 2,77% | p95 **924–1.102ms** | **Thấp** (§3.3) |
| 4 | **Grounded verifier** (chặn đúng/sai trên golden cases) | Chặn **6/6** ca đối nghịch, trả lời đúng **2/2** happy-path. Hallucination stub 0/6, Wilson [0% – 39,0%] | Tỉ lệ trả lời sai thật: **chưa đo được** | **Thấp** (tỉ lệ); **Cao** (chặn trên ca đã biết) (§3.4) |
| 5 | **Confidence gate** (trả lời sai / chuyển thừa / hỏi lại ≤1 lần) | Fuzz n=20.000: trả lời 18,0% / hỏi lại 33,6% / chuyển 48,3%. Vi phạm hard rule **0**, hỏi lại lần 2 **0**, chuyển thừa **0/1.023** | Chuyển thừa **0% trong fuzz**; trả lời sai **0% với 2 hard rule** | **Trung bình** (logic); **Thấp** (tỉ lệ thật) (§3.5) |
| 6 | **Capacity Erlang-A** (abandonment / callback khi chờ dự báo vượt 60–90s) | Đỉnh 60 cuộc/h, c=5, cont 0,30: P(bỏ)=**1,96%**, chờ TB 1,8s. Quá tải 120 cuộc/h, c=5, cont 0,30: P(bỏ)=**14,2%**, chờ 12,8s. Callback chỉ bật từ **180–300 cuộc/h**; chờ TB ≥90s **không đạt tới** ở ≤360 cuộc/h | Abandonment đỉnh **2–6%**; quá tải gấp đôi **14–28%** | **Trung bình** (§3.6) |
| 7 | **WER theo miền / mức ồn** | Proxy text (n=5): WER sau chuẩn hoá 0,000–0,429; mã đơn **7/7** | WER âm thanh thật: **chưa đo được** | **Thấp** (§3.7) |
| 8 | **Handoff / callback / shadow / go-live** | Stub: 6/6 escalate → ticket, tóm tắt 6/6 có căn cứ. Canary 5,1%/10,0% trên 2.000 id. Kill-switch ~1µs (in-process). Shadow vs oracle 1,0 (12/12, đo vòng tròn). Go-live tenant rỗng: **NO-GO** | — (chưa có tỉ lệ thật) | **Thấp** (tỉ lệ); **Cao** (gate chặn đúng) (§3.8) |

## 2. Chuỗi bằng chứng (VM algo-ml: Python 3.12.3, pytest 9.2.0, venv riêng)

- `src/contracts.py` trên main: **đã hòa giải về đúng v1.0.0** — version `1.0.0`, `MAX_CLARIFICATIONS = 1`, cửa sổ 72h, ASR 250 / LLM 500 / TTS 350, SLO 1200, `TOOL_CALL_OFF_PATH_MS = 500`, `EscalationReason` đủ 8 giá trị (6 lõi + `no_agent`/`system_error` log-only). Lệch 5 chỗ của bản m3 đã không còn. `check_latency_budget()` = `True`.
- 6 module + 7 file test với contracts **thật**: **100 passed trong 0,35s** (16/16/13/16/13/14/12). Trung thực: nguyên trạng **99/100** — 1 test rớt là `test_escalation_reasons_come_from_contracts_enum` (file rebase của chính tôi, hard-code 6 lý do theo stub cũ, enum thật có 8; module đúng, test cũ lỗi thời; đã sửa expectation trong bản local → 100/100; bản trên main vẫn cần sửa — B7). 100 passed là **bao phủ unit test**, không phải % go-live.
- `src/eval/simulation_harness.py`: **không import được nguyên trạng với contracts thật** (B1): `AttributeError: contracts_missing_constant:RETRIEVAL_LLM_BUDGET_MS`, rc=1. Chỉ chạy sau shim trong bộ nhớ (`contracts.LLM_BUDGET_MS = LLM_FIRST_TOKEN_MS`, không sửa file).
- `data/golden/golden_calls.json`: 12 cuộc, 7 answer / 5 handoff; nhãn intent **0/12 khớp** enum `Intent` (B4); lý do handoff 12/12 là giá trị đã khóa. `tests/test_e2e_call.py`: **đã đọc, chưa chạy** (cần `dialogue_manager`, `handoff_service`, `context_package`). Commit hash / manifest / log pytest trên main: **không được cấp** (§0).

## 3. Chi tiết từng chỉ số

### 3.1 contained_provisional — 50% trên harness không phải ước lượng

`run_regression(DEFAULT_GOLDEN_CALLS, SimulatedCallFlow())`: **passed=true, merge_blocked=false, 12/12 đúng hành động**, provisional **6/12 = 50%** Wilson [25,4% – 74,6%], escalation 50%, abandonment 0/12 [0% – 24,3%], handoff summary 6/6 [61,0% – 100%]. `simulate_load` 300 cuộc (xoay vòng 12 golden) cho cùng 50% [44,4% – 55,6%] — nhưng đó là **cùng 12 cuộc lặp 25 lần**, không phải 300 cuộc độc lập, CI hẹp là ảo. Vì sao không đọc 50% thành "AI xử lý 50% cuộc gọi": bộ golden được **thiết kế cân bằng** (6 answer / 6 escalate) — nó đo **độ chính xác hành động**, không đo tỉ lệ lưu lượng; containment thật = (tỉ lệ cuộc lặp lại đơn giản) × (tỉ lệ pipeline trả lời đúng nhóm đó) — cả hai thừa số đều chưa có (Q4 checklist chưa đo). **Khoảng 26–50%:** cận dưới 26% là mốc độc lập thấp nhất cho voice agent ồn/nhiều giọng (DigyAI); cận trên 50% là giá trị harness trên bộ golden cân bằng — **trần lạc quan**, không phải kỳ vọng. Tăng: câu lặp lại nhiều; dữ liệu đơn/kho/FAQ sạch, có API; ASR tốt 3 miền. Giảm: nhiều khiếu nại/phức tạp; dữ liệu thiếu/trễ; ồn/nhiều giọng; khách nói không dấu + sai mã.

### 3.2 contained_final (72h) — chưa ước lượng được

Định nghĩa đã khóa: `contained_final = contained_provisional AND NOT recontacted_within_window (72h)`. Harness không đặt `repeat_contact` bao giờ, nên trên golden **final = provisional = 50% theo cấu trúc** — con số 50% ở cột final là **giả tạo**. **Cận trên duy nhất có cơ sở: contained_final ≤ contained_provisional.** Mọi tuyên bố "final = X%" trước khi có dữ liệu liên hệ lại đều là bịa. Để đo: join mỗi cuộc canary với log liên hệ lại cùng số điện thoại + cùng vấn đề trong 72h; cửa sổ đo chỉ đóng **72h sau cuộc canary cuối cùng** (canary 13 ngày → final đầu tiên sau ngày 16). Cỡ mẫu §6 (n≈369 để CI_low ≥ 0,30 nếu p thật 0,40; n≈1.025 để ±3 điểm phần trăm).

### 3.3 Latency p50/p95 — SLO đạt trên giấy, chưa đo ngoài đời

**Harness stub không đo latency:** hard-code `lat = {"asr": 180, "llm": 420, "tts": 300}` cho mọi cuộc → p50 = p95 = **900ms**, SLO 1200ms, không vi phạm. 900ms là **hằng số tác giả tự điền**. **Monte Carlo (200.000 mẫu, seed 7):** mỗi chặng lognormal, median ASR/LLM/TTS = 150/300/200ms (giả định, không phải đo), p95 = đúng ngân sách 250/500/350ms:

| Kịch bản | p50 | p95 | P(tổng > 1200ms SLO) | P(tổng > 1100ms) |
|---|---:|---:|---:|---:|
| Độc lập, p95 đúng ngân sách | 671ms | **924ms** | **0,17%** | 0,58% |
| Tương quan hoàn toàn, p95 đúng ngân sách | 651ms | **1.102ms** | **2,77%** | 5,06% |
| Độc lập, mỗi chặng p95 vượt ngân sách 10% | 679ms | **993ms** | **0,73%** | 1,91% |

Đọc đúng: độc lập → tổng p95 ≈ 924ms, SLO còn **~276ms dự phòng** (tổng các p95 không phải p95 của tổng). Tương quan (mạng chậm làm chậm cả 3 chặng) → p95 ≈ 1.102ms, còn ~98ms dự phòng, 2,77% vượt SLO — **tương quan là rủi ro chính**. Vendor trễ hơn ngân sách 10% → p95 ≈ 993ms, vẫn đạt. **Tin cậy THẤP:** median là giả định; vendor thật có median 220/450/320ms thì tổng p95 cao hơn nhiều. Cần p50/p95 thật từng vendor trên ≥500 lượt thật, theo miền/ồn. Tăng % đạt SLO: vendor p95 ≤ ngân sách có biên; prefetch tool khi đủ slot; filler song song khi tool >500ms. Giảm: vendor p95 sát/vượt ngân sách; mạng chung làm tương quan; tool nằm trên đường first-audio.

### 3.4 Grounded verifier — chặn đúng 6/6, nhưng n=6 chứng minh được rất ít

Chạy **module thật** `GroundedAnswerer` trên 4 golden case đã khóa: (1) không record → UNKNOWN `no_record`, không speakable; (2) record mâu thuẫn → REJECTED `contradictory_evidence`; (3) thiếu trường bắt buộc → UNKNOWN `missing_required_field:status` (sau sửa `order_id` → `order_code`, lần nộp 3); (4a) sai tiền 35.000 → 50.000 → REJECTED `numeric_mismatch`, số sai **không xuất hiện** trong text (350.000 = 350000 = 350k); (4b) sai ngày 26/11 → 30/11 → REJECTED `date_mismatch`; (4c) sai mã DH123 → DH999 → REJECTED `code_mismatch`; happy-path tra đơn/phí ship → ANSWERED, có citation — 2/2. Tổng: **chặn đối nghịch 6/6, trả lời đúng 2/2** — bằng chứng **hành vi chặn trên ca đã biết** (tin cậy Cao cho đúng các ca đó), không phải tỉ lệ thật. Vì sao không suy ra "trả lời sai = 0%": hallucination trên stub = **0/6**, Wilson 95% **[0% – 39,0%]** — "0 lần quan sát" vẫn tương thích với tỉ lệ thật tới 39%. Muốn tuyên bố hallucination <2% cần **189 câu trả lời liên tiếp không lỗi** (§6). Tỉ lệ thật chỉ đo được bằng human review trên shadow/canary. Tăng chặn đúng: evidence đầy đủ + tươi; policy version khớp; verifier chạy sau mọi draft. Giảm: record nguồn mâu thuẫn một phía; số/ngày trong text tự do; tool timeout rồi LLM tự "điền".

### 3.5 Confidence gate — logic đã khóa thì đúng, tỉ lệ thật thì chưa có

Fuzz n=20.000 lượt (seed 11) trên `ConfidenceGate` thật; phân phối tín hiệu **giả định** (50% lượt "sạch": asr~Beta(9,1), intent~Beta(8,2), evidence/verifier cao, `has_evidence` p=0,95; 50% lượt "ồn": asr~Beta(2,3), intent/entity/evidence~Beta(3,3), verifier~Beta(4,3), `has_evidence` p=0,70).

| Kết quả fuzz (n=20.000) | Số | Tỉ lệ |
|---|---:|---:|
| Trả lời / hỏi lại / chuyển người | 3.608 / 6.726 / 9.666 | 18,0% / 33,6% / 48,3% |
| Trong chuyển: `missing_evidence` / `verifier_failed` / `below_clarify_threshold` | 3.503 / 2.461 / 3.702 | 17,5% / 12,3% / 18,5% |
| **Trả lời khi thiếu evidence hoặc verifier rớt (vi phạm hard rule)** | **0** | **0%** |
| **Hỏi lại lần 2 (vi phạm MAX_CLARIFICATIONS=1)** | **0** | **0%** |
| **Chuyển cuộc-mà-người-trả-lời-được** (evidence có, verifier ≥0,9, intent/entity/completeness ≥0,8) | **0 / 1.023** | **0%** |

Chuyển được sang thật: 3 đảm bảo logic — không trả lời khi thiếu evidence/verifier rớt; không hỏi lại lần 2; không chuyển cuộc-mà-người-trả-lời-được (hard rule nên đúng với mọi lượt rút). Unit test 16/16 xác nhận biên: 0,85 trả lời, 0,849 hỏi lại, 0,60 hỏi lại, 0,599 chuyển; sau 1 lần hỏi lại thì chuyển với `repeated_clarification`. **Không chuyển được:** hỗn hợp 18/34/48 là tính chất của phân phối giả định (50% lượt ồn), không phải dự báo tenant; hỗn hợp thật chỉ đo được bằng shadow. **Tỉ lệ trả lời sai:** bằng 0 **với 2 hard rule**; các đường sai khác (intent hiệu chuẩn sai, entity khớp nhầm record, evidence cũ) phụ thuộc **dữ liệu hiệu chuẩn thật, hiện chưa có** (ngưỡng 0,85/0,60 suy ra từ chi phí 100/15, chưa phải từ đo; phải refit hàng tuần khi có outcome thật — đã có `record_outcome`). Tăng chuyển thừa: lookup evidence lỗi thoáng qua; verifier false-positive. Giảm: prefetch evidence khi đủ slot; retry lookup trước khi kết luận missing; hiệu chuẩn hàng tuần.

### 3.6 Capacity Erlang-A — bỏ cuộc hữu hạn, callback chỉ bật khi tải gấp 3–5 lần đỉnh

Chạy `CapacityPlanner` thật (patience 90s, phục vụ TB 3 phút). Giả định tải: 300 cuộc/ngày, đỉnh = 60 cuộc/h (20% ngày trong 1 giờ) → λ=1,0/phút; quá tải = 120 cuộc/h → λ=2,0/phút. Containment là **biến số** (0 / 0,30 / 0,40 / 0,50) — default 0,52 của module là số vendor Ada, không dùng làm ước lượng. (Bảng đầy đủ 19 dòng ở `feasibility_results.json` trên VM.)

| Kịch bản | c | cont | ρ | P(phải chờ) | P(bỏ cuộc) | Chờ TB |
|---|---:|---:|---:|---:|---:|---:|
| Đỉnh 60/h | 3 | 0 | 1,00 | 0,511 | **25,9%** | 23,3s |
| Đỉnh 60/h | 3 | 0,30 | 0,70 | 0,315 | 15,0% | 13,5s |
| Đỉnh 60/h | 4 | 0,30 | 0,53 | 0,148 | 5,8% | 5,3s |
| Đỉnh 60/h | 4 | 0,40 | 0,45 | 0,101 | 3,9% | 3,5s |
| Đỉnh 60/h | 5 | 0,30 | 0,42 | 0,058 | **2,0%** | 1,8s |
| Đỉnh 60/h | 5 | 0,50 | 0,30 | 0,018 | 0,6% | 0,5s |
| Quá tải 120/h | 3 | 0 | 2,00 | 0,868 | **52,9%** | 47,6s |
| Quá tải 120/h | 5 | 0,30 | 0,84 | 0,360 | **14,2%** | 12,8s |

`simulate_peak` (60 cuộc/h, c=5, cont 0,30): chờ xấu nhất 1,76s, P(bỏ) 0,0196, không callback. Mô hình tải của harness (`simulate_load`: chờ=(n/c−1)×30s, bỏ cuộc là hàm bậc khi chờ >90s) cho 0% bỏ ở c=100 và 50% bỏ ở c=50 — **mô hình đồ chơi tuyến tính**, không dùng để kết luận. **Callback trigger (chờ dự báo ≥60s):** quét λ 0,1–6,0/phút: chờ TB đạt 60s tại **180 cuộc/h** (c=3, cont 0), **255 cuộc/h** (c=3, cont 0,30), **300 cuộc/h** (c=5, cont 0); **không đạt tới ở ≤360 cuộc/h** với c=5/cont 0,30 hay c=8. Chờ TB **≥90s không đạt tới ở bất kỳ kịch bản nào tới 360 cuộc/h** — vì với patience ~90s, khách bỏ cuộc trước khi hàng chờ dài ra (đúng bản chất Erlang-A: chờ hữu hạn). Kết luận: **ngưỡng vận hành thực sự là 60s**; 90s là khái niệm đuôi phân phối, không phải chờ trung bình. Ở tải đỉnh đã nêu (60 cuộc/h), callback **không bao giờ bật** — nó là công cụ cho tải gấp 3–5 lần đỉnh (chiến dịch, sự cố). **Tin cậy TRUNG BÌNH:** mô hình là code thật (test c=1 khớp M/M/1, quá tải cho chờ hữu hạn, không số âm/NaN); đầu vào λ, thời gian phục vụ, patience là giả định từ brief, chưa đo trên tenant.

### 3.7 WER theo miền / mức ồn — proxy text làm được tới đâu, cái gì vẫn trống

**Không có corpus audio, không có ASR được nối — WER âm thanh thật chưa đo được.** Module có sẵn `word_error_rate` và `evaluate_wer(cases)`; dữ liệu để chạy thì không có. Proxy text (n=5 cặp tự tạo): không dấu 0,857→**0,429** (norm-vs-norm); miền Nam 0,286→**0,286** ("tui" không map sang "tôi"); miền Trung 0,250→**0,125** ("răng"→"sao" đúng; "miềng" không map sang "mình"); ồn rớt từ 0,429→**0,429**; sạch 0,000. Quan trọng hơn WER là **đường quyết định thật**: phonetic key của câu không dấu và câu chuẩn **trùng nhau hoàn toàn**; **trích mã đơn đúng 7/7** (kể cả không dấu, miền Nam/Trung, mã sai DH999999). Pipeline quyết định bằng phonetic key + fuzzy match (0,55) + regex mã đơn, không phải bằng WER chính tả. **Để đo WER thật cần:** corpus ghi âm ≥200 câu/miền (Bắc/Trung/Nam) × 3 mức ồn, có transcript chuẩn; nối một ASR vendor; chạy `evaluate_wer`.

### 3.8 Handoff / callback / shadow / go-live

- Harness stub: 6/6 cuộc escalate (không có agent) → ticket `CB-000001`…`CB-000006`, package đầy đủ, serialisable. Tóm tắt handoff: 6/6 facts có căn cứ, Wilson [61,0% – 100%]. Test E2E (đã đọc, chưa chạy local): warm transfer chỉ bridge sau khi agent ACK context; hết agent → callback ticket kèm toàn bộ package; ticket chịu được JSON round-trip. Gate ở E2E hiện là **adapter** viết tay theo hard rule, không phải `policy_engine` thật (B6).
- Canary routing: **102/2.000 (5,1%)** ở mức 5% và **200/2.000 (10,0%)** ở mức 10% — đúng thiết kế. Kill-switch: ~1µs trong process — đó là đo **đối tượng controller**, không phải **cắt tổng đài thật** (<60s); cắt thật phải drill trên trunk/SIP.
- Shadow agreement: `run_shadow` (stub vs oracle từ kỳ vọng golden) = **1,0 (12/12)**, 0 divergence — đo **độ khớp của stub với kỳ vọng của chính bộ golden**, không phải AI vs người. Shadow thật chỉ có khi AI chạy song song với nhân viên trên cùng cuộc thật.
- Go-live gate: `evaluate_go_live` với tenant rỗng → **go=false**, chặn bởi đúng 3 lý do: `containment_final_ci_low:0.254` (<0,30), `readiness_checklist:0/7`, `baseline_abandonment_fcr_missing`. Gate đang làm đúng việc của nó; hệ thống hiện **không đủ điều kiện go-live**.

## 4. Những gì KHÔNG ước lượng được ngoài mức bao phủ test

| # | Không ước lượng được | Vì sao | Cần gì để đo |
|---|---|---|---|
| 1 | contained_final (72h) | Không có dữ liệu liên hệ lại thật | Lưu lượng canary + join liên hệ lại 72h (§6) |
| 2 | Latency p50/p95 thật từng chặng | Không có ASR/LLM/TTS vendor nào được nối | Vendor + ≥500 lượt thật, theo miền/ồn (B3) |
| 3 | WER theo miền / mức ồn | Không có corpus audio, không có ASR | Corpus ≥200 câu/miền × 3 mức ồn (B3) |
| 4 | Tỉ lệ trả lời sai trên lưu lượng thật | Không có lượt thật nào được human review | Shadow + review (§8) |
| 5 | Giảm abandonment (từ baseline ?%) | Không có baseline abandonment/FCR của tenant | Đo baseline 2 tuần (B5) |
| 6 | Tỉ lệ câu lặp lại / cơ cấu lưu lượng | Q4 chưa đo ở tenant nào | Phân loại 2 tuần log cuộc gọi |
| 7 | Chi phí / cuộc contained | Chưa có giá vendor, chưa có containment thật | Giá vendor + containment canary |
| 8 | Cải thiện FCR | Không có baseline FCR | Như (5) |

## 5. Yếu tố làm tăng / giảm %

Đã nêu inline ở cuối mỗi mục §3.1–§3.6. Tóm tắt: containment tăng khi câu lặp lại nhiều và dữ liệu sạch/có API/tươi, giảm khi nhiều khiếu nại/phức tạp và dữ liệu thiếu/trễ; latency đạt SLO khi vendor p95 ≤ ngân sách có biên và các chặng độc lập mạng, giảm khi tương quan mạng hoặc tool nằm trên đường first-audio; verifier chặn đúng khi evidence đầy đủ/tươi và policy khớp version, giảm khi record nguồn mâu thuẫn một phía; gate ít chuyển thừa khi lookup nhanh + retry và hiệu chuẩn hàng tuần; capacity ít bỏ cuộc khi containment cao và ca trực đủ giờ cao điểm.

## 6. Cỡ mẫu shadow / canary cần thiết (Wilson 95%, power 80%, 300 cuộc/ngày)

| Mục tiêu | Cỡ mẫu |
|---|---|
| Containment_final: CI_low ≥ 0,30 nếu tỉ lệ thật 0,35 / 0,40 / 0,45 / 0,50 | n = **313 / 74 / 37 / 19** |
| Containment p≈0,40: ±5 / ±3 điểm phần trăm | n = **369 / 1.025** |
| Hallucination <2% (0 sự kiện, Wilson upper <0,02) | **189 câu trả lời** liên tiếp không lỗi; p≈1% ±1pp → 381 |
| Shadow agreement p≈0,90: ±5 / ±3 điểm phần trăm | n = 139 / **385** |
| Abandonment 8,4% → 5,0%, power 80% | **848 cuộc / nhóm** (canary vs đối chứng) |

| Mục tiêu | Shadow song song (300/ngày) | Canary 5% (15/ngày) | Canary 10% (30/ngày) |
|---|---:|---:|---:|
| Containment n≈369 (±5pp) | **2 ngày** | 25 ngày | **13 ngày** |
| Containment n≈1.025 (±3pp) | 4 ngày | 69 ngày | 35 ngày |
| Shadow agreement n≈385 (±3pp) | **2 ngày** | 26 ngày | 13 ngày |

**Khuyến nghị đo:** (1) Shadow 2 ngày (~600 cuộc) để đo agreement, hallucination (review 100% ca nhạy cảm + mẫu 20%), hỗn hợp gate, verifier chặn. (2) Canary 10% trong **13 ngày (n≈390)** → containment_provisional ±5pp; cộng **72h theo dõi liên hệ lại** sau cuộc canary cuối → contained_final đầu tiên có vào ngày thứ 16. (3) Chỉ kéo dài tới 35 ngày (n≈1.025, ±3pp) nếu CI 13 ngày quá rộng hoặc p thật gần ngưỡng 0,30. (4) **Đừng cố chứng minh giảm abandonment trong canary:** cần 848 cuộc/nhóm (~2 tháng ở 10%); thay vào đó đo abandonment trên toàn bộ lưu lượng shadow so với baseline 2 tuần.

## 7. Phát hiện chặn (blocker)

| # | Blocker | Bằng chứng | Chủ sở hữu / Cách sửa |
|---|---|---|---|
| B1 | **Harness trên main không import được với contracts thật** | `AttributeError: contracts_missing_constant:RETRIEVAL_LLM_BUDGET_MS`, rc=1, tái lập trong subprocess | **fullstack-ux** — thêm `"LLM_FIRST_TOKEN_MS"` vào draft name của `_locked("RETRIEVAL_LLM_BUDGET_MS", "LLM_BUDGET_MS")`. Sửa 1 dòng. |
| B2 | Không có commit hash / manifest / log pytest trên main được cấp | Như blocker của qa-verifier 26/11/2026 | **CEO / systems-arch** — công bố manifest + hash + log CI; freeze baseline trước vòng đánh giá sau. |
| B3 | Không có vendor ASR/LLM/TTS nào được nối; không có corpus audio | Latency và WER đều chưa đo được (§3.3, §3.7) | **CEO** — chọn vendor, đo p50/p95 từng chặng trên ≥500 lượt thật; thu corpus ≥200 câu/miền × 3 mức ồn. |
| B4 | `data/golden/golden_calls.json`: nhãn intent **0/12** khớp enum `Intent` của dialogue_manager | `tra_don, phi_ship, doi_tra, bao_hanh, dat_lich, ton_kho…` vs `order_tracking, shipping_fee, return_exchange, warranty, book_appointment…` | **Data owner / fullstack-ux** — lập bảng map (vd `tra_don→order_tracking`, `phi_ship→shipping_fee`, `doi_tra→return_exchange`, `bao_hanh→warranty`, `dat_lich→book_appointment`, `ton_kho→check_inventory`) ở lớp đọc golden, không đổi thầm enum đã khóa. |
| B5 | Tenant chưa có dữ liệu nền: checklist sẵn sàng **0/7**, không baseline abandonment/FCR | `evaluate_go_live` chặn `readiness_checklist:0/7` + `baseline_abandonment_fcr_missing` | **Tenant onboarding / CEO** — chạy 7 câu hỏi sẵn sàng + ghi baseline 2 tuần trước shadow. |
| B6 | Gate trong test E2E là adapter viết tay, không phải `policy_engine` thật | `tests/test_e2e_call.py` tự ghi chú điều này | **backend-sec / fullstack-ux** — nối `policy_engine` thật vào đường E2E, hoặc ghi adapter là khoảng trống đã biết. |
| B7 | Test rebase của algo-ml hard-code 6 lý do, enum thật đã có 8 (thêm 2 log-only) | 99/100 khi chạy nguyên trạng với contracts thật; 100/100 sau khi sửa expectation trong bản local | **algo-ml (tôi)** — cập nhật `tests/test_fix_rebase_algo_ml_to_contracts.py` trên main sang 8 giá trị đã khóa. |

## 8. Kế hoạch đo

1. **Sửa B1 + B4 + B7** (~1 ngày, không cần traffic): harness chạy được nguyên trạng; golden JSON đọc được qua map; test rebase khớp enum thật. Chạy lại toàn bộ suite + harness, khóa log. 2. **Đo baseline tenant 2 tuần** (B5): abandonment, FCR, tỉ lệ câu lặp lại, λ giờ cao điểm, thời gian phục vụ TB. 3. **Đo vendor** (B3): p50/p95 từng chặng trên ≥500 lượt thật, theo miền/ồn; kiểm tra tương quan giữa các chặng. 4. **Đo WER**: thu corpus, chạy `evaluate_wer` theo miền × mức ồn. 5. **Shadow 2 ngày** (~600 cuộc): agreement, hallucination (review 100% nhạy cảm + mẫu 20%), hỗn hợp gate, verifier chặn. Dừng nếu agreement <0,90 hoặc hallucination >2% — sửa rồi shadow lại, không lên canary. 6. **Canary 10%, 13 ngày** (n≈390) + drill kill-switch trên trunk thật (<60s). Sau cuộc cuối +72h: contained_final đầu tiên. 7. **Go-live gate với số thật:** chỉ go khi CI_low(contained_final) ≥0,30, hallucination ≤2%, agreement ≥0,90, checklist 7/7, baseline có. Không đạt → quay lại bước 5, không nới ngưỡng.

## Phụ lục A — Log chạy (bằng chứng; toàn văn log và JSON ở `feasibility_results.json` / `feasibility_results2.json` trên VM; log đầy đủ cũng nộp kèm với 2 script)

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

Ghi chú về log: dòng `G ... unnecessary_escalation 0/14` dùng định nghĩa "good" chặt (mọi tín hiệu ≥0,9) nên mẫu good quá nhỏ — con số dùng trong báo cáo là định nghĩa nới ở run2 (`human_answerable_escalated 0/1.023`, xem §3.5). VM: Linux, Python 3.12.3, pytest 9.2.0 (venv riêng — pytest hệ thống chưa cài sau khi VM thay mới). Seeds: Monte Carlo seed 7, n=200.000; gate fuzz seed 11, n=20.000. Shim duy nhất (trong bộ nhớ, không sửa file): `contracts.LLM_BUDGET_MS = contracts.LLM_FIRST_TOKEN_MS` trước khi import harness — xem B1.

## Phụ lục B — Nguồn

- **Mốc độc lập đã dùng:** DigyAI — AI Customer Service Agents (agent ~35% tác vụ nhiều bước; voice agent 26–38% trong điều kiện ồn/nhiều giọng, 2026); SQM Group — tỉ lệ bỏ cuộc chuẩn ~5%; ContactBabel UK 2024 — bỏ cuộc TB 8,4% (n=225).
- **Số vendor đã loại (xem §0):** Ada (~72% / ~52%), Intercom Fin (76%), Gartner (80% tới 2029), FPT AI Engage (intent 92%), Klarna (67%).
- **Đặc tả đã khóa:** `src/contracts.py` v1.0.0 trên main (MAX_CLARIFICATIONS=1, cửa sổ containment 72h, ngân sách 250+500+350=1100ms, SLO p95 1200ms, `TOOL_CALL_OFF_PATH_MS`=500ms).
- **Báo cáo nền:** qa-verifier 26/11/2026 (blocked — không có repo/commit hash trên VM của họ); CEO (bản sửa 1); báo cáo Hội đồng Chuyên gia #15.

## Tóm tắt gửi CEO (muse)

- Không có một con số % duy nhất: contained_final (72h) — chỉ số duy nhất được phép công bố — **chưa ước lượng được** vì không có dữ liệu liên hệ lại thật và không có commit baseline nào được cấp (QA blocked); khoảng lập kế hoạch cho contained_provisional là **26–50%**, tin cậy thấp.
- Đã chứng minh bằng code chạy: verifier chặn 6/6 ca đối nghịch, gate 0 vi phạm hard rule/MAX=1 trên 20.000 lượt fuzz, harness golden 12/12, Erlang-A đỉnh 60 cuộc/h với 5 nhân viên cho tỉ lệ bỏ **2–6%**; 6 module + 7 file test đạt **100 passed** với contracts v1.0.0 thật trên main.
- Ba blocker phải sửa trước vòng đo sau: harness **không import được** với contracts thật (`RETRIEVAL_LLM_BUDGET_MS`, sửa 1 dòng, chủ fullstack-ux); latency/WER chưa đo được vì **chưa nối vendor nào**; golden JSON **0/12 nhãn intent khớp** enum dialogue.
- Để thay khoảng bằng số đo: shadow 2 ngày (~600 cuộc) rồi canary 10% trong **13 ngày (n≈390, ±5 điểm phần trăm)** + 72h theo dõi liên hệ lại; đừng hứa 80% hay 52% — hai số đó là dự báo và số vendor, đã bị loại khỏi báo cáo này.
