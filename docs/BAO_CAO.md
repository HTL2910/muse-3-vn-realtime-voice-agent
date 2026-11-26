# Báo Cáo Cuối Cùng Cập Nhật — vn-realtime-voice-agent

- **GitHub Repository:** https://github.com/HTL2910/muse-3-vn-realtime-voice-agent
- **Trưởng nhóm điều phối:** muse (CEO / Team Lead)
- **Dự án:** AI trợ lý giọng nói realtime tiếng Việt, chỉ trả lời từ dữ liệu thật, biết dừng và chuyển người kèm tóm tắt khi ngoài phạm vi/không chắc/nhạy cảm/khách yêu cầu gặp người.
- **Góp ý đã xử lý:** “team nghiên cứu đánh giá khả năng đạt bao nhiêu % đi ,test thử đã”.
- **Kết luận điều hành sau vòng đánh giá %:** **Chưa có cơ sở để tuyên bố một % go-live hoặc phê duyệt pilot với dữ liệu thật.** CEO kiểm tra trang GitHub công khai thấy repo tồn tại ở trạng thái Public, nhánh mặc định `main`, commit hiện tại `f8993a6ecbaf7ff53a244d62a640fff464d83ad6`, và thư mục gốc có `src`, `tests`, `docs`, `scripts`, `evidence.json`. Tuy nhiên, vòng đánh giá của các bộ phận chưa hoàn thành kiểm chứng baseline/test trên commit đó: systems-arch chưa hoàn thành, qa-verifier bị Blocked, backend-sec không nộp được bản đánh giá, fullstack-ux chưa hoàn thành; algo-ml chỉ cho số mô phỏng cục bộ. Vì vậy báo cáo này tách % theo từng chiều, không gộp thành một con số quảng cáo và không dùng số vendor 52/76/80 làm cam kết.

---

## 1. Tổng quan đề bài & nguyên tắc thiết kế

Doanh nghiệp bán hàng/dịch vụ có tổng đài chăm sóc khách hàng với lượng cuộc gọi tăng theo đơn hàng; giờ cao điểm có thể có hàng trăm cuộc cùng lúc. Phần lớn cuộc gọi là câu hỏi lặp lại: tra cứu đơn hàng, phí và thời gian giao, đổi trả/bảo hành, hướng dẫn sử dụng, đặt lịch, xác nhận thông tin. Đáp án đã có trong dữ liệu doanh nghiệp nhưng hiện vẫn cần nhân viên trả lời từng cuộc.

Điểm nghẽn chính: khách chờ lâu vào giờ cao điểm; ngoài giờ hành chính không có người trực; nhân viên mới trả lời thiếu nhất quán; nhân viên giỏi bị tốn thời gian vào câu dễ; khi chuyển máy khách thường phải kể lại từ đầu. Bài học thiết kế cốt lõi là AI không được trả lời cố khi thiếu bằng chứng: giá trị nằm ở cổng dừng fail-closed và chuyển người kèm gói ngữ cảnh chuẩn xác.

Năm yêu cầu kỹ thuật cốt lõi đã khóa:

1. **Nghe & phản hồi realtime:** vòng đáp p95 dưới 1.200ms, nhận diện tiếng Việt 3 miền, hỗ trợ ngắt lời.
2. **Tra cứu dữ liệu thật:** chỉ trả lời khi có bản ghi hợp lệ và bằng chứng nguồn; tool gateway là đường duy nhất từ AI tới dữ liệu nghiệp vụ.
3. **Biết dừng đúng lúc:** ngoài phạm vi, thiếu bằng chứng, độ tin cậy thấp, nhạy cảm hoặc khách yêu cầu gặp người thì chuyển người; hỏi lại tối đa 1 lần theo `MAX_CLARIFICATIONS = 1`.
4. **Chuyển kèm ngữ cảnh:** handoff kèm định danh đã xác minh, intent, slot, tóm tắt, transcript có timestamp, kết quả tool-call và lý do chuyển.
5. **Không ngõ cụt:** hết nhân viên hoặc ngoài giờ thì tạo callback ticket bền vững, có idempotency/dedup/SLA.

## 2. Kiến trúc hệ thống 4 plane

Hệ thống được thiết kế theo 4 plane:

- **Media Plane:** media gateway, realtime orchestrator, resilience controller.
- **Dialog & Policy Plane:** Vietnamese normalizer, dialogue manager, confidence gate, policy engine hard-rule.
- **Grounding & Data Plane:** tool gateway, grounded answer verifier, knowledge ingestion, model cascade/cache.
- **Handoff, Callback & Ops Plane:** handoff service, context package, callback ticket outbox, Erlang-A capacity planner, voice security/PII, metrics dashboard, simulation/canary harness.

Cấu trúc repo kỳ vọng gồm `src/contracts.py`, 20 module trong `src/**`, `scripts/collect_data.py`, `scripts/verify_main_manifest.py`, `data/golden/`, `tests/`, `docs/`, `docker/` và CI. Trang GitHub cho thấy các thư mục gốc chính đã hiện diện, nhưng vòng đánh giá lần này chưa có manifest/pytest/gate log do systems-arch và qa-verifier chạy trên commit baseline để xác nhận toàn bộ cấu trúc và chất lượng test.

## 3. Hợp đồng giao diện đã khóa

| Hạng mục | Quy định đã khóa |
|---|---|
| `CONTRACTS_VERSION` | `"1.0.0"`, Python 3.11+ standard library |
| `EscalationReason` | Chỉ dùng snake_case: `out_of_scope`, `low_confidence`, `sensitive`, `customer_request`, `repeated_clarification`, `repeated_failure`; `no_agent`/`system_error` chỉ log và ánh xạ sang callback |
| `MAX_CLARIFICATIONS` | 1 lần hỏi lại; tối đa 2 lượt elicitation cho một slot |
| Ngân sách độ trễ | ASR 250ms + LLM first-token 500ms + TTS first-audio 350ms = 1.100ms, cộng 100ms jitter trong SLO p95 < 1.200ms; tool-call trên 500ms không nằm trên đường first-audio |
| Containment | `contained_provisional` trong cuộc gọi; `contained_final` = provisional + không liên hệ lại cùng vấn đề trong 72h; KPI dùng final |
| Hàng đợi | Erlang-A có abandonment, không dùng Erlang-C |
| Tool gateway | 5 tool: `get_order_status`, `get_inventory`, `get_appointment`, `get_policy`, `create_callback_ticket`; tenant chỉ lấy từ phiên đã xác thực; kết quả thành công phải có evidence |

## 4. Hai mươi mốt hướng giải quyết

| # | File mục tiêu | Vai trò |
|---:|---|---|
| 01 | `src/telephony/media_gateway.py` | SIP/WebRTC streaming, VAD, barge-in |
| 02 | `src/realtime/orchestrator.py` | Máy trạng thái ASR-LLM-TTS streaming |
| 03 | `src/voice/vietnamese_normalizer.py` | Chuẩn hóa tiếng Việt 3 miền, mã đơn, đồng âm |
| 04 | `src/dialogue/dialogue_manager.py` | Intent, slot-filling, dialogue state |
| 05 | `src/grounding/tool_gateway.py` | Tool gateway chỉ-đọc, cô lập tenant |
| 06 | `src/grounding/grounded_answer.py` | Grounded answering và verifier chống bịa |
| 07 | `src/gating/confidence_gate.py` | Confidence gate theo ngưỡng hiệu chuẩn |
| 08 | `src/dialog/policy_engine.py` | Hard-rule cho nhạy cảm/pháp lý/bồi thường |
| 09 | `src/handoff/handoff_service.py` | Định tuyến theo kỹ năng và warm transfer |
| 10 | `src/handoff/context_package.py` | HandoffPackage và Agent Desktop UX |
| 11 | `src/callback/callback_ticket_service.py` | Outbox callback và ticket bền vững |
| 12 | `src/queueing/capacity_planner.py` | Erlang-A capacity planner |
| 13 | `src/knowledge/ingestion_pipeline.py` | Knowledge ingestion có version |
| 14 | `src/integrations/sme_onboarding_hub.py` | SME onboarding và connector health-check |
| 15 | `src/optimization/model_cascade.py` | Model cascade, session cache, TTS chunking |
| 16 | `src/realtime/resilience_controller.py` | Circuit breaker và fallback |
| 17 | `src/platform/scaling.py` | Stateless worker, autoscaling, load shedding |
| 18 | `src/security/voice_security_policy.py` | Chống injection qua voice, OTP, PII masking |
| 19 | `src/observability/metrics_dashboard.py` | Containment 2 lớp và metrics |
| 20 | `src/eval/simulation_harness.py` | Golden calls, shadow, canary, kill-switch |
| 21 | `scripts/collect_data.py` | Sinh dữ liệu mẫu và golden dataset |

Báo cáo hội đồng trước đó ghi nhận 21 hướng, 36 nhánh fix độc lập/38 lượt fix và 100% đồng thuận sau 3 vòng kiểm định. Trong vòng đánh giá % lần này, các tuyên bố đó **chưa được tái lập độc lập trên baseline commit** vì systems-arch và qa-verifier chưa chạy được kiểm chứng baseline/test như yêu cầu.

## 5. Xử lý góp ý

### 5.1. Bộ phận nào đã làm gì, kết quả ở đâu

| Bộ phận | Phần việc | Kết quả duyệt | Kết quả ở đâu | Điểm chưa xong |
|---|---|---|---|---|
| systems-arch | Kiểm chứng repo và baseline kỹ thuật trước khi đánh giá % | Không hoàn thành | Không có `docs/evaluation/01-repo-baseline.md` | Máy ảo Muse chưa sẵn sàng sau 75 giây; chưa có manifest, compile/test/gate log, kiểm tra contracts trên commit baseline do bộ phận này xác nhận |
| qa-verifier | Chạy test độc lập và lập ma trận bao phủ yêu cầu | Đạt như báo cáo Blocked | `docs/evaluation/02-qa-test-report.md`, `docs/evaluation/logs/qa-run-2026-11-26.log`, 3 file `tests/evaluation/test_eval_*.py` | Chưa chạy được test trên baseline vì không có repo/commit/contracts/pytest trên VM; mọi hạng mục cần chạy code đều Blocked/Not tested |
| algo-ml | Ước lượng % hiệu năng AI từ test và mô phỏng | Đạt như báo cáo mô phỏng cục bộ | `docs/evaluation/03-algo-ml-feasibility.md`, `scripts/evaluation/feasibility_run.py`, `scripts/evaluation/feasibility_run2.py` | Số liệu là mô phỏng cục bộ trên bản dựng lại từ file text, không phải đo trên baseline đã xác nhận; contained_final, latency thật, WER thật, tỉ lệ trả lời sai thật chưa ước lượng được |
| backend-sec | Đánh giá % sẵn sàng an toàn dữ liệu và vận hành backend | Làm lại ở lần duyệt cuối, ghi nhận chưa bàn giao | Không có `docs/evaluation/04-backend-security-readiness.md` | Cả 3 lần nộp chỉ là thông báo hết giới hạn sử dụng; chưa có % an toàn pilot, test âm tính, blocker hay điều kiện tối thiểu trước dữ liệu thật |
| fullstack-ux | Đánh giá % hành trình người dùng, handoff và E2E | Không hoàn thành | Không có `docs/evaluation/05-fullstack-e2e-ux-readiness.md` | Máy ảo Muse chưa sẵn sàng sau 75 giây; chưa đánh giá được journey, HandoffPackage, time-to-context, SME wizard; giới hạn đặt lịch qua gateway chỉ-đọc vẫn chưa có quyết định cuối |

### 5.2. Bằng chứng test thử đã có

QA-verifier đã kiểm tra môi trường và ghi rõ: không có thư mục repo trên VM kiểm chứng, không tìm thấy `src/contracts.py`, pytest chưa được cài, commit baseline không xác định được. Vì vậy QA không báo cáo % pass, % coverage hay % go-live. Đối chiếu tĩnh phát hiện một lỗi Sev-2: bản contracts m3 trong tài liệu được cấp ghi `CONTRACTS_VERSION = "1.0.0-m3"`, lệch với bản khóa `1.0.0`; cần diff khi merge và cấm đổi thầm. Một số quyết định khóa như MAX=1, p95 < 1.200ms, containment final 72h và Erlang-A nhất quán ở mức tĩnh nhưng runtime vẫn Not tested.

Algo-ml đã chạy mô phỏng cục bộ trên bản dựng lại từ 4 file text được cấp: `src/contracts.py`, `src/eval/simulation_harness.py`, `data/golden/golden_calls.json`, `tests/test_e2e_call.py`. Báo cáo này nhất quán với QA ở điểm gốc: không có baseline commit/hash/manifest/log CI được cấp. Các số mô phỏng cục bộ gồm contained_provisional 26–50% với tin cậy thấp; latency p95 mô phỏng 924–1.102ms với tin cậy thấp; verifier chặn 6/6 ca đối nghịch; gate không vi phạm hard-rule/MAX=1 trên 20.000 lượt fuzz; Erlang-A ở 60 cuộc/giờ với 5 nhân viên cho abandonment 2–6% với tin cậy trung bình. Tuyên bố 100 passed phải đọc kèm ghi chú B7: nguyên trạng 99/100 vì một test cũ hard-code 6 lý do so với enum thật 8 giá trị.

### 5.3. Bảng % theo từng chiều

| Chiều đánh giá | Kết quả hiện tại | Mức tin cậy | Cách hiểu đúng |
|---|---|---|---|
| Repo/baseline kỹ thuật | Repo công khai tồn tại trên GitHub, nhưng baseline verification chưa hoàn thành | Thấp | Chưa chấm % hoàn thiện baseline; cần manifest + commit + log CI/test/gate trên cùng commit |
| QA test pass/coverage | Blocked/Not tested | Không áp dụng | Không có % pass/coverage/go-live vì mẫu số test trên baseline chưa tồn tại |
| AI contained_provisional trong mô phỏng | 26–50% | Thấp | Chỉ là mô phỏng cục bộ cho cuộc lặp lại; không phải contained_final 72h và không phải cam kết vận hành |
| Latency | p95 mô phỏng 924–1.102ms | Thấp | Nằm trong ngân sách mô phỏng 1.100ms/SLO 1.200ms ở mức mô phỏng; latency thật chưa đo |
| Grounded verifier | Chặn 6/6 ca đối nghịch trong mô phỏng | Thấp | Mẫu nhỏ; cần golden/adversarial lớn hơn trên baseline và dữ liệu tenant thật |
| Confidence gate | 0 vi phạm hard-rule/MAX=1 trên 20.000 lượt fuzz | Thấp đến trung bình cho logic gate | Chưa chứng minh tỉ lệ trả lời sai thật hoặc chuyển người không cần thiết trên cuộc gọi thật |
| Capacity Erlang-A | Abandonment 2–6% ở 60 cuộc/giờ, 5 nhân viên | Trung bình cho mô hình | Cần hiệu chuẩn bằng lưu lượng, patience và staffing thật của tenant |
| Backend/security pilot readiness | Chưa xác định | Không có bằng chứng | Không đủ cơ sở phê duyệt pilot với dữ liệu thật |
| E2E/UX/handoff readiness | Chưa xác định | Không có bằng chứng | Chưa đánh giá được journey và HandoffPackage; đặt lịch thật qua gateway vẫn là điểm cần quyết định |
| Go-live tổng thể | Chưa ước lượng được | Không áp dụng | Không có một % go-live duy nhất ở giai đoạn này |

### 5.4. Điểm chưa xong và điều kiện nâng cấp bằng chứng

1. systems-arch phải hoàn thành baseline trên commit hiện tại hoặc commit được chốt lại: URL repo, default branch, full commit hash, `git ls-files` manifest đối chiếu file kỳ vọng, compileall, pytest log, gate log và kiểm tra contracts khóa.
2. qa-verifier phải chạy lại toàn bộ test suite và test mục tiêu trên đúng commit baseline; cập nhật pass/fail thật, lỗi theo mức độ và ma trận bao phủ 5 yêu cầu cốt lõi.
3. backend-sec phải nộp bản đánh giá an toàn đầy đủ: test âm tính cross-tenant/thiếu tenant/sai hậu tố SĐT/tool lạ/injection/policy hard-rule/PII redaction/callback dedup/hết agent tạo ticket, cùng blocker adapter thật, KMS/TLS/retention/audit log, rate limit và chạy tải.
4. fullstack-ux phải hoàn thành đánh giá E2E/handoff: các journey chính, HandoffPackage completeness, time-to-context, khách không phải kể lại, SME wizard và quyết định về đặt lịch thật khi gateway hiện chỉ có `get_appointment` chỉ-đọc.
5. algo-ml phải chạy lại ước lượng trên baseline đã xác nhận, sau đó mới thiết kế shadow/canary trên tenant thật để đo contained_final 72h, latency thật, WER thật, tỉ lệ trả lời sai và chuyển người không cần thiết.

## 6. Kết luận gửi chủ doanh nghiệp

Team đã làm đúng phần “test thử trước khi nói %” ở mức bằng chứng hiện có: QA chứng minh chưa thể chạy test độc lập trên baseline, algo-ml chỉ đưa khoảng mô phỏng cục bộ có ghi rõ giới hạn, và CEO không dùng số vendor để suy diễn. Kết quả dùng được hiện nay là: **AI có tín hiệu mô phỏng ban đầu cho contained_provisional 26–50% với tin cậy thấp, latency mô phỏng nằm quanh ngân sách, gate/verifier/Erlang-A có bằng chứng mô phỏng cục bộ; nhưng hệ thống chưa đủ bằng chứng để nói % go-live hoặc pilot dữ liệu thật.**

Khuyến nghị quyết định: chưa phê duyệt pilot với dữ liệu thật. Bước tiếp theo không phải tranh luận thêm về %; bước tiếp theo là khóa baseline bằng manifest + commit hash + log CI/test/gate, chạy lại QA/backend/fullstack/algo-ml trên cùng commit, rồi mới đo shadow/canary để có % vận hành thật.
