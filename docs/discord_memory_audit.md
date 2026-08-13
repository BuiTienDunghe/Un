# Discord Memory Sprint 0 Audit — Workflow V5

Ngày audit: 2026-07-24
Repository: `C:\Users\dungbt06\Ún promax\local-ai-core`
Git revision được audit: `d18c73221c1e8490a4e9fb32060526221c2ee4ee` (`main`)
Tài liệu đối chiếu: `discord_memory_workflow_plan_v5_final.md` (đã đọc toàn bộ 1.855 dòng)

## 1. Phạm vi, phương pháp và kết luận ngắn

Audit này chỉ thực hiện Sprint 0. Không có migration nào được tạo/chạy, không sửa runtime, không thay đổi database, không chạy Docker, không tải model và không bắt đầu Sprint 1.

Bằng chứng được lấy từ:

- source, config, Alembic migration và test trong repository;
- `alembic heads` và `alembic current` ở chế độ chỉ đọc;
- SQLAlchemy Inspector chỉ đọc metadata của năm bảng liên quan, không đọc nội dung row;
- test hiện có không gọi model thật và không dùng database runtime để ghi dữ liệu.

Kết luận:

- Bot hiện tại là **per-user trong từng Discord channel object**, không phải per-channel/per-thread dùng chung.
- Mapping từ Discord sang backend conversation nằm **chỉ trong RAM của tiến trình bot**.
- PostgreSQL đã lưu backend conversation/history, nhưng không có metadata Discord để tìm lại mapping sau restart.
- Discord hiện **không bật `use_memory`**. Web UI có thể bật một memory store toàn cục dùng chung bảng `memories` và Qdrant collection `memories`.
- Nền tảng PostgreSQL, RQ, lease/heartbeat và outbox hiện có là nền móng tái sử dụng được, nhưng implementation đang khóa khá chặt vào document ingestion và chưa thể cắm Discord job vào nguyên trạng.
- Không thể backfill đáng tin cậy các conversation Discord hiện tại sang session mới vì database không lưu guild/channel/user/source và backend conversation ID là UUID ngẫu nhiên, không mang dấu vết Discord.
- Các blocker kiến trúc về canonical channel/thread key, legacy cutover, backend ownership, DM/private thread, Web UI isolation và concurrent shared-session chat đã được chốt tại các mục 8–13.
- **Chưa được bắt đầu migration Sprint 1** cho tới khi `POSTGRES_TEST_URL` cô lập và recovery point trước migration ở các mục 14–15 được chuẩn bị, kiểm chứng.

## 2. Kiến trúc hiện tại

```text
Discord gateway
  discord_bot.main
    ├─ /ask
    └─ on_message: chỉ message mention bot
          │
          ├─ key RAM = SHA256(guild_id, current_channel_id, user_id)
          └─ dict[key] = backend conversation_id
                    │
                    ▼
              POST /chat
                    │
                    ▼
             ChatService.respond
          ├─ conversations/messages: PostgreSQL
          ├─ optional use_memory: false từ Discord
          └─ Ollama general model

Web UI
  ├─ POST /chat, use_memory theo checkbox
  └─ /memory CRUD/search
          ├─ memories: PostgreSQL
          └─ memories collection: Qdrant

Document async pipeline
  PostgreSQL jobs + outbox_events
      → outbox dispatcher
      → Redis/RQ queues ocr/index
      → worker lease/heartbeat/retry
      → PostgreSQL + Qdrant documents collection
```

FastAPI được compose tại `backend/app/main.py:32-84`. Runtime dùng `PostgresAuxiliaryStore` cho conversations, messages và memories (`backend/app/main.py:37-52`). PostgreSQL là bắt buộc và URL SQLite bị từ chối (`backend/app/config/settings.py:39-47`).

## 3. Audit Discord bot

### 3.1. Entrypoint và cách khởi động

| Thành phần | Bằng chứng | Hành vi xác nhận |
|---|---|---|
| Python entrypoint | `discord_bot/main.py:153-170` | `main()` gọi `asyncio.run(run())`; `run()` đọc settings, tạo API client/bot và gọi `bot.start(token)`. |
| Compose service | `docker-compose.yml:79-95` | Profile `discord`, command `python -m discord_bot.main`; system prompt được mount read-only. |
| Windows launcher | `run-discord-bot.bat:5-44` | Kiểm tra Docker, `.env`, token và backend health, sau đó chạy foreground bằng `docker compose --profile discord up --build discord-bot`. |
| Discord settings | `discord_bot/main.py:21-46` | Token, client ID, invite URL, backend URL/credentials, prompt path và member context limit lấy từ environment. |
| Intents | `discord_bot/client.py:28-39` | Bật default intents, `message_content=True`, `members=True`; command tree sync trong `setup_hook()`. |

Không có secret Discord hard-code trong các file bot được theo dõi. `.env` bị ignore bởi `.gitignore:33-36`. Audit không sao chép giá trị từ `.env`.

### 3.2. Conversation model và conversation key

Hàm `conversation_key()` ở `discord_bot/main.py:68-70` tạo:

```text
raw = "discord:{guild_id hoặc 0}:{channel_id}:{user_id}"
key = "discord_" + 48 ký tự đầu của SHA-256(raw)
```

Điểm quan trọng:

- Key này chỉ là key của dictionary trong bot; nó **không** được gửi làm backend `conversation_id` ở request đầu tiên.
- Request đầu tiên không có `conversation_id`; backend tự tạo UUID text và trả về.
- Dictionary `conversations: dict[str, str]` được tạo bên trong `create_bot()` (`discord_bot/main.py:73-76`), nên lifetime của mapping bằng lifetime tiến trình.
- `guild_id`, `channel_id` và `user_id` đều tham gia key. Vì vậy hai user trong cùng channel có hai conversation khác nhau.
- Slash `/ask` và mention của cùng user trong cùng current channel dùng cùng logic `ask_backend()` và do đó dùng chung mapping.

Phân loại hiện tại:

| Trục | Hiện trạng |
|---|---|
| Per-user | Có. `user_id` là một phần key. |
| Per-channel | Có phân vùng theo current `channel_id`, nhưng không chia sẻ giữa user. |
| Per-guild | Có phân vùng theo `guild_id`; DM dùng giá trị `0`. |
| Per-thread | Không có field riêng. Bot chỉ chuyển `message.channel.id`/`interaction.channel_id`. |
| Persistence | Không. Dictionary RAM duy nhất. |
| Redis | Không dùng cho mapping Discord. |
| PostgreSQL | Chỉ backend conversation/history nằm ở PostgreSQL; không có Discord mapping. |

Test hiện tại chỉ chứng minh key ổn định với cùng input (`tests/test_discord_api_client.py:96-105`); chưa test phân tách/chia sẻ giữa user, channel, guild và thread.

### 3.3. Luồng message hiện tại

#### Slash `/ask`

`discord_bot/main.py:110-127`:

1. Nhận `question`.
2. Từ chối nếu dài hơn 10.000 ký tự.
3. Defer interaction.
4. Gọi `ask_backend(question, interaction.guild, interaction.channel_id, interaction.user.id)`.
5. Gửi answer, chia chunk tối đa 1.900 ký tự qua `split_for_discord()` (`discord_bot/client.py:6-25`).

#### Mention

`discord_bot/main.py:129-148`:

1. Bỏ qua nếu author là bot.
2. Bỏ qua nếu message không mention bot theo `bot.user.mentioned_in(message)`.
3. Xóa hai dạng mention `<@id>` và `<@!id>` khỏi content.
4. Nếu không còn question, trả hướng dẫn.
5. Gọi backend với `message.guild`, `message.channel.id`, `message.author.id`.
6. Trả lời bằng `message.reply(..., mention_author=False)` cho chunk đầu.

Bot không đọc mọi message vào chat path. Hai trigger duy nhất được đăng ký là:

- application command `/ask`;
- message có mention bot.

Ngoài ra có `/ping` (`discord_bot/main.py:106-108`). Không có prefix command và không có `/memory ...`.

### 3.4. Channel, thread, forum post và DM

Source không có bước normalize hoặc validate Discord location/channel type.

| Loại | Điều source thực sự làm | Khoảng trống |
|---|---|---|
| Text/announcement | Dùng current channel ID làm một thành phần key. | Không kiểm tra type, guild/channel enable flag hoặc retention policy. |
| Thread | Không đọc `parent_id`, không tạo `thread_id`; current thread ID chỉ đi vào tham số tên `channel_id`. | Không thể biểu diễn đồng thời parent channel và thread theo V5. |
| Forum post | Không có nhánh forum. | Không có bằng chứng source/test rằng forum post được normalize như thread. |
| Private thread | Không có policy/permission gate riêng. | Có nguy cơ lưu hoặc retrieve sai phạm vi khi memory được bổ sung. |
| Voice | Không có channel-type gate. | Source không có transcript ingestion; hành vi slash/mention trong voice-related context chưa được test. |
| DM | `guild_context(None, ...)` tạo câu mô tả DM (`discord_bot/main.py:59-65`); conversation key dùng guild `0`. | Không có guard tắt DM memory/chat. Mention handler vẫn phụ thuộc `mentioned_in`; slash không có `guild_only`. Hành vi thực tế trên Discord chưa có test. |

Vì source chỉ truyền current object ID, việc một thread/forum post tình cờ có ID riêng không tương đương với model `guild_id + parent channel_id + thread_id` của V5.

### 3.5. Author, display name, reply, edit và delete

| Metadata/hành vi | Hiện trạng |
|---|---|
| `author_id` | Chỉ dùng để tạo key RAM; không gửi vào `/chat`, không lưu trong backend message. |
| `author_display_name` | Không gửi/lưu theo message. `guild_context()` chỉ gửi danh sách display name của tối đa N non-bot member trong system prompt. |
| Inbound reply | Không đọc `message.reference`, `resolved` hoặc `reply_to_message_id`. |
| Outbound reply | Mention response reply vào message gốc; đây là presentation behavior, không được lưu như relation. |
| Edit | Không đăng ký `on_message_edit`/`on_raw_message_edit`; không cập nhật record. |
| Delete | Không đăng ký `on_message_delete`/`on_raw_message_delete`; không soft-delete record. |
| Discord message ID | Không gửi/lưu. |
| Bot/system flag | Chỉ bỏ qua `message.author.bot`; không lưu `is_bot`, không có xử lý system message riêng. |
| Attachment | Không đọc/lưu. |

Backend hiện chỉ lưu role `user`/`assistant`, content, model và thời gian. Vì vậy model không biết user Discord nào đã nói từng câu.

### 3.6. Restart, backend conversation mất và concurrency

Restart:

- Dictionary bị mất hoàn toàn khi tiến trình kết thúc.
- Tin nhắn kế tiếp không tìm được old backend ID, nên `/chat` tạo conversation mới.
- Backend conversation cũ và messages vẫn còn PostgreSQL nhưng không có metadata để bot tìm lại.
- README xác nhận giới hạn này tại `README.md:121-123`.

Backend conversation mất:

- `LocalAgentClient` nhận HTTP 404 với top-level `error_code=CONVERSATION_NOT_FOUND` và raise `BackendConversationNotFoundError` (`discord_bot/api_client.py:62-89`).
- `ask_backend()` xóa đúng mapping RAM, retry một lần không có ID, rồi lưu ID mới (`discord_bot/main.py:89-100`).
- Đây là recovery hữu ích nhưng không đánh dấu session cũ `orphaned`, không giữ summary và không có audit event vì chưa có persistent Discord session.

Concurrency:

- Không có lock theo conversation key trong bot.
- Hai message đồng thời cho cùng key có thể cùng thấy mapping rỗng, tạo hai backend conversation và để response hoàn thành sau ghi đè mapping của response hoàn thành trước.
- `ChatService` cũng không serialize theo conversation. Hai request có thể đọc cùng history snapshot rồi ghi xen kẽ.
- Conversation, user message và assistant message không được ghi trong một transaction chung; mỗi `add_message()` mở transaction riêng (`backend/app/stores/postgres_auxiliary_store.py:45-51`).

Đây là rủi ro mất nhánh history của runtime hiện tại. Target architecture đã chốt FIFO từng session; Sprint 1 tối thiểu phải loại authoritative RAM mapping, chặn duplicate active session và test concurrent resolve. Durable turn worker có thể được hoàn thiện sau persistent foundation.

## 4. Audit backend

### 4.1. PostgreSQL schema đã xác minh

Alembic source head và database configured hiện tại đều là `20260719_11`. `alembic current` chỉ đọc đã trả `20260719_11 (head)`.

Schema dưới đây được đối chiếu giữa:

- ORM: `backend/app/postgres/models.py`;
- migration gốc: `backend/alembic/versions/20260717_01_postgres_foundation.py`, `20260717_03_redis_jobs.py`, `20260718_05_transactional_outbox.py`, `20260718_07_auxiliary_postgres_domains.py`;
- SQLAlchemy Inspector trên database configured, chỉ đọc metadata.

#### `conversations`

| Column | Kiểu/constraint |
|---|---|
| `id` | `VARCHAR(128)` PK |
| `created_at` | timezone-aware timestamp, NOT NULL, default `now()` |
| `updated_at` | timezone-aware timestamp, NOT NULL, default `now()`, index |

Không có owner, source, guild/channel/thread, status, title, retention hoặc soft-delete. ORM cố ý dùng string để giữ opaque legacy IDs (`backend/app/postgres/models.py:189-197`).

#### `messages`

| Column | Kiểu/constraint |
|---|---|
| `id` | `BIGINT` identity PK |
| `conversation_id` | `VARCHAR(128)` NOT NULL, FK `conversations.id ON DELETE CASCADE`, index |
| `role` | `VARCHAR(32)` NOT NULL |
| `content` | `TEXT` NOT NULL |
| `model_used` | `VARCHAR(255)` nullable |
| `created_at` | timezone-aware timestamp, NOT NULL, default `now()` |

Không có Discord ID, author, guild/channel/thread, reply, edit/delete timestamp, idempotency hoặc message status.

#### `memories`

| Column | Kiểu/constraint |
|---|---|
| `id` | `VARCHAR(128)` PK |
| `content` | `TEXT` NOT NULL |
| `memory_type` | `VARCHAR(64)` NOT NULL |
| `importance` | double precision NOT NULL |
| `metadata_json` | `JSONB` NOT NULL, default `{}` |
| `created_at`, `updated_at` | timezone-aware timestamps, NOT NULL |

Không có guild/member/channel scope, fact identity, status/version, confidence, valid time, expiration, source message, proposal hoặc index status. Không có unique business key hay index retrieval.

#### `jobs`

| Nhóm | Columns/constraints |
|---|---|
| Identity/type | `id VARCHAR(128)` PK, `job_type VARCHAR(64)` |
| Document links | nullable `document_id`, `version_id`, `ingestion_run_id`, đều FK `ON DELETE CASCADE` |
| Lifecycle | `status`, `priority`, `attempts`, `max_attempts`, `available_at`, `started_at`, `completed_at`, `updated_at` |
| Ownership | `worker_id`, `heartbeat_at`, `lease_expires_at` |
| Idempotency/transport | nullable unique `idempotency_key`, nullable unique `redis_job_id` |
| Error/payload | `error_code`, `error_message`, `payload JSONB` |
| Index | `(status, available_at)` |

Schema đủ generic để chứa job không gắn document vì ba FK nullable. Tuy nhiên repository, dispatcher routing và worker hiện không generic; xem mục 4.6.

#### `outbox_events`

| Nhóm | Columns/constraints |
|---|---|
| Identity/event | `id VARCHAR(128)` PK, `event_type`, `aggregate_type`, `aggregate_id` |
| Delivery | `payload JSONB`, `status`, `attempts`, `available_at`, `published_at`, `processed_at`, `last_error`, `created_at` |
| Idempotency/link | nullable unique `idempotency_key`, nullable `job_id` có index, nullable `redis_job_id` |

Database thực tế không có FK từ `outbox_events.job_id` sang `jobs.id`.

Có schema drift cần lưu ý trước khi tái sử dụng rộng:

- ORM biểu diễn `OutboxEvent.idempotency_key` và `created_at` như non-optional;
- migration/database thực tế cho phép NULL ở hai field này.

Code tạo job outbox hiện luôn điền idempotency key, nhưng database chưa enforce contract đó.

Không có bảng nào bắt đầu bằng `discord_` trong ORM/migration hiện tại.

### 4.2. Conversation API và lifecycle

| API | Implementation | Hành vi |
|---|---|---|
| `POST /chat` | `backend/app/routers/chat.py:14-45` | Tạo conversation ngầm nếu request không có ID; đọc history; gọi model; lưu user/assistant message; trả ID. |
| `GET /conversations` | `backend/app/routers/conversations.py:8-10` | List mọi conversation, gồm count. Không filter owner/source. |
| `GET /conversations/{id}` | `backend/app/routers/conversations.py:13-18` | Trả toàn bộ message của conversation. |
| `DELETE /conversations/{id}` | `backend/app/routers/conversations.py:21-24` | Hard delete conversation; FK cascade hard delete messages. |
| Explicit create | Không có endpoint. | Chỉ `ChatService` gọi `store.create_conversation()` khi `/chat` không có ID. |
| Update conversation | Không có endpoint. | `updated_at` chỉ đổi khi thêm message. |

`ChatRequest` có `conversation_id` tối đa 64 ký tự, `system_prompt`, `use_memory=false`, `stream=false` (`backend/app/schemas/chat_schema.py:4-17`). Database lại cho ID dài 128 ký tự; đây là contract mismatch hiện có, dù UUID do backend tạo vẫn vừa 64 ký tự.

`PostgresAuxiliaryStore` là repository chung cho UI/backend chat:

- `conversation_exists`, `create_conversation`;
- `add_message`, `get_messages`;
- `list_conversations`, `get_conversation`, `delete_conversation`;
- memory CRUD và các auxiliary domain khác.

### 4.3. Cleanup/retention và dangling conversation

Cleanup runtime không xóa conversation hay memory:

- `PostgresCleanupService.run_once()` chỉ chạy request log, OCR run, temporary source, superseded document version và deleting document (`backend/app/services/postgres_cleanup_service.py:29-36`).
- Service không import `Conversation`, `Message` hoặc `Memory` (`backend/app/services/postgres_cleanup_service.py:17`).
- Cleanup planner cũng chỉ plan document/version/source/log/OCR/cache domains.

Các cách được source xác nhận có thể làm bot giữ backend ID dangling:

1. `DELETE /conversations/{id}` hard delete conversation.
2. Database reset/restore hoặc thao tác ngoài repository.
3. Với stream chat mới, `ChatService.stream_response()` xóa conversation mới nếu stream không hoàn tất (`backend/app/services/chat_service.py:68-85`). Discord dùng non-stream nên không đi qua nhánh này.

Không có retention tự động cho `conversations`/`messages`. Comment trong bot nói retention “may have removed” conversation, nhưng source cleanup hiện không thực hiện điều đó.

### 4.4. System prompt và chat history vào model

`ChatService.respond()` (`backend/app/services/chat_service.py:28-49`) xây messages theo thứ tự:

```text
1. system_prompt từ request, nếu không có thì general_system.md
2. nếu use_memory=true và có kết quả:
   memory_system.md + tối đa 5 semantic memories
3. tối đa 12 message history gần nhất từ PostgreSQL
4. current user message
```

Các chi tiết đã xác minh:

- Discord gửi `discord_bot/system_prompt.md` cộng `guild_context()` làm per-request `system_prompt` (`discord_bot/main.py:77-78`, `discord_bot/api_client.py:91-99`).
- Prompt Discord định nghĩa persona Ún, ưu tiên ngôn ngữ người dùng và nhắc tôn trọng dữ liệu nhạy cảm; nó không định nghĩa structured memory, guild retrieval hay attribution.
- Per-request prompt thay thế general system prompt, không append sau general prompt.
- History limit mặc định là 12 message, không phải 12 turn (`backend/app/config/settings.py:37`).
- History chỉ có `role` và `content`; `model_used`/timestamp/author không đưa vào model.
- User message chỉ được lưu sau khi model trả lời thành công. Model failure làm current user message không được persist.
- Không có summary, token-budget context builder hoặc attribution format của V5.

### 4.5. `use_memory`, Qdrant collection và retrieval

#### Discord

`LocalAgentClient._chat_request()` chỉ gửi:

```json
{"message": "...", "stream": false}
```

và có thể thêm `conversation_id`, `system_prompt`; không gửi `use_memory` (`discord_bot/api_client.py:91-99`). Backend default là false. Vì vậy Discord chat hiện không dùng memory.

#### Web UI

Web UI có checkbox `#use-memory` (`backend/app/frontend/index.html:17`) và gửi `use_memory` vào `/chat` (`backend/app/frontend/app.js:16`). UI và memory API dùng `MemoryService`/`PostgresAuxiliaryStore`.

#### Qdrant memory contract hiện tại

`QdrantStore.memories_collection_name = "memories"` (`backend/app/stores/qdrant_store.py:25-28`).

Point ID:

```text
UUID5("local-ai-core:memory:{memory_id}")
```

Payload:

```json
{
  "memory_id": "mem_...",
  "content": "...",
  "memory_type": "...",
  "importance": 0.5
}
```

Implementation: `backend/app/stores/qdrant_store.py:122-142`.

Retrieval:

- embed query bằng configured embedding model;
- `query_points(collection="memories", limit=top_k)`;
- không có Qdrant filter;
- không verify point lại với PostgreSQL;
- không có `guild_id`, member/channel scope, `status`, `fact_key` hoặc version;
- không có exact lookup trước semantic.

Write ordering của UI memory:

- add/update upsert Qdrant trước, rồi write PostgreSQL; lỗi PostgreSQL được bù bằng delete/restore vector;
- delete Qdrant trước, rồi delete PostgreSQL; lỗi PostgreSQL được bù bằng re-upsert;
- không dùng outbox;
- không có memory reconciliation/rebuild.

`backend/scripts/rebuild_qdrant.py` chỉ rebuild collection `documents` từ active document chunks; không xử lý `memories`.

### 4.6. Redis/RQ, retry, lease, heartbeat và outbox có thể tái sử dụng

Phần có thể tái sử dụng về ý tưởng và một phần code:

- PostgreSQL là durable job state; Redis chỉ transport job ID (`backend/app/services/job_queue_service.py:8-29`).
- `jobs.idempotency_key` và deterministic Redis job ID.
- Atomic claim từ `queued/retrying` sang `running` (`PostgresDocumentRepository.start_job`, `backend/app/postgres/repositories.py:278-283`).
- Ownership, lease và heartbeat (`heartbeat`, `worker_owns_job`, `complete_owned_job`, dòng 285-307).
- Heartbeat background timer, checkpoint và lost-ownership check (`backend/app/workers/tasks.py:25-47`).
- Retry classification/backoff 10/30/90 giây (`backend/app/services/job_errors.py:7-21`).
- Stale recovery dùng expired lease/heartbeat và `FOR UPDATE SKIP LOCKED` (`backend/app/services/job_recovery_service.py:41-55`).
- Job và outbox được tạo cùng transaction trong `PostgresDocumentRepository.create_job()`/`create_job_outbox_event()` (`backend/app/postgres/repositories.py:238-270`).
- Dispatcher claim concurrent events bằng `FOR UPDATE SKIP LOCKED`, retry/failed state và update Redis mapping (`backend/app/services/outbox_dispatcher_service.py:17-50`).

Phần chưa thể tái sử dụng nguyên trạng:

- `PostgresDocumentRepository.create_job()` bắt buộc document/version/run và idempotency format document.
- `JobQueueService.enqueue()` chỉ route `extract_document` sang OCR; **mọi job type khác** đều bị route sang queue/function index (`backend/app/services/job_queue_service.py:21-22`). Thêm `memory_extract` vào hiện trạng sẽ chạy nhầm `index_document`.
- Worker module chỉ có `extract_document` và `index_document`.
- `JobRecoveryService.reconcile_queued()` chứa logic stage/version của document.
- RQ retry mặc định 10/30/90, khác yêu cầu Qdrant memory 1/3/10 của V5.
- Worker ID hiện là hostname. Nhiều worker process trên cùng host có cùng string ownership; atomic state claim giảm rủi ro duplicate start nhưng identity này chưa đủ mạnh cho ownership isolation tổng quát.
- Outbox database chưa enforce `idempotency_key NOT NULL` và không có FK `job_id`.

Kết luận tái sử dụng: giữ schema/pattern và tách routing/repository/task registry theo job type; không gọi service hiện tại với Discord job type cho tới khi đã refactor và test. Việc này thuộc sprint worker sau, không thuộc Sprint 1.

## 5. Phụ thuộc giữa Discord memory và UI memory

### 5.1. Phần đang dùng chung

Discord và UI dùng chung backend `/chat`, `ChatService`, `PostgresAuxiliaryStore`, bảng `conversations`/`messages`, model router và general chat model.

Discord **không dùng** `MemoryService` ở thời điểm audit vì không gửi `use_memory=true`. UI dùng:

- `backend/app/routers/memory.py`;
- `backend/app/services/memory_service.py`;
- memory methods trong `backend/app/stores/postgres_auxiliary_store.py`;
- bảng `memories`;
- Qdrant collection `memories`;
- checkbox/UI payload trong `backend/app/frontend/index.html` và `app.js`.

### 5.2. Phần phải tách riêng

Để không thay đổi hành vi UI:

- tạo các bảng `discord_*` riêng theo V5;
- tạo repository/service/router Discord riêng;
- tạo Qdrant collection Discord riêng, đề xuất `discord_memories`;
- mọi PostgreSQL/Qdrant query Discord bắt buộc filter guild tại tầng storage;
- không thêm guild/status semantics vào bảng `memories` cũ trong Sprint 1;
- không đổi payload/response của `/memory/*`;
- không tự động bật `use_memory` cho Discord bằng UI memory cũ;
- không đổi `ChatService` general path cho UI nếu chưa có compatibility test.

Dùng chung bảng `memories` với một discriminator trong `metadata_json` không đủ an toàn: query hiện tại không filter metadata và Qdrant search hiện không filter. Nó cũng làm dữ liệu legacy UI không có scope trở nên khó diễn giải.

### 5.3. Phần có thể tái sử dụng mà không đổi UI

- `ChatService`/`/chat` có thể tiếp tục là backend conversation execution path nếu Discord context được build riêng trước khi gọi.
- `conversations`/`messages` có thể tiếp tục lưu model history, còn Discord session/raw message nằm bảng riêng.
- `QdrantStore` pattern `_ensure_named_collection()`, retry và deterministic ID có thể được dùng bởi một Discord-specific store.
- PostgreSQL session factory, transaction pattern, job lifecycle và outbox dispatcher pattern có thể dùng chung sau khi routing được generic hóa.
- `LocalAgentClient` 404 contract, timeout/auth error mapping và Discord answer splitting có thể giữ.

## 6. Inventory file, class, function, API và bảng liên quan

### Discord

| Path | Symbol/phạm vi |
|---|---|
| `discord_bot/main.py` | `DiscordSettings`, `load_system_prompt`, `guild_context`, `conversation_key`, `create_bot`, nested `ask_backend`, `/ping`, `/ask`, `on_message`, `run`, `main` |
| `discord_bot/client.py` | `split_for_discord`, `LocalAgentDiscordBot`, intents, `setup_hook` |
| `discord_bot/api_client.py` | error classes, `LocalAgentSettings`, `BackendAnswer`, `LocalAgentClient.ask_with_conversation`, `_chat_request`, JWT retry |
| `discord_bot/system_prompt.md` | Discord persona system prompt |
| `run-discord-bot.bat` | Foreground Docker Compose launcher |
| `docker-compose.yml` | `discord-bot` service/profile |
| `tests/test_discord_api_client.py` | HTTP payload/error/splitting/key tests |

### Backend conversation/chat

| Path | Symbol/phạm vi |
|---|---|
| `backend/app/main.py` | runtime composition, router registration |
| `backend/app/routers/chat.py` | `POST /chat` |
| `backend/app/routers/conversations.py` | list/detail/delete APIs |
| `backend/app/schemas/chat_schema.py` | `ChatRequest`, `ChatResponse` |
| `backend/app/schemas/conversation_schema.py` | conversation response contracts |
| `backend/app/services/chat_service.py` | `ChatService.respond`, `stream_response`, prompt/history/memory order |
| `backend/app/stores/auxiliary_store.py` | `AuxiliaryStore` protocol |
| `backend/app/stores/postgres_auxiliary_store.py` | conversation/message/memory persistence |
| `backend/app/prompts/general_system.md` | default system prompt |
| `backend/app/prompts/memory_system.md` | UI/global memory context prompt |

### Memory/Qdrant

| Path | Symbol/phạm vi |
|---|---|
| `backend/app/routers/memory.py` | `POST /memory/add`, `POST /memory/search`, `PUT /memory/{id}`, `DELETE /memory/{id}` |
| `backend/app/schemas/memory_schema.py` | CRUD/search payloads |
| `backend/app/services/memory_service.py` | embedding, Qdrant-first CRUD, search |
| `backend/app/stores/qdrant_store.py` | collections `documents`/`memories`, memory payload/query |
| `backend/app/frontend/index.html` | Memory checkbox |
| `backend/app/frontend/app.js` | `use_memory` request flag |
| `backend/scripts/rebuild_qdrant.py` | document-only rebuild |

### PostgreSQL/worker/outbox

| Path | Symbol/phạm vi |
|---|---|
| `backend/app/postgres/models.py` | `Conversation`, `Message`, `Memory`, `Job`, `OutboxEvent` |
| `backend/app/postgres/repositories.py` | document repository, durable jobs, claims, heartbeat, outbox creation |
| `backend/app/services/job_queue_service.py` | Redis/RQ enqueue và retry |
| `backend/app/services/job_recovery_service.py` | queued reconciliation và stale recovery |
| `backend/app/services/outbox_dispatcher_service.py` | transactional outbox dispatcher |
| `backend/app/workers/tasks.py` | OCR/index task, checkpoint, heartbeat |
| `backend/app/services/job_errors.py` | retry classification/backoff |
| `backend/scripts/outbox_dispatcher.py` | dispatcher process |
| `backend/scripts/recover_stale_jobs.py` | recovery command |
| `backend/app/services/postgres_cleanup_service.py` | retention executor, không gồm conversation/memory |
| `backend/app/services/postgres_cleanup_planner.py` | read-only cleanup planning |

### Migration/bảng

| Path | Nội dung |
|---|---|
| `backend/alembic/versions/20260718_07_auxiliary_postgres_domains.py` | tạo `conversations`, `messages`, `memories` |
| `backend/alembic/versions/20260717_01_postgres_foundation.py` | tạo `jobs`, `outbox_events` ban đầu |
| `backend/alembic/versions/20260717_03_redis_jobs.py` | idempotency, Redis ID, heartbeat, lease |
| `backend/alembic/versions/20260718_05_transactional_outbox.py` | outbox idempotency/job/Redis fields |
| `backend/alembic/versions/20260718_06_cleanup_lifecycle.py` | document cleanup fields; không phải conversation cleanup |

Bảng liên quan hiện tại: `conversations`, `messages`, `memories`, `jobs`, `outbox_events`.
Bảng Workflow V5 chưa có: toàn bộ `discord_guilds`, `discord_channels`, `discord_conversation_sessions`, `discord_messages`, `discord_memories`, `discord_memory_sources`, `discord_memory_proposals`, `discord_fact_key_registry` và audit-event domain.

## 7. Gap analysis so với Workflow V5

| Workflow V5 | Đã có | Có thể tái sử dụng | Cần sửa/tạo |
|---|---|---|---|
| Guild isolation | Guild ID có trong key RAM và guild context. | Discord gateway lấy được guild. | DB/Qdrant chưa có guild scope/filter; tạo Discord tables/store riêng. |
| Shared channel/thread session | Current channel ID có trong key. | 404 recovery contract. | Implement canonical key đã chốt và persist active session. |
| Restart continuity | Backend history persist. | `conversations`/`messages`. | Persistent mapping/session API. |
| Orphan recovery | Bot retry một lần khi 404. | Error type và retry flow. | Status `orphaned`, new session, audit event, summary bootstrap. |
| Channel type/policy | Discord intents có guild/message/member data. | discord.py channel objects. | Implement policy đã chốt: text/announcement, thread/forum, private-thread default-off long-term memory, voice unsupported without transcript, DM memory disabled. |
| Concurrent shared-session turns | Không có serialization; bot/backend có race. | PostgreSQL job/lease patterns làm tham khảo. | FIFO per session đã chốt; Sprint 1 chặn duplicate active session và test concurrent resolve, durable turn queue triển khai theo phạm vi sau. |
| Raw Discord message first | Không. | PostgreSQL/session factory. | Sprint 2 `discord_messages`, idempotency. |
| Author/reply/edit/delete | Không. | Discord event framework. | Metadata/event handlers/re-evaluation. |
| Attributed context | Không. | System prompt override/history assembly. | Discord context builder và token budget. |
| Async rolling summary | Không. | Job/outbox/worker pattern. | Summary job/table fields/worker/cursor. |
| Rule filter | Không. | Không có implementation tương ứng. | Tạo mới. |
| Durable memory extract job | Generic tables có. | Job/outbox pattern. | Generic routing + Discord repository/task/queue. |
| `qwen3.5:2b`, structured output, dry-run | Không có config/model path này. | Ollama client/model config pattern. | Sprint 5/6; không thực hiện trong audit. |
| Proposal/schema upgrade | Không. | JSONB/outbox pattern. | Proposal table, JSON Schema, retention/version process. |
| Fact key registry | Không. | Không có business registry tương đương. | Tạo mới. |
| Backend validator | Không. | Pydantic và transaction patterns. | Tạo Discord-specific validator/permission policy. |
| Conflict window/advisory lock | Không. | PostgreSQL transactions. | Tạo canonical identity, lock và resolver. |
| Versioned memory/source | Không. | PostgreSQL source-of-truth convention. | Tạo Discord memory/source tables và atomic replace. |
| Qdrant Discord indexing | UI memory collection primitive. | Collection/retry/upsert mechanics. | Collection riêng, guild/status payload, queue 1/3/10, `pending_reindex`. |
| Exact then semantic retrieval | Chỉ global semantic UI memory. | Embedding/Qdrant client. | Exact PostgreSQL lookup, guild-filtered semantic query, active validation. |
| Reconciliation/rebuild | Chỉ document domain. | Script/service patterns. | Discord-specific reconciliation/rebuild. |
| Slash governance | Chỉ `/ping`, `/ask`. | app command tree. | Toàn bộ `/memory ...`, permission/confirmation/rate limit/audit. |
| Retention/privacy | Request log/OCR/document cleanup có. | Cleanup pattern. | Discord-specific retention, forget/purge, source protection. |
| Metrics/alerts | Generic health/job metrics. | `OperationalService`. | Discord metrics/worker health/backlog. |

Không có thành phần structured Discord memory nào của Release 2–4 được triển khai. UI `memories` hiện tại không được coi là implementation của V5 vì thiếu isolation, fact/version/source/status và PostgreSQL-authoritative retrieval.

## 8. Final Architecture Decisions

Các quyết định trong mục 8–16 là baseline kiến trúc cuối cùng trước Sprint 1 và thay thế các đề xuất hoặc blocker chưa chốt trong phiên bản audit trước:

- shared session dùng canonical guild/channel/thread, không còn per-user;
- thread/forum dùng parent channel và thread ID riêng;
- legacy Discord conversations không được backfill hoặc dùng làm Discord Memory V5;
- backend sở hữu resolve/create session qua API;
- DM memory tắt; private-thread long-term memory mặc định tắt;
- Discord conversation bị cô lập khỏi danh sách Web UI hiện tại bằng `origin` và `visibility`;
- concurrent turns theo FIFO từng session, có hướng durable queue;
- migration bị chặn cho tới khi có PostgreSQL test database và recovery point đạt yêu cầu.

Các quyết định này chỉ chốt thiết kế. Không có API, schema, migration, worker hoặc runtime behavior nào được triển khai trong bước cập nhật tài liệu này.

## 9. Legacy Conversation Cutover Policy

Chính sách cutover đã chốt:

1. Không backfill các Discord conversation cũ vào `discord_conversation_sessions`.
2. Không thể suy ra an toàn `guild_id`, channel, thread hoặc author từ dữ liệu legacy hiện tại:
   - Discord business key chỉ tồn tại trong dictionary RAM;
   - backend conversation ID do `uuid4()` sinh, không mang source;
   - `conversations` không có guild/channel/thread/author/origin;
   - `messages` không có Discord message ID, author hoặc location;
   - UI và Discord đang dùng chung bảng conversation.
3. Giữ nguyên legacy conversations trong PostgreSQL.
4. Không xóa, sửa, merge hoặc gắn lại dữ liệu legacy.
5. Discord shared session mới chỉ được tạo từ thời điểm cutover.
6. Legacy conversation không được dùng làm Discord Memory V5, không được dùng bootstrap shared session và không được suy diễn từ content, prompt hoặc timestamp.

Đây là quyết định cuối và thay thế nội dung “cutover được đề xuất” trước đây. Continuity của persistent Discord session bắt đầu tại cutover, không hồi tố.

## 10. Backend-Owned Session Resolution

Backend sở hữu toàn bộ business mapping và lifecycle resolve/create session:

- Discord bot không giữ authoritative mapping bằng dictionary trong RAM.
- Bot chỉ gửi Discord identifiers cần thiết cho backend.
- Backend normalize canonical location, resolve active session hoặc tạo session mới trong transaction.
- API dự kiến cho Sprint 1:

```text
POST /api/discord/sessions/resolve
```

- Database phải bảo đảm mỗi canonical text/announcement channel hoặc thread/forum post chỉ có tối đa một session `active`.
- Concurrent resolve cùng canonical key phải trả về cùng active session; database constraint là guard bắt buộc, không chỉ dựa vào application check.
- Không giữ PostgreSQL transaction mở trong thời gian model inference.
- Không triển khai API hoặc migration trong bước này.

API path này thay thế đề xuất cũ `POST /discord/sessions/resolve`. Bot không truy cập PostgreSQL trực tiếp và không ghép một public conversation-create call với session-create call ở hai transaction riêng.

## 11. Channel, Thread, Forum and DM Policy

Canonical session policy đã chốt:

| Discord location | Canonical session key | Conversation context | Long-term memory |
|---|---|---|---|
| Text channel | `guild_id + channel_id + thread_id=NULL` | Shared trong channel | Theo guild/channel policy |
| Announcement channel | `guild_id + channel_id + thread_id=NULL` | Shared trong channel | Theo guild/channel policy |
| Public thread | `guild_id + parent_channel_id + thread_id` | Session riêng | Theo policy |
| Private thread | `guild_id + parent_channel_id + thread_id` | Được phép | Mặc định tắt; chỉ bật khi policy/admin cho phép |
| Forum post | `guild_id + parent forum channel_id + thread_id` | Xử lý như thread | Theo policy |
| Voice channel | Không tạo session theo workflow này khi không có transcript | Chưa hỗ trợ | Tắt |
| DM | Không thuộc guild-memory workflow | Không tạo guild-memory session | Tắt trong giai đoạn đầu |

Quy tắc thread:

- thread/forum post không tự lấy raw message của parent channel;
- thread vẫn có thể dùng guild memory và member-in-guild memory theo policy;
- `channel_id` của canonical thread session là parent channel/forum ID, còn `thread_id` là current thread/post ID.

Đây là quyết định cuối và đóng blocker canonical thread/forum cùng DM/private-thread policy của audit trước.

## 12. Web UI Isolation Policy

Discord session/conversation và Web UI chat phải phân biệt nguồn bằng:

```text
origin = discord | web_ui | legacy
```

Chính sách visibility:

```text
Discord session mặc định:
  visibility = internal
```

Yêu cầu:

- Discord conversations không xuất hiện trong danh sách Web UI chat hiện tại.
- Query/list của Web UI phải loại `origin=discord` hoặc áp dụng visibility tương đương; behavior của các conversation hiện đang hiển thị không được thay đổi ngoài yêu cầu cô lập này.
- Legacy rows được giữ nguyên và không được suy diễn thành Discord rows.
- Discord memory tiếp tục tách khỏi bảng `memories`, API `/memory/*` và Qdrant collection `memories` của UI.
- Sprint 1 phải thiết kế chỗ lưu `origin`/`visibility` cho session/conversation, nhưng bước tài liệu này không chốt hay tạo migration cụ thể.

Quyết định này thay thế blocker “Discord conversation có xuất hiện trong `GET /conversations` hay không”: câu trả lời cuối là **không xuất hiện trong danh sách Web UI hiện tại**.

## 13. Concurrent Shared-Session FIFO Policy

Chính sách xử lý concurrent turn đã chốt:

- FIFO riêng cho từng session.
- Một session chỉ có tối đa một turn đang được model xử lý.
- Message khác được lưu và xếp hàng theo thứ tự nhận.
- Không dùng riêng `asyncio.Lock` làm cơ chế chính vì lock mất khi restart và không điều phối nhiều process/instance.
- Không giữ PostgreSQL transaction trong thời gian model inference.
- Thiết kế phải cho phép bổ sung durable session turn queue.

Schema dự kiến:

```text
discord_session_turns
- id
- session_id
- discord_message_id
- sequence_number
- status
- available_at
- started_at
- completed_at
- error
```

Status:

```text
queued
running
completed
failed
cancelled
```

Giới hạn Sprint 1:

- bắt buộc ngăn tạo trùng active session;
- bắt buộc test concurrent resolve session;
- ghi rõ kế hoạch FIFO và compatibility với durable turn queue;
- không bắt buộc triển khai toàn bộ turn worker nếu vượt phạm vi persistent session foundation.

Quyết định này đóng blocker concurrent shared-session policy. Việc triển khai turn worker đầy đủ vẫn là công việc sau foundation, không được kéo rộng Sprint 1.

## 14. PostgreSQL Test Database Requirements

Trước khi tạo migration Sprint 1 phải có PostgreSQL test database riêng qua:

```text
POSTGRES_TEST_URL
```

Gate bắt buộc:

- không dùng database runtime cho bất kỳ test mutation nào;
- chạy lại toàn bộ test PostgreSQL liên quan đang skip vì thiếu test database;
- test Alembic upgrade từ revision phù hợp đến head mới;
- test unique constraint bảo đảm tối đa một active canonical session;
- test concurrent session resolve;
- có quy trình cleanup/reset test database an toàn và giới hạn đúng database test.

Trong audit ban đầu, 15 test đã skip vì chưa có `POSTGRES_TEST_URL`. Chưa có bằng chứng trong bước cập nhật tài liệu này rằng test database đã được chuẩn bị, nên gate này vẫn mở.

## 15. Pre-Migration Recovery Checklist

Trước khi apply migration lên runtime database phải hoàn thành và lưu evidence cho toàn bộ checklist:

- [ ] Tạo `pg_dump` của runtime PostgreSQL.
- [ ] Tính và ghi checksum của backup.
- [ ] Ghi Alembic revision hiện tại.
- [ ] Ghi row counts của các bảng liên quan trước migration.
- [ ] Restore backup vào database tạm/cô lập.
- [ ] Chạy restore drill và kiểm tra database phục hồi sử dụng được.
- [ ] Xác nhận backup, checksum, revision, row counts và restore evidence được lưu tại vị trí vận hành đã duyệt.

Nếu tạo backup, checksum hoặc restore drill thất bại thì **không được apply migration**. Audit này chưa tạo backup và chưa chạy restore drill, nên recovery gate vẫn mở.

## 16. Sprint 1 Readiness Decision

Kết luận cuối:

- Các blocker kiến trúc đã được chốt: canonical session model, thread/forum policy, no-backfill cutover, backend-owned resolution, DM/private-thread policy, Web UI isolation và per-session FIFO.
- Chưa được tạo/apply migration Sprint 1 nếu `POSTGRES_TEST_URL` và pre-migration recovery point chưa sẵn sàng, kiểm chứng.
- Sau khi PostgreSQL test database và recovery point được xác nhận đạt các mục 14–15, hệ thống đủ điều kiện bắt đầu Sprint 1.
- Sprint 1 chỉ tập trung persistent session foundation: canonical shared session, guild isolation, backend resolve/create, active-session uniqueness, restart continuity và orphan recovery foundation.
- Sprint 1 không triển khai rule filter, `qwen3.5:2b` extractor, structured long-term memory, memory proposal/versioning hoặc Qdrant memory retrieval.
- Durable FIFO turn queue được giữ trong design; Sprint 1 tối thiểu ngăn duplicate active session và test concurrent resolve, không bắt buộc hoàn tất turn worker.

**Trạng thái hiện tại: kiến trúc đã sẵn sàng, nhưng implementation/migration gate chưa mở vì test database và recovery point chưa được xác nhận.**

## 17. Sprint 1 Schema Design Notes — chưa tạo migration

### 17.1. Nguyên tắc

- Chỉ thêm persistent guild/channel/session domain; chưa thêm raw message/memory/proposal.
- Dùng table riêng để không đổi UI.
- Discord Snowflake lưu `TEXT`.
- `backend_conversation_id` nên là `VARCHAR(128)`, không phải PostgreSQL UUID, vì `conversations.id` hiện là opaque `VARCHAR(128)` và migration legacy cố ý giữ compatibility.
- FK backend conversation dùng `ON DELETE SET NULL` để UI/API hard delete không bị chặn và không làm thay đổi hành vi UI.
- Resolve/recover phải chạy transactionally và serialize theo canonical location.
- Session/conversation mới phải mang `origin`; Discord session mặc định mang `visibility=internal`.
- `discord_session_turns` là durable FIFO design target, nhưng full turn worker không phải deliverable bắt buộc của Sprint 1.

### 17.2. Canonical location đã chốt

```text
Text/announcement:
  guild_id
  channel_id = current channel ID
  thread_id = NULL

Thread/forum post:
  guild_id
  channel_id = parent channel/forum ID
  thread_id = current thread/post ID

DM:
  memory disabled; không đi vào guild-memory session workflow
```

Canonical location này là quyết định cuối. Sprint 1 migration phải biểu diễn parent channel ở `channel_id` và current thread/forum post ở `thread_id`; audit không tự thêm một quyết định schema khác cho parent metadata.

### 17.3. Bảng thiết kế cho Sprint 1

#### `discord_guilds`

- `id UUID PK`, UUID do application sinh;
- `guild_id TEXT UNIQUE NOT NULL`;
- `guild_name TEXT`;
- `memory_enabled BOOLEAN NOT NULL DEFAULT false`;
- `created_at`, `updated_at TIMESTAMPTZ NOT NULL`.

#### `discord_channels`

- `id UUID PK`;
- `guild_id TEXT NOT NULL`, FK `discord_guilds.guild_id`;
- `channel_id TEXT NOT NULL`;
- `channel_name TEXT`;
- `channel_type TEXT NOT NULL`;
- `memory_enabled BOOLEAN NOT NULL DEFAULT false`;
- `long_term_memory_enabled BOOLEAN NOT NULL DEFAULT false`;
- `retention_days INTEGER NULL`, CHECK positive khi non-null;
- timestamps;
- `UNIQUE (guild_id, channel_id)`;
- CHECK channel type theo V5.

#### `discord_conversation_sessions`

- `id UUID PK`;
- `guild_id TEXT NOT NULL`;
- `channel_id TEXT NOT NULL`;
- `thread_id TEXT NULL`;
- `backend_conversation_id VARCHAR(128) NULL`, FK `conversations.id ON DELETE SET NULL`;
- `origin` phải phân biệt `discord | web_ui | legacy`; Discord session dùng `discord`;
- `visibility` của Discord session mặc định `internal`;
- `status TEXT NOT NULL`;
- `message_count INTEGER NOT NULL DEFAULT 0`, CHECK `>= 0`;
- summary/cursor fields đúng V5 để tránh schema churn ở Sprint 3;
- `started_at`, `last_active_at`, `closed_at`, `orphaned_at`, `created_at`, `updated_at`;
- CHECK status theo V5;
- index lookup `(guild_id, channel_id, thread_id, status)`;
- unique non-null `backend_conversation_id` để một backend conversation không thể thuộc hai Discord session.

Không dùng một unique index đơn giản `(guild_id, channel_id, thread_id) WHERE status='active'`: PostgreSQL coi các NULL là khác nhau và sẽ cho phép nhiều active non-thread session. Dùng một trong hai cách:

```text
UNIQUE (guild_id, channel_id)
  WHERE status='active' AND thread_id IS NULL

UNIQUE (guild_id, channel_id, thread_id)
  WHERE status='active' AND thread_id IS NOT NULL
```

hoặc PostgreSQL `NULLS NOT DISTINCT` nếu migration/tooling được kiểm chứng. Hai partial index rõ ràng hơn và tương thích trực tiếp với hai loại location.

Thiết kế Sprint 1 cũng phải bảo đảm backend conversation liên kết với session có source/visibility đủ để `GET /conversations` của Web UI loại Discord conversations. Cách đặt column cụ thể phải được thể hiện nhất quán trong migration/model/API của Sprint 1; không backfill hoặc suy diễn legacy rows.

`discord_session_turns` được ghi nhận tại mục 13 như schema dự kiến cho FIFO. Chỉ thêm bảng này vào Sprint 1 migration nếu nằm trong phạm vi persistent foundation đã review; full worker không phải acceptance gate bắt buộc.

### 17.4. Transaction/API boundary đã chốt

Bot hiện chỉ là HTTP client, không nên kết nối PostgreSQL trực tiếp. Tạo backend-owned flow:

```text
POST /api/discord/sessions/resolve
  validate/normalize location
  lock canonical location
  upsert guild/channel metadata
  get active session
  nếu không có:
    create conversations row
    create active Discord session
  commit
  return session_id + backend_conversation_id
```

Resolve phải idempotent dưới concurrent request và database phải chặn duplicate active session. Nếu backend conversation đã mất, backend-owned lifecycle phải re-resolve/recover mà không dựa vào dictionary RAM hoặc retry ID cũ vô hạn.

Không thêm public `POST /conversations` chỉ để bot ghép hai call không atomic. Session service trong backend có thể gọi repository tạo conversation và session trong cùng transaction.

## 18. Rủi ro

### 18.1. Dữ liệu/migration

- Không thể nhận diện/backfill old Discord conversation; gắn nhầm có thể lộ UI/private history vào guild.
- Hard delete conversation hiện cascade messages. FK session phải không làm endpoint UI bị fail.
- DB/model mismatch về outbox nullability có thể gây giả định sai ở sprint worker sau.
- Current messages không có attribution; không được merge old histories.
- Bảng mới cần default memory disabled để migration không tự động bắt đầu thu thập dữ liệu.

### 18.2. Concurrency

- Bot dict hiện có race tạo hai conversation.
- Get-or-create shared session cần database serialization, không chỉ “select rồi insert”.
- Hai partial unique index là guard cuối; service nên advisory-lock canonical location hoặc lock registry row.
- Backend chat hiện không serialize message generation theo conversation; shared channel làm xác suất concurrent request tăng mạnh.
- Recovery và normal resolve có thể đua nhau; phải recheck trong transaction.
- FIFO per session đã được chốt, nhưng durable turn queue/worker chưa tồn tại trong source và không được coi là đã triển khai.

### 18.3. Privacy

- Current UI memory là global/unscoped; tái sử dụng trực tiếp sẽ trộn guild/UI.
- DM memory phải tắt; private-thread conversation được phép nhưng long-term memory mặc định tắt theo quyết định cuối. Source hiện chưa enforce policy này.
- Backend conversation list/detail hiện không có owner/source filter trong source; Sprint 1 phải dùng `origin`/`visibility` để Discord conversations không xuất hiện trong danh sách Web UI hiện tại.
- Guild member display names đang được gửi trong mỗi Discord system prompt, tối đa configured limit; đây là data processing hiện có cần review.
- Raw content không xuất hiện trong request logs hiện tại, nhưng Discord raw-message implementation tương lai phải giữ nguyên nguyên tắc này.

### 18.4. Backward compatibility

- Loại user khỏi key sẽ đổi semantics: nhiều user cùng channel bắt đầu thấy shared history.
- Old conversation không nối tiếp sau cutover.
- Thêm FK cứng kiểu UUID sẽ không tương thích opaque string IDs hiện tại.
- Sửa `MemoryService`, bảng `memories` hoặc collection `memories` có thể đổi UI behavior.
- `GET /conversations` phải giữ UI behavior hiện tại nhưng loại Discord conversations mới bằng `origin`/`visibility`.

## 19. Thứ tự sửa file đề xuất cho Sprint 1

Đây chỉ là thứ tự đề xuất; chưa file nào dưới đây được sửa trong audit.

1. `backend/alembic/versions/<new_revision>_discord_persistent_sessions.py`
   Thêm persistent session foundation, canonical active-session constraints và source/visibility support; chỉ thêm `discord_session_turns` nếu phạm vi Sprint 1 đã review. Review SQL offline; chưa đụng structured memory.

2. `backend/app/postgres/models.py`
   Thêm ORM model khớp migration, đặc biệt `backend_conversation_id VARCHAR(128)`, `origin`, `visibility` và null semantics.

3. `backend/app/postgres/discord_repositories.py` (mới)
   Tách Discord session persistence khỏi `PostgresDocumentRepository` và `PostgresAuxiliaryStore`.

4. `backend/app/schemas/discord_schema.py` (mới)
   Request/response contract cho canonical location và backend-owned resolve.

5. `backend/app/services/discord_session_service.py` (mới)
   Normalize/validate policy, transactional resolve, concurrency lock và orphan recovery.

6. `backend/app/routers/discord_sessions.py` (mới), sau đó `backend/app/main.py`
   Expose `POST /api/discord/sessions/resolve` và compose service.

7. `discord_bot/api_client.py`
   Thêm resolve client contract, giữ error mapping hiện có.

8. `discord_bot/main.py`
   Bỏ dict per-user làm source of truth; lấy parent/thread metadata; dùng persistent shared session. Có thể giữ cache chỉ như optimization có invalidation, không làm authoritative mapping.

9. Tests tương ứng trước khi cutover:
   - `backend/tests/test_discord_session_schema.py`;
   - `backend/tests/test_discord_session_repository.py`;
   - `backend/tests/test_discord_session_api.py`;
   - `backend/tests/test_discord_session_concurrency.py`;
   - mở rộng `tests/test_discord_api_client.py`.

Không sửa trong Sprint 1: `MemoryService`, `/memory/*`, UI checkbox, Qdrant memory collection, extractor/model config, raw message handlers hoặc worker memory tasks.

## 20. Danh sách test cần có

### 20.1. Gate Sprint 1

Session identity:

- Hai user trong cùng text channel resolve cùng active session/backend conversation.
- Hai user trong cùng announcement channel resolve cùng active session/backend conversation.
- Hai channel khác nhau không dùng chung session.
- Hai guild khác nhau không dùng chung session.
- Thread dùng parent channel + thread ID và có session riêng.
- Hai thread cùng parent không dùng chung session.
- Forum post được normalize/test như thread bằng fixture Discord phù hợp.
- DM bị từ chối khỏi guild session workflow.
- Private thread có conversation context; long-term memory mặc định tắt.

Persistence/lifecycle:

- Restart bot/process không đổi session.
- Bot restart hoặc chạy nhiều instance không cần authoritative dictionary RAM để tìm session.
- Backend conversation bị hard delete: old session thành orphaned, chỉ một new active session được tạo.
- Recovery retry idempotent; không loop ID cũ.
- Không backfill/mutate old conversations khi migration chạy.
- UI-created conversation vẫn list/get/delete như trước.
- Delete UI conversation được link không bị FK error; session phục hồi an toàn ở request sau.

Constraint/concurrency:

- Không thể tạo hai active non-thread session cùng location.
- Không thể tạo hai active thread session cùng location.
- Hai resolve đồng thời trả cùng session.
- Resolve và recover đồng thời không tạo hai active session.
- FIFO design bảo đảm mỗi session chỉ có một running turn; nếu full turn worker chưa thuộc Sprint 1 thì ít nhất phải có contract/test plan và concurrent resolve test.
- Một backend conversation không thể link hai Discord session.

Validation/privacy:

- Snowflake được giữ nguyên dạng text.
- Guild/channel/thread mismatch bị từ chối.
- Unsupported channel type bị từ chối.
- Default `memory_enabled=false`.
- Discord session không xuất hiện/không làm đổi hành vi UI ngoài contract đã duyệt.
- Discord conversation mới có `origin=discord`, session mặc định `visibility=internal`, và bị loại khỏi Web UI conversation list.
- Logs không chứa token, password hoặc message content.

Migration:

- Upgrade trên PostgreSQL test database ở head `20260719_11`.
- Schema inspector xác nhận column/FK/CHECK/index/nullability.
- Downgrade được review/test trên database test trống dữ liệu Sprint 1.
- Alembic `heads` còn đúng một head.
- Toàn bộ migration/integration test chạy bằng `POSTGRES_TEST_URL`, không dùng runtime database.
- Test database cleanup/reset chỉ tác động database test đã xác minh.

### 20.2. Test cần lên kế hoạch cho các sprint sau

- Raw message idempotency theo Discord message ID.
- Author/display name/reply attribution.
- Edit update same row; delete soft-delete và reevaluate source.
- Summary cursor `(created_at, discord_message_id)`, retry/idempotency và attribution.
- Rule filter precision/recall.
- Vietnamese extractor benchmark, JSON Schema compatibility và repeated-run stability.
- Proposal dry-run không mutate memory/Qdrant.
- Fact registry normalize/candidate pending.
- Atomic supersede/active memory và source preservation.
- Conflict window: contradictory values pending, same values merge sources.
- Proposal/memory expiration race.
- PostgreSQL/Qdrant guild isolation tại query layer.
- Exact lookup trước semantic; current query chỉ active.
- Qdrant missing/stale/orphan/rebuild/reconciliation.
- `/memory show-me`, forget, purge, permission, confirmation và rate limit.

## 21. Điểm chưa thể xác minh và gate còn mở

### 21.1. Chưa thể xác minh từ source

- Privileged intents/permissions thực tế đã bật trong Discord Developer Portal hay chưa.
- Bot đã được install ở guild nào, có private thread/forum permissions nào và command availability trong DM thực tế.
- Reverse proxy/auth middleware ngoài repository có bảo vệ backend hay không; source FastAPI hiện không đăng ký auth middleware hoặc `/api/login`.
- Conversation nào trong PostgreSQL là Discord, UI hay client khác. Schema không lưu source nên không thể phân loại.
- Có external cron/manual SQL nào xóa conversation ngoài cleanup source hiện tại hay không.
- Qdrant live data/payload hiện tại; audit xác minh contract source nhưng không scroll/copy point content.
- Chính sách consent/retention được guild admin chấp thuận.
- Audit ban đầu chưa có `POSTGRES_TEST_URL`, nên PostgreSQL integration tests liên quan đã skip; bước cập nhật tài liệu này không kiểm tra hoặc tạo test database.
- Recovery point gồm dump/checksum/row counts/restore drill chưa được tạo hoặc xác minh trong bước tài liệu này.

Model `qwen3.5:2b` không được tải/chạy/kiểm tra, đúng phạm vi Sprint 0.

### 21.2. Blocker kiến trúc đã đóng

- Canonical text/announcement channel key đã chốt.
- Canonical parent-channel/thread/forum key đã chốt.
- Legacy no-backfill cutover đã chốt.
- Backend-owned `POST /api/discord/sessions/resolve` đã chốt.
- DM/private-thread policy đã chốt.
- Web UI isolation bằng `origin`/`visibility` đã chốt.
- Per-session FIFO và durable turn queue direction đã chốt.

### 21.3. Gate kỹ thuật còn mở

1. `POSTGRES_TEST_URL` cô lập phải được chuẩn bị và các test ở mục 14/20 phải pass.
2. Pre-migration recovery checklist ở mục 15 phải hoàn tất, gồm successful restore drill.

Hai gate này không phải quyết định kiến trúc còn tranh luận; chúng là điều kiện vận hành bắt buộc. Chưa được tạo/apply migration khi một trong hai gate chưa đạt.

## 22. Kết quả lệnh audit/test

Kết quả dưới đây thuộc lần audit source ban đầu. Trong bước chốt quyết định kiến trúc này chỉ đọc hai tài liệu, sửa `docs/discord_memory_audit.md` và chạy kiểm tra text/Git read-only; không chạy Alembic online, database query, test mutation, Docker hoặc model.

Các lệnh/chức năng audit ban đầu đã chạy:

- Liệt kê file bằng `rg --files`, tìm `AGENTS.md` (không có trong repository scope).
- Đọc toàn bộ `discord_memory_workflow_plan_v5_final.md`.
- Đọc source/config/migration/test được liệt kê ở mục 6 bằng lệnh read-only.
- `git status --short`, `git rev-parse HEAD`, `git branch --show-current`, `git ls-files`.
- `.\.venv\Scripts\python.exe -m alembic heads`.
- `.\.venv\Scripts\python.exe -m alembic current` với `DATABASE_URL` lấy cục bộ nhưng không in giá trị.
- SQLAlchemy Inspector read-only cho metadata của `conversations`, `messages`, `memories`, `jobs`, `outbox_events`; không query row content.
- Test:

```text
.\.venv\Scripts\python.exe -m pytest \
  tests/test_discord_api_client.py \
  backend/tests/test_chat_api.py \
  backend/tests/test_conversations_api.py \
  backend/tests/test_memory_api.py \
  backend/tests/test_worker_hardening.py \
  backend/tests/test_qdrant_store.py \
  backend/tests/test_transactional_outbox.py \
  backend/tests/test_stale_recovery.py -q
```

Kết quả:

```text
10 passed, 15 skipped, 2 warnings
```

- 8 Discord client tests, worker backoff test và Qdrant dimension test pass.
- 15 test cần PostgreSQL test URL bị skip; không chuyển chúng sang database runtime vì các test đó tạo/xóa dữ liệu.
- Hai warning là deprecation từ Starlette/httpx test client và Python `audioop`; không phải test failure.
- Không có Docker/model/network mutation nào được chạy.
