# Nền vận hành + Agent Eval v0 — kế hoạch

Status: đang làm (27/10/2026) — điều phối và ticket: `coordination.md`, `issues/`

Quyết định đã áp dụng (chủ dự án uỷ quyền "chủ động làm cho đến khi hoàn thiện", 27/10; đổi được bất
cứ lúc nào): Q1 (b) · Q2 (i) · Q3 (c) · Q4 (b). Q1 (d) là việc của chủ dự án — tự bật Docker Desktop
cùng Windows là cài đặt máy, agent không đổi.

Nguồn: khung 4 mốc của chủ dự án (đã duyệt về nguyên tắc), phản biện độc lập của một agent Fable,
và kiểm lại bằng code trong phiên 27/10. Chưa code gì.

## Bản chất

Trước khi dạy Ún giỏi hơn, phải có hai thứ: một nền chạy được mà không cần người trông, và một bài
thi chấm được Ún hôm nay giỏi đến đâu. Hiện cả hai đều chưa có. Bài thi đêm đã có nhưng gần sáu tuần
không chạy nổi lần nào, vì nó tưởng các dịch vụ luôn bật sẵn trong khi thật ra chúng đã tắt. Bài thi
cho agent thì chưa tồn tại. Kế hoạch này sửa nền trước, dựng bài thi sau, rồi mới làm một thí nghiệm
model và nâng cấp agent — mỗi bước đều phải qua bài thi.

## Thay đổi so với bản 4 mốc gốc

| Bản gốc | Sửa thành | Lý do (bằng chứng) |
|---|---|---|
| M1 là một mốc | Tách 1a → 1b → 1c → 1d | M1 trộn một việc chưa rõ nguyên nhân (eval đêm), một đổi hành vi (v2) và ba việc cơ học; tách để một chỗ hỏng không kéo cả mốc |
| Eval đêm: "xác nhận đúng compose project" | Hỏi câu khác: vì sao stack không chạy lúc 03:00, và vì sao `/health` treo thay vì báo `degraded` | Job không dùng compose — chỉ bật uvicorn (`backend/scripts/nightly_eval.py:203-220`); `docker compose ps` chỉ là bước chẩn đoán (`:72-74`). Lỗi đã được ghi rõ (`finish()` + ATTENTION + `diagnose()`), nên bỏ mục "có ghi log không" |
| "Test xác nhận downstream chấp nhận v2" | Test nhắm khoá (lượt, phiên bản) | Định dạng JSON vẫn ghi `"v1"` cả khi pipeline là v2 (`discord_memory_extractor.py:24-35`); test hiện tại assert hằng `"v1"` (`test_discord_memory_extractor.py:136,146`) nên đổi v2 vẫn xanh |
| Thư mục `evals/` mới ở gốc | Hai cách, chờ chọn (Q2) | Repo đã có ba nhà cho eval: code ở `backend/scripts/`, dữ liệu ở `data/benchmarks/` (tracked), kết quả ở `data/evaluation/results/` (ignore trừ `kept/`, `.gitignore:52-58`). `evals/` là nhà thứ tư và gốc import thứ ba |
| Gọi agent: chưa nói | `AgentService.run()` với 3 backend giả, model thật | Xem M2. Chat web không truyền `tool_context` (`routers/chat.py:40`), nên 10 bài lịch sử không chạy qua HTTP được |
| Ghi token, cố định seed | Bọc router để đọc token sau mỗi lượt; manifest ghi "không seed" | Token nằm trong ContextVar chỉ giữ lượt gọi cuối (`llm_clients/usage.py:20-35`); seed chưa được nối cho chat (`services/model_router.py:81` chỉ lấy temperature/top_p) |
| M3: viết giả thuyết trước | Thêm điều kiện tiên quyết | `split_manifest --check` + `leak_check` xanh (`training/README.md:44`); commit script train trước khi chạy GPU (bài học 07/09: mất code train) |

## Mốc 1a — Eval đêm chạy lại

Sự thật đã đo (log `data/logs/nightly_eval.log`, 27/10):

| Kết quả | Số đêm |
|---|---|
| Đạt (exit 0) | 10, lần cuối đêm 16/09 |
| Exit 97 (`/health` không trả lời trong 180 s) | 51 |
| Khác (exit 1, cửa sổ bị đóng) | 3 |

Phần chẩn đoán kèm theo mỗi đêm hỏng (có 48 đêm ghi chẩn đoán) cho thấy stack của Ún không chạy, theo
hai kiểu:

| `docker compose ps` lúc 03:00 | Nghĩa | Số đêm |
|---|---|---|
| exit 1 | Docker Desktop không trả lời | 30 |
| exit 0, danh sách rỗng | Docker chạy, container của Ún đã tắt | 18 |

Sáng 27/10: Docker trả lời, mọi container của Ún đã tắt khoảng 5 ngày; `edu-postgres-1` của dự án
edu đang giữ cổng 5432. `/health` luôn trả 200 kể
cả khi `degraded` (`operational_service.py:170`), nhưng phép thử Postgres không có connect timeout
(`postgres/database.py:21`) và `redis.ping()` không có socket timeout (`operational_service.py:95`),
nên khi phụ thuộc chết thì `/health` có thể treo — **giả thuyết, chưa tái hiện**.

Việc:
1. Tái hiện: tắt stack, chạy `nightly-eval-once.bat` bằng tay, xem `/health` treo ở phép thử nào.
2. Thêm timeout cho các phép thử trong `/health` để "phụ thuộc tắt" thành `degraded` nhanh.
3. Xử lý phụ thuộc theo cách đã chọn ở Q1.
4. Sửa banner: `nightly-eval-once.bat:24-25` có ký tự xuống dòng thật giữa `data\logs\nightly_eval.log`
   (in ra `ightly_eval.log`); chỉ hỏng chữ hiển thị, không hỏng eval.

Nghiệm thu: một đêm 03:00 thật exit 0; một lần chạy tay khi stack tắt kết thúc nhanh với thông báo
nêu đúng phụ thuộc nào tắt.

## Mốc 1b — Một cách cài

Launcher chạy `pip install -e . --no-deps` một lần; xoá 19 chỗ `sys.path.insert` (scripts 7,
training 8, tests 2, tools 1, alembic 1).

Nghiệm thu: launcher chạy từ venv sạch trên Windows; CI xanh; một script trong `backend/scripts/` và
một trong `training/` chạy được không cần hack.

## Mốc 1c — Compose chỉ chuyển tiếp (đổi hành vi có chủ đích)

Bỏ các `${VAR:-default}` trùng với Settings (16 biến trùng tên), để Settings là nơi duy nhất có
mặc định. Hệ quả: container memory-worker chuyển từ v1 sang v2. Commit riêng, ghi rõ đây là đổi
hành vi.

Nghiệm thu: test mới kiểm khoá (lượt, phiên bản) đỏ trước sửa, xanh sau sửa; log container báo v2.

## Mốc 1d — Dọn nhỏ (được phép trượt)

- Một cơ chế bật bot, để dashboard và panel cùng thấy một trạng thái; sửa luôn lỗi panel gọi
  `/turns/cancel-open` thiếu khoá API (cùng file `discord_bot/control.py`).
- Dời `services/job_errors.py`, `services/job_routing.py` ra khỏi `services/`.
- Chuyển truy vấn trong `routers/dashboard.py` vào một service.

## Mốc 2 — Agent Eval v0

Cách gọi agent: `AgentService.run()` với 3 backend giả theo Protocol (`agent_service.py:23-47`, mẫu
`_bare_agent` trong `backend/tests/test_agent_service.py`), model thật qua Ollama.

| Đo được | Không đo |
|---|---|
| Chọn công cụ, tham số, dùng kết quả, biết dừng, ghép câu trả lời | Chất lượng truy xuất, persona, ngữ cảnh trí nhớ, đường SSE |

Bổ sung: một bài smoke qua HTTP `/chat use_tools` với stack thật; lịch sử chạy với guild cố định
trên dữ liệu giả, và có bài riêng cho trường hợp **không guild** — agent phải nhận lỗi "chỉ dùng được
trong kênh Discord" và không bịa (đây là hành vi thật trên web).

Bộ bài khởi đầu (không phải chỉ tiêu cứng; thiếu tiêu chí chấm tốt thì giảm số bài):

| Loại | Số bài |
|---|---|
| Tra cứu tài liệu (cần hoặc không cần `search_documents`) | 20 |
| Lịch sử hội thoại (guild cố định + không guild) | 10 |
| Trạng thái hệ thống (snapshot giả) | 5 |
| Không cần công cụ / từ chối có căn cứ | 5 |

Cố định và ghi vào manifest: `general-v0` (`qwen3.5:9b`, top_p 0.9), `max_steps 3`,
`tool_result_max_chars 2400` (ghi tường minh vì mặc định trong code là 1200, `main.py:268`), hash
prompt hệ thống, phiên bản dataset, phiên bản bộ chấm, "không seed", nhiệt độ theo Q3.

Ghi mỗi lần chạy: `manifest.json`, `task_results.jsonl`, `events.jsonl`, `summary.json`. `events`
lấy từ `steps` mà `run()` trả về (đã có `latency_ms` từng vòng), không đọc `agent_traces`.

Baseline: 3 lần, so theo từng bài; báo cáo ghi rõ "baseline thăm dò, chưa đủ chứng minh thống kê".

Nghiệm thu: 3 lần chạy đủ artifact; ít nhất 5 bài được chấm tay để đối chiếu bộ chấm tự động; báo
cáo dao động theo từng bài.

## Mốc 3 — Một thí nghiệm model

Chọn **một** mục tiêu theo các bộ đo thành phần (`backend/scripts/evaluate_rag.py`,
`memory_e2e_eval.py`, `benchmark_discord_memory_extractor.py`, `training/common/eval_*.py`), không
theo Agent Eval. Trước khi chạy GPU: spec ghi giả thuyết, tập đo, điều kiện dừng;
`split_manifest --check` + `leak_check` xanh; script train đã commit.

## Mốc 4 — Harness theo lỗi đã đo

Registry công cụ có schema, ngân sách token/thời gian, lỗi/thử lại, tracing — chỉ làm phần nào mà
lỗi ở M2 chỉ ra. Chạy lại đúng bộ đo sau mỗi thay đổi. Tách hai loại lợi ích: kiểm soát (registry,
ngân sách) và chất lượng (chọn đúng công cụ, trả lời đúng — thường do mô tả công cụ, prompt, model).

Tiêu chí nghiệm thu: theo bảng của chủ dự án (hồi quy xanh, ít gọi sai công cụ, ngân sách có test,
trace tái dựng được một lần chạy, không suy giảm trên Agent Eval v0, timeout/lỗi công cụ/vượt ngân
sách có kết quả kiểm soát được).

## Điều kiện mở lại C/D/E

- C (gói con Discord): khi làm tính năng Discord kế tiếp, nếu gom nhóm giảm được phụ thuộc xuyên tầng.
- D (một gốc import): đánh giá lại ngay sau 1b.
- E (chia theo miền): chỉ khi có bằng chứng phụ thuộc chéo đang cản việc.

## Quyết định còn mở

**Q1 — Eval đêm xử lý phụ thuộc thế nào**

| Cách | Ưu | Nhược |
|---|---|---|
| (a) Job tự bật stack rồi chờ | Tự lành khi Docker chạy mà container tắt (18/48 đêm) | Vô dụng khi Docker Desktop chết (30/48 đêm); đụng edu trên 5432 |
| (b) Job kiểm phụ thuộc trước, thiếu thì dừng ngay, báo rõ | Đơn giản, trung thực | Vẫn đỏ nếu stack không bật |
| (c) Đổi cổng Postgres của Ún (vd 5433) + (a) | Hết tranh cổng với edu vĩnh viễn | Đụng `.env`, compose, docs; rủi ro trung bình; đảo quyết định 22/10 (tạm tắt edu thay vì đổi cổng); vẫn vô dụng khi Docker chết |
| (d) Docker Desktop tự bật cùng Windows + container `restart: unless-stopped` | Chặn cả hai kiểu hỏng | Đổi cài đặt Docker (chủ dự án tự làm); vẫn tranh cổng với edu; Docker từng sập vì socket cũ (29/09) |

**Q2 — Đặt Agent Eval ở đâu**

| Cách | Ưu | Nhược |
|---|---|---|
| (i) Theo quy ước: code `backend/scripts/agent_eval.py`, bài `data/benchmarks/agent_eval/`, kết quả `data/evaluation/results/agent_eval/<run_id>/` | Không thêm nhà, không thêm gốc import; gitignore có sẵn; M2 không phải chờ 1b | Eval rải ba nơi như các eval cũ |
| (ii) `evals/` mới ở gốc | Một chỗ cho mọi thứ của eval | Nhà thứ tư; cần 1b xong trước; phải thêm luật gitignore; nên dồn eval cũ về đó thành một mốc riêng |

**Q3 — Nhiệt độ khi đo**

| Cách | Ưu | Nhược |
|---|---|---|
| (a) 0.4 như chạy thật | Đo đúng thứ người dùng thấy | Dao động lớn, cần nhiều lượt hơn |
| (b) 0 + nối seed cho chat | Dao động nhỏ | Đo cấu hình không ship; phải sửa router |
| (c) So trước/sau ở (b), kiểm thực tế một lượt ở (a) | Có cả hai | Gấp đôi thời gian GPU |

**Q4 — Dữ liệu cho 20 bài tài liệu**

| Cách | Ưu | Nhược |
|---|---|---|
| (a) Đoạn trích viết tay | Đơn giản | Không giống truy xuất thật |
| (b) Ghi lại kết quả truy xuất thật trên corpus lab một lần, rồi phát lại | Giống thật, ổn định giữa các lần | Cần stack lúc ghi; phải ghi lại khi đổi retrieval |
| (c) Truy xuất thật mỗi lần | Đo cả đường truy xuất | Lẫn lỗi truy xuất với lỗi agent; cần full stack |

## Chưa kiểm

- `/health` treo khi phụ thuộc tắt: suy từ code, chưa tái hiện.
- Launcher sau `pip install -e .` trên Windows: chưa chạy.
- Dashboard không thấy bot do panel bật: suy từ code.
