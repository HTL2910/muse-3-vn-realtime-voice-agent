# vn-realtime-voice-agent

AI trợ lý giọng nói realtime trả lời khách hàng bằng tiếng Việt — chỉ trả lời
trong phạm vi dữ liệu được cấp (đơn hàng, tồn kho, lịch hẹn, FAQ, chính sách),
tuyệt đối không bịa. Khi gặp câu ngoài phạm vi, không chắc chắn, tình huống
nhạy cảm hoặc khách yêu cầu gặp người — AI chuyển cho nhân viên kèm tóm tắt,
transcript và nhu cầu đã xác định. Nếu không có nhân viên rảnh / ngoài giờ
trực, AI ghi nhận yêu cầu, tạo phiếu và hẹn gọi lại.

- **Repo:** https://github.com/HTL2910/vn-realtime-voice-agent
- **Trạng thái:** khung repo (skeleton) — contracts v1.0.0 + cổng manifest +
  CI + hạ tầng đã có; **0/21 module approach đã merge**.
- **Báo cáo đầy đủ của Hội đồng Chuyên gia** (bối cảnh, bằng chứng thị trường,
  21 hướng giải quyết) sẽ do CEO cung cấp toàn văn để đặt vào file này ở
  bước gộp cuối — file README này hiện chỉ là bản tạm.

## Quyết định đã khóa (src/contracts.py v1.0.0)

- `EscalationReason` snake_case duy nhất: `out_of_scope`, `low_confidence`,
  `sensitive`, `customer_request`, `repeated_clarification`,
  `repeated_failure`; `no_agent` / `system_error` chỉ để log, luôn map
  sang `CALLBACK`.
- `MAX_CLARIFICATIONS = 1` lần hỏi lại; `decide_clarification()` khóa
  cách đếm bằng code (lần phát hiện thiếu slot đầu tiên là elicitation
  ban đầu, không tính; đúng 1 lần hỏi lại; vẫn thiếu thì escalate
  `repeated_clarification`).
- Containment 2 lớp; `contained_final` = provisional + không liên hệ lại
  cùng vấn đề trong **72h cố định**.
- Ngân sách độ trễ: ASR 250 + LLM 500 + TTS 350 = 1100 ms + 100 ms jitter,
  trong SLO p95 `TOTAL_SLO_P95_MS = 1200` ms; tool-call > 500 ms không
  nằm trên đường first-audio.
- Hàng đợi **Erlang-A** (M/M/c+M), mean patience 90 s — không dùng Erlang-C.
- Một kiểu import duy nhất: `from src.contracts import ...`; mọi module
  fail-closed khi `CONTRACTS_VERSION` sai (`assert_contracts_version()`).

## Cây thư mục

```
src/
  contracts.py            # hợp đồng chung duy nhất (stdlib only)
  telephony/ realtime/ voice/ dialogue/ nlu/ grounding/ gating/ dialog/
  handoff/ callback/ queueing/ knowledge/ integrations/ optimization/
  platform/ security/ observability/ eval/ api/ web/
scripts/verify_main_manifest.py   # cổng manifest + kiểm tra thứ tự
tests/                    # test contracts + test cổng manifest
data/golden/              # dữ liệu golden (collect_data.py --seed 42)
.github/workflows/ci.yml # compileall + pytest + grep CI
docker/docker-compose.yml # Redis / Kafka / PostgreSQL (local dev)
```

## Chạy kiểm tra

```bash
python -m compileall src scripts
python -m pytest -q
# Cổng manifest — chế độ skeleton (khung repo, trước khi module đầu tiên merge):
python scripts/verify_main_manifest.py --skeleton --publish-evidence evidence.json --require-evidence
# Cổng manifest — chế độ đầy đủ (mặc định, merge gate):
python scripts/verify_main_manifest.py
```

Chế độ đầy đủ fail cho tới khi đủ 21 approach + contracts + scaffolding —
đó là thiết kế: gate chỉ xanh khi merge thật sự hoàn tất, kèm 3 bằng chứng
(commit hash + `git ls-files`/hash + log pytest) trên đúng 1 commit.

## Hạ tầng local

```bash
docker compose -f docker/docker-compose.yml up -d
```
