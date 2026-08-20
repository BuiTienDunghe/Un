# Changelog

Mọi thay đổi đáng chú ý của Local AI Core được ghi tại đây.

Định dạng theo [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
phiên bản tuân theo [Semantic Versioning 2.0.0](https://semver.org/lang/vi/).

Quy ước version của dự án: `1.0.0` là **ảnh chụp nền** của hệ thống tại thời điểm
có kế hoạch phát triển chính thức. Mỗi phase trong `docs/DEVELOPMENT_PLAN.md`
đóng lại thì tăng một minor version.

## [Unreleased]

### Added
- **Chế độ tài khoản admin/member** (P3-1): bật `LOCAL_AI_AUTH_ENABLED` (kèm
  `LOCAL_AI_JWT_SECRET` ≥32 ký tự và `LOCAL_AI_API_KEY` — validator ép đủ, mặt
  HTTP fail-closed) là web thành nhiều người dùng: người đầu tiên đăng ký làm
  quản trị viên rồi tạo tài khoản cho người khác; đăng nhập JWT (access 15
  phút + refresh thu hồi được); hội thoại thuộc về từng người (người khác nhìn
  vào là 404), member không xóa/sửa được tài nguyên chung (tài liệu, memory,
  các trang quản trị — 403). Bot Discord, eval và smoke test giữ nguyên lane
  X-API-Key. Tắt cờ là trở về đúng chế độ một-người-dùng zero-setup như cũ.
  Migration `20260820_23` (users, refresh_tokens, conversations.user_id).
- **Điều khiển bot Discord từ dashboard** (P3-2): nút Bật/Tắt + trạng thái đọc
  thẳng từ `docker compose ps` — cùng cơ chế run-discord-bot.bat nên không thể
  lệch thực tế.
- **Biểu đồ 14 ngày trên dashboard** (P3-3): câu hỏi/lỗi mỗi ngày và độ trễ
  p50/p95 từ `request_logs`, SVG tự vẽ không cần thư viện.
- **OCR Console** (P3-4): trang `/ui/ocr.html` — upload, theo dõi tiến độ theo
  trang, xem kết quả, đưa thành tài liệu, tải zip, quản lý lịch sử; không cần
  curl. **Phase P3 (Đa người dùng & quản trị) đóng.**
- **Guard xác định cho memory tự áp dụng** (P2-1b): tự áp dụng đòi evidence
  trích **nguyên văn** từ tin gốc và fact **trùng từ-nội-dung** với tin gốc —
  benchmark chứng minh confidence là hằng 1.0 kể cả khi sai nên ngưỡng τ chỉ còn
  là công tắc. Extractor mặc định chuyển `qwen3.5:2b` → `qwen3.5:9b` (2b để lọt
  ~49% fact độc, không harness nào cứu được — xem `docs/p2_progress.md`).
  Đề xuất trượt guard chờ người duyệt, không mất gì.
- **Lệnh Discord `/memory` và `/status`** (P2-3): xem điều agent đang nhớ về
  chính mình trong server (ephemeral, phân biệt 🤖/👤) và sức khỏe hệ thống rút
  gọn. Bộ lệnh chốt: `/ask · /docs · /memory · /status · /ping`.
- **Nhật ký hành động agent** (P2-4): panel dòng thời gian trên dashboard +
  `GET /agent/activity` — quyết định memory (nhớ/từ chối/thu hồi), câu trả lời
  dùng công cụ, việc nền; hàng còn gỡ được có nút Thu hồi ngay tại chỗ.
  **Phase P2 (Agent tự hành) đóng.**
- **Chế độ agent — tool use** (P2-2): bật chip «Công cụ» trên web (cờ `use_tools`
  của `/chat`) hoặc `DISCORD_AGENT_TOOLS_ENABLED` cho bot — model tự quyết định
  gọi công cụ (tìm tài liệu kèm nguồn, đọc trí nhớ dài hạn, xem trạng thái hệ
  thống) trước khi trả lời, tối đa `agent.max_steps` vòng. Mỗi bước lưu bảng
  `agent_traces` (migration `20260819_22`) gắn với câu trả lời, xem lại qua
  `GET /agent/traces/{message_id}` và hiện ngay dưới câu trả lời trên web.
  Tool lỗi trở thành dữ liệu cho model xoay xở, không làm hỏng câu trả lời.
- **Memory tự áp dụng theo ngưỡng tin cậy** (P2-1): đề xuất có confidence ≥
  `DISCORD_MEMORY_AUTO_APPLY_THRESHOLD` (mặc định 0.8, `off` để tắt) được agent
  tự approve qua đúng đường duyệt (`reviewed_by="agent"` — audit và mirror y hệt
  người duyệt); dưới ngưỡng vẫn chờ trên dashboard; đề xuất xóa luôn chờ người.
  Panel mới «Memory đang hiệu lực» cho biết ai duyệt (🤖/👤) kèm nút **Thu hồi**
  1 click (giữ nguyên sử liệu). Approve giờ định tuyến create/supersede/revive:
  fact đổi ý ra version mới + gỡ mirror cũ, và học lại được sau thu hồi — trước
  đó fact cập nhật lần hai kẹt 409 vĩnh viễn.
- **Discord RAG — lệnh `/docs`** (P1-1, ra mắt với tên `/hoi`): hỏi đáp tài liệu ngay trong Discord, chọn tài liệu
  bằng autocomplete hoặc bỏ trống để tìm tất cả; câu trả lời kèm footer nguồn gọn
  (`[1,3] file.pdf · trang 5`) giữ nguyên ánh xạ `[Source n]`. Gọi thẳng `/rag/chat` với
  timeout dài; lượt hỏi persist vào hội thoại session của kênh nên sidebar web không rác.
- **Condense-question trước retrieval** (P1-2): câu hỏi nối tiếp được model viết lại thành
  câu độc lập rồi mới retrieval; lượt đầu và mọi lỗi condense đều rơi về nguyên trạng.
  Bản viết lại phơi ra trường `retrieval_question`; công tắc `rag.condense_enabled`.
  Kèm bộ eval hội thoại 10 cặp tiếng Việt và chế độ `--conversation-dataset` trong
  harness, tự đo cả baseline không-condense để chứng minh mức cải thiện.
- **Memory extractor chế độ đề xuất** (P1-3): bật qua `.env`, launcher tự pull
  `qwen3.5:2b`, khởi động outbox dispatcher + memory worker trên host
  (`scripts/memory_worker.py`, SimpleWorker vì Windows không fork). Candidate nằm ở
  `pending/deferred` chờ duyệt — không tồn tại đường code nào tự áp dụng memory.
- **Duyệt memory trên dashboard** (P1-4): panel "Đề xuất ghi nhớ chờ duyệt" với nút
  Duyệt/Từ chối; API `/api/memory-review/*` (approve/reject là endpoint ghi, cần
  `X-API-Key` khi bật khóa); audit trail đầy đủ (`reviewed_at`, `reviewed_by`,
  decision) — từ chối chỉ ghi lại, không xóa gì.
- **Hợp nhất kho memory** (P1-5): duyệt một đề xuất Discord thì `canonical_fact`
  được mirror (idempotent, id `mem_dc_*`) vào kho `/memory` mà web chat «Ghi nhớ»
  sử dụng — trợ lý web dùng được điều học từ Discord. Phase P1 đóng.
- Nhật ký thi công P1 kèm lý do từng quyết định: `docs/p1_progress.md`.
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
- **Định hướng agent-first** (19/08, plan bản 1.1): thêm phase P2 «Agent tự hành» — memory
  tự áp dụng theo ngưỡng tin cậy (người giám sát + thu hồi thay vì duyệt tay), vòng lặp
  tool-use, nhật ký hành động agent. Lệnh Discord `/hoi` đổi tên **`/docs`** (tham số
  `document`) cho bộ lệnh tiếng Anh nhất quán với `/ask`, `/ping`.
- Outbox dispatcher đòi lại event kẹt `processing` quá hạn (T4): dispatcher chết giữa
  mark và publish không còn làm kẹt job vĩnh viễn; re-publish an toàn nhờ dedupe.
- Model SQLAlchemy và migration đã khớp nhau: tạo 13 index mà model khai báo nhưng chưa
  migration nào tạo, sửa 17 khai báo model nói sai về database (P0-6, migration `20260818_21`).
- `outbox_events.idempotency_key` chuyển sang `NOT NULL` — giá trị NULL vô hiệu hóa
  chống trùng lặp vì PostgreSQL coi các NULL là khác nhau trong unique index.
- Phiên bản ứng dụng đọc từ `app.__version__` thay cho chuỗi cứng.

### Fixed
- Bộ test không còn làm bẩn Qdrant dùng chung: collection memory của test tách riêng
  (`QDRANT_MEMORIES_COLLECTION=memories_test`); trước đó embed mock 3 chiều đã tạo
  collection `memories` sai chiều, khiến mọi thao tác ghi memory thật (1024 chiều)
  thất bại với dimension mismatch. Collection bẩn đã được xác minh toàn rác test và xóa.
- Ba test migration khôi phục database về revision ghim cứng thay vì `head`, khiến toàn bộ
  test chạy sau đó thất bại khi có migration mới.
- Từ audit toàn dự án 18/08 (58 phát hiện, xác minh đối kháng): dashboard gửi kèm
  `X-API-Key` (trước đó vỡ hoàn toàn khi bật `LOCAL_AI_PROTECT_READS`); ô nhập khóa dùng
  đúng design token (trước đó tham chiếu 5 biến CSS không tồn tại); race khi chuyển hội
  thoại giữa lúc đang stream không còn ghi đè/xóa nhầm ID và kẹt skeleton; cache tiêu đề
  cục bộ được dọn theo danh sách server và không còn che tên đã đổi trên server; launcher
  khởi động cleanup worker (trước đó xóa tài liệu kẹt `deleting` vĩnh viễn ở bản cài mặc
  định); trạng thái `cancel_requested` trả về giá trị thật thay vì luôn `false`;
  `enqueue_in` dùng `timedelta` đúng chuẩn RQ 2.x; chat thường không còn rò vỏ hội thoại
  rỗng khi model lỗi ở lượt đầu; hai nhánh stream/non-stream của `/rag/chat` dùng chung
  một mapping nguồn qua schema.

### Removed
- Chuyển 29 báo cáo lịch sử (migration SQLite→PostgreSQL, sprint Discord memory) vào
  `docs/archive/`; xóa 1 tài liệu prompt đã thực thi và 2 script one-shot hết nhiệm vụ.
  `docs/` giờ chỉ còn tài liệu sống mô tả hệ thống hiện tại.

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
