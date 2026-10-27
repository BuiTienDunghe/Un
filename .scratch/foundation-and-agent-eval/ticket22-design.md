# Ticket 22 — thiết kế tách mềm Discord (fable 5.1, 28/10/2026, đọc trên main 3c6e512)

Chỉ thiết kế, chỉ đọc. Mọi số đo bằng `grep`/`wc` trên `backend/app` lúc 02:30 ngày 28/10; mọi chỗ ghi
"ý tôi" là ý kiến, chủ dự án chọn.

## Bản chất

Hôm nay một phần ba code của backend là Discord, và phần đó được khâu vào lõi ở bốn chỗ: file khởi động
dựng mọi dịch vụ Discord bằng tay, vòng lặp agent biết sẵn công cụ "đọc lịch sử Discord", bộ kiểm câu trả
lời mượn hai hàm tiện ích nằm nhầm trong file Discord, và bảng cơ sở dữ liệu của Discord nằm chung file với
bảng của lõi. Tách mềm nghĩa là: vẫn một repo, một cơ sở dữ liệu, không đổi bảng; chỉ dời code Discord vào
một thư mục riêng, và đổi bốn mối khâu thành một ổ cắm — lõi mở sẵn chỗ để cắm (sổ đăng ký công cụ, danh
sách router, một hàm khởi động), Discord tự cắm vào lúc bật máy. Thước đo thành công: xoá thư mục Discord
đi thì lõi vẫn import được và chạy được (web, RAG, tài liệu), còn test và Agent Eval thì trùng như cũ.

## Số đo hiện trạng

| Đo | Số | Cách đo |
|---|---|---|
| `backend/app` | 126 file, 23 375 dòng | `find`/`wc` |
| File tên `discord_*` | 21 file, 7 336 dòng (31%) | `wc app/*/discord_*.py` |
| Thuộc Discord nhưng không mang tên | `routers/memory_review.py` 74, `routers/condensations.py` 60, `workers/memory_tasks.py` 145, `stores/member_redaction.py` 140, `routers/bot.py` 36 + `services/bot_control_service.py`; `schemas/dashboard_schema.py` 2 lớp | đọc import của từng file |
| Script Discord | `scripts/forget_member.py` 420, `benchmark_discord_memory_extractor.py` 524, `recover_discord_memory_jobs.py` 30 | |
| **Lõi import Discord** (cạnh thật) | 4 file: `main.py` (7 dòng import, ~60 dòng nối dây), `postgres/models.py:12` (hằng số), `services/agent_service.py:21` (`history_hit_payload`), `services/answer_grounding.py:28-29` (`STOPWORDS`, `fold`) | `grep "from app\.\S*discord"` trừ file Discord |
| Lõi nhắc Discord mà không import | `settings.py` 25 trường `discord_*`; `jobs/routing.py` 1 tuyến job (chuỗi đường dẫn); `dashboard_service.py` 3 model; `operational_service.py` 2 model + 1 mã job; `stores/postgres_auxiliary_store.py:195` 1 model; `chat_service.py` chuỗi `"discord"`; `model_registry.py` tên biến env | `grep -i discord` |
| Discord import lõi (chiều cho phép) | `postgres.models` ×9, `security.api_key` ×2, `utils.vi_tokenizer`, `services.memory_service`, `services.chat_service`, `jobs.routing`, `jobs.retry` | |
| `postgres/models.py` | 1 310 dòng; model Discord ở dòng 322–1011 (từ `class DiscordConversationSession` tới trước `class Message`) = 690 dòng (53%), 10 bảng; import `discord_memory_constants` (138 dòng) ở đầu file | |
| Migration | 12 / 36 file đụng bảng `discord_*`; Alembic `env.py:8` lấy `Base.metadata` từ `app.postgres.models` | |
| Importer ngoài `app/` | `backend/tests` 21 file / 50 dòng import; `backend/scripts` 6 file / 15 dòng; `tools/`, `training/`, `tests/` gốc: 0; `discord_bot/` không import `app` | |
| Registry công cụ (ticket 20 #1 (1), 3d5927a) | `REGISTRY` là dict cấp module trong `agent_service.py`; `AGENT_TOOLS`/`TOOL_NAMES`/`_DECLARED` tính một lần lúc import; handler là method của `AgentService` | đọc diff |

Ba điều rút ra từ bảng: (1) mối khâu thật chỉ có 4 file, phần còn lại là "biết tên" qua model và chuỗi;
(2) phần nặng nhất về dòng (model, 663 dòng) lại là phần không được đụng theo phạm vi ticket (không
migration); (3) registry của ticket 20 chưa cắm được từ ngoài — ba lý do ở câu 2.

## Câu 1 — ranh giới file

Nguyên tắc chia: **cái gì chỉ tồn tại vì có Discord thì sang gói; cái gì lõi vẫn cần khi không có Discord
thì ở lại**. Hạ tầng dùng chung (job queue, outbox, retry, worker tài liệu) ở lại dù Discord dùng nó.

| Nhóm | Đi đâu | Vì sao |
|---|---|---|
| `services/discord_*.py` (16 file) | `app/discord/` | chỉ Discord dùng |
| `postgres/discord_repositories.py`, `discord_memory_repositories.py`, `discord_memory_job_repository.py` | `app/discord/` | chỉ Discord dùng |
| `postgres/discord_memory_constants.py` | **ở lại lõi** (câu 3) | `models.py` import nó; model ở lại thì hằng số ở lại |
| `routers/discord_history.py`, `discord_sessions.py`, `memory_review.py`, `condensations.py` | `app/discord/` | router của phiên, lịch sử, duyệt ký ức, rút gọn — toàn Discord |
| `routers/bot.py` + `services/bot_control_service.py` | `app/discord/` (ý tôi) | bật/tắt tiến trình bot Discord từ dashboard; không có Discord thì không có gì để bật. Cách khác: coi là "vận hành" và để lại lõi — tốn 1 import hook thêm cho dashboard |
| `schemas/discord_*.py`; `DiscordSessionSummary`, `DiscordAgentStats` trong `dashboard_schema.py` | `app/discord/` | hình dạng dữ liệu Discord |
| `workers/memory_tasks.py` | `app/discord/` | task RQ nạp ký ức Discord; `jobs/routing.py` giữ **chuỗi** đường dẫn task (không import) hoặc để gói đăng ký tuyến lúc khởi động — xem "ổ cắm" |
| `stores/member_redaction.py`, `scripts/forget_member.py`, `recover_discord_memory_jobs.py`, `benchmark_discord_memory_extractor.py` | `app/discord/` (script giữ chỗ cũ, đổi import) | ngữ nghĩa Discord (author_id, mục `search_history`) |
| `search_history` của agent: `SEARCH_HISTORY_SCHEMA`, `_search_history`, `_history_item`, `HISTORY_MESSAGE_MAX_CHARS`, `HistoryBackend` | `app/discord/agent_tools.py` | công cụ Discord, lõi không biết |
| `STOPWORDS`, `fold` (`discord_memory_guard.py:1-40`) | **về lõi** `app/utils/vi_text.py` | `answer_grounding.py` của lõi đang mượn |
| `job_queue_service`, `outbox_dispatcher_service`, `jobs/retry`, `jobs/routing`, `workers/tasks.py` | ở lại | hạ tầng chung, tài liệu dùng |
| `memory_service`, `routers/memory.py`, `schemas/memory_schema` | ở lại | trí nhớ web (câu 5) |
| `chat_service`, `agent_service` (vòng lặp, ngân sách, registry), `answer_grounding` | ở lại | lõi |
| `settings.py` 25 trường `discord_*` | ở lại **lần này** | tách Settings là việc khác, không đổi hành vi; ghi là nợ |
| `dashboard_service`, `operational_service`, `postgres_auxiliary_store` đọc model Discord | ở lại, giữ nguyên | import từ `app.postgres.models` (lõi), không vi phạm luật; là phần "mềm" của tách mềm — xem câu 3 (B) nếu muốn cứng |

Tên gói: `app/discord/`. Lưu ý một rủi ro nhỏ: bot dùng thư viện `discord` (pip); trong `app/` mọi import
đều tuyệt đối (`app.discord`) nên không đụng nhau, nhưng một script chạy với `cwd=backend/app` thì `import
discord` sẽ lấy nhầm gói. Không script nào làm vậy hôm nay; ghi một dòng trong README của gói.

**Ổ cắm** lõi mở ra (mỗi thứ một hàm, không có cái nào biết tên Discord):

| Ổ cắm | Ở đâu | Discord cắm gì |
|---|---|---|
| `ToolRegistry.register(tool, order=)` | `agent_service.py` | `search_history` (sau này `read_messages_around`) với backend riêng |
| `app.include_router` | `main.py` gọi `discord.register(app, settings, sessions)` một lần | 4 router |
| `jobs/routing.py` giữ **chuỗi** `job_type` + `task_path` (trỏ vào `app.discord.workers…`), không có `register_route` trong ticket này | `jobs/routing.py` | không cắm gì; lý do: `operational_service.py:28` (lõi) import `DISCORD_MEMORY_INGEST_JOB_TYPE` từ `jobs.routing` — đem hằng số đó sang gói là lõi phải import gói, vi phạm đúng luật duy nhất của ticket. Ghi là nợ "biết tên", cùng loại với settings |
| `app.state.*` | do `register()` đặt | `discord_turn_service`, `discord_history_service`, … |

Hai thứ lõi vẫn gọi tên Discord sau ticket này, ghi rõ là **nợ**: 25 trường settings, và ba dịch vụ lõi
đọc bảng Discord để hiện số trên dashboard/health.

## Câu 2 — thứ tự commit, không đụng ticket 20

Ticket 20 (Nhân viên 1) đang sửa `agent_service.py` (bước (2) handle, (3) read_document, rồi #2–#4) và
vài dòng cấu hình trong `main.py`/`agent_eval.py`. Ticket 22 chỉ có **một** commit cần đụng
`agent_service.py`; mọi commit khác tránh file đó.

| # | Commit | File đụng | Lùi được? | Kiểm |
|---|---|---|---|---|
| C1 | `STOPWORDS`, `fold` sang `app/utils/vi_text.py`; `answer_grounding` và `discord_memory_guard` import từ đó (guard re-export tên cũ) | 3 file, ~40 dòng | có | test grounding + guard xanh |
| C2 | `git mv` toàn bộ nhóm "sang gói" ở câu 1 vào `app/discord/`; sửa ~65 dòng import ở test/script **và 2 dòng ở `scripts/agent_eval.py:45-46`** (file này ticket 20 cũng đang sửa phần cấu hình — hunk khác vùng, nhưng gộp C2 lúc 20 không có commit treo trên nó); `main.py` chỉ đổi 8 dòng import (15, 39–46). **Giữ một shim** `app/services/discord_history_service.py` re-export (câu 4) để `agent_service.py:21` không phải đổi | ~27 file dời, ~72 dòng import | có (git mv ngược) | cả bộ test; `alembic check` (model không dời) |
| C3 | `app/discord/__init__.py::register(app, settings, sessions, *, admin_guard, read_guard)` gom `main.py:122-165, 264, 322-323` + include `memory_review`, `condensations`, `bot`; `main.py` còn một dòng `discord.register(...)`, đặt **cuối cùng** trong lifespan (sau khi `app.state.chat_service` và `app.state.agent_service` đã dựng — hôm nay khối Discord ở 122–165 đứng TRƯỚC agent ở ~265, nên phải dời xuống). Phần `history_service=` cho `AgentService` tạm GIỮ trong `register()` (đặt `app.state.agent_service.history_service`), vì C4 chưa có | `main.py` −60/+2, gói +70 | có | bộ test; smoke `/health`, `/dashboard` |
| C4 | **Sau khi ticket 20 bước (3) gộp**, do Nhân viên 1 làm (họ đang giữ file): registry cắm được + dời `search_history` sang `app/discord/agent_tools.py`; bỏ tham số `history_service` của `AgentService`; `register()` của C3 đổi sang `registry.register(...)`; `agent_eval.py` đăng ký fixture history qua gói; xoá shim | `agent_service.py` ~120 dòng, `agent_eval.py` ~10, gói +60 | có | 7 file test agent; **Agent Eval lạnh trùng 40/40 so với mốc đo cùng buổi trên đúng `main` ngay trước C4** (một lần A lạnh trên merge-base, rồi một lần trên C4; `tools_sha256` của hai manifest phải bằng nhau — giá trị cụ thể lúc đó sẽ khác `872acc92…` vì bước (2)–(3) của 20 đã thêm công cụ; so từng bài chỉ tới chỗ khác đầu tiên) |
| C5 | Test tĩnh: AST mọi module `app/**` trừ `app/discord/**` và `main.py` không import `app.discord`; và test "lõi import được khi không có gói" bằng `__import__` chặn (mẫu `test_postgres_runtime_guard.py:21`) trên danh sách module lõi | 1 file test | có | tự nó |
| C6 | Docs (`current_architecture.md`, README gói), CHANGELOG, xoá allowlist shim khỏi C5 | docs | có | — |

C1, C2, C3, C5 làm được **ngay**, song song với ticket 20, vì không đụng `agent_service.py` (C2 đụng đúng
0 dòng của nó nhờ shim; C3 đụng `main.py` ở vùng 122–165/264 còn ticket 20 đụng vùng 265–275 — hai hunk
kề nhau, nên C3 nên gộp **trước** bước (2) của 20 hoặc ngay sau, tránh cùng lúc). C4 là điểm hẹn duy nhất.

Hình dạng registry cho C4 (đề xuất, Nhân viên 1 quyết chi tiết khi code):
- Một object `ToolRegistry` với `register(tool, order: int)`, `schemas()`, `names()`, `declared()` tính
  mỗi lần gọi (hoặc cache vô hiệu khi register). Lý do: ba thứ `AGENT_TOOLS`/`TOOL_NAMES`/`_DECLARED`
  đang tính lúc import nên đăng ký muộn không thấy.
- **Một** registry mặc định cấp module `DEFAULT_REGISTRY` (lõi đăng ký hai công cụ của mình vào đó lúc
  import); `AgentService(registry=DEFAULT_REGISTRY)`; `register()` của gói Discord đăng ký vào
  `app.state.agent_service.registry` lúc khởi động; `agent_eval.py` dựng registry riêng cho mỗi lần chạy
  (lõi + fixture history). Không có lớp bí danh nào tính lúc import nữa.
- Hệ quả bắt buộc, kẻo phép đo hỏng mà không ai thấy: `tools_sha256` trong manifest của `agent_eval`, bảng
  `_DECLARED` cho `arguments_shape`, và cờ `tool_declared` (ticket 16) đều phải đọc từ **registry của
  instance sau khi đã đăng ký**, không từ một hằng cấp module chụp lúc import — nếu không manifest sẽ
  thiếu `search_history` mà không báo, và mốc so sánh vô nghĩa. Việc cho Nhân viên 1 trong C4: liệt kê
  12 importer hiện có của `AGENT_TOOLS`/`TOOL_NAMES`, chia "đọc lúc import" / "đọc lúc gọi", chuyển hết
  sang đọc lúc gọi.
- Giữ chữ ký handler của 3d5927a `(service, arguments, tool_context) -> ToolOutput`; handler Discord là
  method của một object giữ `history_service`, nên không cần thuộc tính Discord trên `AgentService`.
- `order`: lõi 10 (`search_documents`), 30 (`system_status`); Discord đăng ký 20 → thứ tự model thấy
  **y hệt** trước C4 → `tools_sha256` không đổi → phép kiểm "Agent Eval lạnh trùng" còn giá trị.

**D2 (chỉ khai báo công cụ Discord khi `tool_context` có guild) KHÔNG nằm trong C4.** Nó đổi prompt của
mọi bài web (33/40 bài Agent Eval mất một công cụ trong danh sách), nên không còn trùng 40/40 được, và
hist-08..10 (bài web hỏi về Discord, chấm "phải nói không xem được") đổi hành vi. Nói thẳng: mục 3 của
phạm vi ticket ("chỉ khai báo khi có guild") và mục 6 ("hành vi không đổi, Agent Eval lạnh trùng") **không
cùng đúng được trong một commit** — chủ dự án đang chọn giữa hai mục của chính ticket, không phải giữa tôi
và ticket. Làm D2 thành commit riêng, đo bằng v0.3 có đăng ký trước. Hai cách: D1 giữ (không đổi gì, hash
bằng) / D2 (đúng ý "lõi không biết Discord" hơn, nhưng là thay đổi hành vi phải đo). Ý tôi: D1 trong 22,
D2 đo cùng v0.3 của ticket 20.

## Câu 3 — model Discord ở đâu (Alembic)

| | (A) Ở lại `postgres/models.py`, một metadata | (B) Sang `app/discord/models.py`, cùng `Base` |
|---|---|---|
| Alembic | không đổi; `env.py` giữ `Base.metadata` | `env.py` phải `import app.discord.models` để metadata đủ; quên là `alembic check`/autogenerate thấy 10 bảng "thừa" |
| Luật "lõi không import Discord" | giữ được tuyệt đối (hằng số 138 dòng ở lại lõi) | `env.py` cần một ngoại lệ ghi tên; `dashboard_service`, `operational_service`, `postgres_auxiliary_store:195` phải thôi import model Discord → cần 3 hook (stats provider, health provider, bộ lọc hội thoại) |
| Khoá ngoại chéo (`discord_sessions.backend_conversation_id` → `conversations`, …) | như nay | vẫn chạy nếu cùng `Base` và import trước khi dùng; thêm một test khẳng định `Base.metadata.tables` đủ 10 bảng |
| Dòng còn lại trong `models.py` | 1 310 | 620 |
| Rủi ro | 0 | trung bình: lỗi import thứ tự chỉ lộ khi chạy migration/dashboard |
| Công | 0 | ~1 ngày: dời 663 dòng + 3 hook + test |
| Khớp phạm vi ticket ("không đổi bảng, không migration — chỉ dời code") | có | có về bảng, nhưng vượt "chỉ dời code" vì phải thêm hook |

Ý tôi: **(A) trong ticket 22**, ghi (B) là bước sau có điều kiện: làm khi dashboard/health có cơ chế
"provider" sẵn (ticket khác cần nó), lúc đó (B) chỉ còn là dời file. Lý do chính: (A) là cách duy nhất
giữ "hành vi không đổi, test trùng" mà không chạm Alembic, và phần lõi "biết tên bảng Discord" là đúng
nghĩa của chữ *mềm* chủ dự án chọn.

## Câu 4 — lớp re-export tạm

Số liệu: 21 file test (50 dòng import), 6 script (15 dòng), 0 ở `tools/`, `training/`, test gốc, bot.
Tức là mọi importer đều trong repo, sửa được trong một commit; không có người dùng ngoài.

| | (i) Không shim, sửa hết trong C2 | (ii) Shim mọi đường cũ (~20 file một dòng) | (iii) Shim đúng một file đang bị lõi cần |
|---|---|---|---|
| Xung đột với ticket 20 | C2 phải sửa `agent_service.py:21` → đụng file NV1 đang sửa | không | không |
| Test tĩnh C5 | sạch | phải allowlist 20 shim (chúng là lõi import Discord) | allowlist 1 file, có ngày hết hạn |
| Dọn | không cần | C6 xoá 20 file | C6 xoá 1 file |
| Rủi ro quên dọn | — | cao | thấp |

Ý tôi: **(iii)** — shim duy nhất `app/services/discord_history_service.py` (`from app.discord.history_service
import *` + `__all__`), tồn tại từ C2 tới C4; mọi test/script sửa import ngay ở C2.

## Câu 5 — ranh giới với trí nhớ web (R7)

| | Trí nhớ web (lõi) | Trí nhớ Discord (gói) |
|---|---|---|
| Bảng / kho | `memories` (`Memory`, `models.py:1034`) + Qdrant `memories` | `discord_memories`, `discord_memory_candidates`, `discord_memory_sources`, `discord_memory_jobs`… (10 bảng, cùng Base) |
| Code | `memory_service.py`, `routers/memory.py`, `schemas/memory_schema.py` | extractor, verifier, rule_filter, guard, review_service, worker_service, `memory_tasks.py`, `routers/memory_review.py` |
| Chiều gọi | **không gọi** gì của Discord | gọi lõi qua đúng hai hàm: `MemoryService.upsert_with_id("mem_dc_<uuid>", …)` và `remove_with_id` (`discord_memory_review_service.py:244-307`) |
| Hợp đồng | id `mem_dc_*` chỉ là một id như mọi id khác; lõi không được suy diễn gì từ tiền tố (hôm nay chỉ có một chú thích ở `memory_service.py:37`, giữ) | một ký ức Discord đã duyệt được **chiếu** sang trí nhớ web dưới id `mem_dc_`; duyệt lại/thu hồi thì gói tự gỡ ảnh chiếu |
| Xoá theo người (`forget_member`) | lõi không biết | gói xoá bảng của mình rồi gỡ vector `mem_dc_` qua `QdrantStore` của lõi (ticket 17/19) |
| Ngoại lệ "mềm" | `dashboard_service`/`operational_service` đếm bảng ký ức Discord để hiện số | — |

Test giữ ranh giới: thêm vào C5 một khẳng định `memory_service.py` không import `app.discord` (đã nằm trong
AST test) và một test hợp đồng: `upsert_with_id` với id tuỳ ý rồi `remove_with_id` — không có nhánh nào
đọc tiền tố.

## Nghiệm thu đề nghị (khớp mục 5–6 của ticket)

| Kiểm | Khi nào |
|---|---|
| AST: không module lõi nào import `app.discord` (trừ `main.py` và shim có hạn) | C5, mỗi lần CI |
| Lõi import được khi `app.discord` bị chặn (`__import__` guard) cho `agent_service`, `chat_service`, `rag_service`, `memory_service`, `answer_grounding` | C5 |
| Bộ test backend + gốc xanh, `alembic check` không lệch | mỗi commit |
| Agent Eval lạnh trùng từng bài với mốc đo cùng buổi trên `main` ngay trước C4; `tools_sha256` của hai manifest bằng nhau | sau C4 (gỡ model trước mỗi lần đo, so từng bài tới chỗ khác đầu tiên; bộ bài là v0.3 nếu 20 đã gộp) |
| Eval đêm xanh | đêm sau C3 và sau C4 |

## Chỗ có lựa chọn thật (để opus hỏi chủ dự án)

1. `routers/bot.py` + `bot_control_service` sang gói hay ở lại "vận hành" — ý tôi: sang gói.
2. Model Discord: (A) ở lại / (B) sang gói — ý tôi: (A) lần này.
3. Shim: (iii) một file — ý tôi: (iii).
4. D2 (chỉ khai báo công cụ Discord khi có guild): làm trong 22 hay đo riêng với v0.3 — ý tôi: đo riêng.
5. Ai làm C4: Nhân viên 1 ngay sau bước (3) của 20, hay người khác chờ 20 xong hẳn — ý tôi: Nhân viên 1,
   vì cùng file, cùng tuần.
