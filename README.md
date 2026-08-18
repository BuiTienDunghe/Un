# Local AI Core

[![CI](https://github.com/BuiTienDunghe/Un/actions/workflows/ci.yml/badge.svg)](https://github.com/BuiTienDunghe/Un/actions/workflows/ci.yml)

**Local AI Core** là nền tảng trợ lý AI tự lưu trữ dành cho trò chuyện, hỏi đáp tài liệu và hỗ trợ công việc với mô hình chạy cục bộ. Hệ thống kết hợp quản lý tài liệu có version, OCR, tìm kiếm ngữ nghĩa và RAG để tạo câu trả lời có dẫn nguồn. Bot Discord **Ún** là kênh sử dụng tùy chọn, kết nối trực tiếp với cùng backend này.

## Trạng thái sản phẩm

Local AI Core vận hành theo kiến trúc **PostgreSQL-only**. PostgreSQL là source of truth duy nhất cho toàn bộ dữ liệu nghiệp vụ; Qdrant chỉ là chỉ mục vector cho retrieval. SQLite không còn được runtime sử dụng.

Các tính năng cốt lõi đã sẵn sàng để vận hành gồm chat AI, document ingestion, OCR, indexing bất đồng bộ, RAG có citation, versioning tài liệu, theo dõi sức khỏe dịch vụ và Discord bot Ún.

## Khả năng nổi bật

### Trợ lý AI cục bộ

- Trò chuyện tổng quát với mô hình cục bộ.
- Quản lý hội thoại và lịch sử phiên chat.
- Cấu hình model chat, embedding, vision và OCR theo môi trường triển khai.
- Giao diện web và API FastAPI dùng chung một backend.

### Quản lý và khai thác tài liệu

- Upload PDF, DOCX, TXT và Markdown.
- Lưu bản gốc, trích xuất nội dung, OCR khi tài liệu scan hoặc thiếu text layer.
- Chia nội dung thành chunk, tạo embedding và index bất đồng bộ.
- Hỏi đáp RAG theo tài liệu đã index, trả về citation theo đoạn nguồn.
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
| Web UI | Chat, quản lý tài liệu, theo dõi tác vụ và tình trạng hệ thống. |
| FastAPI | API, JWT, hội thoại, upload, RAG và nghiệp vụ ứng dụng. |
| PostgreSQL 16 | Dữ liệu chuẩn: users, conversations, documents, versions, chunks, jobs, outbox và metadata. |
| Redis + RQ | Hàng đợi và điều phối tác vụ nền. |
| OCR worker | Trích xuất/OCR nội dung tài liệu. |
| Index worker | Chunking, embedding và index vector theo version. |
| Outbox dispatcher | Phát tác vụ nghiệp vụ đáng tin cậy từ PostgreSQL. |
| Cleanup worker | Thực thi retention policy đã cấu hình. |
| Qdrant | Chỉ mục vector phục vụ retrieval. |
| Ollama | Cung cấp model AI chạy cục bộ. |
| Docker Compose | Điều phối các dịch vụ runtime. |
| Discord bot Ún | Client Discord tùy chọn gọi API backend. |

Luồng dữ liệu chính là: tệp gốc → PostgreSQL lưu document/version và metadata → OCR/index worker → chunks chuẩn trong PostgreSQL → vector versioned trong Qdrant → RAG xác thực version active từ PostgreSQL trước khi trả lời.

## Dữ liệu và retrieval

Tệp gốc được lưu theo document ID trong thư mục dữ liệu của hệ thống. PostgreSQL lưu trạng thái và dữ liệu chuẩn của document, version, chunk, citation và tác vụ. Qdrant lưu vector theo định danh versioned.

Runtime chỉ truy vấn Qdrant point có đầy đủ `version_id` và `chunk_id`, đồng thời xác minh version active trong PostgreSQL. Point Qdrant legacy chỉ có `index_version` không được runtime retrieval hoặc cleanup sử dụng. Việc dọn legacy Qdrant points bị hoãn cho tới khi có phê duyệt và evidence độc lập.

## Discord bot Ún

Ún giúp sử dụng Local AI Core trong Discord mà không nhân bản logic AI/RAG ra bot.

- `/ping` kiểm tra bot có phản hồi.
- `/ask` gửi câu hỏi tới backend Local AI Core.
- Mention `@Ún` trong kênh rồi đặt câu hỏi để chat tự nhiên.
- Tính cách bot được cấu hình riêng trong `discord_bot/system_prompt.md`.
- Bot có thể gửi ngữ cảnh server gồm tên server, số thành viên và tối đa 100 display name của thành viên không phải bot. Giới hạn này điều chỉnh được qua `DISCORD_MEMBER_CONTEXT_LIMIT`.
- Discord token chỉ được đọc từ `DISCORD_TOKEN` trong môi trường cục bộ; token không thuộc source code, README hay commit.

Để bot nhận mention và đọc thông tin thành viên, cần bật **Message Content Intent** và **Server Members Intent** trong Discord Developer Portal, tại trang Bot. Discord bot là service tùy chọn, không ảnh hưởng đến các dịch vụ cốt lõi khi không chạy.

`run-discord-bot.bat` chạy bot ở foreground. Đóng cửa sổ chạy hoặc nhấn Ctrl+C sẽ dừng bot. Bot cần backend đã sẵn sàng và file `.env` cục bộ có cấu hình Discord/backend hợp lệ.

## Vận hành và độ tin cậy

- Endpoint `/health` theo dõi FastAPI, PostgreSQL, Redis, Qdrant, Ollama và các worker chính.
- PostgreSQL backup và Qdrant snapshot là các điểm phục hồi trước thay đổi quan trọng.
- Restore phải được kiểm chứng trong môi trường cô lập trước khi áp dụng vào môi trường vận hành.
- Cleanup tuân theo retention policy; không được dùng cleanup thường kỳ để xóa dữ liệu có giá trị khôi phục.
- Thay thế tài liệu không ghi đè version đang hoạt động trước khi version mới hoàn tất.
- SQLite archive lịch sử chỉ dành cho migration/audit read-only, không được đưa lại vào runtime path.

Alembic head hiện tại là `20260813_19`.

## Model mặc định

| Vai trò | Model mặc định |
| --- | --- |
| Chat tổng quát và RAG | qwen3.5:9b |
| Embedding | qwen3-embedding:0.6b |
| Vision | qwen3.5:9b |
| OCR | glm-ocr:latest |

RAG mặc định sử dụng chunk khoảng 480 tokens, overlap 80 tokens và tối đa 5 chunk ngữ cảnh. Các thông số có thể được điều chỉnh cho phù hợp với phần cứng, model và loại tài liệu.

## Yêu cầu vận hành

- Docker Desktop hoặc môi trường Docker Compose tương thích.
- Ollama và các model được cấu hình cho hệ thống.
- PostgreSQL, Redis và Qdrant thông qua stack Docker Compose.
- File `.env` cục bộ với thông số database, JWT, model và các service cần thiết.
- Nếu dùng Discord: `DISCORD_TOKEN`, thông tin backend và privileged intents đã được cấp trên Discord Developer Portal.

Không commit file `.env`, token Discord, JWT secret, mật khẩu database, backup riêng tư hoặc dữ liệu upload thực tế.

## Giới hạn cần biết

- Chất lượng câu trả lời phụ thuộc vào model cục bộ, phần cứng và chất lượng tài liệu đã index.
- Tài liệu chỉ dùng được trong RAG sau khi pipeline OCR/index thành công.
- Citation phản ánh phần nội dung đã trích xuất được từ tài liệu nguồn.
- Bot Ún cần Discord gateway, token hợp lệ, privileged intents và backend hoạt động.
- Ngữ cảnh thành viên Discord cần được sử dụng phù hợp với chính sách riêng tư của từng server.
- Mapping hội thoại Discord hiện nằm trong bộ nhớ tiến trình bot; sau khi bot khởi động lại, tin nhắn tiếp theo sẽ bắt đầu một phiên backend mới.

## Kiểm thử và CI

Mỗi pull request và mỗi lần push vào `main` đều chạy `.github/workflows/ci.yml` với ba job:

| Job | Chạy trên | Nội dung |
| --- | --- | --- |
| Static checks | Ubuntu | `compileall` toàn bộ Python, `node --check` cho script giao diện, kiểm tra các file YAML cấu hình parse được |
| Backend tests | Ubuntu + service container PostgreSQL 16 và Redis 7 | `alembic upgrade head` rồi `pytest backend/tests`, cuối cùng khẳng định database vẫn ở head |
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

Ba test migration cố ý hạ cấp database để kiểm tra một revision theo cả hai chiều, rồi khôi phục về `head` trong `finally`. Nếu một test mới hạ cấp mà không khôi phục, bước cuối của job backend sẽ báo lỗi ngay thay vì để các test sau thất bại vì schema cũ.

## Tài liệu bổ sung

- `docs/current_architecture.md`: kiến trúc và cấu hình vận hành.
- `docs/versioned_ingestion.md`: vòng đời ingest và version tài liệu.
- `docs/postgres_migration.md`: migration và vận hành PostgreSQL.
- `docs/phase6_operations.md`: vận hành, kiểm tra và khắc phục sự cố.
- `docs/sqlite_to_postgres_final_report.md`: tổng kết migration SQLite sang PostgreSQL.
- `backend/tests/` và `tests/`: regression test cho API, persistence, workers, RAG và Discord API client.

## Định hướng phát triển

Kế hoạch phát triển tổng thể (phase, KPI, đối chiếu thị trường) nằm tại `docs/DEVELOPMENT_PLAN.md` — đây là tài liệu định hướng chính thức, thay cho danh sách dưới đây.

- Mở rộng chính sách retention và backup theo môi trường triển khai.
- Nâng độ bền vững của mapping hội thoại Discord qua lần khởi động lại bot.
- Bổ sung đánh giá retrieval/model theo bộ tài liệu thực tế.
- Chỉ thực hiện legacy Qdrant cleanup sau khi có mapping, evidence và phê duyệt riêng.
