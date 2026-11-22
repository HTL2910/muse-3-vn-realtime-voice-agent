# Khởi tạo repo GitHub vn-realtime-voice-agent + contracts v1.0.0 + cổng manifest/CI

_systems-arch · Chuyên gia Kiến trúc Hệ thống · lần nộp 1_

## Việc được giao

Góp ý cần xử lý: chủ doanh nghiệp yêu cầu 'tạo repo đi chứ' sau khi đọc báo cáo cuối — báo cáo đã thừa nhận repo mới chỉ là 'repo cục bộ' không có URL, main trống, chưa từng có commit hash/manifest/log pytest. Việc của bạn: (1) Tạo repo GitHub tên vn-realtime-voice-agent (giả định: tài khoản HTL2910 của chủ doanh nghiệp như 2 dự án trước, private), git init, nhánh main. (2) Tạo toàn bộ cây thư mục theo README §2.2: src/ (contracts.py + telephony, realtime, voice, dialogue, nlu, grounding, gating, dialog, handoff, callback, queueing, knowledge, integrations, optimization, platform, security, observability, eval, api, web), scripts/, data/golden/, tests/, docs/, docker/. (3) Viết src/contracts.py v1.0.0 (chỉ dùng Python standard library) khóa toàn bộ quyết định hội đồng đã chốt: CONTRACTS_VERSION='1.0.0'; EscalationReason snake_case duy nhất gồm out_of_scope, low_confidence, sensitive, customer_request, repeated_clarification, repeated_failure (no_agent/system_error chỉ để log, luôn map sang CALLBACK); MAX_CLARIFICATIONS=1 lần hỏi lại + hàm decide_clarification() khóa cách đếm bằng code; containment 2 lớp, final = provisional + không liên hệ lại cùng vấn đề trong 72h CỐ ĐỊNH; ngân sách độ trễ ASR_PARTIAL_MS=250, LLM_FIRST_TOKEN_MS=500, TTS_FIRST_AUDIO_MS=350, TOTAL_SLO_P95_MS=1200 (tổng 1100ms + 100ms jitter), TOOL_CALL_OFF_PATH_MS=500; mô hình hàng đợi Erlang-A; một kiểu import duy nhất 'from src.contracts import ...'; mọi module fail-closed khi CONTRACTS_VERSION sai. (4) Viết scripts/verify_main_manifest.py: kiểm tra đủ 21 approach + contracts + scaffolding, SHA-256 từng file, compileall, pytest, hỗ trợ --publish-evidence/--require-evidence, và kiểm tra THỨ TỰ (module import src.contracts chỉ tính là merged khi contracts có trong cùng manifest). (5) CI .github/workflows/ci.yml chạy compileall + pytest + grep CI cấm TOTAL_TURN_P95_MS, user_requested, OUT_OF_SCOPE và định nghĩa trùng hằng số trong src/. (6) pyproject.toml (Python 3.11+), .gitignore, docker/docker-compose.yml (Redis/Kafka/PostgreSQL). README.md sẽ do CEO cung cấp toàn văn báo cáo cuối để đặt vào repo ở bước gộp cuối — bạn tạo file README.md tạm ghi tên dự án + link repo. Kết quả nộp: URL repo + commit hash đầu tiên + manifest (git ls-files + SHA-256) + evidence.json + log gate exit 0 trên khung repo.

## Bài làm

## Kết quả bàn giao — khung repo vn-realtime-voice-agent

**Repo (dự kiến):** https://github.com/HTL2910/vn-realtime-voice-agent — private, tài khoản HTL2910 (chưa tạo được từ máy này vì `gh` chưa đăng nhập; xem lệnh ở cuối bài).
**Repo local:** `~/workspace/vn-realtime-voice-agent`, nhánh `main`, 2 commit, cây làm việc sạch.

**Commit đầu tiên:** `208e7361c15bb61fb958ade21f425b9bb251d4ba` — "Skeleton: contracts v1.0.0, manifest gate (+order check, --skeleton), CI, infra" (34 files).
**Commit thứ hai:** `8ea0938` — evidence.json của lần chạy gate trên commit đầu tiên.

**Gate skeleton (log thật trên máy ảo):**
```
verify_main_manifest: PASS — merge verified
compile: ok
pytest: ok
extra files (ignored): 30
evidence: commit=208e7361c15bb61fb958ade21f425b9bb251d4ba files=34 tests_ok=True complete=True -> evidence.json
GATE SKELETON EXIT: 0
```
pytest trên khung repo: **39 passed** (18 contracts + 11 gate + 10 order-check).

**Gate đầy đủ (chế độ mặc định, merge gate): exit 1 — đúng như thiết kế**, vì 21 file approach chưa merge. Danh sách thiếu đúng 21 file: `scripts/collect_data.py`, `src/callback/callback_ticket_service.py`, `src/dialog/policy_engine.py`, `src/dialogue/dialogue_manager.py`, `src/eval/simulation_harness.py`, `src/gating/confidence_gate.py`, `src/grounding/grounded_answer.py`, `src/grounding/tool_gateway.py`, `src/handoff/context_package.py`, `src/handoff/handoff_service.py`, `src/integrations/sme_onboarding_hub.py`, `src/knowledge/ingestion_pipeline.py`, `src/observability/metrics_dashboard.py`, `src/optimization/model_cascade.py`, `src/platform/scaling.py`, `src/queueing/capacity_planner.py`, `src/realtime/orchestrator.py`, `src/realtime/resilience_controller.py`, `src/security/voice_security_policy.py`, `src/telephony/media_gateway.py`, `src/voice/vietnamese_normalizer.py`.

**Manifest (git ls-files + SHA-256, 35 files, sau commit thứ hai):**
```
9acecb905abff47b3d793bf979d68544726f675cb22cf88639bd0c5a1f6d6324  .github/workflows/ci.yml
a4ed29205b51b7c2feedbc062b16660f85cf5d147fb3aec7139d2c891e87d910  .gitignore
934af70747878f49a5af5e5d72955bad557688a5d49f2e2b26ee046547fee666  README.md
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  data/.gitkeep
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  data/golden/.gitkeep
d4c2ebcfc82408387ef5b97741067cff76ce9ea7c2d6e25b6b89b2273a406548  docker/docker-compose.yml
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  docs/.gitkeep
e614d41a8771cbd83b8057a128ab518979f26c616207798fe46dca1b8d12c1ef  evidence.json
8293962c1ed4db05087ee6ba83c1a978b45f8ebc7b8a94e4242cfdad16f816c1  pyproject.toml
28dafb5e87c111100e598b9627f81580657d2d1585a17a221f2dfd8ceb4e224a  scripts/verify_main_manifest.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/api/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/callback/__init__.py
150e20f9a665dd74ee0d1f97796a75608dcada8da0dcccb368977f74332bcea9  src/contracts.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/dialog/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/dialogue/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/eval/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/gating/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/grounding/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/handoff/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/integrations/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/knowledge/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/nlu/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/observability/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/optimization/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/platform/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/queueing/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/realtime/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/security/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/telephony/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/voice/__init__.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/web/__init__.py
1c0a1248177c6d96c0a8f1418d7fdf4689d476959515e4f15ef2f24b4a2958a3  tests/test_contracts.py
60d7d8641f6a24bdf1811b9ae07f04ffdb9d6f0464d6404e011911a696b043e5  tests/test_fix_gate_order_check.py
8531d5aaf3111767469de021049713d7b0a373338cd1ae6e48723281e7755f32  tests/test_fix_merge_pipeline_gate.py
```

**evidence.json (tóm tắt):** `commit_hash=208e7361c15bb61fb958ade21f425b9bb251d4ba`, `file_source="git ls-files"`, `files=34`, `tests_ok=true`, `gate_ok=true`, `mode="skeleton"`, `complete=true`. Toàn văn trong khối (đã nộp file `evidence.json`)

(đã nộp file `scripts/verify_main_manifest.py`)

(đã nộp file `.github/workflows/ci.yml`)

(đã nộp file `pyproject.toml`)

(đã nộp file `.gitignore`)

(đã nộp file `docker/docker-compose.yml`)

(đã nộp file `README.md`)

(đã nộp file `tests/test_contracts.py`)

(đã nộp file `tests/test_fix_gate_order_check.py`)

(đã nộp file `tests/test_fix_merge_pipeline_gate.py`)

(đã nộp file `evidence.json`)

## Tạo remote GitHub + push (chủ doanh nghiệp thực hiện — máy này chưa đăng nhập GitHub)

```bash
gh auth login
gh repo create HTL2910/vn-realtime-voice-agent --private --description "Realtime Vietnamese voice AI for customer service"
cd ~/workspace/vn-realtime-voice-agent
git remote add origin https://github.com/HTL2910/vn-realtime-voice-agent.git
git push -u origin main
# Sau push, kiểm chứng lại trên remote:
git ls-remote https://github.com/HTL2910/vn-realtime-voice-agent.git HEAD
```

## Tóm tắt gửi CEO (muse)

- Khung repo `vn-realtime-voice-agent` đã có thật trên máy local (nhánh `main`, commit đầu `208e736`, 34 file): contracts v1.0.0 khóa đủ quyết định hội đồng (thêm Erlang-A + fail-closed version), cổng manifest có kiểm tra thứ tự và chế độ skeleton, CI compileall/pytest/grep, hạ tầng Redis/Kafka/Postgres, 39 test xanh trên máy ảo.
- Gate skeleton exit 0 với evidence complete (commit hash + ls-files/hash + log pytest); gate đầy đủ vẫn đỏ đúng như thiết kế vì 0/21 module approach đã merge.
- Việc duy nhất chưa xong: **tạo repo GitHub** — máy này chưa đăng nhập GitHub nên không tạo được remote; chủ doanh nghiệp chạy 4 lệnh ở trên để tạo + push, sau đó CI GitHub sẽ báo kết quả thật.
- Bước tiếp theo: CEO đưa toàn văn báo cáo cuối vào README, rồi merge 21 module theo thứ tự đã khóa (contracts trước, module import contracts sau — gate kiểm tra thứ tự này).

## File đã nộp

- `evidence.json`
- `scripts/verify_main_manifest.py`
- `.github/workflows/ci.yml`
- `pyproject.toml`
- `.gitignore`
- `docker/docker-compose.yml`
- `README.md`
- `tests/test_contracts.py`
- `tests/test_fix_gate_order_check.py`
- `tests/test_fix_merge_pipeline_gate.py`
- `evidence.json`
