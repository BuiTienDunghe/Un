# Kế hoạch chi tiết phát triển Discord Memory cho `local-ai-core` — Workflow V5 Final

## 1. Mục tiêu

Xây dựng hệ thống memory riêng cho Discord bot với các đặc điểm:

- Mỗi Discord server (`guild_id`) là một vùng memory độc lập.
- Mỗi channel hoặc thread có một session hội thoại chung.
- Mỗi message lưu rõ ai nói, nói ở đâu, trả lời ai và thời điểm nào.
- Bot tiếp tục đúng conversation sau khi restart.
- Memory Discord không bị trộn với memory của Web UI.
- Model extractor khoảng 2B, instruct, non-thinking.
- Model chỉ đề xuất thao tác memory; backend mới có quyền cập nhật dữ liệu.
- Thông tin mới có thể thay thế thông tin cũ theo version.
- Câu hỏi hiện tại chỉ dùng memory đang `active`.
- Có dry-run, pending review, retry, rebuild và reconciliation.
- PostgreSQL là nguồn dữ liệu chuẩn; Qdrant chỉ phục vụ semantic retrieval.
- Có conflict window để ngăn hai cập nhật trái ngược cùng lúc dùng last-write-wins.
- Có retention riêng cho proposal và quy trình nâng extractor schema.
- Chốt `qwen3.5:2b` làm memory extractor đầu tiên.
- Structured output dùng JSON Schema làm chế độ chính; JSON mode chung chỉ là fallback.
- Cấu hình sampling ban đầu ưu tiên tính lặp lại và phải được xác nhận trong Sprint 5.

Bản V4 này hoàn thiện các điểm còn thiếu được phát hiện trong review V3: proposal retention, deterministic conflict resolution, schema upgrade path, Snowflake cursor safety và Acceptance Criteria cho toàn bộ Sprint.

---

# 2. Nguyên tắc kiến trúc

## 2.1. Hai luồng độc lập

### Luồng chat trực tuyến

```text
Discord message
→ Validate guild/channel/thread
→ Tìm session
→ Lưu raw message
→ Lấy memory liên quan
→ Ghép summary + recent messages
→ Chat model
→ Trả lời Discord
```

### Luồng memory bất đồng bộ

```text
Raw message đã lưu
→ Rule filter
→ Durable memory job
→ Transactional outbox
→ Redis/RQ
→ Model extractor 2B
→ Backend validator
→ Versioned PostgreSQL memory
→ Qdrant indexing queue
→ Reconciliation/rebuild
```

Mục tiêu của việc tách luồng:

- Chat không phải chờ memory extractor.
- Model memory lỗi không làm bot ngừng trả lời.
- Có thể retry mà không tạo memory trùng.
- Có thể chạy dry-run trước khi bật auto-apply.
- Có thể rebuild Qdrant từ PostgreSQL.

---

## 2.2. Model memory đã chốt

Model khởi đầu:

```text
qwen3.5:2b
```

Chính sách:

- Chạy non-thinking.
- Tên model nằm trong config, không hard-code trong worker.
- Structured output ưu tiên truyền JSON Schema object vào trường `format` của Ollama.
- `format: "json"` chỉ là fallback khi schema mode không tương thích với phiên bản Ollama đang chạy.
- Cấu hình benchmark ban đầu: `temperature=0.0`, `seed=42`, `stream=false`, context 4096.
- Model vẫn phải qua strict backend validation dù response parse được thành JSON.
- Phải benchmark tiếng Việt trước khi bật auto-apply.
- Sau khi benchmark đạt yêu cầu, ghi lại phiên bản Ollama và model digest/tag đã được kiểm chứng.
- Giai đoạn đầu luôn chạy dry-run.

---

# 3. Ranh giới dữ liệu

## 3.1. Guild isolation

```text
Một guild_id = một vùng memory độc lập
```

Mọi truy vấn PostgreSQL và Qdrant bắt buộc phải có `guild_id`.

Không được:

```text
Search toàn bộ dữ liệu
→ lấy kết quả
→ mới lọc guild trong application
```

Phải lọc ngay tại tầng database/vector query:

```text
WHERE guild_id = current_guild
```

## 3.2. Session model

```text
guild_id + channel_id + thread_id
→ một session chung
```

Không tạo conversation riêng theo từng user.

Mỗi message vẫn lưu:

```text
author_id
author_display_name
```

để biết chính xác ai nói câu nào.

## 3.3. Thread model

- Thread là session riêng.
- Forum post được xử lý như thread.
- Thread không tự động lấy toàn bộ raw message của channel cha.
- Thread có thể dùng guild memory, member-in-guild memory và channel-level memory nếu policy cho phép.
- Khi thread archive/unarchive:
  - còn hạn → dùng lại session;
  - hết hạn → tạo session mới và dùng summary cũ làm context khởi tạo.

## 3.4. Direct Message

DM không thuộc guild memory.

Giai đoạn đầu:

```text
DM memory = disabled
```

Nếu cần hỗ trợ sau này, phải có workflow riêng.

---

# 4. Chuẩn hóa channel type

Các giá trị cho phép:

```text
text
announcement
forum
public_thread
private_thread
voice
dm
```

Chính sách đề xuất:

| Channel type | Memory |
|---|---|
| `text` | Hỗ trợ |
| `announcement` | Tùy cấu hình |
| `forum` | Xử lý như thread |
| `public_thread` | Hỗ trợ |
| `private_thread` | Tùy quyền riêng tư |
| `voice` | Không lưu nếu không có transcript |
| `dm` | Tắt trong guild workflow |

Dùng PostgreSQL enum hoặc `CHECK constraint`.

---

# 5. Cấu trúc dữ liệu

## 5.1. `discord_guilds`

```text
id UUID PK
guild_id TEXT UNIQUE NOT NULL
guild_name TEXT
memory_enabled BOOLEAN NOT NULL DEFAULT false
created_at TIMESTAMPTZ NOT NULL
updated_at TIMESTAMPTZ NOT NULL
```

## 5.2. `discord_channels`

```text
id UUID PK
guild_id TEXT NOT NULL
channel_id TEXT NOT NULL
channel_name TEXT
channel_type TEXT NOT NULL
memory_enabled BOOLEAN NOT NULL DEFAULT false
long_term_memory_enabled BOOLEAN NOT NULL DEFAULT false
retention_days INTEGER
created_at TIMESTAMPTZ NOT NULL
updated_at TIMESTAMPTZ NOT NULL
```

Ràng buộc:

```text
UNIQUE (guild_id, channel_id)
CHECK channel_type IN (
  'text',
  'announcement',
  'forum',
  'public_thread',
  'private_thread',
  'voice',
  'dm'
)
```

## 5.3. `discord_conversation_sessions`

```text
id UUID PK
guild_id TEXT NOT NULL
channel_id TEXT NOT NULL
thread_id TEXT NULL
backend_conversation_id UUID NULL
status TEXT NOT NULL
message_count INTEGER NOT NULL DEFAULT 0
summary TEXT NULL
summary_version INTEGER NOT NULL DEFAULT 0
summarized_until_message_id TEXT NULL
summarized_until_created_at TIMESTAMPTZ NULL
started_at TIMESTAMPTZ NOT NULL
last_active_at TIMESTAMPTZ NOT NULL
closed_at TIMESTAMPTZ NULL
orphaned_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ NOT NULL
updated_at TIMESTAMPTZ NOT NULL
```

Trạng thái:

```text
active
closed
expired
orphaned
deleted
```

Constraint:

```text
CHECK status IN ('active','closed','expired','orphaned','deleted')
```

Partial unique index:

```text
Mỗi guild_id + channel_id + thread_id
chỉ có tối đa một session status='active'
```

Ghi chú về Discord Snowflake:

- `discord_message_id` được lưu dạng `TEXT` để không phụ thuộc giới hạn số nguyên của ngôn ngữ/runtime.
- Không dùng phép so sánh từ điển `discord_message_id > ...` để xác định message mới hơn.
- Cursor summary phải dùng cặp `(created_at, discord_message_id)`; `created_at` là khóa thời gian chính, `discord_message_id` chỉ làm tie-breaker.
- `summarized_until_created_at` và `summarized_until_message_id` phải được cập nhật cùng transaction với `summary_version`.

## 5.4. `discord_messages`

```text
id UUID PK
discord_message_id TEXT UNIQUE NOT NULL
guild_id TEXT NOT NULL
channel_id TEXT NOT NULL
thread_id TEXT NULL
session_id UUID NOT NULL
author_id TEXT NOT NULL
author_display_name TEXT NOT NULL
content TEXT NOT NULL
reply_to_message_id TEXT NULL
is_bot BOOLEAN NOT NULL DEFAULT false
created_at TIMESTAMPTZ NOT NULL
edited_at TIMESTAMPTZ NULL
deleted_at TIMESTAMPTZ NULL
ingested_at TIMESTAMPTZ NOT NULL
```

Index đề xuất:

```text
(guild_id, channel_id, thread_id, created_at DESC)
(session_id, created_at DESC)
(author_id, guild_id)
```

## 5.5. `discord_memories`

```text
id UUID PK
guild_id TEXT NOT NULL
channel_id TEXT NULL
member_id TEXT NULL
scope TEXT NOT NULL
subject_type TEXT NOT NULL
subject_key TEXT NOT NULL
fact_key TEXT NOT NULL
value_json JSONB NOT NULL
status TEXT NOT NULL
confidence NUMERIC(4,3) NOT NULL
importance_score NUMERIC(4,3) NULL
valid_from TIMESTAMPTZ NOT NULL
valid_until TIMESTAMPTZ NULL
expires_at TIMESTAMPTZ NULL
supersedes_memory_id UUID NULL
origin_proposal_id UUID NULL
index_status TEXT NOT NULL DEFAULT 'pending'
created_by_message_id TEXT NOT NULL
created_at TIMESTAMPTZ NOT NULL
updated_at TIMESTAMPTZ NOT NULL
```

Scope:

```text
guild
channel
member_in_guild
conversation
```

Status:

```text
active
superseded
disputed
pending_review
expired
deleted
```

Index status:

```text
pending
indexed
pending_reindex
failed
not_required
```

Constraint:

```text
CHECK scope IN ('guild','channel','member_in_guild','conversation')

CHECK status IN (
  'active',
  'superseded',
  'disputed',
  'pending_review',
  'expired',
  'deleted'
)

CHECK index_status IN (
  'pending',
  'indexed',
  'pending_reindex',
  'failed',
  'not_required'
)
```

Partial unique index:

```text
Trong cùng:
guild_id + scope + subject_key + fact_key

chỉ được có tối đa một memory active.
```

Với scope `member_in_guild`, khóa cần thêm `member_id`.

Với scope `channel`, khóa cần thêm `channel_id`.

## 5.6. `discord_memory_sources`

```text
memory_id UUID NOT NULL
discord_message_id TEXT NOT NULL
author_id TEXT NOT NULL
source_role TEXT NOT NULL
created_at TIMESTAMPTZ NOT NULL
```

`source_role`:

```text
primary
supporting
confirmation
contradiction
```

Mỗi memory phải có ít nhất một nguồn.

## 5.7. `discord_memory_proposals`

Dùng cho dry-run và pending review:

```text
id UUID PK
guild_id TEXT NOT NULL
discord_message_id TEXT NOT NULL
extractor_schema_version TEXT NOT NULL
model_name TEXT NOT NULL
raw_output JSONB
normalized_output JSONB
fact_identity_hash TEXT NULL
proposed_value_hash TEXT NULL
validation_status TEXT NOT NULL
decision TEXT NOT NULL
confidence NUMERIC(4,3)
apply_after TIMESTAMPTZ NULL
expires_at TIMESTAMPTZ NULL
error_message TEXT NULL
created_at TIMESTAMPTZ NOT NULL
reviewed_at TIMESTAMPTZ NULL
reviewed_by TEXT NULL
```

Decision:

```text
dry_run
awaiting_conflict_check
auto_apply
pending_review
ignore
rejected
expired
failed
```

Index đề xuất:

```text
(fact_identity_hash, decision, created_at DESC)
(discord_message_id, extractor_schema_version)
(expires_at)
```

`fact_identity_hash` được tạo từ canonical identity:

```text
guild_id
+ scope
+ subject_type
+ subject_key
+ fact_key
+ channel_id/member_id discriminator nếu scope yêu cầu
```

Hash chỉ phục vụ tra cứu/khóa logic, không thay thế unique constraint nghiệp vụ trong PostgreSQL.


---

# 6. Fact key registry

## 6.1. Convention

```text
namespace.attribute
```

Quy tắc:

- lowercase;
- dùng dấu chấm giữa namespace và attribute;
- dùng underscore cho từ ghép;
- không có khoảng trắng;
- normalize trước khi validate;
- case-insensitive sau normalize.

Ví dụ:

```text
project.database_backend
project.embedding_model
project.ocr_model
project.architecture
project.deadline
project.status
member.role
member.current_task
server.primary_language
server.rule
```

## 6.2. Không để model tạo fact key tự do

Quy trình:

```text
1. Model chọn từ registry nếu có
2. Nếu không có:
   → đề xuất candidate_fact_key
3. Candidate không được auto-apply
4. Đưa pending_review
5. Admin/backend mapping chốt fact_key chuẩn
```

## 6.3. Registry đề xuất

```text
discord_fact_key_registry
- fact_key
- subject_type
- value_schema
- allowed_scopes
- sensitive
- auto_apply_allowed
- description
- created_at
- updated_at
```

---

# 7. Workflow chi tiết

## Bước 1 — Nhận message

Bot nhận Discord message và lấy:

```text
discord_message_id
guild_id
channel_id
thread_id
author_id
author_display_name
reply_to_message_id
content
created_at
channel_type
```

Kiểm tra:

- message có thuộc guild không;
- guild có bật memory không;
- channel có bật memory không;
- channel type có được hỗ trợ không;
- message có phải bot/system message không.

## Bước 2 — Tìm session

Query session `active` theo:

```text
guild_id + channel_id + thread_id
```

Nếu có:

```text
→ dùng session hiện tại
→ update last_active_at
```

Nếu không:

```text
→ tạo backend conversation
→ tạo Discord session mới
```

## Bước 3 — Xử lý backend conversation bị mất

Nếu backend trả `conversation not found`:

```text
1. Đánh dấu session cũ = orphaned
2. Không retry conversation_id cũ vô hạn
3. Tạo backend conversation mới
4. Tạo session mới
5. Copy summary cũ làm bootstrap context
6. Ghi audit event
```

## Bước 4 — Lưu raw message

Lưu message vào PostgreSQL trước mọi xử lý khác.

Yêu cầu:

- idempotency theo `discord_message_id`;
- edit/update không tạo row mới;
- delete chỉ đánh dấu `deleted_at`;
- giữ reply relationship;
- không log toàn bộ content ở production.

## Bước 5 — Tạo online chat context

Context builder lấy theo thứ tự:

```text
1. System prompt
2. Exact active facts
3. Relevant guild memory
4. Member-in-guild memory
5. Session summary
6. Recent messages
7. Current message
```

Recent message format:

```text
[Dũng | 20:10]
Dự án hiện dùng PostgreSQL.

[Minh | 20:11 | trả lời Dũng]
SQLite đã bỏ hoàn toàn chưa?
```

Ưu tiên:

```text
Current message
> recent messages
> exact active facts
> summary
> semantic episodic memory
> historical memory
```

## Bước 6 — Chat response

Chat model trả lời ngay.

Memory extractor không nằm trong critical path của chat.

## Bước 7 — Trigger summary bất đồng bộ

Trigger khi:

```text
message_count >= 200
hoặc
unsummarized_messages >= 50
```

Tạo durable summary job:

```text
queue = conversation_summary
```

Summary worker:

```text
1. Lấy message chưa summarize
2. Tạo summary có attribution
3. Merge với summary cũ
4. Cập nhật summary_version
5. Cập nhật đồng thời summarized_until_created_at và summarized_until_message_id
```

Trong lúc job chưa hoàn thành:

```text
bot dùng summary cũ + recent unsummarized messages
```

## Bước 8 — Rule filter

Rule filter bỏ qua:

```text
hello
ok
emoji đơn lẻ
spam
command
message bot
message đã xóa
channel tắt long-term memory
```

Ưu tiên:

```text
chốt dùng
đã chuyển sang
hiện đang dùng
không dùng nữa
thay bằng
từ giờ
tôi phụ trách
deadline là
quyết định là
```

Output:

```json
{
  "should_analyze": true,
  "reason": "explicit_update_signal"
}
```

## Bước 9 — Tạo memory job

Nếu cần phân tích:

```text
1. Tạo durable PostgreSQL job
2. Tạo outbox event cùng transaction
3. Dispatcher enqueue Redis/RQ
4. Memory worker nhận job
```

Queue:

```text
memory_extract
```

Idempotency key:

```text
discord_message_id + extractor_schema_version
```

## Bước 10 — Model 2B extractor

Input:

```text
- current message
- author
- reply message
- vài message gần nhất
- active memory có liên quan
- fact key registry phù hợp
```

Output bắt buộc:

```json
{
  "should_store": true,
  "scope": "guild",
  "subject_type": "project",
  "subject_key": "local-ai-core",
  "fact_key": "project.database_backend",
  "operation": "replace",
  "value": "PostgreSQL",
  "confidence": 0.97,
  "evidence_message_ids": ["123456"]
}
```

Operation:

```text
ignore
insert
replace
confirm
dispute
expire
delete
```

Model không được:

- sửa DB;
- tự gán guild_id;
- tự bypass validator;
- tạo scope ngoài danh sách;
- tạo fact key chưa đăng ký rồi auto-apply;
- trả văn bản ngoài JSON schema.

## Bước 11 — Dry-run

Cấu hình ban đầu:

```text
MEMORY_EXTRACTOR_DRY_RUN=true
```

Dry-run:

```text
extractor chạy
→ validator chạy
→ proposal được lưu
→ không update active memory
→ không enqueue Qdrant indexing
```

Benchmark tối thiểu:

```text
100–300 case tiếng Việt
```

Nhóm test:

```text
assertion
question
correction
negation
proposal
uncertainty
joke
sarcasm
typo
abbreviation
multi-user conflict
reply-dependent context
```

### Quản lý `extractor_schema_version`

Tăng schema version khi một trong các yếu tố sau thay đổi:

- cấu trúc JSON output;
- ý nghĩa của operation/scope;
- convention `fact_key`;
- rule normalize hoặc validation làm thay đổi kết quả tương thích;
- cách biểu diễn `value`.

Quy trình nâng từ `v1` lên `v2`:

```text
1. Khóa contract v2 bằng JSON Schema mới
2. Chạy toàn bộ benchmark tiếng Việt
3. Chạy shadow/dry-run song song v1 và v2
4. So sánh precision, recall, conflict rate và invalid JSON rate
5. Chỉ đổi production default sau khi đạt ngưỡng
6. Giữ proposal v1 bất biến để audit
7. Không tự động re-extract lịch sử cũ
8. Muốn backfill phải dùng job/script riêng, dry-run trước
```

Script đề xuất:

```text
scripts/reextract_discord_memory.py
  --from-schema v1
  --to-schema v2
  --guild-id <optional>
  --dry-run
```

Memory được tạo từ proposal phải giữ `origin_proposal_id` để truy ngược model và schema đã tạo ra nó.

### Compatibility gate cho Ollama + Qwen3.5

Sprint 5 phải kiểm tra trực tiếp request thực tế:

```text
model = qwen3.5:2b
think = false
stream = false
format = JSON Schema object
options.temperature = 0.0
options.seed = 42
options.num_ctx = 4096
```

JSON Schema phải được đưa đồng thời vào:

```text
1. Trường `format` của Ollama request
2. Prompt extractor dưới dạng contract rõ ràng
```

Không coi structured output là đạt chỉ vì response parse được một lần. Compatibility gate phải đo:

```text
- invalid JSON rate
- schema violation rate
- markdown/code-fence contamination
- thinking text lẫn vào content
- độ ổn định khi chạy lặp cùng input
- hành vi sau restart Ollama
- hành vi trên phiên bản Ollama dự kiến dùng production
```

Nếu `think=false` làm structured output không ổn định:

```text
1. Giữ dry-run
2. Không bật auto-apply
3. Thử phiên bản Ollama tương thích hơn
4. Dùng JSON mode fallback + strict backend validation nếu cần
5. Không bỏ qua validator dù JSON hợp lệ
```

Sau khi đạt gate, ghi vào tài liệu vận hành:

```text
validated_ollama_version
validated_model_tag
validated_model_digest
extractor_schema_version
benchmark_report
```

## Bước 12 — Backend validator

Kiểm tra:

```text
JSON schema
guild isolation
scope
subject
fact key registry
fact key normalization
operation
confidence
author permission
current memory state
duplicate
question vs assertion
joke/sarcasm
sensitive fact
```

Decision:

```text
confidence >= 0.90
→ auto-apply nếu fact cho phép

0.70–0.89
→ pending_review

< 0.70
→ ignore
```

Fact nhạy cảm hoặc quan trọng không auto-apply chỉ dựa vào confidence.

## Bước 12.1 — Conflict window và xử lý cạnh tranh

Không áp dụng ngay proposal có đủ confidence. Proposal auto-apply trước tiên chuyển sang:

```text
decision = awaiting_conflict_check
apply_after = now + conflict_window_seconds
```

Giá trị khuyến nghị ban đầu:

```text
conflict_window_seconds = 15
```

Memory apply worker xử lý sau cửa sổ này:

```text
1. Nhóm proposal theo canonical fact identity
2. Acquire PostgreSQL transaction advisory lock cho fact identity
3. Đọc tất cả proposal hợp lệ trong conflict window
4. Nếu cùng một giá trị:
   → merge evidence/source
   → apply một lần
5. Nếu có các giá trị khác nhau từ những tác giả khác nhau:
   → không auto-apply proposal nào
   → chuyển tất cả sang pending_review
   → giữ active memory hiện tại không đổi
6. Nếu chỉ có một proposal hợp lệ:
   → tiếp tục versioned transaction
```

Không dùng `SKIP LOCKED` cho cập nhật cùng một fact vì có thể bỏ qua conflict. Dùng transaction-scoped advisory lock hoặc một fact-head row được `SELECT ... FOR UPDATE` để serialize cùng canonical fact identity.

Quy tắc an toàn:

```text
conflict gần thời gian + khác proposed value
→ pending_review, không dùng last-write-wins
```

Nếu nhiều người cùng xác nhận một giá trị:

```text
cùng proposed value
→ một memory update
→ các message còn lại trở thành supporting/confirmation sources
```

## Bước 13 — Versioned memory transaction

Ví dụ:

```text
SQLite = active
PostgreSQL proposal = replace
```

Transaction:

```text
1. Acquire fact identity lock
2. Lock active memory/fact head
3. Recheck proposal state và conflict window
4. SQLite:
   active → superseded
   valid_until = now

5. Tạo PostgreSQL:
   status = active
   valid_from = now
   supersedes_memory_id = SQLite memory
   origin_proposal_id = proposal đã duyệt

6. Lưu memory sources
7. Tạo Qdrant indexing outbox event
8. Commit
```

Nếu transaction lỗi:

```text
không memory nào bị thay đổi dở dang
```

## Bước 14 — Qdrant indexing job

Queue riêng:

```text
qdrant_index
```

Retry:

```text
1 giây
3 giây
10 giây
```

Nếu hết retry:

```text
index_status = pending_reindex
```

Payload:

```json
{
  "memory_id": "uuid",
  "guild_id": "guild_123",
  "scope": "guild",
  "subject_key": "local-ai-core",
  "fact_key": "project.database_backend",
  "status": "active"
}
```

## Bước 15 — Memory retrieval

Thứ tự:

```text
1. Exact fact key lookup
2. PostgreSQL metadata filtering
3. Qdrant semantic retrieval
4. BM25 chỉ bật nếu benchmark chứng minh cần
```

Current question:

```text
status = active
```

Historical question:

```text
status IN (active, superseded)
```

Qdrant filter bắt buộc:

```text
guild_id = current_guild
status = active
```

## Bước 16 — Message edit

Khi message sửa:

```text
1. Update raw message
2. Tìm proposal/memory source liên quan
3. Tạo reevaluation job
4. Nếu fact thay đổi:
   → supersede hoặc dispute memory cũ
```

## Bước 17 — Message delete

Khi message bị xóa:

```text
1. Mark deleted_at
2. Gỡ source link
3. Kiểm tra memory còn nguồn khác không
4. Nếu không còn nguồn:
   → pending_review hoặc disputed
5. Không xóa memory ngay nếu còn xác nhận khác
```

## Bước 18 — Reconciliation

Chạy định kỳ:

```text
PostgreSQL active nhưng Qdrant thiếu
→ reindex

Qdrant còn stale vector
→ delete/update

Payload sai guild/status
→ repair

Memory superseded nhưng vector active
→ remove/update

Qdrant có point không tồn tại trong PostgreSQL
→ delete
```

## Bước 19 — Rebuild Qdrant

Script:

```text
scripts/rebuild_discord_memory_qdrant.py
```

Tham số:

```text
--dry-run
--guild-id
--batch-size
--delete-stale
```

PostgreSQL luôn là nguồn chuẩn.

---

# 8. Memory retrieval context cuối cùng

```text
SYSTEM PROMPT

CURRENT VERIFIED FACTS
- Structured active facts

RELEVANT GUILD MEMORY
- Semantic memory liên quan

CURRENT MEMBER MEMORY
- member_in_guild memory của người hỏi

SESSION SUMMARY
- summary hiện tại

RECENT MESSAGES
- có author attribution

CURRENT REQUEST
- message mới
```

Quy tắc:

- không đưa memory superseded cho current answer;
- không nhắc lịch sử nếu user không hỏi;
- disputed memory không được khẳng định chắc chắn;
- message mới ưu tiên hơn memory cũ;
- giới hạn số memory và tổng token.

---

# 9. Slash commands

## Thành viên

```text
/memory status
/memory show-me
/memory forget-me
/memory recent
```

`/memory show-me`:

```text
- chỉ hiển thị memory scope=member_in_guild
- member_id = người gọi
- guild_id = guild hiện tại
- mặc định 10 record gần nhất
- hỗ trợ phân trang
```

## Admin

```text
/memory enable
/memory disable
/memory enable-channel
/memory disable-channel
/memory pending
/memory approve
/memory reject
/memory reset-channel
/memory purge-server
```

`/memory purge-server` bắt buộc:

```text
admin permission
confirmation
rate limit
audit log
```

---

# 10. Retention

Đề xuất:

```text
Raw messages: 90–180 ngày
Dry-run proposals: 7–14 ngày
Ignored/failed proposals: 14–30 ngày
Pending proposals: tối đa 30 ngày, sau đó chuyển expired/rejected theo policy
Auto-applied proposals: giữ khi memory còn active; sau khi superseded giữ thêm tối thiểu 90 ngày
Job logs: 14–30 ngày
Session summary: giữ lâu hơn raw messages
Active memories: giữ đến khi bị thay thế/xóa/hết hạn
Superseded memories: giữ lịch sử hoặc archive
Fact key registry: không tự động xóa; chỉ disable/version
```

Cleanup không được xóa proposal nếu nó vẫn được tham chiếu bởi `discord_memories.origin_proposal_id`, trừ khi đã lưu snapshot audit tối thiểu cần thiết.

Không lưu attachment binary trong PostgreSQL.

Chỉ lưu:

```text
attachment_url
filename
mime_type
size
storage_reference
```

---

# 11. Cấu hình đề xuất

```yaml
discord_memory:
  enabled: true

  extractor:
    model: "qwen3.5:2b"
    thinking: false

    # Chế độ chính: truyền JSON Schema object vào trường format của Ollama.
    ollama_format: "json_schema"
    json_schema_path: "config/discord_memory_extractor_schema_v1.json"

    # Fallback khi schema mode không tương thích; backend vẫn validate nghiêm ngặt.
    fallback_ollama_format: "json"

    temperature: 0.0
    seed: 42
    stream: false
    dry_run: true
    schema_version: "v1"
    context_tokens: 4096

  thresholds:
    auto_apply: 0.90
    pending_review: 0.70
    conflict_window_seconds: 15

  session:
    max_messages: 200
    summary_trigger_messages: 50
    idle_timeout_minutes: 60

  retrieval:
    exact_lookup_first: true
    semantic_search_enabled: true
    bm25_enabled: false
    max_memories_in_prompt: 10
    max_tokens_for_memory: 2000

  worker:
    memory_extract_queue: "memory_extract"
    summary_queue: "conversation_summary"
    qdrant_index_queue: "qdrant_index"
    retry_max: 3
    retry_backoff_seconds: [1, 3, 10]

  retention:
    raw_messages_days: 180
    proposals_dry_run_days: 7
    proposals_ignored_failed_days: 14
    proposals_pending_days: 30
    proposals_auto_apply_after_superseded_days: 90
    job_logs_days: 14
    superseded_memories_days: 365
```

---

# 12. Metrics

```text
discord_messages_ingested_total
discord_sessions_active
discord_sessions_orphaned_total
conversation_summary_jobs_total
conversation_summary_jobs_failed
memory_jobs_total
memory_jobs_failed
memory_proposals_dry_run_total
memory_created_total
memory_replaced_total
memory_ignored_total
memory_pending_review_total
memory_conflict_groups_total
memory_conflict_proposals_total
memory_proposals_expired_total
memory_retrieval_latency_ms
memory_exact_lookup_hits_total
memory_semantic_lookup_hits_total
memory_qdrant_stale_points
memory_qdrant_pending_reindex
```

---

# 13. Test bắt buộc

## Session

- Hai user trong cùng channel dùng chung session.
- Hai channel khác nhau không dùng chung session.
- Hai guild khác nhau không dùng chung session.
- Thread có session riêng.
- Restart bot vẫn dùng đúng session.
- Backend conversation bị mất được phục hồi.

## Attribution

```text
Dũng: Tôi dùng PostgreSQL.
Minh: Tôi dùng MySQL.
```

Bot phải biết từng câu thuộc ai.

## Update fact

```text
Dũng: Dự án dùng SQLite.
Dũng: Chốt chuyển sang PostgreSQL.
```

Kết quả:

```text
SQLite = superseded
PostgreSQL = active
```

## Không lưu sai

```text
Có nên dùng PostgreSQL không?
→ ignore
```

```text
Hình như dùng PostgreSQL.
→ pending/ignore
```

```text
Dũng là CEO Microsoft :))
→ ignore
```

## Conflict

```text
Dũng: Chốt PostgreSQL.
Minh: Hình như vẫn là SQLite.
```

Kết quả:

```text
PostgreSQL active
câu của Minh = disputed/pending
```

Conflict đồng thời:

```text
T+0s: Dũng: Chốt PostgreSQL.
T+1s: Minh: Chốt MySQL.
```

Kết quả:

```text
cả hai proposal = pending_review
active memory cũ giữ nguyên
không dùng last-write-wins
```

Cùng xác nhận:

```text
Dũng: Chốt PostgreSQL.
Minh: Đồng ý, PostgreSQL.
```

Kết quả:

```text
một active memory PostgreSQL
hai source: primary + confirmation
```

## Fact key

- `db_backend`, `backend_database` không được tạo thành fact mới tùy ý.
- Model phải map về `project.database_backend`.
- Candidate chưa đăng ký phải pending.

- Nâng extractor schema `v1 → v2` phải chạy benchmark và dry-run trước.
- Proposal v1 vẫn giữ nguyên để audit.
- Backfill schema mới không được tự động áp dụng nếu chưa qua validator.

## Qdrant

- Guild isolation.
- Missing vector.
- Stale vector.
- Collection reset.
- Rebuild từ PostgreSQL.
- Superseded memory không retrieve cho current facts.

## Proposal và memory expiration

Proposal:

```text
pending proposal có expires_at < now
→ chuyển expired/rejected theo policy
→ không được apply
→ không tạo Qdrant job
```

Memory tạm thời:

```text
active memory có expires_at < now
→ chuyển expired
→ không được retrieve cho current facts
→ Qdrant point được xóa/cập nhật qua outbox
```

Race condition:

```text
proposal hết hạn trong lúc worker chuẩn bị apply
→ worker recheck expires_at trong transaction
→ không apply nếu đã hết hạn
```

## Privacy

- `/memory show-me` không hiển thị memory người khác.
- `/memory forget-me` chỉ tác động trong guild hiện tại.
- Production log không chứa message content.
- Purge cần admin + confirmation + rate limit.

---

# 14. Kế hoạch Agile

## Release 1 — Conversation Memory MVP

### Sprint 0 — Audit

Công việc:

- audit conversation hiện tại per-user/per-channel;
- xác định mapping RAM/Redis/PostgreSQL;
- đọc schema conversations/messages/memories;
- xác định backend conversation lifecycle;
- audit mention/full-message, thread/forum và UI memory coupling;
- tạo `docs/discord_memory_audit.md`.

Acceptance Criteria:

- Không sửa runtime trong Sprint 0.
- Không đoán schema hoặc endpoint.
- Tài liệu audit liệt kê file, bảng, API và rủi ro migration.
- Test hiện tại vẫn giữ nguyên trạng thái.
- Có quyết định rõ về migration per-user → per-channel/per-thread.

### Sprint 1 — Persistent sessions

Công việc:

- Alembic migration;
- session per-channel/per-thread;
- guild isolation;
- backend orphan recovery;
- CHECK/unique constraints.

Acceptance Criteria:

- Hai user cùng channel dùng chung session.
- Hai channel/guild khác nhau không dùng chung session.
- Thread có session riêng.
- Restart bot vẫn khôi phục session.
- Backend conversation bị xóa được phục hồi mà không retry vô hạn.

### Sprint 2 — Raw messages + attribution

Công việc:

- lưu author/reply/edit/delete;
- context builder;
- token limits;
- index PostgreSQL.

Acceptance Criteria:

- Mỗi message idempotent theo `discord_message_id`.
- Bot phân biệt đúng người nói và reply chain.
- Edit cập nhật row cũ; delete dùng soft delete.
- Context không vượt token budget.
- Production log không ghi message content.

### Sprint 3 — Async rolling summary

Công việc:

- queue `conversation_summary`;
- summary version;
- cursor `(created_at, message_id)`;
- summary không chặn chat.

Acceptance Criteria:

- Trigger đúng theo số message chưa summarize.
- Summary job retry được và idempotent.
- Không tóm tắt trùng hoặc bỏ sót message.
- Trong lúc chờ, bot dùng summary cũ + recent unsummarized messages.
- Summary giữ attribution, quyết định và vấn đề còn mở.

## Release 2 — Structured Memory

### Sprint 4 — Rule filter

Acceptance Criteria:

- Bỏ qua lời chào, emoji, spam, command và bot message.
- Channel tắt long-term memory không tạo extraction job.
- Câu cập nhật rõ ràng vẫn được chuyển sang extractor.
- Rule output có reason code.
- Có unit test precision/recall cho rule filter trên tập mẫu.

### Sprint 5 — Model 2B benchmark

Acceptance Criteria:

- Model cụ thể là `qwen3.5:2b`, cấu hình ngoài code và chạy non-thinking.
- Request benchmark dùng JSON Schema object, `temperature=0.0`, `seed=42`, `stream=false`, context 4096.
- Có 100–300 case tiếng Việt được version hóa.
- Đo invalid JSON rate, schema violation rate, remember/ignore precision, operation accuracy và fact-key accuracy.
- Chạy lặp cùng input để đo độ ổn định.
- Test sau restart Ollama và trên đúng phiên bản dự kiến dùng production.
- Có baseline, báo cáo benchmark, Ollama version và model digest/tag.
- Chưa bật auto-apply trong sprint này.

### Sprint 6 — Dry-run extractor

Acceptance Criteria:

- Output tuân thủ JSON Schema.
- Mọi proposal được lưu vào `discord_memory_proposals`.
- Dry-run không sửa `discord_memories` và không index Qdrant.
- Idempotency theo message + schema version.
- Lỗi model/JSON không làm worker crash.

### Sprint 7 — Fact key registry

Acceptance Criteria:

- Có registry table và seed các fact key phổ biến.
- Normalize lowercase/dot/underscore hoạt động ổn định.
- Fact key chưa đăng ký luôn vào pending review.
- Sensitive/auto-apply policy được enforce ở backend.
- `db_backend` và biến thể được map về canonical key hoặc bị pending.

### Sprint 8 — Versioned memory store

Acceptance Criteria:

- Mỗi canonical fact chỉ có tối đa một active value.
- Replace chạy atomically với `superseded` + `active`.
- Memory giữ source và `origin_proposal_id`.
- `valid_from`, `valid_until`, `expires_at` hoạt động đúng.
- Rollback không để trạng thái dở dang.

### Sprint 9 — Validator + conflict resolver

Acceptance Criteria:

- Validate schema, guild, scope, fact key, operation và permission.
- Threshold chỉ là một tín hiệu, không bypass sensitive policy.
- Conflict trong cửa sổ thời gian chuyển tất cả proposal sang pending.
- Hai proposal cùng giá trị được merge source và chỉ apply một lần.
- Không dùng last-write-wins cho contradictory values.

### Sprint 10 — Memory worker + outbox

Acceptance Criteria:

- Durable job và outbox được tạo cùng transaction.
- Worker retry/backoff và heartbeat hoạt động.
- Một message không tạo memory hai lần.
- Chat path không bị block bởi extractor.
- Failed job có metric và trạng thái phục hồi được.

## Release 3 — Retrieval

### Sprint 11 — Qdrant indexing queue

Acceptance Criteria:

- Queue riêng `qdrant_index`.
- PostgreSQL commit trước khi tạo/upsert vector.
- Retry 1/3/10 giây; hết retry → `pending_reindex`.
- Payload luôn có `guild_id`, `memory_id`, `fact_key`, `status`.
- Superseded/deleted memory không còn active vector.

### Sprint 12 — Exact lookup

Acceptance Criteria:

- Intent có thể map câu hỏi phổ biến sang canonical fact key.
- Query exact luôn filter `guild_id` + `status=active`.
- Exact hit được ưu tiên trước semantic.
- Có metric exact hit/miss.
- Current question không nhận historical value.

### Sprint 13 — Semantic retrieval

Acceptance Criteria:

- Qdrant query filter guild ngay tại vector DB.
- Có giới hạn top-k và token budget.
- Superseded/disputed/deleted không vào current context.
- Paraphrase tìm được memory liên quan.
- Stale/missing point không làm lộ memory từ guild khác.

### Sprint 14 — Reconciliation + rebuild

Acceptance Criteria:

- Script hỗ trợ `--dry-run`, `--guild-id`, `--batch-size`, `--delete-stale`.
- Phát hiện missing, stale, orphan và sai payload.
- Rebuild collection từ PostgreSQL active memories.
- Chạy lại idempotent.
- Có metric/summary created, updated, deleted, skipped, failed.

## Release 4 — Governance

### Sprint 15 — Slash commands

Acceptance Criteria:

- `/memory show-me` chỉ xem memory của chính người gọi trong guild hiện tại.
- Pending approve/reject kiểm tra quyền admin.
- Có pagination.
- Purge yêu cầu confirmation và rate limit.
- Mọi thao tác quản trị có audit log.

### Sprint 16 — Retention/privacy

Acceptance Criteria:

- Cleanup áp dụng đúng retention từng loại proposal.
- Pending proposal có `expires_at` quá hạn chuyển `expired/rejected` và không bao giờ được apply.
- Apply worker recheck `expires_at` bên trong transaction để tránh race condition.
- Active memory hết hạn chuyển `expired` và bị loại khỏi retrieval/Qdrant.
- Không xóa proposal đang được active memory tham chiếu nếu chưa giữ audit snapshot.
- Forget/purge xóa đồng bộ PostgreSQL và Qdrant.
- Không lưu binary attachment hoặc secret trong log.

### Sprint 17 — Metrics/alerts/operations

Acceptance Criteria:

- Health check cho memory, summary và Qdrant workers.
- Alert cho failed jobs, pending reindex, stale points và proposal backlog.
- Có dashboard hoặc endpoint metrics tối thiểu.
- Backup/restore PostgreSQL được kiểm thử.
- Rebuild Qdrant drill chạy thành công.

### Quy tắc chuyển Release

Không chuyển Release nếu Sprint bắt buộc trước đó chưa đạt Acceptance Criteria và chưa có kết quả test được ghi lại.

# 14.1. Gate bắt buộc trước khi Codex bắt đầu Sprint 0

Config đã chốt trong tài liệu:

```yaml
extractor:
  model: "qwen3.5:2b"
  thinking: false
  ollama_format: "json_schema"
  json_schema_path: "config/discord_memory_extractor_schema_v1.json"
  fallback_ollama_format: "json"
  temperature: 0.0
  seed: 42
  stream: false
  schema_version: "v1"
  context_tokens: 4096
```

Lưu ý:

- Sprint 0 chỉ audit, chưa tích hợp model.
- Sprint 5 mới được phép kết luận cấu hình trên đủ ổn định cho production.
- Không coi `temperature=0.0` là bằng chứng duy nhất của tính deterministic.
- Không bật auto-apply nếu compatibility gate chưa đạt.
- Conflict window mặc định ban đầu là 15 giây.

# 15. Definition of Done

Hệ thống chỉ hoàn tất khi:

- Session chung theo channel/thread.
- Bot biết rõ ai nói từng câu.
- Restart không mất session.
- Backend conversation orphan được phục hồi.
- Guild isolation được enforce ở DB và Qdrant.
- Summary chạy bất đồng bộ và dùng cursor `(created_at, message_id)`.
- Fact key có registry và normalize.
- Model cụ thể `qwen3.5:2b` chạy benchmark và dry-run trước auto-apply.
- Structured output compatibility với phiên bản Ollama production đã được xác nhận và ghi lại.
- Extractor schema upgrade có benchmark, shadow dry-run và audit.
- Model không sửa DB trực tiếp.
- Backend validator kiểm soát mọi proposal.
- Conflict gần thời gian không dùng last-write-wins.
- Proposal retention và expiration hoạt động.
- Mỗi fact chỉ có một active value.
- Source message được lưu.
- Exact lookup chạy trước semantic search.
- Qdrant indexing dùng queue riêng.
- Có retry, pending_reindex và reconciliation.
- Có rebuild từ PostgreSQL.
- Message edit/delete được reevaluate.
- `/memory show-me` đúng phạm vi.
- Purge có admin, confirmation và rate limit.
- Production log không chứa message content.
- Bộ test Discord memory chạy thành công.

---

# 16. Workflow tổng kết

```text
Discord Message
        ↓
Guild/Channel/Thread Validation
        ↓
Persistent Shared Session
        ↓
Raw Message PostgreSQL
        ├──────────────────────────────────┐
        ↓                                  ↓
Online Chat Path                     Async Memory Path
        ↓                                  ↓
Exact Active Facts                    Rule Filter
        ↓                                  ↓
Semantic Retrieval nếu cần            Durable Job + Outbox
        ↓                                  ↓
Session Summary + Recent Messages      Model 2B Extractor
        ↓                                  ↓
Chat Model                             Backend Validator
        ↓                                  ↓
Discord Response                       Dry-run / Pending / Apply
                                           ↓
                                  Versioned PostgreSQL Memory
                                           ↓
                                    Qdrant Index Queue
                                           ↓
                                  Reconciliation / Rebuild
```
