# Local AI Core

[![CI](https://github.com/BuiTienDunghe/Un/actions/workflows/ci.yml/badge.svg)](https://github.com/BuiTienDunghe/Un/actions/workflows/ci.yml)

*English overview: [README.en.md](README.en.md) — one page, with the measured results.
Kết quả đo tổng hợp: [docs/RESULTS.md](docs/RESULTS.md). Các sự cố đã gặp và cách bắt được
chúng: [docs/FAILURE_MODES.md](docs/FAILURE_MODES.md).*

**Local AI Core** là nền tảng trợ lý AI tự lưu trữ dành cho trò chuyện, hỏi đáp tài liệu và hỗ trợ công việc với mô hình chạy cục bộ. Hệ thống kết hợp quản lý tài liệu có version, OCR, tìm kiếm ngữ nghĩa và RAG để tạo câu trả lời có dẫn nguồn. Bot Discord **Ún** là kênh sử dụng tùy chọn, kết nối trực tiếp với cùng backend này.

## Trạng thái sản phẩm

Local AI Core vận hành theo kiến trúc **PostgreSQL-only**. PostgreSQL là source of truth duy nhất cho toàn bộ dữ liệu nghiệp vụ; Qdrant chỉ là chỉ mục vector cho retrieval. SQLite không còn được runtime sử dụng.

Các tính năng cốt lõi đã sẵn sàng để vận hành gồm chat AI, document ingestion, OCR, indexing bất đồng bộ, RAG có citation, versioning tài liệu, theo dõi sức khỏe dịch vụ và Discord bot Ún.

## Khả năng nổi bật

### Trợ lý AI cục bộ

- Trò chuyện tổng quát với mô hình cục bộ.
- Chế độ công cụ (agent, bật theo từng tin): model tự tra tài liệu (`search_documents`, `read_document`) và trạng thái hệ thống trước khi trả lời. Ở chế độ này tin nhắn dài được tới 100 000 ký tự (chat thường 10 000): đoạn dán vừa gửi đi nguyên văn khi cả prompt còn vừa cửa sổ của model, dài hơn thì model nhận một phiếu và đọc dần bằng `read_document`.
- Quản lý hội thoại và lịch sử phiên chat.
- Cấu hình model chat, embedding, vision và OCR theo môi trường triển khai.
- Giao diện web và API FastAPI dùng chung một backend.

### Quản lý và khai thác tài liệu

- Upload PDF, DOCX, TXT và Markdown.
- Lưu bản gốc, trích xuất nội dung, OCR khi tài liệu scan hoặc thiếu text layer.
- Chia nội dung thành chunk, tạo embedding và index bất đồng bộ.
- Hỏi đáp RAG theo tài liệu đã index, trả về citation theo đoạn nguồn.
- Citation được lưu cùng câu trả lời, nên mở lại hội thoại cũ vẫn thấy đủ nguồn như lúc trả lời.
- Tìm kiếm lai kết hợp vector search và BM25 để cải thiện độ liên quan.
- Theo dõi trạng thái upload, OCR và indexing.

### Versioning và chống trùng lặp

Mỗi tài liệu có một định danh logic, có thể có nhiều version. Nội dung được nhận diện bằng SHA-256 để xử lý trùng lặp một cách rõ ràng và an toàn.

| Trường hợp upload | Xử lý |
| --- | --- |
| Tên trùng, nội dung trùng | Dùng document hiện có hoặc hủy. Không tạo file, version, chunk hay vector mới. |
| Tên khác, nội dung trùng | Đổi tên document hiện có sang tên mới hoặc hủy. Không tạo document/version mới. |
| Tên trùng, nội dung khác | Thay bằng version mới, giữ cả hai document với tên phân biệt, hoặc hủy. |
| Tên khác, nội dung khác | Tạo document mới và version đầu tiên. |

Khi thay nội dung, version cũ vẫn active cho tới khi version mới OCR/index thành công. Cách này bảo đảm việc upload lỗi hoặc index lỗi không làm mất khả năng truy xuất tài liệu đang dùng.

## Kiến trúc

| Thành phần | Trách nhiệm |
| --- | --- |
| Web UI | Một trang duy nhất (`/ui/`, hash router, không build step) với 11 màn: Chat, Tài liệu, Nghiên cứu, Ghi nhớ, Bảng điều khiển, OCR, Bot Discord, Model, Người dùng, Cài đặt, Chunks. Link cũ `/ui/dashboard.html`, `/ui/ocr.html`, `/ui/chunks.html?document_id=` vẫn chạy nhờ redirect. |
| FastAPI | API, khóa truy cập X-API-Key (lớp 1), hội thoại, upload, RAG và nghiệp vụ ứng dụng. |
| PostgreSQL 16 | Dữ liệu chuẩn: users, conversations, documents, versions, chunks, jobs, outbox và metadata. |
| Redis + RQ | Hàng đợi tác vụ nền: job trí nhớ Discord (khi bật), và OCR/index chỉ khi đặt `INGESTION_EXECUTION_BACKEND=rq`. |
| OCR + index | Trích xuất/OCR, chunking, embedding và index vector theo version. Mặc định (`INGESTION_EXECUTION_BACKEND=thread`) chạy trong luồng phụ của chính tiến trình API; container `worker-ocr` / `worker-index` của compose chỉ dùng với `rq`, launcher không bật chúng. |
| Outbox dispatcher + memory worker | Đẩy job trí nhớ Discord từ PostgreSQL sang Redis và xử lý chúng; launcher chỉ bật khi `DISCORD_MEMORY_INGESTION_ENABLED=true`. |
| Cleanup worker | Thực thi retention policy đã cấu hình. |
| Backup worker | Dump PostgreSQL định kỳ, kèm bản lưu tệp gốc và `.env` (`docs/backup_restore.md`). |
| Qdrant | Chỉ mục vector phục vụ retrieval. |
| Ollama | Cung cấp model AI chạy cục bộ. |
| Docker Compose | Điều phối các dịch vụ runtime. |
| Discord bot Ún | Client Discord tùy chọn gọi API backend. |

Luồng dữ liệu chính là: tệp gốc → PostgreSQL lưu document/version và metadata → OCR/index (luồng phụ của API theo mặc định) → chunks chuẩn trong PostgreSQL → vector versioned trong Qdrant → RAG xác thực version active từ PostgreSQL trước khi trả lời.

## Dữ liệu và retrieval

Tệp gốc được lưu theo document ID trong thư mục dữ liệu của hệ thống. PostgreSQL lưu trạng thái và dữ liệu chuẩn của document, version, chunk, citation và tác vụ. Qdrant lưu vector theo định danh versioned.

Runtime chỉ truy vấn Qdrant point có đầy đủ `version_id` và `chunk_id`, đồng thời xác minh version active trong PostgreSQL. Point Qdrant legacy chỉ có `index_version` không được runtime retrieval hoặc cleanup sử dụng. Việc dọn legacy Qdrant points bị hoãn cho tới khi có phê duyệt và evidence độc lập.

## Discord bot Ún

Ún giúp sử dụng Local AI Core trong Discord mà không nhân bản logic AI/RAG ra bot.

- `/ping` kiểm tra bot có phản hồi.
- `/ask` gửi câu hỏi tới backend Local AI Core.
- `/docs` hỏi đáp theo tài liệu đã index (RAG): chọn tài liệu bằng autocomplete hoặc bỏ trống để tìm trong tất cả; câu trả lời kèm nguồn theo tên tệp và số trang.
- `/memory` cho riêng người gọi xem agent đang nhớ gì về họ trong server; `/status` cho riêng người gọi xem sức khỏe hệ thống.
- Mention `@Ún` trong kênh rồi đặt câu hỏi để chat tự nhiên. Lượt Discord chỉ chạy chế độ công cụ ở server có trong `DISCORD_AGENT_TOOLS_GUILD_ALLOWLIST` (mặc định rỗng: không server nào, mọi lượt là chat thường).
- Tính cách bot được cấu hình riêng trong `discord_bot/system_prompt.md`.
- Bot có thể gửi ngữ cảnh server gồm tên server, số thành viên và tối đa 100 display name của thành viên không phải bot. Giới hạn này điều chỉnh được qua `DISCORD_MEMBER_CONTEXT_LIMIT`.
- Discord token chỉ được đọc từ `DISCORD_TOKEN` trong môi trường cục bộ; token không thuộc source code, README hay commit.

Để bot nhận mention và đọc thông tin thành viên, cần bật **Message Content Intent** và **Server Members Intent** trong Discord Developer Portal, tại trang Bot. Discord bot là service tùy chọn, không ảnh hưởng đến các dịch vụ cốt lõi khi không chạy.

`run-discord-bot.bat` chạy bot ở foreground. Đóng cửa sổ chạy hoặc nhấn Ctrl+C sẽ dừng bot. Bot cần backend đã sẵn sàng và file `.env` cục bộ có cấu hình Discord/backend hợp lệ.

Ngoài ra còn hai công tắc: màn **Bot Discord** trên web bật/tắt cùng container `discord-bot` đó, còn `discord-bot-control.bat` mở panel chạy bot thẳng trên máy (không qua Docker). Hai đường thấy nhau: web từ chối bật bot thứ hai khi panel đang chạy một bot (`409 BOT_RUNNING_ON_HOST`).

## Vận hành và độ tin cậy

- Endpoint `/health` theo dõi FastAPI, PostgreSQL, Redis, Qdrant, Ollama, các worker chính và độ tươi của bản backup PostgreSQL.
- Khi bật memory đề xuất (`DISCORD_MEMORY_INGESTION_ENABLED=true`), launcher khởi động thêm outbox dispatcher và memory worker; candidate memory chờ duyệt, không gì tự áp dụng. Bật thêm extractor (`DISCORD_MEMORY_EXTRACTOR_ENABLED=true`) thì khác: đề xuất có độ tin ≥ 0,8 (`DISCORD_MEMORY_AUTO_APPLY_THRESHOLD`, đặt `off` để duyệt tay tất cả) và qua bộ kiểm bằng chứng tất định được agent tự áp dụng, ghi vết và hoàn tác được một cú click; đề xuất xoá luôn chờ người duyệt.
- Backup PostgreSQL chạy tự động cùng launcher (mặc định 24 giờ một bản, giữ 14 ngày). Xem `docs/backup_restore.md` cho bài diễn tập restore hàng quý.
- PostgreSQL backup và Qdrant snapshot là các điểm phục hồi trước thay đổi quan trọng.
- Restore phải được kiểm chứng trong môi trường cô lập trước khi áp dụng vào môi trường vận hành.
- Cleanup tuân theo retention policy; không được dùng cleanup thường kỳ để xóa dữ liệu có giá trị khôi phục.
- Thay thế tài liệu không ghi đè version đang hoạt động trước khi version mới hoàn tất.
- SQLite archive lịch sử chỉ dành cho migration/audit read-only, không được đưa lại vào runtime path.

Alembic head hiện tại là `20261027_35` (`20261027_35_agent_trace_summaries.py`).

## Model mặc định

Tên model không còn nằm trong `models.yaml`. Mỗi vai trò là một bản ghi có phiên bản trong
`backend/app/config/model_versions.yaml` với một con trỏ `active`; đổi model = sửa con trỏ đó
(hoặc `MODEL_VERSION_<ROLE>=<id>` trong shell cho riêng một máy) rồi khởi động lại. Bản active
hỏng lúc khởi động thì hệ tự lùi về bản trước và báo ở `/health` (`model_fallback`), `/models`
(`registry`) và `data/logs/ATTENTION_model_fallback.txt`; riêng embedding không bao giờ tự lùi.
Cách promote, demote, revert và rebuild collection: `docs/model_registry.md`.

| Vai trò | Phiên bản active | Model |
| --- | --- | --- |
| Chat tổng quát và RAG (`general`) | `general-v0` | qwen3.5:9b |
| Embedding (`embedding`) | `embedding-v0` | qwen3-embedding:0.6b — collection `documents` / `memories` |
| OCR (`ocr`) | `ocr-v1` | local-ai/glm-ocr:eot-v1 — glm-ocr:latest khai thêm token kết thúc, dựng tay một lần bằng `scripts.build_ocr_model` (`docs/model_registry.md`); máy chưa dựng thì lùi về `ocr-v0`, bản này không qua probe trên Ollama 0.34.x nên OCR thành `disabled` |
| Reranker (`reranker`) | `reranker-v0` | cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 |
| Extractor / verifier trí nhớ Discord | `extractor-v0` / `verifier-v0` | qwen3.5:9b (cả hai tắt mặc định: `DISCORD_MEMORY_EXTRACTOR_ENABLED` / `_VERIFIER_ENABLED`) |
| Condenser (Gemini, tắt mặc định) | `condenser-v0` | gemini-2.5-flash |
| Vision | `active: null` — chưa có gì dùng (`/vision/chat` trả 501) | — |

Ứng viên đám mây cho `general`: `general-haiku-v1` (claude-haiku-5-5) nằm sau v0 nên không bao
giờ tự phục vụ; dùng thử trên một máy bằng `MODEL_VERSION_GENERAL=general-haiku-v1` trong shell
với `ANTHROPIC_API_KEY` trong `.env`. Chạy được cả lượt công cụ của agent.

`cd backend && python -m app.config.model_registry --check` kiểm tra file (CI chạy mỗi commit);
`--show` in ra máy này sẽ phục vụ phiên bản nào.

RAG mặc định sử dụng chunk khoảng 480 tokens, overlap 80 tokens và tối đa 5 chunk ngữ cảnh. Các thông số có thể được điều chỉnh cho phù hợp với phần cứng, model và loại tài liệu.

## Yêu cầu vận hành

- Docker Desktop hoặc môi trường Docker Compose tương thích.
- Ollama và các model được cấu hình cho hệ thống.
- PostgreSQL, Redis và Qdrant thông qua stack Docker Compose.
- File `.env` cục bộ với thông số database, khóa truy cập (tùy chọn), model và các service cần thiết.
- Nếu dùng Discord: `DISCORD_TOKEN`, thông tin backend và privileged intents đã được cấp trên Discord Developer Portal.

Không commit file `.env`, token Discord, khóa `LOCAL_AI_API_KEY`, mật khẩu database, backup riêng tư hoặc dữ liệu upload thực tế.

## Truy cập và bảo mật

Mặc định hệ thống **không bật xác thực**: mọi endpoint đều mở với ai truy cập được cổng 8000.
Đó là lựa chọn có chủ đích cho máy cá nhân — đường "một cú click" không thể bắt bạn dán khóa
trước khi gửi tin nhắn đầu tiên.

Khi chia sẻ trong LAN, hãy bật khóa truy cập:

1. Sinh khóa: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Đặt vào `.env`: `LOCAL_AI_API_KEY=<khóa vừa sinh>`
3. Khởi động lại backend.
4. Trên web: **Cài đặt → Bảo mật → Khóa truy cập**, dán khóa rồi bấm Lưu.

Từ lúc đó mọi endpoint **ghi và xóa** yêu cầu header `X-API-Key`; thiếu hoặc sai key trả về 401.
Endpoint đọc vẫn mở để giao diện hoạt động ngay; đặt `LOCAL_AI_PROTECT_READS=true` để khóa
luôn cả endpoint đọc (`/health` và `/models` vẫn mở vì launcher và smoke test cần chúng).

Bot Discord đọc cùng biến `LOCAL_AI_API_KEY`; `docker-compose.yml` đã truyền sẵn vào container.
Nếu bật khóa mà quên cấu hình cho bot thì mọi lượt Discord sẽ bị từ chối.

Đây là xác thực **lớp 1**: một khóa dùng chung, không phải phân quyền nhiều người dùng.
Chế độ tài khoản (quản trị viên / thành viên, P3-1) có sẵn nhưng tắt mặc định: `LOCAL_AI_AUTH_ENABLED=true`
bắt buộc kèm `LOCAL_AI_JWT_SECRET` dài ít nhất 32 ký tự và `LOCAL_AI_API_KEY` (làn dịch vụ cho bot, eval,
smoke test), thiếu thì backend không khởi động. Người đăng ký đầu tiên trên web là quản trị viên; sau đó mọi
endpoint, kể cả đọc, cần đăng nhập hoặc khóa (trừ `/health`, `/models` và đăng nhập).

## Giới hạn cần biết

- Chất lượng câu trả lời phụ thuộc vào model cục bộ, phần cứng và chất lượng tài liệu đã index.
- Tài liệu chỉ dùng được trong RAG sau khi pipeline OCR/index thành công.
- Citation phản ánh phần nội dung đã trích xuất được từ tài liệu nguồn.
- Bot Ún cần Discord gateway, token hợp lệ, privileged intents và backend hoạt động.
- Ngữ cảnh thành viên Discord cần được sử dụng phù hợp với chính sách riêng tư của từng server.
- Phiên hội thoại Discord lưu bền trong PostgreSQL theo mặc định (`DISCORD_PERSISTENT_SESSIONS_ENABLED=true`, do `docker-compose.yml` và `.env.example` đặt; panel trên máy luôn bật); bot khởi động lại vẫn giữ ngữ cảnh. Tắt cờ này cho bot container thì mapping rơi về bộ nhớ tiến trình bot.

## Kiểm thử và CI

Mỗi pull request và mỗi lần push vào `main` đều chạy `.github/workflows/ci.yml` với bốn job:

| Job | Chạy trên | Nội dung |
| --- | --- | --- |
| Static checks | Ubuntu | `compileall` toàn bộ Python, `node --check` cho script giao diện, kiểm tra các file YAML cấu hình và `pyproject.toml` parse được, `python -m app.config.model_registry --check` |
| Backend tests | Ubuntu + service container PostgreSQL 16, Redis 7 và Qdrant | `alembic upgrade head` → `alembic check` (cửa chặn schema) → `pytest backend/tests`, cuối cùng khẳng định database vẫn ở head |
| Retrieval eval gate | Ubuntu + PostgreSQL 16, Redis 7, Qdrant và Ollama với model embedding | Bật API thật rồi chạy `scripts.evaluate_rag --retrieval-only` trên bộ đánh giá nhiều tài liệu, so với baseline "bare" (tắt contextual retrieval và reranker vì runner không có model sinh chữ lẫn extra `[rerank]`) |
| Bot and tools tests | Windows | `pytest tests` cho Discord API client, control panel và quy tắc định danh kênh; đồng thời chứng minh `requirements.txt` cài được sạch trên Windows |

Chạy đúng bộ kiểm thử đó tại máy cần một database cô lập có tên kết thúc bằng `_test` và Redis DB 15 — `backend/tests/conftest.py` từ chối mọi database khác:

```powershell
$env:POSTGRES_TEST_URL='postgresql+psycopg://local_ai:<mật khẩu>@127.0.0.1:5432/local_ai_core_test'
$env:REDIS_TEST_URL='redis://127.0.0.1:6379/15'
$env:DATABASE_URL=$env:POSTGRES_TEST_URL
.\.venv\Scripts\python.exe -m alembic upgrade head
cd backend; ..\.venv\Scripts\python.exe -m pytest tests -q; cd ..
.\.venv\Scripts\python.exe -m pytest tests -q
```

Bốn test migration cố ý hạ cấp database để kiểm tra một revision theo cả hai chiều, rồi khôi phục về `head` trong `finally`. Nếu một test mới hạ cấp mà không khôi phục, bước cuối của job backend sẽ báo lỗi ngay thay vì để các test sau thất bại vì schema cũ.

## Tài liệu bổ sung

- `docs/current_architecture.md`: kiến trúc và cấu hình vận hành.
- `docs/model_registry.md`: registry phiên bản model — promote, demote, revert, rebuild collection, fallback lúc khởi động.
- `docs/versioned_ingestion.md`: vòng đời ingest và version tài liệu.
- `docs/postgres_migration.md`: migration và vận hành PostgreSQL.
- `docs/phase6_operations.md`: vận hành, kiểm tra và khắc phục sự cố.
- `docs/backup_restore.md`: backup tự động và bài diễn tập restore.
- `CHANGELOG.md`: lịch sử phát hành theo Keep a Changelog và quy ước version.
- `docs/sqlite_to_postgres_final_report.md`: tổng kết migration SQLite sang PostgreSQL.
- `backend/tests/` và `tests/`: regression test cho API, persistence, workers, RAG và Discord API client.

## Định hướng phát triển

Kế hoạch phát triển tổng thể (phase, KPI, đối chiếu thị trường) nằm tại `docs/DEVELOPMENT_PLAN.md` — đây là tài liệu định hướng chính thức, thay cho danh sách dưới đây.

- Mở rộng chính sách retention và backup theo môi trường triển khai.
- Bổ sung đánh giá retrieval/model theo bộ tài liệu thực tế.
- Chỉ thực hiện legacy Qdrant cleanup sau khi có mapping, evidence và phê duyệt riêng.
