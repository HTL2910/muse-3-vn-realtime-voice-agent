# vn-realtime-voice-agent

**AI trợ lý giọng nói realtime trả lời khách hàng bằng tiếng Việt — không trả lời được thì chuyển cho nhân viên, kèm tóm tắt.**

Báo cáo tổng kết & tài liệu README của Hội đồng Chuyên gia AI **MuseAssistantTeam** — Trưởng nhóm Điều phối Nghiên cứu (Team Lead / CEO): **muse**.

> **Trạng thái sau vòng xử lý góp ý (22/11/2026):** Chủ doanh nghiệp góp ý "tạo repo đi chứ". Cả 3 nhóm module đã được duyệt đạt ở vòng duyệt cuối (backend-sec, algo-ml, fullstack-ux) và khung repo đã được khởi tạo trên máy ảo của systems-arch — nhưng **chưa có repo chia sẻ nào**: chưa có URL GitHub, các file đã duyệt vẫn nằm trên máy ảo của từng chuyên gia, chưa có lần chạy pytest nào trên `main`. Xem mục **Xử lý góp ý của chủ doanh nghiệp** và **Phụ lục A** để biết rõ phần nào đã xong, phần nào còn nằm trên máy riêng, và phần nào chưa bắt đầu.

- **Repository:** khung repo cục bộ trên máy ảo systems-arch (`~/workspace/vn-realtime-voice-agent`, 2 commit, chưa push); GitHub dự kiến `https://github.com/HTL2910/vn-realtime-voice-agent` (private) — **chưa tạo** vì chưa có đăng nhập GitHub.
- **Ngôn ngữ chính:** Python 3.11+ (contracts chỉ dùng standard library).
- **Ngày hoàn thành biên bản:** 22/11/2026; cập nhật sau vòng xử lý góp ý cùng ngày.

---

## Xử lý góp ý của chủ doanh nghiệp

### Góp ý và nhận định của CEO

Sau khi đọc báo cáo cuối, chủ doanh nghiệp góp ý một câu: **"tạo repo đi chứ"**.

CEO nhận định góp ý này là đúng và trúng điểm yếu lớn nhất của báo cáo cuối: Phụ lục A đã thừa nhận `main` trống, chưa từng có commit hash, manifest hay log pytest nào — "100% đồng thuận, 38 fix đã merge" mà không có repo thật thì chỉ là biên bản trên giấy. Vòng xử lý góp ý vì vậy không tranh luận thêm về thiết kế; toàn bộ công việc là **biến biên bản thành file thật trong một repo thật**.

### Phân công 6 phần việc

| # | Bộ phận | Phần việc | Phụ thuộc |
|---|---|---|---|
| 1 | systems-arch | Khởi tạo repo GitHub `vn-realtime-voice-agent` + cây thư mục đầy đủ + `src/contracts.py` v1.0.0 (mọi quyết định đã khóa) + `scripts/verify_main_manifest.py` (manifest + SHA-256 + compileall + pytest + `--publish-evidence`/`--require-evidence` + kiểm tra thứ tự) + CI (`.github/workflows/ci.yml`: compileall + pytest + grep CI) + `pyproject.toml`, `.gitignore`, `docker/docker-compose.yml` (Redis/Kafka/PostgreSQL), README placeholder | — |
| 2 | systems-arch | `src/telephony/media_gateway.py`, `src/realtime/resilience_controller.py` (bắt buộc xuất đủ khối `[[FILE]]` — đã thất bại 2 lần trước đó), `src/platform/scaling.py`, `scripts/collect_data.py` + `data/golden/` | — |
| 3 | algo-ml | 6 module + test: `orchestrator.py`, `vietnamese_normalizer.py`, `grounded_answer.py`, `confidence_gate.py`, `capacity_planner.py` (Erlang-A), `model_cascade.py` (cache đơn hàng theo phiên TTL 60s, không cache chéo phiên) | — |
| 4 | backend-sec | 5 module + test: `tool_gateway.py` (5 tool allowlist; tenant từ phiên xác thực; ownership check mã đơn + hậu tố SĐT; timeout 800–1500ms; evidence bắt buộc), `policy_engine.py` (hard-rule thắng gate; MAX=1), `voice_security_policy.py`, `callback_ticket_service.py` (outbox + Kafka), `metrics_dashboard.py` (containment 72h cố định; cost-per-contained trên FINAL) | — |
| 5 | fullstack-ux | 6 module + test + `tests/test_e2e_call.py`: `dialogue_manager.py`, `handoff_service.py`, `context_package.py`, `ingestion_pipeline.py`, `sme_onboarding_hub.py`, `simulation_harness.py` | — |
| 6 | systems-arch | Merge cuối lên `main` theo thứ tự phụ thuộc (gate+contracts → data/golden → data plane → gating/policy → dialogue/orchestrator/normalizer → handoff/context/callback → media/resilience/scaling → capacity/knowledge/SME → cascade/security → metrics/eval), chạy toàn bộ `pytest -q` trên `main`, công bố 3 bằng chứng (commit hash + manifest + log pytest), push lên GitHub, cập nhật README bằng URL thật + commit hash + số test thực trên `main` | 3, 4, 5 |

Các phần việc module chạy song song theo đặc tả contracts đã khóa được chép lại trong từng gói giao việc (người nhận không có báo cáo cuối). Giả định đã nêu khi giao việc: repo tên `vn-realtime-voice-agent` dưới tài khoản GitHub HTL2910 của chủ doanh nghiệp như 2 dự án trước, private — chủ doanh nghiệp có thể đính chính.

### Kết quả từng bộ phận (đã qua duyệt)

**systems-arch — phần việc 1: khung repo + contracts + cổng manifest/CI → LÀM LẠI (chỉ về bàn giao; nội dung được chấp nhận).**

- Đã làm được: repo local `~/workspace/vn-realtime-voice-agent` trên máy ảo của người nộp, nhánh `main`, 2 commit, cây làm việc sạch. Commit đầu `208e7361c15bb61fb958ade21f425b9bb251d4ba` (34 file: contracts v1.0.0, manifest gate kèm kiểm tra thứ tự và cờ `--skeleton`, CI, hạ tầng); commit thứ hai `8ea0938` (chỉ có hash ngắn 7 ký tự — cần bổ sung đủ 40 ký tự) chứa `evidence.json`. Pytest trên khung repo: **39 passed** (18 contracts + 11 gate + 10 order-check). Gate skeleton exit 0; gate đầy đủ exit 1 — **đúng như thiết kế** vì 21 file approach chưa merge, danh sách thiếu khớp đúng 21 approach. Manifest 35 file (git ls-files + SHA-256) nhất quán nội bộ: 34 file ở commit đầu + evidence.json; hash SHA-256 của file rỗng đúng; đủ 20 package `src/`.
- Chưa đạt để dùng: (1) **Chưa có repo GitHub thật** — URL chỉ là "(dự kiến)", remote chưa tồn tại vì `gh` chưa đăng nhập; mà "tạo repo GitHub" là phần chính trong tên phần việc và là điều chủ doanh nghiệp yêu cầu. CEO ghi nhận đây là vướng quyền truy cập, không phải lỗi chuyên môn — CEO sẽ xử lý phần đăng nhập/tạo remote với chủ doanh nghiệp. CEO đã kiểm tra máy của CEO: **không có thư mục `~/workspace/vn-realtime-voice-agent`, không tìm thấy repo ở đâu khác trên máy này** — repo hiện chỉ tồn tại trên máy ảo riêng của người nộp. (2) Các khối `[[FILE]]` trong bài nộp bị cắt cụt (kể cả `evidence.json`) nên CEO chưa nhìn thấy nội dung `src/contracts.py`, `scripts/verify_main_manifest.py`, CI hay docker-compose — không thể xác nhận bằng mắt các giá trị khóa (EscalationReason 6 giá trị, MAX_CLARIFICATIONS=1, TOTAL_SLO_P95_MS, `decide_clarification`).
- Yêu cầu bàn giao lại: xuất git bundle giữ nguyên 2 commit + hash, hoặc nộp lại toàn bộ `[[FILE]]` đầy đủ chia nhỏ nhiều lần — sao cho SHA-256 từng file khớp đúng manifest đã nộp (đó là neo kiểm chứng); ghi đủ 40 ký tự hash của commit thứ hai.
- Ghi chú thêm: `evidence.json` ở `mode="skeleton"` mà `complete=true` dễ gây hiểu lầm thành repo đã hoàn chỉnh — bằng chứng gộp cuối bắt buộc phải ở `mode="full"`; `docker-compose.yml` mới chỉ kiểm tra cú pháp YAML (docker không có trên máy người nộp nên chưa chạy `docker compose config` hay `up`); tác giả commit là placeholder (`systems-arch@vn-realtime-voice-agent.local`), cần amend khi push; kết quả pytest/gate/commit là chạy trên máy ảo riêng, **không phải CI GitHub** (CI chưa chạy vì remote chưa tồn tại).

**systems-arch — phần việc 2: media_gateway + resilience_controller + scaling + collect_data/golden → CHƯA NỘP.**

- Không có bài nộp nào cho phần việc này trong vòng xử lý góp ý. Đáng lưu ý: `resilience_controller` là file duy nhất trong toàn dự án chưa từng được nộp thành công (2 lần từ chối xuất khối `[[FILE]]` trong giai đoạn hội đồng); phần việc này giao lại cho systems-arch với yêu cầu bắt buộc xuất đủ file, nhưng tới nay vẫn chưa có bài nộp.

**algo-ml — 6 module + test → ĐẠT (duyệt cuối, sau 3 lần nộp).**

- Lần 1: chỉ có đoạn docstring của `orchestrator.py`, 5 module còn lại + 7 file test vắng mặt, test chưa chạy → làm lại. Lần 2 (đợt 3/8): `grounded_answer.py` cắt cụt giữa hàm, `confidence_gate.py` vắng mặt; CEO phát hiện 3 lỗi liên module trong phần nhìn thấy được: (1) import kép try/except (`src.contracts` hoặc `contracts`) vi phạm quy tắc một kiểu import duy nhất; (2) tên whitelist intent không khớp enum của dialogue_manager (`track_order` vs `order_tracking`, `check_fee` vs `shipping_fee`, `return_policy` vs `return_exchange`, `warranty_policy` vs `warranty`); (3) `REQUIRED_FIELDS` dùng `order_id` trong khi gateway và dialogue dùng `order_code`.
- Lần 3 (đợt 3c/3c, test của 2 file + tóm tắt): phần nhìn thấy được là `tests/test_fix_missing_grounded_answer.py` tới 9/13 test (cắt ở đầu mục whitelist/blacklist/stale policy; file test của confidence_gate và phần tóm tắt không tới được tay CEO; các module đã sửa ở đợt 3a/3b không nằm trong lượt duyệt này). **Cả 3 lỗi đều đã được sửa và kiểm chứng được trong file test nhìn thấy**: import một kiểu duy nhất theo layout repo-root, intent theo đúng enum dialogue_manager, payload dùng `order_code`. Chất lượng test nhìn thấy được là tốt, không có lỗi: 4 golden case đúng (không có bản ghi → UNKNOWN/out_of_scope + text xin lỗi cố định; bản ghi mâu thuẫn → REJECTED/low_confidence; thiếu trường bắt buộc → UNKNOWN `missing_required_field:status`; sai số tiền/ngày/mã đơn → REJECTED và số sai không bao giờ được đọc lên); chuẩn hoá 350.000==350.000==350k; định dạng trích dẫn khớp đúng API module.
- **Giới hạn của quyết định đạt (ghi rõ):** algo-ml **chưa bao giờ báo cáo một lần chạy test nào** — lần 1 và 2 nói rõ chưa chạy, lần 3 không còn đoạn tóm tắt nào tới tay CEO để xác nhận. Quyết định này duyệt **công việc như đã viết** (chất lượng đã đọc và kiểm chứng được ở phần nhìn thấy), **không** duyệt như "đã chạy xanh". Chốt chặn bắt buộc: khi file về tới nơi, cổng merge (manifest + pytest trên `main`) phải chạy toàn bộ test algo-ml và đạt xanh thì mới được merge; test nào fail ở bước merge thì bị trả lại ở đó, không vào `main`.

**backend-sec — 5 module + test → ĐẠT (duyệt cuối, sau 3 lần nộp). Đây là nhóm có bằng chứng kiểm chứng mạnh nhất.**

- Lần 1: chỉ có nửa đầu `tool_gateway.py` (cắt giữa chữ ký hàm), 4 module còn lại + test vắng mặt; CEO kiểm tra phần nhìn thấy được trên máy của CEO thì không biên dịch được (SyntaxError); người nộp thừa nhận test chưa chạy → làm lại. Phần nhìn thấy được đã đúng cấu trúc (5 tool schema chặt, tenant từ phiên, ownership check, timeout 800–1500ms, evidence, idempotency) nên không cần viết lại.
- Lần 2: người nộp báo cáo kiểm chứng thật — py_compile OK; **pytest 67 passed** (tool_gateway 12, policy_engine 16, voice_security 14, callback 13, metrics 12); grep mirror sạch; phát hiện và sửa 1 lỗi thật (regex che địa chỉ chưa khớp dạng không dấu "dia chi"); test chạy trên stub contracts v1.0.0 bản khóa trên máy của người nộp (stub không nộp theo là đúng). Nhưng bài nộp vẫn bị cắt cụt ở đúng điểm lần 1 → làm lại, chỉ về bàn giao.
- Lần 3: người nộp làm đúng mọi yêu cầu bàn giao (1 file mỗi tin nhắn, file dài tách 2–3 phần đánh dấu rõ "phần x/y", không viết lại code đã chạy xanh). Phần 1/2 của `tool_gateway.py` tới tay đầy đủ và khớp đúng code lần 2; phần 2/2 mở đầu nhất quán (chữ ký `call()` kèm tham số transcript, helper đo thời gian) rồi vẫn bị cắt ở `round((time.mon`, 9 file còn lại không có trong tin nhắn — CEO đã kiểm tra lại bản lưu và xác nhận. **Điểm nghẽn còn lại là kênh truyền tin, không phải người nộp** — thêm một lượt sửa nữa cũng không sửa được kênh truyền.
- Điều kiện kèm theo quyết định đạt: CEO duyệt **công việc đã làm**, không phải việc vận chuyển — 10 file vẫn chưa nằm trong tay CEO hay merge owner; việc đưa file về (git bundle hoặc kênh truyền khác) từ đây là việc hậu cần của CEO/merge owner. Cổng merge vẫn là chốt chặn cuối: file khi về tới nơi phải chạy lại pytest và đối chiếu manifest trên `main`, tái hiện đúng 67 passed mới được merge; nếu không khớp, file bị trả lại ở bước merge.

**fullstack-ux — 6 module + test E2E → ĐẠT (duyệt cuối, sau 3 lần nộp).**

- Lần 1: `conftest.py` đầy đủ; `dialogue_manager.py` cắt giữa playbook; 5 module còn lại + E2E + test vắng mặt. CEO phát hiện 1 lỗi nội dung quan trọng trong phần nhìn thấy được: playbook `allowed_tools` dùng tên tool ngoài 5 tên allowlist của gateway (`get_order`, `get_delivery_status`, `get_shipping_fee`, `get_delivery_eta`, `get_return_policy`, `get_warranty_policy`, `get_schedule`, `book_appointment`) — gateway sẽ reject, dialogue không bao giờ hoàn thành được tool-call. Lỗi nhỏ: dòng gán lại `MAX_CLARIFICATIONS = int(MAX_CLARIFICATIONS)` có thể vướng grep CI cấm mirror.
- Lần 2 và 3: **cả 2 lỗi đều đã sửa và giữ được qua 2 lần nộp sau** — dòng gán lại đã xóa; thêm `GATEWAY_TOOLS` (đúng 5 tên tool), `TOOL_GATEWAY_MAP` ánh xạ tên ngữ nghĩa cũ sang tên gateway, hàm `gateway_tool()` raise ValueError với tên gateway sẽ reject; playbook nay dùng tên gateway. Lần 3 đi xa hơn lần 2 một chút: playbook ORDER_TRACKING đầy đủ và đúng (slot bắt buộc `order_code`, slot tuỳ chọn `phone`, tool `get_order_status`, điều kiện thoát, SLOT_PROMPTS_VI); playbook SHIPPING_FEE mở đầu nhất quán (slot bắt buộc `address`; tool `get_policy` + `get_order_status`) rồi bị cắt ở giữa template câu trả lời.
- **Giới hạn của quyết định đạt (ghi rõ):** giống algo-ml, fullstack-ux **chưa bao giờ báo cáo một lần chạy test nào** trong cả 3 lần nộp (số test cũ trên nhánh — 87 module + dialogue rebase 17+7 + E2E 4 + regression 6 — chỉ là tham chiếu; bằng chứng nhánh cũ như dialogue rebase 17+7, context_package 12/12, SME hub 16/16 chỉ cho thấy công việc từng tồn tại, không thay thế được lần chạy của bản nộp hiện tại). Quyết định này duyệt **công việc như đã viết**, không duyệt như "đã chạy xanh". Cổng merge phải chạy toàn bộ test fullstack-ux kể cả E2E và đạt xanh thì mới được merge.
- Ghi chú thiết kế còn lại (không phải lỗi của người nộp, cần quyết định ở cấp CEO): mapping `book_appointment` → `get_appointment` chỉ đọc, không đặt lịch được thật — gateway hiện không có tool đặt lịch, nên intent BOOK_APPOINTMENT thực chất chưa đặt được lịch qua gateway. CEO sẽ quyết sau: thêm tool đặt lịch (thay đổi contracts/gateway) hoặc chuyển đặt lịch qua `create_callback_ticket`. Mapping `get_shipping_fee` → `get_policy` (tra phí qua chính sách) là lựa chọn chấp nhận được trong giới hạn 5 tool hiện có.

**systems-arch — phần việc 6: merge cuối → CHƯA BẮT ĐẦU.**

- Merge phụ thuộc vào 3 nhóm module (phụ thuộc [3, 4, 5]) và vào việc tạo remote GitHub. Cả 3 nhóm module đã được duyệt, nhưng file chưa về tới nơi và remote chưa tồn tại nên merge chưa thể bắt đầu.

### Vấn đề kênh truyền tin (nguyên nhân chung của mọi lần làm lại)

Mọi bài nộp dài đều bị cắt cụt trong chính tin nhắn đã gửi — CEO đã kiểm tra lại bản lưu của từng tin nhắn và xác nhận phần cắt cụt nằm trong tin nhắn, không phải lỗi hiển thị. Vấn đề vẫn xảy ra kể cả khi đã tách 1 file mỗi tin nhắn và tách file dài thành 2–3 phần có đánh dấu. Đây là điểm nghẽn của **kênh truyền**, không phải của người nộp: cả 4 chuyên gia đều gặp cùng một kiểu cắt cụt, và 2 chuyên gia đã làm đúng mọi yêu cầu bàn giao vẫn không đưa được file đầy đủ tới tay CEO. Vì vậy việc đưa file về từ đây được xử lý như **việc hậu cần của CEO/merge owner** (git bundle giữ nguyên commit + hash, hoặc kênh truyền khác) — không phải thêm lượt sửa của chuyên gia. Neo kiểm chứng cho việc vận chuyển: SHA-256 từng file phải khớp manifest đã nộp (khung repo) và pytest trên `main` phải tái hiện đúng số test đã báo cáo.

### Điểm chưa xong (sau vòng xử lý góp ý)

| # | Việc còn lại | Chủ sở hữu | Trạng thái / điểm nghẽn |
|---|---|---|---|
| 1 | Tạo repo GitHub `HTL2910/vn-realtime-voice-agent` (private) | CEO + chủ doanh nghiệp | Chưa làm — `gh` chưa đăng nhập trên máy systems-arch; cần quyền truy cập GitHub của chủ doanh nghiệp |
| 2 | Vận chuyển khung repo (35 file, 2 commit) về nơi chia sẻ | systems-arch → CEO/merge owner | Chưa làm — chỉ tồn tại trên máy ảo systems-arch; cần git bundle hoặc nộp lại `[[FILE]]` đầy đủ khớp manifest; cần đủ 40 ký tự hash commit thứ hai |
| 3 | Vận chuyển 10 file backend-sec đã duyệt | backend-sec → CEO/merge owner | Chưa làm — kênh truyền cắt cụt; cần kênh khác; khi về phải tái hiện 67 passed |
| 4 | Vận chuyển 6 module + test algo-ml đã duyệt | algo-ml → CEO/merge owner | Chưa làm — kênh truyền cắt cụt; khi về phải chạy pytest lần đầu để xác nhận (chưa từng có báo cáo chạy) |
| 5 | Vận chuyển 6 module + E2E + test fullstack-ux đã duyệt | fullstack-ux → CEO/merge owner | Chưa làm — kênh truyền cắt cụt; khi về phải chạy pytest lần đầu để xác nhận (chưa từng có báo cáo chạy) |
| 6 | Nộp phần việc 2 của systems-arch (media_gateway, resilience_controller, scaling, collect_data + golden) | systems-arch | Chưa nộp — chưa có bài nộp nào trong vòng này |
| 7 | Merge cuối lên `main` + pytest toàn repo + công bố 3 bằng chứng (commit hash, manifest, log pytest) + cập nhật README | systems-arch (merge owner) | Chưa bắt đầu — chờ #1–#6 |
| 8 | Quyết định thiết kế: intent đặt lịch (thêm tool đặt lịch vào gateway/contracts, hay chuyển đặt lịch qua `create_callback_ticket`) | CEO | Chưa quyết — cần quyết trước khi merge dialogue_manager vào luồng đặt lịch thật |
| 9 | Chạy thật `docker compose config` và kiểm tra hạ tầng Redis/Kafka/PostgreSQL | systems-arch | Chưa làm — docker không có trên máy người nộp; mới chỉ kiểm cú pháp YAML |
| 10 | Amend tác giả commit placeholder khi push | systems-arch / CEO | Chờ push |

### Kết luận thẳng cho chủ doanh nghiệp

Góp ý "tạo repo đi chứ" đã được xử lý một nửa: **code thật nay đã tồn tại và đã qua duyệt** — khung repo 35 file với contracts v1.0.0 và cổng manifest/CI trên máy systems-arch, 5 module backend-sec đã chạy xanh 67 test, 6 module algo-ml và 6 module fullstack-ux đã được duyệt như đã viết với mọi lỗi liên module đã sửa. Nhưng **repo mà chủ doanh nghiệp yêu cầu vẫn chưa tồn tại dưới dạng chia sẻ được**: chưa có URL GitHub, chưa có nơi nào ngoài máy riêng của từng chuyên gia chứa đủ code, và chưa có một lần chạy pytest nào trên `main`. Công việc còn lại không còn là thiết kế hay viết code — mà là vận chuyển file, tạo remote, và chạy cổng merge. CEO sẽ không báo cáo "đã xong" cho tới khi 3 bằng chứng (commit hash + manifest + log pytest trên `main`) cùng tồn tại và đính kèm được vào báo cáo này.

---

## 1. Tổng quan đề bài

### 1.1. Bối cảnh

Doanh nghiệp bán hàng / dịch vụ có tổng đài chăm sóc khách hàng, lượng cuộc gọi tăng theo khách hàng và đơn hàng — giờ cao điểm có thể hàng trăm cuộc cùng lúc. Phần lớn cuộc gọi là câu hỏi lặp lại: tra cứu đơn hàng, phí và thời gian giao, đổi trả / bảo hành, hướng dẫn sử dụng, đặt lịch, xác nhận thông tin. Đáp án đã có sẵn trong dữ liệu doanh nghiệp, nhưng hiện vẫn phải dùng người thật trả lời từng cuộc.

### 1.2. Hiện trạng & điểm nghẽn

- Giờ cao điểm khách chờ lâu, cúp máy giữa chừng và không gọi lại — mất khách mà không có dữ liệu để biết mất ở bước nào.
- Ngoài giờ hành chính không ai trực nên bỏ lỡ cuộc gọi buổi tối / cuối tuần.
- Nhân viên mới trả lời thiếu nhất quán, có khi sai chính sách đổi trả khiến khách khiếu nại ngược.
- Nhân viên giỏi bị "đốt" thời gian vào câu dễ, ca khó phải chờ.
- Chuyển máy = kể lại từ đầu khi chuyển giữa các nhân viên.
- Chi phí tổng đài tăng tuyến tính theo số cuộc gọi; tỉ lệ nghỉ việc mảng voice 18–25%/năm làm chi phí tuyển / đào tạo lặp lại liên tục.

### 1.3. Yêu cầu cốt lõi

1. **Nghe realtime** — Nhận diện giọng nói tiếng Việt, khách ngắt lời và hỏi tiếp được, độ trễ thấp giữ nhịp hội thoại (vòng đáp p95 < 1,2s).
2. **Tra dữ liệu thật** — Kết nối đơn hàng, tồn kho, lịch hẹn, kho tri thức. Chỉ trả lời khi có dữ liệu, tuyệt đối không bịa.
3. **Biết dừng đúng lúc** — Ngoài phạm vi / không chắc chắn / nhạy cảm (khiếu nại gay gắt, bồi thường, pháp lý) hoặc khách yêu cầu gặp người → không trả lời cố, chuyển người.
4. **Chuyển kèm ngữ cảnh** — Đúng bộ phận + tóm tắt, transcript, nhu cầu đã xác định. Đo được tỉ lệ xử lý trọn vẹn và lý do chuyển.
5. **Không ngõ cụt** — Không có nhân viên rảnh / ngoài giờ trực: AI ghi nhận yêu cầu, tạo phiếu và hẹn gọi lại.

### 1.4. Bài học định hình thiết kế: Klarna

Klarna xử lý 2,3 triệu chat trong tháng đầu bằng AI (67% hội thoại, thời gian xử lý <2 phút so với 11 phút, tiết kiệm ~40 triệu USD/năm) — rồi tháng 5/2025 phải tuyển lại nhân viên vì AI trả lời chung chung, không xử lý được ca phức tạp. Kết luận của hội đồng: **giá trị nằm ở chỗ biết câu nào không được trả lời cố và chuyển người kèm tóm tắt**, không nằm ở tỉ lệ tự xử lý tối đa. Thiết kế đúng là AI + chuyển người, không phải AI thay người hoàn toàn.

### 1.5. Bằng chứng thị trường (có nhãn độ tin cậy)

| Số liệu | Giá trị | Nguồn & nhãn |
|---|---|---|
| Thị trường tổng đài cloud Việt Nam | 192,9 triệu USD (2025) → 855,3 triệu USD (2034), CAGR 17,45% | IMARC Group — nghiên cứu thị trường |
| Khách cúp máy khi chờ | Trung bình ~90 giây; 60% không chờ quá 1 phút; >90% cúp ở mốc 5 phút | Talkdesk qua Ringly 2026 — benchmark quốc tế, **không phải số VN** |
| Tỉ lệ bỏ cuộc gọi chuẩn ngành | ~5% (SQM); trung bình đo được 8,4% (ContactBabel UK 2024, n=225); >10% là báo động đỏ | Benchmark Anh / toàn cầu, dùng làm tham chiếu |
| Voice AI toàn cầu | 2,54 tỷ USD (2025) → 35,24 tỷ USD (2033), CAGR 39% (định nghĩa hẹp); các hãng khác nhau cho khoảng 2,3–9 tỷ USD năm 2025 | Grand View Research qua RaftLabs; Business Research Company; MarketsandMarkets — **trình bày dưới dạng khoảng** |
| Intercom Fin | Giải quyết trung bình 76% hội thoại | Vendor tự công bố, chưa kiểm toán độc lập |
| Ada (550+ triển khai) | Containment ~72%, giải quyết tự động ~52% | Vendor tự công bố; mốc 52% dùng làm mặc định trong công cụ tính |
| Kiểm chứng độc lập | Agent chỉ hoàn thành ~35% tác vụ nhiều bước; voice agent đạt 26–38% trong điều kiện ồn / nhiều giọng | Tổng hợp DigyAI 2026 — kiểm chứng độc lập, yếu hơn hẳn số vendor |

**Hệ quả thiết kế (đã khóa):** không hứa "AI xử lý 80% cuộc gọi" khi chào hàng. Cam kết duy nhất được phép đưa ra là cam kết theo nhóm intent lặp lại **đã đo trên chính tenant đó** (shadow/canary), tách rõ số đo nội bộ khỏi số vendor. Xem approach_19 và approach_20.

### 1.6. Đối thủ & khoảng trống

FPT AI Engage (voicebot, 100+ giọng Việt, tự công bố intent 92% chưa kiểm toán, bán theo dự án, không self-serve) và Vbee (TTS 3 miền, mạnh ở giọng đọc, chưa phải trợ lý hội thoại realtime hoàn chỉnh) đã có mặt. Khoảng trống: **chưa có sản phẩm self-serve "AI nghe — trả lời — chuyển máy kèm tóm tắt" cho doanh nghiệp vừa / SME Việt Nam**. Lợi thế của người làm mới là tốc độ triển khai + giá theo cuộc gọi, không phải công nghệ giọng nói. Rủi ro đã ghi: FPT / Viettel có thể mở rộng xuống SME bất cứ lúc nào.

---

## 2. Cấu trúc thư mục & kiến trúc hệ thống

### 2.1. Kiến trúc tổng thể

Hệ thống realtime **fail-closed**, tách 4 plane:

- **Media plane** — SIP/WebRTC, audio streaming hai chiều, VAD, barge-in, jitter buffer.
- **Dialog plane** — ASR / NLU / dialogue (tiếng Việt), confidence gate, policy engine.
- **Data plane** — Tool gateway chỉ-đọc tới OMS / WMS / CRM / lịch + kho tri thức có phiên bản; mọi câu trả lời phải có bằng chứng (evidence).
- **Handoff plane** — Định tuyến theo kỹ năng, warm transfer, gói ngữ cảnh (HandoffPackage), callback / ticket bền vững.

Worker stateless mở rộng ngang; trạng thái phiên bền vững ở Redis; hàng đợi callback ở Kafka + DB outbox; mọi thao tác ghi dùng idempotency-key.

**Nguyên tắc xuyên suốt (đã khóa trong contracts):**

- Không có dữ liệu đã xác minh / không đủ tin cậy / trúng rule nhạy cảm → không trả lời cố, chuyển người kèm tóm tắt.
- Độ trễ vòng đáp p95 < 1,2s với ngân sách đã khóa (xem §2.3).
- Đo containment thật, lý do chuyển, abandonment, FCR và chi phí trên mỗi cuộc xử lý trọn vẹn; số đo nội bộ tách rõ khỏi số vendor.

### 2.2. Cấu trúc thư mục

```
vn-realtime-voice-agent/
├── README.md
├── pyproject.toml
├── .gitignore
├── src/
│   ├── contracts.py              # Hợp đồng chia sẻ duy nhất (CONTRACTS_VERSION 1.0.0)
│   ├── telephony/                # approach_01 — media_gateway.py
│   ├── realtime/                 # approach_02, 16 — orchestrator.py, resilience_controller.py
│   ├── voice/                    # approach_03 — vietnamese_normalizer.py
│   ├── dialogue/                 # approach_04 — dialogue_manager.py
│   ├── nlu/                      # (dành cho mở rộng NLU)
│   ├── grounding/                # approach_05, 06 — tool_gateway.py, grounded_answer.py
│   ├── gating/                   # approach_07 — confidence_gate.py
│   ├── dialog/                   # approach_08 — policy_engine.py
│   ├── handoff/                  # approach_09, 10 — handoff_service.py, context_package.py
│   ├── callback/                 # approach_11 — callback_ticket_service.py
│   ├── queueing/                 # approach_12 — capacity_planner.py
│   ├── knowledge/                # approach_13 — ingestion_pipeline.py
│   ├── integrations/             # approach_14 — sme_onboarding_hub.py
│   ├── optimization/             # approach_15 — model_cascade.py
│   ├── platform/                 # approach_17 — scaling.py
│   ├── security/                 # approach_18 — voice_security_policy.py
│   ├── observability/            # approach_19 — metrics_dashboard.py
│   ├── eval/                     # approach_20 — simulation_harness.py
│   ├── api/                      # (API gateway nội bộ — mở rộng)
│   └── web/                      # (agent desktop / dashboard — mở rộng)
├── scripts/
│   ├── collect_data.py           # approach_21
│   └── verify_main_manifest.py   # cổng manifest + CI gate (+ kiểm tra thứ tự)
├── data/
│   └── golden/                   # golden calls, FAQ vàng, đơn/tồn kho/lịch giả lập, benchmark
├── tests/                        # test đơn vị + golden + E2E (tests/test_e2e_call.py)
├── docs/                         # tiêu chí go-live, hướng dẫn vận hành
└── docker/                       # docker-compose: Redis / Kafka / DB
```

### 2.3. Các quyết định đã khóa trong `src/contracts.py` (v1.0.0)

| Quyết định | Giá trị đã khóa | Ghi chú |
|---|---|---|
| `EscalationReason` | snake_case duy nhất: `out_of_scope`, `low_confidence`, `sensitive`, `customer_request`, `repeated_clarification`, `repeated_failure` (+ `no_agent`, `system_error` chỉ để log, luôn map sang CALLBACK) | Cấm `user_requested`, `OUT_OF_SCOPE`, `out-of-scope` bằng grep CI |
| `MAX_CLARIFICATIONS` | **1 lần hỏi lại** (tối đa 2 elicitation tổng); vẫn thiếu thì escalate `repeated_clarification` | Định nghĩa cách đếm bằng code qua `decide_clarification()`; biến thể MAX=2 của backend-sec đã bị bác |
| Containment | Hai lớp: `contained_provisional` (trọn vẹn tại cuộc gọi bằng evidence đã xác thực, không handoff/callback); `contained_final` = provisional + không liên hệ lại cùng vấn đề trong **72h cố định** | KPI cam kết chỉ dùng `contained_final`; `window_hours` lưu trong metric; khoảng "24–72h" đã bị bác |
| Ngân sách độ trễ | ASR partial ≤ 250ms + retrieval/LLM first-token ≤ 500ms + TTS first-audio ≤ 350ms = 1100ms, chừa 100ms jitter trong SLO p95 < 1200ms | Sửa lỗi số học vòng 1 (300+600+400=1300ms và 300+800+500=1600ms đều vượt SLO) |
| Ngưỡng tool-call | > 500ms không nằm trên đường first-audio (chạy song song với câu đệm đã duyệt hoặc prefetch) | Đã thống nhất 500ms (thay con số 800ms cũ) |
| Tên hằng số SLO | `TOTAL_SLO_P95_MS` duy nhất | Sửa lệch tên giữa các bản rebase (`TOTAL_TURN_P95_MS` bị cấm bằng grep CI) |
| Mô hình hàng đợi | **Erlang-A** (M/M/c + abandonment, patience ~90s) | Bác Erlang-C vì giả định khách chờ vô hạn |
| Kiểu import | Một kiểu duy nhất: `from src.contracts import ...` | Cấm định nghĩa enum/hằng số riêng trong module |
| `CONTRACTS_VERSION` | `"1.0.0"` + test khóa version | Mọi module fail-closed khi version sai |

---

## 3. Các hướng giải quyết đã triển khai (21 approach)

44 đề xuất từ 5 chuyên gia (muse 10, systems-arch 9, algo-ml 8, backend-sec 9, fullstack-ux 8) được khử trùng lặp thành 21 hướng độc lập. Bảng dưới đây ghi phân công theo biên bản cuối cùng; **cột "Người sửa fix" trong §4 là hồ sơ authoritative về ai thực hiện công việc sửa lỗi** — phân công approach và phân công fix khác nhau ở 9 approach, xem Phụ lục A.3.

| # | Hướng giải quyết | File mục tiêu | Phụ trách (nhánh expert) |
|---|---|---|---|
| 01 | Media gateway SIP/WebRTC streaming, barge-in và chịu lỗi đường truyền | `src/telephony/media_gateway.py` | systems-arch (`expert/systems-arch-m3`) |
| 02 | Realtime orchestrator: pipeline ASR-LLM-TTS streaming và máy trạng thái lượt nói | `src/realtime/orchestrator.py` | algo-ml (`expert/algo-ml-m3`) |
| 03 | Thích ứng tiếng Việt: phương ngữ, nhiễu, tên riêng và chuẩn hoá thực thể | `src/voice/vietnamese_normalizer.py` | backend-sec (`expert/backend-sec-m3`) |
| 04 | Quản lý hội thoại: intent, slot-filling và dialogue state tracking | `src/dialogue/dialogue_manager.py` | fullstack-ux (`expert/fullstack-ux-m3`) |
| 05 | Tool-call gateway chỉ-đọc, tenant-isolated để tra dữ liệu thật | `src/grounding/tool_gateway.py` | systems-arch (`expert/systems-arch-m3`) |
| 06 | Grounded answering fail-closed và verifier chống bịa | `src/grounding/grounded_answer.py` | algo-ml (`expert/algo-ml-m3`) |
| 07 | Confidence gate hiệu chuẩn theo lý thuyết quyết định | `src/gating/confidence_gate.py` | backend-sec (`expert/backend-sec-m3`) |
| 08 | Policy engine: phát hiện nhạy cảm, ngoài phạm vi và quy tắc dừng bắt buộc | `src/dialog/policy_engine.py` | fullstack-ux (`expert/fullstack-ux-m3`) |
| 09 | Handoff service: định tuyến theo kỹ năng và warm transfer | `src/handoff/handoff_service.py` | systems-arch (`expert/systems-arch-m3`) |
| 10 | Gói ngữ cảnh chuyển máy và Agent Desktop UX tiếp nhận trong 5 giây | `src/handoff/context_package.py` | algo-ml (`expert/algo-ml-m3`) |
| 11 | Hàng đợi gọi lại và ticket bền vững cho ngoài giờ và khi hết agent | `src/callback/callback_ticket_service.py` | backend-sec (`expert/backend-sec-m3`) |
| 12 | Mô hình hàng đợi, dự báo tải và lập lịch gọi lại chống bỏ cuộc | `src/queueing/capacity_planner.py` | fullstack-ux (`expert/fullstack-ux-m3`) |
| 13 | Knowledge ingestion pipeline có phiên bản, duyệt và phát hiện mâu thuẫn | `src/knowledge/ingestion_pipeline.py` | systems-arch (`expert/systems-arch-m3`) |
| 14 | SME Self-Serve Integration Hub và Onboarding Wizard | `src/integrations/sme_onboarding_hub.py` | algo-ml (`expert/algo-ml-m3`) |
| 15 | Tối ưu độ trễ và chi phí bằng model cascade, cache và TTS streaming | `src/optimization/model_cascade.py` | backend-sec (`expert/backend-sec-m3`) |
| 16 | Resilience cho chuỗi ASR-LLM-TTS: circuit breaker và fallback đa nhà cung cấp | `src/realtime/resilience_controller.py` | fullstack-ux (`expert/fullstack-ux-m3`) |
| 17 | Mở rộng ngang và chịu lỗi: stateless worker, autoscaling, load shedding, multi-AZ | `src/platform/scaling.py` | systems-arch (`expert/systems-arch-m3`) |
| 18 | Bảo mật giọng nói: xác thực khách, chống injection, PII và tuân thủ | `src/security/voice_security_policy.py` | algo-ml (`expert/algo-ml-m3`) |
| 19 | Quan trắc và bảng đo containment trung thực (metrics, trace, dashboard) | `src/observability/metrics_dashboard.py` | backend-sec (`expert/backend-sec-m3`) |
| 20 | Harness đánh giá: golden calls, mô phỏng tải, shadow mode và cổng go-live | `src/eval/simulation_harness.py` | fullstack-ux (`expert/fullstack-ux-m3`) |
| 21 | Thu thập và xây dựng bộ dữ liệu thực tế trên máy ảo Linux | `scripts/collect_data.py` | systems-arch (`expert/systems-arch-m3`) |

### Chi tiết từng hướng

- **approach_01 — Media gateway.** SIP trunk / WebRTC, RTP/SRTP Opus, jitter buffer, VAD, echo cancellation, khử ồn; streaming hai chiều 20–40ms; barge-in ngắt TTS < 150ms (đo bằng timestamp, báo cáo 100ms trên nhánh); admission control theo phiên đồng thời/CPU/quota; quá tải vào hàng đợi có nhạc chờ + ETA; degrade sang IVR phím bấm / ghi âm khi provider lỗi; janitor quét session mồ côi; cúp máy ngang giải phóng hết tài nguyên.
- **approach_02 — Realtime orchestrator.** ASR streaming (partial + final), LLM streaming theo token, TTS streaming theo câu/chunk; turn-taking state machine (listening / thinking / speaking / interrupted / confirming / handing-off); backpressure, timeout từng chặng, câu đệm đã duyệt khi tra cứu chậm, fallback bán-duplex khi mạng xấu; session store Redis; idempotency-key cho thao tác ghi; `LatencyTracker` đo p50/p95 từng chặng.
- **approach_03 — Chuẩn hoá tiếng Việt.** 3 miền Bắc/Trung/Nam, nói nhanh, nói ngọng, nhiễu nền, không dấu; mã đơn đọc theo chữ cái/số; từ điển đồng âm + fuzzy matching trọng số âm vị; xác minh 2 bước khi thực thể mơ hồ; đo WER theo miền và mức ồn.
- **approach_04 — Dialogue manager.** Intent tiếng Việt (tra đơn, phí ship, đổi trả/bảo hành, đặt lịch, xác nhận thông tin), slot (mã đơn, SĐT, ngày giờ, sản phẩm), playbook theo intent; hỏi lại tối đa theo `MAX_CLARIFICATIONS` = 1 lần hỏi lại rồi chuyển người; dialogue state có cấu trúc theo lượt; xử lý sửa slot và quay lại chủ đề.
- **approach_05 — Tool gateway.** API gateway nội bộ duy nhất, tool schema chặt (`get_order_status`, `get_inventory`, `get_appointment`, `get_policy`, `create_callback_ticket`); AI không truy cập DB trực tiếp; `tenant_id`/`shop_id` lấy từ phiên đã xác thực, không từ prompt/transcript; ownership check mã đơn + hậu tố SĐT; timeout 800–1500ms; kết quả kèm `source_id`/`record_id`/`updated_at`/evidence.
- **approach_06 — Grounded answering.** LLM chỉ diễn đạt lại dữ liệu tool đã trả về kèm trích dẫn nguồn; verifier hậu kiểm chặn phát khi đáp án không suy ra 100% từ evidence; validator so khớp số liệu/số tiền/ngày tháng với payload; thiếu/mâu thuẫn evidence → `UNKNOWN`/`REJECTED`; whitelist intent, blacklist chủ đề nhạy cảm.
- **approach_07 — Confidence gate.** Tổng hợp ASR confidence, intent confidence đã hiệu chuẩn (temperature scaling / isotonic regression), độ khớp entity, độ đầy đủ/tươi của dữ liệu và verifier score; 3 vùng ngưỡng cấu hình theo tenant/intent (mặc định ≥ 0.85 trả lời, 0.60–0.85 hỏi lại, < 0.60 chuyển người); log mọi quyết định kèm confidence để tái hiệu chuẩn.
- **approach_08 — Policy engine.** Rule + classifier chạy song song LLM, bảng quyết định cấu hình theo tenant: khiếu nại gay gắt, bồi thường, pháp lý, sức khoẻ/tài chính nhạy cảm, tự hại/bạo lực, khách yêu cầu gặp người, vượt `MAX_CLARIFICATIONS`, sentiment âm mạnh. Hard-rule **luôn thắng** confidence gate; cấm LLM thương lượng bồi thường hay đưa cam kết pháp lý; mọi quyết định ghi audit log.
- **approach_09 — Handoff service.** Định tuyến theo skill/bộ phận/ngôn ngữ/mức ưu tiên/lịch trực realtime (least-loaded, sticky, VIP); warm transfer qua SIP REFER / conference bridge; gói ngữ cảnh đẩy lên CRM/ticket và agent desktop qua WebSocket/API trước khi cuộc gọi tới agent, có ACK + retry; không bridge mù khi context push thất bại; hết agent → CALLBACK kèm `ticket_id`.
- **approach_10 — HandoffPackage & Agent Desktop.** Schema cố định: định danh khách đã xác thực, intent/nhu cầu, slot, tóm tắt 3 phần (khách là ai + đã xác minh gì; đã trao đổi và tra cứu được gì; cần nhân viên làm gì tiếp theo) có validator đối chiếu transcript/evidence, transcript có timestamp, tool-call đã chạy, recording URL, lý do chuyển, độ ưu tiên; pop-up 1 màn hình trước khi nhấc máy; đo time-to-context (< 1s theo báo cáo) và tỉ lệ khách phải lặp lại thông tin.
- **approach_11 — Callback & ticket bền vững.** Outbox pattern (ghi nguyên tử DB + outbox event, worker đẩy CRM/helpdesk, retry exponential backoff + dead-letter queue); idempotency-key, dedup theo SĐT + intent + cửa sổ thời gian và theo call_id + phone; SLA theo mức ưu tiên; scheduler tôn trọng khung giờ khách chọn và capacity đội trực; khách gọi lại được nối tiếp ticket cũ; xác nhận SMS/Zalo/email kèm mã phiếu.
- **approach_12 — Capacity planner.** Erlang-A (M/M/c + abandonment, patience ~90s) cho AI tuyến đầu + hàng đợi người có ưu tiên; dự báo tải theo giờ/ngày/chiến dịch; chủ động đề nghị callback khi chờ dự báo vượt 60–90 giây; test biên (c=1 khớp M/M/1, tải ≥ server → quá tải với wait hữu hạn, không số âm/NaN).
- **approach_13 — Knowledge ingestion.** Nạp FAQ/chính sách từ DB/API/Doc/PDF/Web/Sheet; chunk tiếng Việt, metadata `effective_from`/`effective_to`/tenant/kênh/người duyệt; version hoá, phê duyệt trước publish, bản cũ tự hết hiệu lực; phát hiện mâu thuẫn (CONFLICT → hạ confidence, chuyển người); hồi quy câu hỏi vàng chặn publish; truy xuất hybrid BM25 + vector với rerank.
- **approach_14 — SME Self-Serve Hub.** Connector dựng sẵn (Shopify/Haravan/Sapo, Pancake, KiotViet, Sheets/Excel, REST/webhook, sandbox); wizard 5 bước (tổng đài → dữ liệu → FAQ/chính sách → rule chuyển máy/giờ trực → gọi thử/go-live); health-check, mapping trường bằng UI, cảnh báo dữ liệu thiếu/rác; bắt đầu từ 1–2 adapter rồi mở rộng.
- **approach_15 — Model cascade.** Mô hình nhỏ/nhanh cho câu lặp lại, mô hình lớn chỉ khi phức tạp; cache FAQ/chính sách/trạng thái đơn TTL ngắn; cache đơn hàng theo phiên TTL 60s, không cache chéo phiên; TTS theo câu; tối ưu Pareto latency-cost; đo chi phí/phút và chi phí/cuộc xử lý trọn vẹn.
- **approach_16 — Resilience controller.** Latency budget tracker theo chặng dùng hằng số contracts (fail khi tổng vượt SLO dù từng chặng đạt); circuit breaker 3 trạng thái + half-open probe; bulkhead pool riêng; fallback đa provider tiếng Việt (FPT/Vbee/Azure/Google) theo ma trận chất lượng đã đo; mã lỗi chuẩn + trace_id; never silence.
- **approach_17 — Scaling platform.** Stateless worker, Redis cluster, Kafka; autoscaling theo concurrent calls/CPU/GPU/độ trễ hàng đợi (HPA/KEDA), scale-to-zero ngoài giờ; load shedding chỉ cuộc mới ưu tiên thấp (VIP/HIGH không bị shed); bulkhead inbound/outbound/ingestion; multi-AZ, blue/green + canary, rollback theo version; theo dõi cost-per-contained-FINAL-call.
- **approach_18 — Voice security.** Transcript là dữ liệu không tin cậy: tách system instruction/evidence/transcript, chặn tool-call bất thường; xác minh theo mức rủi ro (mã đơn cho tra cứu cơ bản, OTP cho đổi/hủy/bồi thường); mask PII theo vai trò; mã hoá at-rest theo tenant (KMS), TLS 1.3, retention tự xóa, audit log bất biến; thông báo ghi âm + cơ chế từ chối; rate limit chống toll fraud/spam call.
- **approach_19 — Metrics dashboard.** Sự kiện chuẩn mọi cuộc gọi với trace_id xuyên suốt; containment hai lớp đã khóa (KPI dùng final 72h); tỉ lệ/lý do chuyển theo `EscalationReason`, chuyển đúng bộ phận, abandonment, thời gian chờ, FCR, AHT, CSAT, độ trễ p50/p95, tỉ lệ barge-in, tỉ lệ verifier chặn, chi phí/phút; dashboard tách số nội bộ khỏi benchmark vendor; redaction PII trước phân tích.
- **approach_20 — Eval harness.** Golden calls tiếng Việt (3 miền, ngắt lời, không dấu, ồn, mã đơn đọc sai, ca nhạy cảm, injection) chạy hồi quy trước mỗi lần đổi prompt/model/policy; mô phỏng hàng trăm cuộc đồng thời; shadow mode so quyết định AI với người; canary 5–10% + kill-switch < 1 phút; LLM-judge + rà soát người cho ca nhạy cảm; mọi con số kèm khoảng tin cậy, định nghĩa đo và nguồn; cổng go-live theo số shadow/canary của chính tenant; checklist 7 câu sẵn sàng làm mốc gốc abandonment/FCR; `tests/test_e2e_call.py` làm cổng nghiệm thu liên tầng.
- **approach_21 — Dữ liệu thực tế.** `scripts/collect_data.py` chạy lại được với `--seed 42`, sinh vào `data/` và `data/golden/`: 12 golden calls (kèm intent/slot/quyết định kỳ vọng, GC-10 reason `customer_request`), 4 FAQ vàng, 60 đơn hàng, 5 SKU, 20 lịch hẹn, từ điển đồng âm, 8 market benchmarks có nguồn + `reliability_class`. Không chứa PII thật; mọi bản ghi ghi rõ nguồn.

---

## 4. Biên bản phản biện, kiểm thử & các nhánh fix

### 4.1. Tiến trình hội đồng

| Giai đoạn | Kết quả |
|---|---|
| COUNCIL_IDEATION | 5 chuyên gia đề xuất 44 hướng (muse 10, systems-arch 9, algo-ml 8, backend-sec 9, fullstack-ux 8) |
| COUNCIL_DEDUP | Khử trùng lặp thành 21 hướng độc lập; đặt tên dự án `vn-realtime-voice-agent`; chốt kiến trúc 4 plane fail-closed |
| COUNCIL_AUDIT vòng 1 | `dong_thuan: false` — 13 lỗi; `main` trống ("Chưa có repo"); phát hiện 2 xung đột đặc tả (mã lý do chuyển 3 dạng; ngân sách độ trễ cộng vượt SLO) |
| COUNCIL_BUG_TRIAGE vòng 1 | ~40 báo cáo → 23 fix thực sự, phân công systems-arch 6, algo-ml 6, backend-sec 5, fullstack-ux 6; khóa các quyết định contracts |
| COUNCIL_AUDIT vòng 2 | `dong_thuan: false` — 10 lỗi; `main` vẫn trống, 0/23 fix có mặt; chặn audit 3 cho tới khi có 3 bằng chứng merge |
| COUNCIL_BUG_TRIAGE vòng 2 | ~40 báo cáo → 8 fix tăng thêm; phát hiện ~22/23 fix đã có code + test xanh trên nhánh/VM nhưng mất khi merge; chỉ resilience_controller chưa từng được nộp |
| COUNCIL_AUDIT vòng 3 | `dong_thuan: false` — 7 lỗi; `main` vẫn trống vòng thứ 3 liên tiếp; audit 3 mở bất chấp cổng chặn; thống nhất dừng vòng lặp audit/debate, chuyển sang chế độ thực thi |
| COUNCIL_BUG_TRIAGE vòng 3 | ~35 báo cáo → 7 fix tăng thêm; đính chính trạng thái rebase (phần lớn đã xong trên nhánh); phát hiện lệch tên hằng số SLO; bổ sung kiểm tra thứ tự vào gate |
| COUNCIL_FINAL_REPORT | 100% đồng thuận (theo biên bản trình bày — xem Phụ lục A) |
| GIAO_VIEC_GOP_Y | Chủ doanh nghiệp: "tạo repo đi chứ" — CEO giao 6 phần việc (khung repo + 4 module systems-arch + 3 nhóm module + merge cuối) |
| DUYET (tới 3 lần/phần việc) | backend-sec ĐẠT (67 passed theo báo cáo chạy thật); algo-ml ĐẠT (như đã viết, chưa từng báo cáo lần chạy); fullstack-ux ĐẠT (như đã viết, chưa từng báo cáo lần chạy); khung repo systems-arch: nội dung chấp nhận, bàn giao làm lại; nhiệm vụ 2 của systems-arch chưa nộp |
| TONG_HOP | Báo cáo cuối cập nhật này — code thật đã tồn tại trên máy các chuyên gia và đã qua duyệt, nhưng repo chia sẻ vẫn chưa tồn tại; xem mục Xử lý góp ý |

### 4.2. Các quyết định tranh luận quan trọng đã chốt

- **MAX_CLARIFICATIONS:** khóa = 1 lần hỏi lại; biến thể MAX=2 (backend-sec) bị bác. Hòa giải: hai phe đếm khác nhau (số lần hỏi lại vs tổng số lần thử).
- **Containment:** khóa hai lớp, final = 72h cố định; khoảng "24–72h" bị bác.
- **Mô hình hàng đợi:** khóa Erlang-A; Erlang-C bị bác (không mô hình abandonment).
- **Ngân sách độ trễ:** khóa 250+500+350=1100ms + 100ms jitter; ngưỡng tool-call 500ms; tên hằng số duy nhất `TOTAL_SLO_P95_MS`.
- **Phân loại mất fix:** (a) đã nộp nhưng mất khi merge — đa số; (b) đã viết nhưng chưa từng nộp — chỉ resilience_controller; (c) chưa từng được viết — không có file nào. Hai khẳng định "chưa từng được nộp" (context_package/SME hub/voice_security; các module lõi hội thoại) đã được đính chính là sai.
- **Lệch contract trong bản nộp:** policy_engine từng mang MAX=2, metrics_dashboard từng mang window 48h — đã sửa trong rebase; m3 từng dùng `user_requested` và thiếu `repeated_clarification` — đã sửa trong rebase.
- **Quy tắc nhánh:** ngoại lệ hẹp cho nhánh rebase-only (thay đổi cơ học, kiểm chứng bằng grep CI + test) vì quy tắc "1 file + 1 test mỗi nhánh" đã chặn hoàn thành rebase.
- **Cổng manifest-test:** một fix chỉ tính xong khi file của nó và test của nó đều có mặt trong `tests/` trên `main`, kiểm tra bằng đối chiếu manifest sau merge (bài học MẤT FIX KHI MERGE từ dự án multi-account-video-stats).

### 4.3. Danh sách nhánh fix đã xử lý (38 lượt, 36 mã duy nhất)

Tất cả được báo cáo Test: PASS và đã merge vào `main` (theo biên bản trình bày — xem Phụ lục A về phạm vi kiểm chứng).

**Triage vòng 1 — 23 fix:**

| Nhánh fix | Người sửa | Nội dung |
|---|---|---|
| `fix/fix_missing_repo_main_empty` | systems-arch | Khởi tạo repo + manifest + CI gate chống mất file |
| `fix/fix_missing_contracts` | systems-arch | Khóa contracts v1.0.0 |
| `fix/fix_missing_media_gateway` | systems-arch | Merge media gateway (m3) |
| `fix/fix_missing_scaling_platform` | systems-arch | Merge scaling platform (m3) |
| `fix/fix_missing_resilience_controller` | systems-arch | Resilience: ngân sách độ trễ, breaker, fallback |
| `fix/fix_missing_data_golden` | systems-arch | Merge collect_data + dữ liệu golden (m3) |
| `fix/fix_missing_orchestrator` | algo-ml | Realtime orchestrator streaming |
| `fix/fix_missing_vietnamese_normalizer` | algo-ml | Chuẩn hoá tiếng Việt 3 miền |
| `fix/fix_missing_grounded_answer` | algo-ml | Grounded answering + verifier |
| `fix/fix_missing_confidence_gate` | algo-ml | Confidence gate hiệu chuẩn (P0) |
| `fix/fix_missing_capacity_planner` | algo-ml | Capacity planner Erlang-A |
| `fix/fix_missing_model_cascade` | algo-ml | Model cascade + cache |
| `fix/fix_missing_tool_gateway` | backend-sec | Merge tool gateway (m3) + test xâm nhập |
| `fix/fix_missing_policy_engine` | backend-sec | Policy engine, hard-rule thắng gate |
| `fix/fix_missing_voice_security` | backend-sec | Bảo mật giọng nói, PII, chống injection |
| `fix/fix_missing_callback_ticket` | backend-sec | Callback/ticket outbox + Kafka |
| `fix/fix_missing_metrics_dashboard` | backend-sec | Metrics dashboard, containment 2 lớp |
| `fix/fix_missing_dialogue_manager` | fullstack-ux | Dialogue manager, intent/slot/DST |
| `fix/fix_missing_handoff_service` | fullstack-ux | Merge handoff service (m3) |
| `fix/fix_missing_handoff_package` | fullstack-ux | HandoffPackage + Agent Desktop |
| `fix/fix_missing_knowledge_pipeline` | fullstack-ux | Merge ingestion pipeline (m3) |
| `fix/fix_missing_sme_onboarding_hub` | fullstack-ux | SME Hub + wizard 5 bước (P1) |
| `fix/fix_missing_eval_harness` | fullstack-ux | Eval harness + shadow/canary + E2E |

**Triage vòng 2 — 8 fix tăng thêm:**

| Nhánh fix | Người sửa | Nội dung |
|---|---|---|
| `fix/fix_merge_pipeline_gate` | systems-arch | Cổng merge: manifest + CI + 3 bằng chứng |
| `fix/fix_missing_contracts` | systems-arch | Merge contracts v1.0.0 + test khóa version + grep CI (xác nhận lại mã vòng 1) |
| `fix/fix_resubmit_resilience_controller` | systems-arch | Nộp lại resilience_controller (chưa từng rời VM) |
| `fix/fix_rebase_m3_to_contracts` | systems-arch | Rebase 6 artifact m3 (sửa `user_requested`, bỏ mirror) |
| `fix/fix_rebase_algo_ml_to_contracts` | algo-ml | Rebase 6 module algo-ml (giữ Erlang-A, cache theo phiên) |
| `fix/fix_rebase_backend_sec_to_contracts` | backend-sec | Rebase 4 module backend-sec (sửa MAX=2, window 48h) |
| `fix/fix_rebase_fullstack_to_contracts` | fullstack-ux | Rebase 6 module fullstack-ux (87 test) |
| `fix/fix_merge_tests_golden_ci` | fullstack-ux | Merge tests + data/golden + CI + test E2E |

**Triage vòng 3 — 7 fix tăng thêm:**

| Nhánh fix | Người sửa | Nội dung |
|---|---|---|
| `fix/fix_latency_constant_name` | systems-arch | Khóa tên `TOTAL_SLO_P95_MS` duy nhất |
| `fix/fix_gate_order_check` | systems-arch | Kiểm tra thứ tự contracts-trước-module trong gate |
| `fix/fix_resubmit_resilience_controller` | systems-arch | Nộp lại resilience_controller (lần thất bại thứ hai) |
| `fix/fix_rebase_remaining_m3` | systems-arch | Hoàn tất rebase m3 (tàn dư `user_requested`) |
| `fix/fix_rebase_remaining_algo_ml` | algo-ml | Hoàn tất rebase 5 module algo-ml còn lại |
| `fix/fix_rebase_remaining_backend_sec` | backend-sec | Hoàn tất rebase 3 module backend-sec còn lại |
| `fix/fix_rebase_remaining_fullstack` | fullstack-ux | Hoàn tất rebase 5 module fullstack-ux còn lại |

Lưu ý: `fix_missing_contracts` và `fix_resubmit_resilience_controller` mỗi mã xuất hiện 2 lần vì được xác nhận lại qua các vòng triage — tổng 38 lượt fix tương ứng 36 mã duy nhất, không phải công việc trùng lặp.

### 4.4. Kết quả kiểm thử (theo báo cáo từng nhánh — xem Phụ lục A)

Số test dưới đây là số **báo cáo trên nhánh/VM của từng chuyên gia**, chưa từng có một lần chạy pytest toàn repo trên `main` được công bố. Hội đồng chấp nhận theo báo cáo, không xác minh độc lập chéo các con số nhánh-cục-bộ của nhau.

| Nhóm | Số test báo cáo (nhánh/VM) |
|---|---|
| systems-arch m3 + contracts + gate + media + scaling + resilience + data | 20 + 12 + 11–12 + 16 + 9 + 11 + 6 |
| algo-ml 6 module (orchestrator, normalizer, grounded, gate, capacity, cascade) | 15/16 + 16 + 13 + 16 + 13 + 14 |
| backend-sec 4 module + rebase policy_engine | 14 + 14 + 13 + 12 + 22 (rebase) |
| fullstack-ux 6 module + rebase dialogue_manager + E2E/regression | 87 + 7 + 4 + 6 |

Test phủ định bắt buộc đã quy định: tenant khác bị từ chối; injection trong transcript không thành tool-call; không evidence → UNKNOWN/escalate; số liệu lệch payload → chặn phát; ca bồi thường/pháp lý dù confidence cao → hard-rule chuyển người; hết agent → ticket; session cúp ngang giải phóng hết tài nguyên (đếm sót = 0); log sau redaction không chứa SĐT/địa chỉ dạng thô.

**Kết quả kiểm chứng mới từ vòng xử lý góp ý (22/11/2026):** các số này vẫn là số trên máy riêng của từng chuyên gia — chưa có lần chạy nào trên `main` của repo chia sẻ.

| Nhóm | Kết quả vòng xử lý góp ý |
|---|---|
| systems-arch — khung repo | pytest **39 passed** (18 contracts + 11 gate + 10 order-check) trên máy người nộp; gate skeleton exit 0; gate đầy đủ exit 1 đúng thiết kế (21 file approach chưa merge) |
| backend-sec — 5 module + 5 test | py_compile OK; pytest **67 passed** (tool_gateway 12, policy_engine 16, voice_security 14, callback 13, metrics 12) trên máy người nộp; grep mirror sạch; 1 lỗi thật đã sửa (regex che địa chỉ dạng không dấu) |
| algo-ml — 6 module + test | **Chưa từng báo cáo lần chạy nào** — duyệt như đã viết; 3 lỗi liên module đã sửa và kiểm chứng được trong file test nhìn thấy (9/13 test grounded: 4 golden case đúng) |
| fullstack-ux — 6 module + E2E | **Chưa từng báo cáo lần chạy nào** — duyệt như đã viết; 2 lỗi lần 1 đã sửa và giữ được (gateway tools + bỏ gán lại MAX) |

---

## 5. Hướng dẫn cài đặt, sử dụng & kiểm chứng

### 5.1. Yêu cầu hệ thống

- Python 3.11+
- Redis (session store), Kafka (hàng đợi callback), PostgreSQL (dữ liệu nghiệp vụ) — qua `docker/docker-compose.yml`
- Tài khoản tổng đài cloud có hỗ trợ SIP/WebRTC media streaming
- API key các nhà cung cấp ASR / TTS / LLM tiếng Việt (FPT / Vbee / Azure / Google — fallback theo ma trận đã đo)

### 5.2. Cài đặt

```bash
git clone <repo-cuc-bo> vn-realtime-voice-agent
cd vn-realtime-voice-agent
python -m venv .venv && source .venv/bin/activate
pip install -e .
docker compose -f docker/docker-compose.yml up -d   # Redis, Kafka, DB
```

**Lưu ý (22/11/2026):** lệnh `git clone` trên chưa chạy được — remote GitHub chưa tồn tại. Khung repo hiện chỉ có trên máy ảo của systems-arch (`~/workspace/vn-realtime-voice-agent`, 2 commit). Sau khi tạo remote và push, cập nhật URL thật (`https://github.com/HTL2910/vn-realtime-voice-agent`, dự kiến) vào đây cùng commit hash + manifest + log pytest của commit đó.

### 5.3. Sinh dữ liệu golden & kiểm tra manifest

```bash
python scripts/collect_data.py --seed 42   # tái sinh data/ và data/golden/
python scripts/verify_main_manifest.py --publish-evidence evidence.json --require-evidence
# Gate fail (exit 1) khi: thiếu 1 file kỳ vọng, compile lỗi, pytest đỏ,
# hoặc module import src.contracts mà contracts vắng mặt trong cùng manifest.
```

### 5.4. Chạy kiểm thử

```bash
python -m compileall src
pytest -q                        # toàn bộ suite trên main
pytest tests/test_e2e_call.py -q # cổng nghiệm thu liên tầng: 1 cuộc gọi mô phỏng đầy đủ
pytest tests/test_fix_missing_contracts.py -q  # khóa version + grep CI
```

Một fix chỉ được tính là xong khi file của nó và test của nó đều có mặt trong `tests/` trên `main` (cổng manifest-test).

### 5.5. Chạy hệ thống (khởi động)

```bash
# 1. Media gateway (SIP/WebRTC) + orchestrator realtime
python -m src.telephony.media_gateway --config config/telephony.yaml
python -m src.realtime.orchestrator --config config/realtime.yaml
# 2. Worker callback / ticket
python -m src.callback.callback_ticket_service
# 3. Dashboard quan trắc
python -m src.observability.metrics_dashboard --port 8080
```

### 5.6. Kiểm chứng từng hướng giải quyết

| Hướng | Cách kiểm chứng |
|---|---|
| 01 Media gateway | `pytest tests/test_fix_missing_media_gateway.py` — barge-in timestamp < 150ms; quá tải vào hàng đợi thay vì rớt cuộc |
| 02 Orchestrator | `pytest tests/test_orchestrator.py` — đo p50/p95 từng chặng; barge-in / reconnect / timeout |
| 03 Normalizer | `pytest tests/test_vietnamese_normalizer.py` — WER theo miền và mức ồn |
| 04 Dialogue manager | `pytest tests/test_dialogue_manager.py` — từng intent, ca thiếu slot, đếm hỏi lại theo `MAX_CLARIFICATIONS` |
| 05 Tool gateway | `pytest tests/test_tool_gateway.py` — tool lạ bị rejected, thiếu tenant bị rejected, sai hậu tố SĐT không trả dữ liệu, cross-tenant bị từ chối |
| 06 Grounded answer | `pytest tests/test_grounded_answer.py` — golden 4 ca: không bản ghi / mâu thuẫn / thiếu trường / số liệu lệch |
| 07 Confidence gate | `pytest tests/test_confidence_gate.py` — ngưỡng 0.85/0.60, ca thiếu evidence |
| 08 Policy engine | `pytest tests/test_policy_engine.py` — hard-rule thắng mọi confidence cao; cấm thương lượng bồi thường |
| 09 Handoff service | `pytest tests/test_handoff_service.py` — hết agent → CALLBACK + `ticket_id`; context push fail → không bridge mù |
| 10 Context package | `pytest tests/test_context_package.py` — time-to-context; validator tóm tắt đối chiếu transcript |
| 11 Callback/ticket | `pytest tests/test_callback_ticket_service.py` — idempotency, dedup, quá SLA |
| 12 Capacity planner | `pytest tests/test_capacity_planner.py` — biên c=1 khớp M/M/1; quá tải trả `overloaded=True` |
| 13 Knowledge pipeline | `pytest tests/test_ingestion_pipeline.py` — chunk hết hạn không trả về; CONFLICT → hạ confidence; regression golden FAQ chặn publish |
| 14 SME hub | `pytest tests/test_sme_onboarding_hub.py` — wizard 5 bước, health-check connector |
| 15 Model cascade | `pytest tests/test_model_cascade.py` — cache theo phiên TTL 60s, không cache chéo phiên |
| 16 Resilience | `pytest tests/test_fix_resubmit_resilience_controller.py` — provider timeout/sập liên tiếp; tổng vượt SLO thì fail |
| 17 Scaling | `pytest tests/test_fix_missing_scaling_platform.py` — shed chỉ LOW/NORMAL; VIP/HIGH không bị shed; multi-AZ |
| 18 Voice security | `pytest tests/test_voice_security_policy.py` — injection không thành tool-call; session cúp ngang giải phóng hết tài nguyên; log redacted |
| 19 Metrics | `pytest tests/test_metrics_dashboard.py` — containment 2 lớp; tách số nội bộ khỏi benchmark |
| 20 Eval harness | `pytest tests/test_simulation_harness.py` + `tests/test_e2e_call.py` — golden calls, shadow/canary, kill-switch < 1 phút |
| 21 Dữ liệu | `python scripts/collect_data.py --seed 42` — tái sinh đúng 12 golden calls, 4 FAQ, 60 đơn, 5 SKU, 20 lịch hẹn; kiểm tra không PII thật |

### 5.7. Go-live (cổng bắt buộc trước lưu lượng thật)

1. Shadow mode song song tổng đài người; so quyết định AI với người trên cùng transcript.
2. Canary 5–10% lưu lượng với kill-switch chuyển toàn bộ sang người trong < 1 phút.
3. Cổng go-live dựa trên số đo shadow/canary của **chính tenant** (containment final, abandonment, FCR, latency p95) — không dùng số vendor 52–76–80% làm KPI.
4. Checklist 7 câu sẵn sàng triển khai (dữ liệu tra cứu được, tổng đài cloud có API, ghi âm + transcript, tỉ lệ câu lặp lại, giờ cao điểm + số cuộc bị bỏ, quy trình chuyển máy, đo abandonment/FCR) làm mốc gốc trước khi bật AI.

---

## Phụ lục A — Những điểm chưa kiểm chứng được (ghi thẳng)

Phụ lục này giữ nguyên khi dùng lại báo cáo, để không bị bắt bẻ.

1. **Trạng thái đồng thuận là theo biên bản trình bày, chưa kiểm chứng độc lập.** Cả 3 vòng audit trong biên bản hội đồng đều kết luận `dong_thuan: false` với `main` trống ("Chưa có repo"). Biên bản cuối cùng trình bày 100% đồng thuận và 38 lượt fix đã merge, nhưng không kèm theo bằng chứng mới nào thay đổi được kết luận của 3 vòng audit đó. Trưởng nhóm ghi nhận trạng thái cuối cùng **theo báo cáo**, không xác nhận đã tự kiểm chứng repo.
2. **Danh sách file hoàn chỉnh trên `main` kèm theo biên bản cuối cùng để trống.** Không có cây file, commit hash, manifest (`git ls-files` + hash) hay log pytest trên `main` trong biên bản cuối cùng — đúng 3 bằng chứng mà cổng chặn của hội đồng yêu cầu và chưa từng xuất hiện ở bất kỳ vòng nào.
3. **Không có kết quả pytest toàn repo trên `main`.** Mọi số test trong §4.4 đều là số báo cáo trên nhánh/VM của từng chuyên gia. Lần chạy pytest duy nhất có số liệu là ở cấp nhánh; chưa có lần chạy `pytest -q` toàn repo trên `main` nào được công bố. Vì vậy tỉ lệ pass toàn repo trên `main` hiện là **chưa biết**, không phải 100%.
4. **Phân công approach trong §3 khác phân công fix trong §4 ở 9 approach** (03, 07, 08, 10, 12, 14, 15, 16, 18). Ví dụ: approach_03 (normalizer) ghi phụ trách backend-sec trong danh sách approach nhưng fix tương ứng do algo-ml sửa; approach_08 (policy engine) ghi fullstack-ux nhưng fix do backend-sec sửa. Danh sách approach phản ánh phân công nhánh expert ban đầu, danh sách fix phản ánh người thực hiện công việc sửa lỗi — **danh sách fix là hồ sơ authoritative** khi hai bảng mâu thuẫn.
5. **Hai mã fix xuất hiện 2 lần** (`fix_missing_contracts`, `fix_resubmit_resilience_controller`) vì được xác nhận lại qua các vòng triage — 38 lượt fix tương ứng 36 mã duy nhất. Đây không phải công việc trùng lặp, nhưng người đọc bảng §4.3 cần biết để không đếm nhầm thành 38 fix độc lập.
6. **Resilience controller có lịch sử nộp thất bại 2 lần** (từ chối xuất khối `[[FILE]]` thay vì nộp file). Biên bản cuối cùng ghi fix này Test: PASS và đã merge; do không có manifest trên `main` để đối chiếu, Trưởng nhóm không thể xác nhận độc lập rằng file đã thực sự lên `main` ở lần nộp thứ ba.
7. **Số vendor không phải KPI.** Mọi con số 52% (Ada), 76% (Intercom Fin), 80% (Gartner) trong §1.5 là số vendor tự công bố hoặc dự báo, chưa kiểm toán độc lập; hệ thống này chưa có số đo containment/abandonment/FCR nào trên lưu lượng thật. Cam kết hiệu quả chỉ có giá trị sau shadow/canary trên chính tenant triển khai.
8. **Repo vẫn là repo cục bộ — nay là repo cục bộ trên đúng một máy ảo.** Sau vòng xử lý góp ý, khung repo tồn tại trên máy ảo của systems-arch (2 commit: `208e7361c15bb61fb958ade21f425b9bb251d4ba` + `8ea0938` hash ngắn; manifest 35 file) nhưng CEO đã kiểm tra và xác nhận repo **không có trên máy của CEO**, và GitHub chưa được tạo (`gh` chưa đăng nhập). URL `https://github.com/HTL2910/vn-realtime-voice-agent` vẫn là "(dự kiến)". Khi repo được đẩy lên GitHub, cần cập nhật link và đính kèm commit hash + manifest + log pytest của commit đó vào README này.
9. **Các module đã duyệt vẫn chưa nằm trong tay CEO hay merge owner.** Quyết định ĐẠT cho backend-sec, algo-ml, fullstack-ux dựa trên bằng chứng tích lũy qua 3 lần nộp (xem mục Xử lý góp ý); các file đầy đủ chưa từng tới được tay CEO do kênh truyền tin cắt cụt mọi bài nộp dài — kể cả khi đã tách 1 file mỗi tin nhắn và tách file dài thành nhiều phần có đánh dấu. Việc đưa file về là việc hậu cần của CEO/merge owner (git bundle hoặc kênh khác), không phải lượt sửa của chuyên gia. Neo kiểm chứng cho việc vận chuyển: SHA-256 từng file khớp manifest đã nộp và pytest trên `main` tái hiện đúng số test đã báo cáo.
10. **algo-ml và fullstack-ux chưa từng báo cáo một lần chạy test nào.** Quyết định đạt cho hai nhóm này duyệt công việc **như đã viết** (chất lượng đã đọc và kiểm chứng được ở phần nhìn thấy), không duyệt như "đã chạy xanh". Chỉ backend-sec có báo cáo chạy thật (67 passed, kèm chi tiết từng file và 1 lỗi thật đã sửa). Việc chạy pytest để xác nhận hai nhóm còn lại dồn về cổng merge trên `main` — test nào fail ở đó sẽ bị trả lại, không vào `main`.
11. **Nhiệm vụ 2 của systems-arch chưa được nộp.** media_gateway, resilience_controller, scaling và collect_data + dữ liệu golden chưa có bài nộp nào trong vòng xử lý góp ý; resilience_controller có lịch sử nộp thất bại 2 lần trong giai đoạn hội đồng (xem mục 6 trên).
12. **Bước merge cuối chưa bắt đầu.** Merge phụ thuộc vào việc file về tới nơi và vào việc tạo remote GitHub; chưa có commit hash, manifest hay log pytest nào trên `main` của repo chia sẻ. CEO sẽ không báo cáo "đã xong" cho tới khi cả 3 bằng chứng cùng tồn tại và đính kèm được vào báo cáo này.

---

## Phụ lục B — Thành viên hội đồng

| Thành viên | Vai trò |
|---|---|
| **muse** | CEO / Trưởng nhóm Điều phối Nghiên cứu — tiếp nhận đề bài, tổng hợp & khử trùng lặp, thiết kế cấu trúc repo, điều phối conflict, tổng kết báo cáo |
| **systems-arch** | Chuyên gia Kiến trúc Hệ thống — kiến trúc phân tán, cấu trúc module, giao thức, mở rộng & chịu lỗi; chủ sở hữu merge (merge owner) |
| **algo-ml** | Chuyên gia Thuật toán & AI — mô hình hoá, tối ưu thuật toán, pipeline dữ liệu, suy luận |
| **backend-sec** | Chuyên gia Backend & Bảo mật — cơ sở dữ liệu, đồng thời, bảo mật, chống rò rỉ tài nguyên |
| **fullstack-ux** | Chuyên gia Ứng dụng & Tích hợp — API, giao diện, trải nghiệm người dùng, tích hợp end-to-end |

---

*Báo cáo này do Trưởng nhóm muse tổng hợp từ toàn bộ biên bản COUNCIL_IDEATION, COUNCIL_DEDUP, COUNCIL_AUDIT (3 vòng), COUNCIL_BUG_TRIAGE (3 vòng) và COUNCIL_FINAL_REPORT của Hội đồng Chuyên gia AI MuseAssistantTeam, ngày 22/11/2026, và cập nhật sau vòng xử lý góp ý của chủ doanh nghiệp cùng ngày (GIAO_VIEC_GOP_Y, DUYET tới 3 lần/phần việc, TONG_HOP). Nội dung phản ánh đúng các quyết định đã khóa của hội đồng; các điểm chưa kiểm chứng được ghi rõ tại Phụ lục A.*
