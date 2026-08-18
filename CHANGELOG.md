# Changelog

Mọi thay đổi đáng chú ý của Local AI Core được ghi tại đây.

Định dạng theo [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
phiên bản tuân theo [Semantic Versioning 2.0.0](https://semver.org/lang/vi/).

Quy ước version của dự án: `1.0.0` là **ảnh chụp nền** của hệ thống tại thời điểm
có kế hoạch phát triển chính thức. Mỗi phase trong `docs/DEVELOPMENT_PLAN.md`
đóng lại thì tăng một minor version.

## [Unreleased]

### Added
- CI GitHub Actions chạy trên mọi pull request và push vào `main`: static check,
  bộ test backend với service container PostgreSQL 16 + Redis 7 + Qdrant, và bộ
  test bot/tools trên Windows (P0-1).
- Citation của câu trả lời RAG được lưu cùng tin nhắn trong bảng `message_sources`,
  nên mở lại hội thoại cũ vẫn thấy đủ nguồn như lúc trả lời (P0-3, migration `20260818_20`).
- Backup PostgreSQL tự động: worker định kỳ gọi `backup_postgres.py`, xoay vòng theo
  hạn lưu trữ, phơi độ tươi của bản backup ra `/health`; kèm tài liệu diễn tập restore
  `docs/backup_restore.md` (P0-4).
- `pyproject.toml` và `CHANGELOG.md`; `pip install -e .` hoạt động với layout hai gốc
  import của dự án (P0-5).
- Test chặn hồi quy schema: `alembic check` chạy trong CI và một test tương đương chạy
  cục bộ (P0-6).
- Xác thực lớp 1: header `X-API-Key` bảo vệ mọi endpoint ghi/xóa, cấu hình bằng
  `LOCAL_AI_API_KEY`; tùy chọn `LOCAL_AI_PROTECT_READS` khóa cả endpoint đọc. Giao diện web,
  bot Discord, bộ eval và smoke test đều gửi khóa (P0-2).

### Changed
- Model SQLAlchemy và migration đã khớp nhau: tạo 13 index mà model khai báo nhưng chưa
  migration nào tạo, sửa 17 khai báo model nói sai về database (P0-6, migration `20260818_21`).
- `outbox_events.idempotency_key` chuyển sang `NOT NULL` — giá trị NULL vô hiệu hóa
  chống trùng lặp vì PostgreSQL coi các NULL là khác nhau trong unique index.
- Phiên bản ứng dụng đọc từ `app.__version__` thay cho chuỗi cứng.

### Fixed
- Ba test migration khôi phục database về revision ghim cứng thay vì `head`, khiến toàn bộ
  test chạy sau đó thất bại khi có migration mới.

## [1.0.0] - 2026-08-18

Ảnh chụp nền của hệ thống đang vận hành: kiến trúc PostgreSQL-only đã hoàn tất, RAG có
dẫn nguồn đã đo được chất lượng, hai kênh web và Discord dùng chung backend.

### Added
- **Trợ lý AI cục bộ**: chat với model chạy trên máy qua Ollama, lưu toàn bộ lịch sử
  hội thoại, tiêu đề hội thoại sinh tự động, giao diện web không cần bước build.
- **Quản lý tài liệu có version**: upload PDF/DOCX/TXT/Markdown, nhận diện trùng lặp bằng
  SHA-256, mỗi tài liệu nhiều version, version cũ vẫn phục vụ tới khi version mới index xong.
- **OCR và ingestion bất đồng bộ**: OCR khi tài liệu thiếu text layer, chunking, embedding
  và index chạy qua hàng đợi Redis + RQ với transactional outbox, lease/heartbeat và
  idempotency key.
- **RAG có dẫn nguồn**: tìm kiếm lai dense (Qdrant) + BM25 tiếng Việt (pyvi) hợp nhất bằng
  RRF; câu trả lời trích dẫn theo tên tệp và số trang.
- **Bot Discord Ún**: cùng backend, phiên hội thoại bền qua khởi động lại, pipeline lượt
  FIFO đảm bảo thứ tự và không giao trùng.
- **Dashboard quản trị**: thống kê agent web và Discord, tình trạng dịch vụ, model và hàng đợi.
- **Vận hành**: `/health` theo dõi FastAPI, PostgreSQL, Redis, Qdrant, Ollama và các worker;
  cleanup worker theo retention policy; launcher một cú click cho Windows.
- **Bộ eval RAG tiếng Việt** 47 câu hỏi, dùng làm cửa kiểm soát chất lượng retrieval.

### Security
- Ở phiên bản 1.0.0 hệ thống **chưa có xác thực**: mọi endpoint mở với bất kỳ ai truy cập được
  cổng 8000. Xác thực lớp 1 được thêm sau đó (xem mục Unreleased). Dù vậy, đây vẫn là một khóa
  dùng chung chứ không phải phân quyền nhiều người dùng; đừng expose ra Internet.

### Giới hạn đã biết
- Trí nhớ web và Discord là hai hệ rời nhau (G2).
- Bot Discord chưa dùng được tài liệu, chỉ gọi `/chat` (G3).
- Câu hỏi nối tiếp chưa được viết lại trước khi retrieval, nên RAG hụt hơi trong hội thoại
  nhiều lượt (G5).
- Bộ eval mới phủ một tài liệu và đã bão hòa ở 100%, chưa đo được tiến bộ tiếp theo (G7).
- BM25 chạy trong tiến trình, giới hạn quy mô corpus (G8).

[Unreleased]: https://github.com/BuiTienDunghe/Un/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/BuiTienDunghe/Un/releases/tag/v1.0.0
