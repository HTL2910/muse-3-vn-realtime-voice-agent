# Chạy test độc lập và lập ma trận bao phủ yêu cầu

_qa-verifier · Chuyên gia Kiểm chứng & Phản biện · lần nộp 1_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu test thử trước khi nói % đạt được. Thông tin nền: hệ thống phải nghe realtime tiếng Việt với vòng đáp p95 dưới 1.200ms, chỉ trả lời từ dữ liệu thật, biết dừng khi ngoài phạm vi/không chắc/nhạy cảm/khách yêu cầu gặp người, chuyển kèm HandoffPackage, và tạo callback khi hết nhân viên hoặc ngoài giờ; các khóa kỹ thuật gồm MAX_CLARIFICATIONS=1, containment final 72h, ngân sách độ trễ ASR 250ms + LLM first-token 500ms + TTS first-audio 350ms = 1100ms với 100ms jitter, tool-call trên 500ms không nằm trên đường first-audio, Erlang-A thay Erlang-C. Việc cần làm trên đúng commit baseline do systems-arch xác nhận: chạy toàn bộ test suite và test mục tiêu cho contracts/version/grep mirror; tool gateway với ca tool lạ bị rejected, thiếu tenant bị rejected, sai hậu tố SĐT không trả dữ liệu, cross-tenant bị từ chối; grounded answer với 4 golden case không bản ghi, mâu thuẫn, thiếu trường, sai số liệu/ngày/mã đơn; confidence gate ở ngưỡng 0.85/0.60 và tuân thủ MAX_CLARIFICATIONS=1; policy engine hard-rule thắng confidence cao; callback idempotency/dedup/SLA; metrics containment hai lớp và cost-per-contained tính trên final; dialogue sửa slot và quay lại chủ đề; handoff không bridge mù khi context push fail và hết agent thì tạo ticket; capacity planner biên c=1 và quá tải có wait hữu hạn; normalizer 3 miền/không dấu/mã đơn; resilience khi tổng độ trễ vượt SLO; E2E một cuộc gọi mô phỏng đầy đủ. Nếu thiếu test, chỉ bổ sung test đánh giá trong tests/evaluation/ và ghi rõ là test mới, không sửa code sản phẩm trong phần việc này. Kết quả cần nộp: docs/evaluation/02-qa-test-report.md, log lệnh chạy trong docs/evaluation/logs/, và tests/evaluation/test_*.py nếu có thêm test. Báo cáo phải có lệnh đã chạy, môi trường, số pass/fail, lỗi theo mức độ, ma trận bao phủ 5 yêu cầu cốt lõi và các quyết định đã khóa với trạng thái Pass/Fail/Not tested/Blocked kèm bằng chứng; % test pass hoặc % bao phủ yêu cầu không được trình bày như % go-live.

## Bài làm

# Báo cáo QA — Chuyên gia Kiểm chứng & Phản biện (qa-verifier)
**Dự án:** vn-realtime-voice-agent — AI trợ lý giọng nói realtime tiếng Việt
**Báo cáo cho:** CEO (muse) · Phòng: Hội đồng Nghiên cứu
**Ngày kiểm chứng:** 26/11/2026 · **Môi trường:** VM Linux qa-verifier, Python 3.12.3, git 2.43.0, pytest: *not installed / not found*
**Commit baseline:** ❌ **KHÔNG XÁC ĐỊNH ĐƯỢC — BLOCKED**

> **Kết luận điều hành (đọc trước): KHÔNG CÓ CƠ SỞ ĐỂ TUYÊN BỐ BẤT KỲ % ĐẠT / % GO-LIVE NÀO.**
> Phần việc tiền lệ của systems-arch (“Kiểm chứng repo và baseline kỹ thuật trước khi đánh giá %”) ghi rõ *KHÔNG hoàn thành: Máy ảo Muse chưa sẵn sàng sau 75 giây*. Trên VM của qa-verifier ngày 26/11/2026 cũng **không tồn tại** thư mục repo, không có `src/contracts.py`, không có commit hash nào để khóa baseline. Mọi số “100% đồng thuận / 38 fix PASS / 39 passed” trong tài liệu #15/#19 đều là **báo cáo của hội đồng, chưa có log pytest + manifest + commit hash trên `main` được công bố và qa-verifier không tái lập được**. Theo đúng góp ý của chủ doanh nghiệp — *phải test thử trước khi nói % đạt được* — báo cáo này ghi **Blocked / Not tested** ở mọi hạng mục cần chạy code, không ngoại suy, không đổi % pass test thành % go-live.

---

## 1. Bằng chứng môi trường & lệnh đã chạy (tái lập được)

Thực thi trực tiếp trên VM qa-verifier, 26/11/2026:

```bash
$ pwd; ls -la ~
/home/hatch
$ ls ~/workspace/vn-realtime-voice-agent
ls: cannot access '/home/hatch/workspace/vn-realtime-voice-agent': No such file or directory
$ find ~ -maxdepth 4 -name "contracts.py"
# (không có kết quả)
$ python3 --version   # Python 3.12.3
$ pytest --version    # /bin/bash: pytest: command not found
$ git --version       # git version 2.43.0
```

Danh sách file “trên nhánh main” trong phiếu giao việc (62 file: `src/contracts.py`, 20 module `src/**`, `tests/test_*.py` ×33, `data/**`, CI…) là **danh sách khai báo**, không phải listing qa-verifier quan sát được: không kèm commit hash, không kèm `evidence.json`/manifest SHA-256 có thể kiểm tra, và repo không có mặt trên VM này. Đây là cùng một khoảng trống mà Phụ lục A của #15 và bản sửa #19 đã tự thừa nhận: *“chưa từng có commit hash, manifest hay log pytest trên main được công bố”*, *“repo hiện chỉ tồn tại trên máy ảo riêng của người nộp [systems-arch]”*, *“chưa có lần chạy pytest nào trên main”*.

**Hệ quả bắt buộc:** Điều kiện tiên quyết trong phiếu giao việc — *“trên đúng commit baseline do systems-arch xác nhận”* — **chưa thỏa**. Chạy test trên một bản sao không rõ nguồn gốc, hoặc bịa log, sẽ vi phạm nguyên tắc fail-closed của chính hệ thống. qa-verifier dừng ở Blocked thay vì nộp số giả.

Log đầy đủ được nộp kèm tại `docs/evaluation/logs/qa-run-2026-11-26.log` (FILE block ở cuối).

## 2. Kết quả test — số pass/fail trung thực

| Hạng mục | Lệnh dự kiến | Pass | Fail | Trạng thái |
|---|---|---:|---:|---|
| Toàn bộ test suite | `python -m pytest -q` | — | — | **Blocked** — không có repo/pytest trên VM |
| Contracts / version / grep mirror | `pytest tests/test_systems_arch_m3.py tests/test_fix_missing_contracts.py -q` + grep khóa | — | — | **Blocked** (chỉ đối chiếu tĩnh được, §3) |
| Tool gateway (4 ca biên) | test mục tiêu §4.1 | — | — | **Blocked** — cần code chạy |
| Grounded answer (4 golden case) | §4.2 | — | — | **Blocked** |
| Confidence gate 0.85/0.60, MAX=1 | §4.3 | — | — | **Blocked** |
| Policy engine hard-rule > confidence | §4.4 | — | — | **Blocked** |
| Callback idempotency/dedup/SLA | §4.5 | — | — | **Blocked** |
| Metrics containment 2 lớp, cost/final | §4.6 | — | — | **Blocked** |
| Dialogue sửa slot / quay lại chủ đề | §4.7 | — | — | **Blocked** |
| Handoff no-blind-bridge / hết agent → ticket | §4.8 | — | — | **Blocked** |
| Capacity planner c=1 / quá tải wait hữu hạn, Erlang-A | §4.9 | — | — | **Blocked** |
| Normalizer 3 miền / không dấu / mã đơn | §4.10 | — | — | **Blocked** |
| Resilience vượt SLO p95 | §4.11 | — | — | **Blocked** |
| E2E 1 cuộc gọi mô phỏng đầy đủ | `pytest tests/test_e2e_call.py -q` | — | — | **Blocked** |
| **Test đánh giá MỚI bổ sung (phần việc này)** | `pytest tests/evaluation/ -q` | — | — | **Not tested trên baseline** — đã viết, sẵn sàng chạy ngay khi có commit; test tự `skip` có lý do rõ khi thiếu `src/` thay vì fail giả/pass giả (xem §6) |

**Không báo cáo % pass, % coverage, % go-live** — mẫu số không tồn tại. Bất kỳ % nào ở giai đoạn này đều là bịa.

## 3. Đối chiếu tĩnh trên tài liệu được cấp (không thay thế chạy test)

Chỉ dựa trên #14 (contracts m3), #15, #19 — ghi rõ đây là *đọc code trong tài liệu*, không phải chạy code:

| Quyết định đã khóa | Giá trị kỳ vọng | Bằng chứng tĩnh | Trạng thái tĩnh |
|---|---|---|---|
| CONTRACTS_VERSION | theo #19 là `1.0.0`; #14 ghi `"1.0.0-m3"` | #14: `CONTRACTS_VERSION = "1.0.0-m3"` | ⚠️ **Fail — lệch phiên bản**: bản m3 ≠ bản khóa 1.0.0. Cần diff khi merge, cấm đổi thầm (chính #14 cũng cảnh báo vậy). Sev-2. |
| MAX_CLARIFICATIONS | `=1` | #19 mô tả policy_engine “MAX=1”; #14 Decision.CLARIFY ghi “one re-ask, then handoff” — nhất quán về ngữ nghĩa | Pass (tĩnh) / runtime **Not tested** |
| Vòng đáp p95 | `< 1200 ms` | #14 design rules ghi p95 < 1.2s | Pass (tĩnh) / **Not tested** |
| Ngân sách độ trễ | ASR 250 + LLM first-token 500 + TTS first-audio 350 = 1100 ms, +100 ms jitter = 1200 ms; tool-call >500 ms **không** nằm trên đường first-audio | Không thấy các hằng số này trong trích đoạn #14 được cấp (bị cắt bớt) | **Not tested** — cần grep mirror trên file thật: `ASR.*250`, `500`, `350`, `1100`, `1200` trên `src/contracts.py` + `src/telephony/media_gateway.py` + `src/realtime/orchestrator.py` |
| Containment final | cửa sổ `72h` cố định | #19: metrics “containment 72h cố định; cost-per-contained trên FINAL” | Pass (tĩnh) / **Not tested** |
| Erlang | **Erlang-A** (có abandonment), cấm Erlang-C | #19: capacity_planner “(Erlang-A)” | Pass (tĩnh) / **Not tested** — cần grep: có `erlang_a`, không có đường tính chỉ dùng Erlang-C |
| Tenant | tenant_id từ phiên xác thực, **không bao giờ** từ lời khách/prompt | #14: ghi rõ nguyên tắc này; `TenantContext.tenant_id` từ trunk/session | Pass (tĩnh) / **Not tested** |
| Allowlist tool | đúng 5 tool: get_order_status, get_inventory, get_appointment, get_policy, create_callback_ticket; 4 đầu read-only | #14 `ToolName` + `ALLOWED_TOOLS` + `READ_ONLY_TOOLS` khớp 5/4 | Pass (tĩnh) |
| Evidence bắt buộc | mọi answer có (source_id, record_id, updated_at) | #14 `Evidence` dataclass + “answer without evidence is forbidden” | Pass (tĩnh) / **Not tested** |
| Idempotency | mọi write có idempotency_key | #14 design rules ghi rõ | Pass (tĩnh) / **Not tested** |
| Escalation/HandoffReason | #19 nhắc “EscalationReason 6 giá trị” cần xác nhận bằng mắt; #14 có `HandoffReason` **7 giá trị** (out_of_scope, low_confidence, sensitive, user_requested, repeated_failure, no_agent, system_error) | Tên enum và số lượng **không khớp** mô tả ở #19 | ⚠️ **Fail — cần hòa giải contracts**: hoặc đổi tên, hoặc thừa 1 giá trị. Sev-2, chặn merge cho tới khi CEO khóa lại một nguồn sự thật duy nhất. |

**Lỗi theo mức độ (tổng hợp §2–§3):**
- **Sev-1 (Blocker) ×1 — B-01:** Không có baseline commit / repo / log khả kiểm trên bất kỳ VM nào qa-verifier truy cập được; tiền lệ systems-arch cũng chưa hoàn thành. *Không thể nghiệm thu.*
- **Sev-2 (Major) ×2 — M-01:** Lệch `CONTRACTS_VERSION` 1.0.0-m3 vs 1.0.0. **M-02:** Lệch tên/số lượng enum lý do chuyển (HandoffReason 7 vs “EscalationReason 6”).
- **Sev-3 (Minor) ×1 — m-01:** pytest không được cài sẵn trên VM QA; cần `pyproject.toml`/requirements khóa phiên bản + CI là nguồn chạy chuẩn, không phụ thuộc VM cá nhân.
- **Chưa phân loại (cần chạy mới biết):** toàn bộ 13 nhóm hành vi §4 — giữ nguyên trạng thái Blocked, không suy đoán pass.

## 4. Đặc tả test mục tiêu phải chạy trên baseline (đã cụ thể hóa — test mới ở §6 hiện thực hóa)

**4.1 Tool gateway:** (a) tool lạ (`drop_table`, `get_order_status_v2`) → `rejected`, không gọi backend; (b) thiếu tenant_id / tenant rỗng → `rejected`; (c) sai hậu tố SĐT (ownership: mã đơn đúng nhưng suffix không khớp) → `not_found/rejected`, **data rỗng** — chống rò rỉ qua thông báo lỗi phân biệt được; (d) cross-tenant (phiên tenant A tra record tenant B) → từ chối, không trả evidence của B. Thêm: timeout tool 800–1500 ms → `timeout`, fail-closed.

**4.2 Grounded answer — 4 golden case bắt buộc fail-closed:** (1) *không có bản ghi* → không answer, HANDOFF/CALLBACK; (2) *bản ghi mâu thuẫn* (2 nguồn khác trạng thái/giá) → không chọn bừa, CLARIFY(≤1)/HANDOFF; (3) *thiếu trường bắt buộc* (thiếu updated_at/giá/ngày giao) → không answer thiếu evidence; (4) *sai số liệu/ngày/mã đơn* so với evidence → đáp án phải khớp từng ký tự evidence, sai 1 ký tự = fail test. Mọi answer hợp lệ: đủ 3 trường evidence.

**4.3 Confidence gate:** biên chính xác: `0.85` → ANSWER (khi policy cho phép); `0.849` → không answer thẳng; `0.60` → biên dưới của CLARIFY; `0.599` → HANDOFF; đếm clarification: lần 1 CLARIFY, lần 2 **buộc** HANDOFF bất kể confidence tăng (`MAX_CLARIFICATIONS=1`, race: 2 lượt clarify đồng thời không được vượt 1).

**4.4 Policy engine:** hard-rule (sensitive: khiếu nại gay gắt / bồi thường / pháp lý; user_requested) thắng confidence `0.99` → HANDOFF luôn; thứ tự cổng: policy **trước** gate (đã có `test_fix_gate_order_check.py` trong danh sách khai báo — phải chạy lại trên baseline).

**4.5 Callback:** cùng idempotency_key gửi 2 lần (kể cả song song — race condition) → đúng 1 ticket; dedup theo (tenant, call_id/phone, nhu cầu) trong cửa sổ; SLA: ticket có `scheduled_at`/hạn gọi lại, quá hạn → FAILED/DEAD_LETTER có log, không mất im lặng; ngoài giờ & hết agent đều tạo được ticket.

**4.6 Metrics:** containment **hai lớp** tách bạch: *provisional* (kết thúc cuộc gọi) vs *final* (sau 72h, trừ đi ca mở lại/chuyển muộn); `cost_per_contained = tổng chi phí / số contained FINAL` — test chích 1 ca reopen ở giờ 71 (vẫn final=contained nếu đóng lại trước 72h theo định nghĩa khóa — cần CEO xác nhận biên này trong code thật) và 1 ca reopen ở giờ 73 (không được hồi tố final đã chốt); cấm dùng provisional làm mẫu số chi phí.

**4.7 Dialogue:** sửa slot giữa chừng (đổi mã đơn / đổi ngày hẹn) → state cập nhật, bằng chứng cũ bị vô hiệu, tra lại tool; ngắt chủ đề rồi quay lại (barge-in + topic return) → khôi phục đúng slot/intent trước đó, không hỏi lại từ đầu.

**4.8 Handoff:** context push fail (API đích lỗi/timeout) → **không bridge mù**: giữ khách ở AI/queue + tạo ticket dự phòng, log `SYSTEM_ERROR`; hết agent → CALLBACK ticket kèm đúng HandoffPackage (tóm tắt, transcript, slots, evidence, skill/độ ưu tiên đúng bộ phận).

**4.9 Capacity planner:** biên `c=1` (1 agent: không chia 0, không âm, wait hữu hạn); quá tải (λ > c·μ) với Erlang-A → thời gian chờ dự báo **hữu hạn** nhờ abandonment (điểm phân biệt Erlang-A vs C — nếu ra ∞/NaN là Fail); patience=0 và patience→∞ là 2 biên phải có test.

**4.10 Normalizer tiếng Việt:** 3 miền Bắc/Trung/Nam (từ địa phương trong `data/vietnamese_homophones.json`), dạng không dấu → có dấu đúng intent, mã đơn đọc rời chữ/số, đồng âm — mỗi miền ≥1 ca vàng; không chuẩn hóa làm đổi mã đơn/số tiền.

**4.11 Resilience:** tổng độ trễ mô phỏng > SLO 1200 ms → kích hoạt DegradationMode (IVR_FALLBACK/QUEUED/VOICEMAIL theo #14), không phát đáp án trễ như bình thường; tool-call 900 ms chạy nền không chặn first-audio ≤ ngân sách.

**4.12 E2E:** 1 cuộc gọi mô phỏng đầy đủ trong `tests/test_e2e_call.py` + golden `data/golden/golden_calls.json`: chào → tra đơn có evidence → trả lời trong ngân sách → khách hỏi câu nhạy cảm → HANDOFF kèm package → (mô phỏng hết agent) → CALLBACK ticket idempotent. Thiếu bất kỳ mắt xích nào = Fail.

## 5. Ma trận bao phủ — 5 yêu cầu cốt lõi × quyết định đã khóa

| # | Yêu cầu cốt lõi | Quyết định khóa liên quan | Pass | Fail | Not tested | Blocked |
|---|---|---|---|---|---|---|
| 1 | Nghe realtime VN, p95 <1200 ms | 250+500+350=1100, +100 jitter; tool >500 ms off-path; Erlang-A cho staffing | — | — | — | ✅ (không có code chạy) |
| 2 | Tra dữ liệu thật, chỉ trả lời khi có dữ liệu | 5-tool allowlist; tenant từ phiên; evidence bắt buộc; 4 golden case | Tĩnh: allowlist/evidence Pass (§3) | — | Runtime | ✅ |
| 3 | Biết dừng đúng lúc | Gate 0.85/0.60; MAX_CLARIFICATIONS=1; hard-rule > confidence | Tĩnh: MAX=1 Pass | Lệch enum lý do (M-02) | Runtime | ✅ |
| 4 | Chuyển kèm ngữ cảnh | HandoffPackage đủ trường; no-blind-bridge; đúng skill/bộ phận | — | — | — | ✅ |
| 5 | Không ngõ cụt (callback) | Idempotency/dedup/SLA; containment final 72h; cost trên final | Tĩnh: 72h/final Pass | — | Runtime | ✅ |

## 6. Test mới bổ sung (chỉ trong `tests/evaluation/`, không sửa code sản phẩm)

Nộp kèm 3 file ở cuối báo cáo này — **đều là test mới của qa-verifier**:
- `tests/evaluation/test_eval_contracts_gateway.py` — contracts/version/grep-mirror (đọc file dạng text, không import ép), tool gateway 4 ca biên + timeout.
- `tests/evaluation/test_eval_gates_policy_callback_metrics.py` — gate biên 0.85/0.60 + MAX=1 + race clarify, policy thắng 0.99, callback idempotent song song/dedup/SLA, metrics 2 lớp + cost/final + biên reopen 71h/73h.
- `tests/evaluation/test_eval_dialogue_handoff_capacity_resilience_e2e.py` — sửa slot/quay lại chủ đề, handoff no-blind-bridge, capacity c=1/quá tải Erlang-A, normalizer 3 miền/không dấu/mã đơn, resilience vượt SLO, E2E 1 cuộc gọi.

Nguyên tắc viết: dùng import mềm — module/thuộc tính chưa có trên baseline thì `pytest.skip("Blocked: …")` kèm lý do, **không** fake-pass; hằng số khóa (0.85, 0.60, 1, 1100, 1200, 72) đặt ở đầu file để CEO đối chiếu 1 chỗ. Khi systems-arch công bố commit hash + repo, chỉ cần: `pip install -e . && python -m pytest tests/evaluation/ -q` là có ngay số pass/fail/skip thật cho §2.

## 7. Điều kiện gỡ Blocked (giao lại rõ ràng, không mơ hồ)

1. systems-arch (hoặc CEO) công bố: **URL repo + commit hash đủ 40 ký tự của baseline + `evidence.json`/manifest SHA-256 + log `pytest -q` thô** — đúng 3 bằng chứng #19 đã hứa.
2. Hòa giải M-01/M-02 trong contracts (một `CONTRACTS_VERSION`, một enum lý do chuyển) và ghi vào changelog.
3. qa-verifier chạy lại nguyên §4 + test mới §6 trên đúng hash đó, nộp bản cập nhật của báo cáo này với log trong `docs/evaluation/logs/` — **chỉ khi đó** mới được ghi số pass/fail và % pass test (vẫn tách riêng, không gọi là % go-live; go-live cần thêm shadow/canary trên tenant thật, ngoài phạm vi phần việc này).

---

## Tóm tắt gửi CEO (muse)
- **Blocked, không có % nào được phép công bố:** repo/baseline commit không tồn tại trên VM QA và phần việc tiền lệ của systems-arch cũng chưa hoàn thành — mọi số PASS trước đây là báo cáo chưa tái lập được.
- Đã đối chiếu tĩnh: phần lớn quyết định khóa khớp, nhưng có **2 lỗi Sev-2** — lệch `CONTRACTS_VERSION` (1.0.0-m3 vs 1.0.0) và lệch enum lý do chuyển (HandoffReason 7 giá trị vs “EscalationReason 6”).
- Đã bàn giao đặc tả test mục tiêu đầy đủ cho 13 nhóm + **3 file test đánh giá mới** trong `tests/evaluation/` (chỉ thêm test, không sửa code sản phẩm), sẵn sàng chạy ngay khi có hash.
- Cần CEO/systems-arch cung cấp URL repo + commit hash 40 ký tự + manifest + log pytest thô để gỡ Blocked và chạy nghiệm thu thật.

(đã nộp file `docs/evaluation/02-qa-test-report.md`)

(đã nộp file `docs/evaluation/logs/qa-run-2026-11-26.log`)

(đã nộp file `tests/evaluation/test_eval_contracts_gateway.py`)

(đã nộp file `tests/evaluation/test_eval_gates_policy_callback_metrics.py`)

(đã nộp file `tests/evaluation/test_eval_dialogue_handoff_capacity_resilience_e2e.py`)

## File đã nộp

- `docs/evaluation/02-qa-test-report.md`
- `docs/evaluation/logs/qa-run-2026-11-26.log`
- `tests/evaluation/test_eval_contracts_gateway.py`
- `tests/evaluation/test_eval_gates_policy_callback_metrics.py`
- `tests/evaluation/test_eval_dialogue_handoff_capacity_resilience_e2e.py`
