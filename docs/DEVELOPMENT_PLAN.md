# Kế hoạch phát triển tổng thể — Local AI Core

**Phiên bản:** 1.1 · **Ngày:** 15/08/2026 · **Cập nhật:** 19/08/2026 (định hướng agent-first) · **Trạng thái:** Đang hiệu lực
**Thay thế:** các định hướng rải rác trong README và `docs/discord_memory_workflow_plan_v5_final.md` (phần roadmap; phần thiết kế memory của tài liệu đó vẫn là spec cho P1-3..P1-5)

---

## 1. Tầm nhìn & định vị

> **Local AI Core là một agent AI cục bộ tự hành cho cá nhân và nhóm nhỏ: mọi dữ liệu ở trên máy của bạn, mọi câu trả lời có nguồn kiểm chứng được, các quy trình (ghi nhớ, index, dọn dẹp) do agent tự vận hành — con người giám sát thay vì duyệt tay. Vận hành bằng một cú click.**

So với các sản phẩm cùng phân khúc (Open WebUI, AnythingLLM, LibreChat), khác biệt chúng ta chọn để giữ và đào sâu:

1. **Tiếng Việt là công dân hạng nhất** — BM25 với pyvi, bộ eval tiếng Việt riêng, UI thuần Việt. Không dự án lớn nào làm tốt điều này.
2. **Citation-grounded triệt để** — câu trả lời tài liệu luôn có nguồn theo trang/đoạn; version tài liệu bất biến (Postgres là source of truth duy nhất).
3. **Một agent tự hành, nhiều bề mặt** — sản phẩm là agent có trí nhớ và công cụ, tự vận hành quy trình học/ghi nhớ; web và Discord là hai cửa truy cập cùng một agent (chung backend + bộ nhớ từ P1, Discord là kênh đồng hành chính).
4. **Vận hành tối giản** — một máy Windows + Docker + Ollama; không dịch vụ cloud bắt buộc.

### Nguyên tắc bất biến (không thương lượng khi thêm tính năng)

- PostgreSQL là nguồn dữ liệu chuẩn duy nhất; Qdrant chỉ là chỉ mục.
- Không transaction DB nào ôm qua lời gọi model.
- Migration chỉ additive; version tài liệu cũ sống tới khi version mới thành công.
- Mọi thay đổi chất lượng RAG phải qua bộ eval trước khi thành mặc định.
- Tính năng mới không phá đường "một cú click" (`run-local-ai-core.bat`).
- Hành động tự hành của agent (ghi nhớ, index, dọn dẹp) phải để lại audit trail và thu hồi được (bổ sung 19/08).

### Điều chỉnh định hướng 19/08/2026 — agent-first

Dự án chuyển trọng tâm từ "workspace hai kênh" sang **một agent tự hành**: các quy trình
(ghi nhớ, index, dọn dẹp) do agent tự thực hiện; con người **giám sát và thu hồi** thay vì
duyệt tay từng mục. Hệ quả trong plan:

- Thêm phase **P2 — Agent tự hành** (mới); các phase cũ lùi số: đa người dùng → P3,
  RAG nâng cao → P4, năng lực mở rộng → P5.
- Bộ lệnh Discord chuyển sang tên tiếng Anh chuyên nghiệp: `/hoi` → `/docs` (✅ 19/08);
  `/ask` sẽ thành cửa vào agent tự chọn tool ở P2-2.
- Nền human-review xây ở P1-4 **không bỏ đi** — nó trở thành lưới giám sát: hàng chờ cho
  candidate dưới ngưỡng tin cậy và nút thu hồi cho memory đã tự áp dụng.

---

## 2. Hiện trạng — đánh giá có số liệu (08/2026)

### Điểm mạnh đã kiểm chứng

| Hạng mục | Bằng chứng |
| --- | --- |
| Chất lượng RAG | Baseline đo ngày 14/08: **hybrid pass 100%, recall@5 100%, MRR 0.933** trên bộ 47 câu tiếng Việt (dense: 97.9% / MRR 0.810 → hybrid là mặc định có căn cứ) |
| Độ bền dữ liệu | Versioned ingestion + SHA-256 dedup + transactional outbox + lease/heartbeat worker |
| Discord pipeline | FIFO durable per-session, idempotent delivery, speaker attribution, đã bật persistent sessions |
| UI/UX | App chat hiện đại + dashboard quản trị, đã qua 2 vòng review đối kháng (17 lỗi xác nhận đã sửa) |
| Kiểm thử | 493 test backend + 59 test bot/tools chạy trong CI mỗi commit (Ubuntu + Windows); eval harness tự động cả single-turn lẫn hội thoại |

### Khoảng trống chính (xếp theo độ đau)

| # | Khoảng trống | Hệ quả |
| --- | --- | --- |
| ~~G1~~ ✅ | ~~**Không có xác thực**~~ — đã đóng lớp 1 bằng P0-2 (API key cho endpoint ghi/xóa); phân quyền nhiều người dùng vẫn thuộc P3 | ~~Ai trong LAN cũng xóa được dữ liệu~~ |
| ~~G2~~ ✅ | ~~**Trí nhớ hai hệ rời**~~ — đã đóng bằng P1-3..P1-5: extractor đề xuất → người duyệt trên dashboard → memory đổ vào kho chung mà web chat dùng | ~~"Agent có trí nhớ" mới chỉ tồn tại trên giấy~~ |
| ~~G3~~ ✅ | ~~**Discord chưa dùng được tài liệu**~~ — đã đóng bằng P1-1 (lệnh `/hoi`, nay là `/docs`, kèm nguồn) | ~~Nửa giá trị RAG không đến được kênh chat chính~~ |
| ~~G4~~ ✅ | ~~**Citation không lưu vào lịch sử**~~ — đã đóng bằng P0-3 (bảng `message_sources`) | ~~Mở lại hội thoại là mất nguồn~~ |
| ~~G5~~ ✅ | ~~**Câu hỏi nối tiếp không được viết lại**~~ — đã đóng bằng P1-2 (condense, eval 10/10, MRR 0.950 vs 0.787 baseline) | ~~RAG hụt hơi trong hội thoại thật~~ |
| ~~G6~~ ✅ | ~~**Không CI**~~ — đã đóng bằng P0-1 (`.github/workflows/ci.yml`) | ~~test Postgres ít khi được chạy~~ |
| G7 | Eval mới 1 tài liệu (đã bão hòa ở 100%) | Không đo được tiến bộ tiếp theo |
| G8 | BM25 in-process (RAM + rebuild theo process) | Trần khả năng mở rộng corpus |

---

## 3. Đối chiếu thị trường — học ai, học gì, bỏ gì

Khảo sát 15/08/2026 trên các dự án mã nguồn mở uy tín nhất phân khúc:

| Dự án | Stars | Điều đáng học nhất cho chúng ta |
| --- | --- | --- |
| [Open WebUI](https://github.com/open-webui/open-webui) | ~148.8k | **RBAC + user groups** làm chuẩn mực admin; hybrid search (BM25+vector) mặc định — xác nhận hướng ta đã đi; **model evaluation arena** trong admin; hệ plugin Pipes/Filters/Tools |
| [RAGFlow](https://github.com/infiniflow/ragflow) | ~88.3k | **Chunking giải thích được** (template + visualization cho người duyệt); **traceable citations**; fused re-ranking |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | ~54k | UX "document-first workspace" — người không kỹ thuật dùng được ngay |
| [LibreChat](https://github.com/danny-avila/LibreChat) | ~42k | **Agents + MCP + tool use**; fork/branch hội thoại; resumable streams |
| [Onyx (Danswer)](https://github.com/onyx-dot-app/onyx) | ~13k | Connectors nguồn dữ liệu doanh nghiệp; trợ lý theo team |

**Kỹ thuật RAG đáng áp dụng nhất:** [Contextual Retrieval của Anthropic](https://www.anthropic.com/engineering/contextual-retrieval) — prepend ngữ cảnh tài liệu vào từng chunk trước khi embed/index: giảm 49% retrieval failure, **giảm 67% khi kết hợp reranking**; khuyến nghị luôn đi đôi contextual embedding + contextual BM25. Với hệ local, chi phí sinh context chỉ là thời gian index (chấp nhận được), không tốn tiền API.

**Những thứ cố tình KHÔNG theo** (giữ định vị tối giản):
- Hỗ trợ 9 vector DB / đa provider phức tạp kiểu Open WebUI — ta giữ Qdrant + Ollama (+ Gemini/DeepSeek đã có làm tùy chọn).
- Code interpreter sandbox đa ngôn ngữ kiểu LibreChat — ngoài trọng tâm.
- Connector SaaS kiểu Onyx — dữ liệu ta là file cục bộ, đúng định vị riêng tư.

---

## 4. Lộ trình theo phase

> Mỗi phase **tự ship được** và có tiêu chí nghiệm thu đo được. Ước lượng theo buổi làm việc (~3h). Không phase nào phá nguyên tắc bất biến ở mục 1.

### P0 — Nền móng tin cậy *(1–2 tuần · mở khóa mọi thứ sau)*

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P0-1 ✅ | **CI GitHub Actions**: pytest (kèm Postgres+Redis service container), compileall, chạy trên PR + main | Badge xanh; test Postgres chạy mỗi commit thay vì "khi nhớ ra" | 2 buổi |
| P0-2 ✅ | **Xác thực lớp 1**: API key qua header cho mọi endpoint ghi/xóa (endpoint đọc công khai trong LAN tùy config); bot dùng luồng JWT có sẵn khi nâng cấp lớp 2 | Không có key → 401 ở endpoint ghi; UI tự đính key từ Settings | 2–3 buổi |
| P0-3 ✅ | **Lưu citation vào lịch sử**: bảng `message_sources` (message_id, chunk_id, filename, page, excerpt, score) | Mở lại hội thoại RAG vẫn thấy đủ nguồn như lúc trả lời | 2 buổi |
| P0-4 ✅ | **Backup tự động**: task định kỳ gọi `backup_postgres.py` + xoay vòng; hướng dẫn restore drill | Bản backup mới nhất < 24h tuổi; restore thử thành công 1 lần/quý | 1 buổi |
| P0-5 ✅ | `pyproject.toml` (requires-python, metadata) + CHANGELOG.md khởi tạo | `pip install -e .` hoạt động; phiên bản đầu tag `v1.0.0` | 1 buổi |
| P0-6 ✅ | **Đồng bộ model ↔ migration**: `alembic check` hiện báo drift thật (một loạt index khai báo trên model nhưng chưa migration nào tạo, vài lệch `nullable`/unique-constraint). Cần một migration bù rồi bật lại bước `alembic check` trong CI | `alembic check` xanh và chạy trong CI mỗi commit | 1–2 buổi |

### P0.5 — Nợ kỹ thuật từ audit 18/08 *(xen kẽ với P1 · mỗi mục độc lập)*

> Nguồn: audit toàn dự án 6 hướng + phản biện đối kháng (58 phát hiện, đã xác minh).
> Các lỗi nhỏ đã sửa ngay trong ngày; bảng này là phần **chưa sửa** vì cần migration
> hoặc refactor có kiểm soát. Xếp theo độ đau thực tế.

| ID | Hạng mục | Bản chất | Ước lượng |
| --- | --- | --- | --- |
| T1 | **Upload lại nội dung của tài liệu đã xóa → 500 vĩnh viễn**: unique `content_hash` vẫn giữ hash của bản ghi `deleted`; kèm rò thư mục trên đĩa | Migration: partial unique index `WHERE status != 'deleted'` (+ xử lý IntegrityError thành conflict decision); hoặc xóa hash khi cleanup chốt xóa | 2 buổi |
| T2 | **Hủy ingestion ở chế độ RQ khi job còn queued → kẹt vĩnh viễn** (run `queued`, document `processing`, không đường retry) | Cho phép cancel chốt ngay khi job chưa được claim; thêm đường thoát reindex cho document kẹt | 2 buổi |
| T3 | **`_replace_content` commit hash mới trước khi biết reindex enqueue được** → hash lệch nội dung đã index | Chặn replace bằng 409 khi còn run active (cùng predicate với `create_reindex`); enqueue thất bại thì tạo run `queued` bền | 1–2 buổi |
| ~~T4~~ ✅ | **Outbox event kẹt `processing` vĩnh viễn** nếu dispatcher chết giữa mark và publish | Thêm mệnh đề reclaim theo tuổi vào `dispatch_pending` (an toàn vì enqueue đã dedupe) | 1 buổi |
| T5 | **Discord turn retry sau mất lease giữa chừng → gọi model 2 lần, ghi trùng cặp message** | Chỉ persist message sau khi `save_response` xác nhận ownership | 2 buổi |
| T6 | **`sentence-transformers` (~650MB–2.5GB) trong install bắt buộc cho reranker đang tắt** | Chuyển sang `[project.optional-dependencies] rerank`; CI bỏ bước torch CPU; Docker image nhẹ đi tương ứng | 1–2 buổi |
| T7 | **`PostgresDocumentService` chứa 2 bản sao pipeline ingestion đồng bộ tay** (thread vs RQ, đã có micro-drift) | Tách `IngestionPipeline` một bản duy nhất tham số hóa bằng checkpoint hook; tách upload-conflict thành service riêng | 4–5 buổi |
| T8 | **Frontend fork đôi helper** (app.js/dashboard.js) — nguồn gốc lỗi dashboard thiếu API key vừa sửa | Tách `/ui/common.js` ($, el, withApiKey, api, theme/prefs) — script tag thường, không cần build | 1 buổi |
| T9 | Gom các mục nhỏ đã xác nhận: DashboardService thay SQL trong router; đảo phụ thuộc parsers→services; `ConversationLifecycle` chung cho chat/rag; gom wiring OCR router; race trùng tên file khi upload đồng thời (cần partial unique index, gộp với T1); fencing ownership cho `fail_job`/`mark_cancelled`; fixture `memory_transport` đếm job memory-ingest toàn cục → nhạy dữ liệu sót, scope theo prefix (thấy 1 lần fail không tái hiện 19/08) | Dọn dần khi đụng vào từng vùng, không cần đợt riêng | rải rác |
| T11 | **Test và runtime dùng chung Qdrant**: collection `memories` đã cô lập bằng `QDRANT_MEMORIES_COLLECTION` (19/08, sau khi test 3-dim làm hỏng đường ghi memory thật); collection `documents` hiện chỉ an toàn nhờ test dùng fake store — chưa có guard tường minh | Cô lập tên collection `documents` cho test giống memories, hoặc guard chiều vector khi tạo | 1 buổi |
| T12 | **Đánh bóng agent P2-2** (gom, không chặn dùng): UI hiện lại trace khi mở hội thoại cũ (messages cần trả kèm id); footer tool cho tin Discord; hủy vòng lặp khi client ngắt; map lỗi tools-với-provider-cloud thành 502 rõ nghĩa; tránh nạp memory hai lần khi bật cả «Ghi nhớ» lẫn «Công cụ» | Dọn khi đụng vào từng vùng | 2–3 buổi |
| T10 | **Script migration SQLite hết nhiệm vụ 07/2027**: `migrate_sqlite_to_postgres.py`, `migrate_sqlite_documents_to_postgres.py`, `migrate_document_storage.py`, `audit_sqlite_readonly.py` + 2 test đi kèm bị ghim bởi cam kết giữ SQLite archive read-only 1 năm | Gỡ sau review xóa archive (sớm nhất 19/07/2027) | 1 buổi (2027) |

### P1 — Một agent, hai kênh *(2–3 tuần · giá trị người dùng lớn nhất)* — **ĐÃ ĐÓNG 19/08** (nhật ký: `docs/p1_progress.md`)

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P1-1 ✅ | **Discord RAG**: lệnh `/hoi` — 19/08 đổi tên `/docs` (câu hỏi + chọn tài liệu hoặc all) gọi `/rag/chat`, trả lời kèm nguồn rút gọn | Hỏi tài liệu trong Discord nhận câu trả lời có `[Source]` + tên file/trang | 2–3 buổi |
| P1-2 ✅ | **Condense-question**: trước retrieval, dùng model general viết lại câu hỏi nối tiếp thành câu độc lập (bỏ qua khi là lượt đầu) | Bộ eval hội thoại mới (10 cặp câu nối tiếp) đạt ≥ 80% recall | 2 buổi |
| P1-3 ✅ | **Bật memory extractor Discord** (`DISCORD_MEMORY_EXTRACTOR_ENABLED=true`) ở chế độ đề xuất | Candidate xuất hiện trong DB với proposal; không memory nào tự áp dụng | 1 buổi |
| P1-4 ✅ | **Duyệt memory trên dashboard**: bảng candidate (nội dung đề xuất, nguồn, độ tin) + nút duyệt/từ chối | Admin duyệt được từ UI; audit trail đầy đủ | 3 buổi |
| P1-5 ✅ | **Hợp nhất kho memory**: memory duyệt từ Discord đổ vào kho `/memory` (Qdrant) mà web chat dùng | Bật "Ghi nhớ" ở web → trợ lý dùng được điều học từ Discord | 2 buổi |

### P2 — Agent tự hành *(định hướng 19/08 · agent là sản phẩm, kênh chat là bề mặt)* — nhật ký: `docs/p2_progress.md`

> Chuyển từ "người duyệt tay" sang "agent tự vận hành, người giám sát". Đổi lại là bất biến
> mới ở §1: mọi hành động tự hành phải audit được và thu hồi được. Hạ tầng P1 giữ nguyên vai
> trò: đường approve của P1-4 thành đường auto-apply, dashboard thành màn giám sát.

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P2-1 ✅ | **Memory tự áp dụng theo ngưỡng tin cậy**: candidate có confidence ≥ τ (mặc định 0.8, chỉnh qua `.env`, `off` để tắt) được tự approve qua đúng đường duyệt hiện có (`reviewed_by="agent"`, audit giữ nguyên); dưới ngưỡng vẫn vào hàng chờ duyệt; approve định tuyến create/supersede/revive nên fact đổi ý và học-lại-sau-thu-hồi đều chạy; delete-proposal luôn chờ người | Memory học từ Discord dùng được ở web không cần cú click nào (✅ live 19/08: agent áp dụng sau ~20s, search 0.534); mọi memory tự áp dụng có provenance và thu hồi được 1 click từ dashboard (✅ đã thu hồi một fact 2b bịa sai với confidence 1.0) | 2–3 buổi |
| P2-1b | **Nâng extractor theo số liệu benchmark 19/08**: `DISCORD_MEMORY_EXTRACTOR_MODEL` → `qwen3.5:9b`; guard xác định thành điều kiện auto-apply (evidence nguyên văn trong tin gốc + fact trùng từ-nội-dung); τ giữ làm công tắc, không còn là tín hiệu chính (confidence đo được là hằng 1.0) | Benchmark tái lập chính sách mới: poison ≤ 21,6% coverage ≥ 96% như số đo; live: memory tự áp dụng phản ánh đúng tin gốc | 1–2 buổi |
| P2-2 ✅ | **Vòng lặp agent + tool use** (function calling native qua Ollama): `/ask` (qua `DISCORD_AGENT_TOOLS_ENABLED`) và web chat (chip «Công cụ», cờ `use_tools`) thành cửa vào agent; tools = tìm tài liệu (RAG), đọc memory, trạng thái hệ thống; trace từng bước lưu bảng `agent_traces` (migration `20260819_22`), xem lại qua `GET /agent/traces/{message_id}` | ✅ Live 19/08: câu hỏi cần cả tài liệu lẫn memory → agent tự gọi docs → memory → docs, trả lời mở đầu đúng phong cách đã nhớ + dẫn đúng tài liệu (02:15, 21 bản), 7 bước trace phát lại được | 5–6 buổi |
| P2-3 | **Bộ lệnh Discord chuyên nghiệp**: ~~`/hoi`~~ → `/docs` (✅ 19/08, tham số `document`); thêm `/memory` (điều agent đã nhớ về kênh/người hỏi), `/status` (health rút gọn) — tên lệnh tiếng Anh chuẩn, mô tả tiếng Việt | Bộ lệnh nhất quán `/ask` `/docs` `/memory` `/status` `/ping`; `/memory` liệt kê đúng memory liên quan | 2 buổi |
| P2-4 | **Nhật ký hành động agent**: gom hành động tự hành (memory apply, index, cleanup, backup) về một dòng thời gian trên dashboard | Mọi hành động tự hành tra được một chỗ: việc gì, lúc nào, kết quả, kèm nút thu hồi nếu áp dụng | 2 buổi |

### P3 — Đa người dùng & quản trị *(3–4 tuần · khi mở cho nhóm)*

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P3-1 | **Tài khoản + RBAC tối giản** (admin/member — học mô hình Open WebUI, không sao chép độ phức tạp): JWT + refresh theo chuẩn FastAPI production | Hội thoại thuộc user; member không xóa được tài liệu chung | 5–6 buổi |
| P3-2 | **Điều khiển bot từ dashboard**: start/stop/status (thay control panel Tkinter) | Nút hoạt động; trạng thái đúng với thực tế process | 3 buổi |
| P3-3 | **Biểu đồ thời gian trên dashboard**: câu hỏi/ngày, latency p50/p95, lỗi — từ `request_logs` có sẵn | 2 chart 14 ngày, cập nhật cùng auto-refresh | 2 buổi |
| P3-4 | **OCR console UI** (backend API đã đủ từ lâu) | Upload → theo dõi job → xem kết quả → promote thành tài liệu, không cần curl | 3–4 buổi |

### P4 — RAG nâng cao, có đo lường *(chạy nền liên tục, mỗi mục một thí nghiệm)*

| ID | Hạng mục | Giả thuyết cần kiểm chứng bằng eval | Ước lượng |
| --- | --- | --- | --- |
| P4-1 | **Mở rộng bộ eval**: 3–5 tài liệu thật + 30 câu đa tài liệu + eval trong CI (gate: không tụt quá 2 điểm) | Baseline mới thay bộ 1-tài-liệu đã bão hòa | 2 buổi |
| P4-2 | **Contextual retrieval** (Anthropic): sinh 50–100 token ngữ cảnh/chunk lúc index bằng model local | MRR đa tài liệu tăng ≥ 5 điểm (kỳ vọng theo paper: −49% failure) | 3 buổi |
| P4-3 | **Bật reranker** (đã có sẵn `RerankerService`, warmup lúc startup) | Kết hợp P4-2 hướng tới mức −67% failure của paper | 1–2 buổi |
| P4-4 | **Postgres FTS thay BM25 in-process** (tsvector + GIN + unaccent) | Không tụt chất lượng; RAM không tăng theo corpus; nhất quán đa process | 3–4 buổi |
| P4-5 | **Chunk visualization** (học RAGFlow): xem chunk của tài liệu trong UI, đánh dấu chunk kém | Người dùng tự chẩn đoán được "tại sao trả lời sai" | 3 buổi |

### P5 — Năng lực mở rộng *(tương lai, chọn lọc theo nhu cầu thật)*

> Tool use cơ bản đã chuyển lên P2-2 (trở thành lõi agent). Ở đây còn các mở rộng chọn lọc.

- **Tool bên ngoài cho agent** (thời tiết nội bộ? tra cứu ERP xưởng?) — chỉ khi có use case cụ thể.
- **Vision attachments**: đính ảnh vào chat (nền `vision_chat` đã có; endpoint `/vision/chat` đang 501).
- **Web search opt-in** cho câu hỏi ngoài tài liệu (học Open WebUI, mặc định tắt vì định vị riêng tư).
- **MCP client** nếu hệ sinh thái nội bộ cần nối tool ngoài (LibreChat là tham chiếu tốt).
- Fork/branch hội thoại; resumable streams đa tab (LibreChat).

---

## 5. Kiến trúc đích (không đổi xương sống, chỉ bồi)

```
Web UI ─┐                                  ┌─ Qdrant (vector index)
        ├─ FastAPI ── services ── Postgres ┤
Discord ─┘    │                            └─ FTS (tsvector, P4-4)
              ├─ Auth layer (P0-2 → P3-1)
              ├─ Memory hub (P1-5): một kho, hai kênh đọc/ghi
              ├─ Agent core (P2-2): planner + tools (RAG/memory/status), trace từng bước
              └─ RQ workers (ocr/index/memory) + outbox + cleanup
```

- **API versioning**: giữ endpoint hiện tại; breaking change đầu tiên (P3-1) mở namespace `/api/v1/`, alias cũ giữ 1 minor version.
- **Agent core (P2)**: vòng lặp plan→act→observe đặt trong `services/`, dùng lại retrieval/memory/health có sẵn làm tool — không thêm framework agent ngoài; trace từng bước ghi Postgres.
- **Cấu trúc code**: giữ `routers → services → repositories/stores` (đã khớp chuẩn FastAPI production); không thêm framework.
- **Plugin-lite**: chưa làm hệ plugin tổng quát (Pipes kiểu Open WebUI) cho tới khi có ≥ 2 nhu cầu mở rộng thật — tránh over-engineering.

## 6. Chất lượng & quy trình

| Mảng | Chuẩn áp dụng |
| --- | --- |
| Test | 3 tầng (unit service / integration repository / endpoint) — đã có nền; mục tiêu coverage 80% cho `services/` khi CI chạy (P0-1) |
| Eval | Là **gate chất lượng RAG**: mọi thay đổi retrieval/prompt phải chạy eval trước-sau, ghi kết quả vào PR |
| Review | Thay đổi lớn qua review đối kháng (đã chứng minh hiệu quả: 17 lỗi thật bị bắt trong 2 vòng) |
| Release | Tag `vX.Y.Z` + CHANGELOG (P0-5); mỗi phase đóng = một minor version |
| Migration | Additive-only; mỗi migration có downgrade; restore drill mỗi quý |

## 7. KPI theo dõi (đo trên dashboard + eval)

| KPI | Hiện tại | Mục tiêu cuối P1 | Mục tiêu cuối P4 |
| --- | --- | --- | --- |
| Answer pass rate (eval) | 1.00 (1 tài liệu — bão hòa) | ≥ 0.90 bộ đa tài liệu mới | ≥ 0.95 |
| MRR | 0.933 | ≥ 0.85 (bộ mới, khó hơn) | ≥ 0.90 |
| Câu hỏi nối tiếp đạt (bộ eval hội thoại) | 10/10, MRR 0.950 ✅ | ≥ 0.80 ✅ | ≥ 0.90 |
| Kênh Discord dùng tài liệu | ✅ `/docs` kèm nguồn (P1-1) | có, kèm nguồn ✅ | — |
| Memory đưa vào dùng | pipeline người-duyệt end-to-end ✅ (P1) | pipeline chạy end-to-end ✅ | tự áp dụng theo ngưỡng (P2-1), tỷ lệ bị thu hồi < 30% |
| CI | ✅ 3 job (P0-1) | xanh trên main ✅ | eval gate trong CI |

## 8. Rủi ro & đối sách

| Rủi ro | Mức | Đối sách |
| --- | --- | --- |
| Model 9B chạy nhiều trên CPU (máy phụ) → latency ~45s/câu RAG | Chấp nhận (quyết định 15/08) | Kiến trúc không giả định latency thấp; nếu chuyển máy chính: chỉ cần đổi `models.yaml` |
| Một người bảo trì | Cao | P0 dồn vào automation (CI, backup, eval gate) trước tính năng |
| Scope creep từ cảm hứng dự án lớn | Trung | Mục "cố tình KHÔNG theo" ở §3; mỗi mục P4 cần use case thật mới làm |
| Bảo mật khi mở LAN cho nhóm | Cao nếu bỏ qua | P0-2 là điều kiện tiên quyết của P3; không mở nhóm trước khi có auth |
| Extractor tự áp dụng memory sai → trí nhớ bẩn | **Cao — đã đo 19/08**: confidence là hằng 1.0 ở mọi lỗi (τ vô nghĩa); 2b lọt 49% độc, 9b + guard xác định còn 21,6% (benchmark 150 case, `docs/p2_progress.md`) | P2-1b: extractor → 9b + guard evidence/overlap trong auto-apply; giám sát + thu hồi 1 click là lưới chính, không phải tạm bợ; benchmark lại sau mỗi thay đổi extractor |

## 9. Việc bắt đầu ngay (tuần tới)

1. ~~**P0-1 CI**~~ — ✅ xong (`.github/workflows/ci.yml`, 3 job: static / backend+PostgreSQL+Redis / bot trên Windows).
2. ~~**P0-3 lưu citation**~~ — ✅ xong (migration `20260818_20`, nguồn hiện lại khi mở hội thoại cũ).
3. ~~**P0-2 API key**~~ — ✅ xong (header `X-API-Key`, mặc định tắt để không phá đường một cú click).
4. ~~**P0-6 đồng bộ migration**~~ — ✅ xong (migration `20260818_21`, `alembic check` đã là cửa chặn trong CI).

**P0 và P1 đã đóng; P2-1 và P2-2 xong 19/08** (nhật ký: `docs/p2_progress.md`). Việc tiếp theo: **P2-1b** (extractor → 9b + guard, theo benchmark) hoặc **P2-3 phần còn lại** (`/memory`, `/status`) rồi **P2-4** (nhật ký hành động agent).

---

## Nguồn tham khảo

- [Open WebUI — GitHub](https://github.com/open-webui/open-webui) (~148.8k★): RBAC, hybrid search, evaluation arena, plugin system
- [RAGFlow — GitHub](https://github.com/infiniflow/ragflow) (~88.3k★): explainable chunking, traceable citations
- [AnythingLLM — GitHub](https://github.com/Mintplex-Labs/anything-llm) (~54k★): document-first UX
- [LibreChat — GitHub](https://github.com/danny-avila/LibreChat) (~42k★): agents/MCP, conversation branching
- [Anthropic — Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval): −49% retrieval failure, −67% kèm reranking
- [Searching for Best Practices in RAG (arXiv 2407.01219)](https://arxiv.org/pdf/2407.01219)
- Chuẩn FastAPI production 2026: cấu trúc domain, JWT + refresh, test 3 tầng ([tổng hợp](https://dev.to/datanestdigital/production-ready-fastapi-project-structure-2026-guide-b1g))
- So sánh phân khúc: [OpenWebUI vs LibreChat vs Onyx](https://onyx.app/insights/openwebui-vs-librechat-vs-onyx), [AnythingLLM vs Open WebUI vs LibreChat](https://runaihome.com/blog/anythingllm-vs-open-webui-vs-librechat-2026/)
