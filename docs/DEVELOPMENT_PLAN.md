# Kế hoạch phát triển tổng thể — Local AI Core

**Phiên bản:** 1.2 · **Ngày:** 15/08/2026 · **Cập nhật:** 19/08 (agent-first) · 21/08/2026 (track D — kỹ năng AI + ngân sách inference) · 23/08/2026 (kết luận phản biện P4-4 — đo trước khi đổi schema) · **Trạng thái:** Đang hiệu lực
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
- **Ngân sách inference cố định**: tính năng agent mới không được tăng số lượt gọi model mặc định của một câu hỏi thường; kiểm tra/xác minh ưu tiên cơ chế không-LLM hoặc model nhỏ chuyên hóa; việc nền phải nhường request tương tác — Ollama một máy chỉ phục vụ một request một lúc (bổ sung 21/08).

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

### Điều chỉnh định hướng 21/08/2026 — track D (kỹ năng AI engineer)

Bổ sung một track phát triển **song song với các phase sản phẩm**, chọn theo tiêu chí kép:
mỗi mục vừa nâng chất hệ thống vừa xây một kỹ năng AI-engineer đo được (eval, fine-tune,
agent design, LLMOps, AI security). Đi kèm là phân tích phần cứng 21/08: agent gọi model
**tuần tự nhiều lần** nên độ trễ cộng dồn (turn 3 bước hiện đã cần timeout 360s trên máy
phụ), và Ollama một máy chỉ phục vụ một request một lúc — việc nền chạy sai lúc sẽ chặn
người dùng thật. Hệ quả: bất biến "ngân sách inference" ở §1 và số phận tách ba của mục
agent nâng cao (D3a/D3b giữ, D3c gác). Chi tiết: §4, mục "Track D".

### Điều chỉnh định hướng 23/08/2026 — đo trước khi đổi schema (kết luận phản biện P4-4)

Bản thiết kế P4-4 v1 (`docs/p4_4_design.md`) đã qua một vòng **phản biện đối kháng 5 tác
nhân** (2 bảo vệ, 2 công kích, 1 giám khảo). Kết quả: **giữ mục tiêu, không chọn v1 nguyên
trạng** — không phải vì ý tưởng sai mà vì bản v1 tự vi phạm ngưỡng dừng dung lượng của
chính nó (đo 2.28× ở cấu hình ship, ngưỡng dừng 2×) và chứa lỗi có thể **sai âm thầm**.
v1 **không bị vứt**: nó được giữ nguyên làm phương án 1 trong hai, đặt cạnh v2 với ưu/nhược
và quy tắc chọn ở **§9d** — máy vận hành chốt bằng số đo, không bằng lập luận. Ba hệ quả:

1. **Đưa chỉ mục sparse vào PostgreSQL vẫn là đích đến.** Ba nỗi đau G8 (RAM theo corpus,
   rebuild lại từ đầu, không nhất quán đa tiến trình) là thật và chỉ lớn dần theo số chunk;
   không phương án rẻ nào xoá được cả ba.
2. **Trình tự đảo lại: ĐO trước, viết migration sau.** Đây là bài học P4-3 lặp lại ở dạng
   khác — ở P4-3 suýt kết luận sai vì đo trên torch CPU-only; ở đây v1 chốt `jsonb` cho
   `retrieval_tf` mà chưa ai chạy `pg_column_size`, và riêng lựa chọn đó đẩy dung lượng từ
   **1.06× lên 1.90×** corpus trần.
3. **Tách phần rẻ khỏi phần đắt.** Phần "trì trệ mỗi lần mở lên" gỡ được bằng một thay đổi
   trong tiến trình, **không cần schema** (P4-4a). Chỉ RAM và chấm-điểm-O(corpus) mới bắt
   buộc xuống DB (P4-4b).

**Bằng chứng định lượng** — đo thật trên corpus fixture D1 (27 chunk, máy nhẹ, tokenizer
thật của repo); các mức lớn hơn là **ngoại suy tuyến tính, CHƯA ĐO**:

| Corpus | RAM chỉ mục | Rebuild (câu hỏi đầu sau mỗi lần index/restart) | Chấm BM25 mỗi query |
| --- | --- | --- | --- |
| 27 (đo thật) | 0.07 MB | 0.147 s | 0.27 ms |
| 1 000 | ~2.6 MB | ~5.4 s | ~10 ms |
| 5 000 | ~13 MB | ~27 s | ~50 ms |
| 10 000 | ~26 MB | ~54 s | ~100 ms |
| 100 000 | ~260 MB | ~9 phút | ~1 s |

Đọc bảng: **RAM không phải thứ đau trước** — 10 000 chunk mới tốn ~26 MB, không đáng gì.
Thứ đau trước là hai cột bên phải, và chúng cần **hai lời giải khác nhau**: cột giữa do
P4-4a xoá (98.1% thời gian rebuild là tách từ pyvi), cột phải **chỉ P4-4b** xoá được.

**Ngưỡng kích hoạt P4-4b**: không ghim một mốc chunk cứng. Khi corpus vận hành chạm
~5 000 chunk thì hai cột phải đã ở mức người dùng cảm nhận được. Lập luận ngược cũng có
trọng lượng và được ghi nhận: **di trú khi dữ liệu còn nhỏ thì rẻ** — backfill 27–300 chunk
là vài giây, còn 50 000 chunk kèm dựng GIN là một cửa sổ bảo trì thật trên hệ đang có người
dùng. Vì vậy **thời điểm do người vận hành quyết, nhưng thứ tự (v2 → đo → code) không đổi**.

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
| ~~G1~~ ✅ | ~~**Không có xác thực**~~ — đã đóng lớp 1 bằng P0-2 (API key cho endpoint ghi/xóa) và lớp 2 bằng P3-1 (tài khoản admin/member, JWT — 20/08) | ~~Ai trong LAN cũng xóa được dữ liệu~~ |
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
| ~~T1~~ ✅ | **Upload lại nội dung của tài liệu đã xóa → 500 vĩnh viễn** — đã sửa 21/08: migration `20260820_24` chuyển sang partial unique index `WHERE status != 'deleted'` (khớp với lookup vốn đã loại deleted); rò thư mục đã được cleanup worker xử lý từ đợt audit | ✅ | 2 buổi |
| ~~T2~~ ✅ | **Hủy ingestion ở chế độ RQ khi job còn queued → kẹt vĩnh viễn** — đã sửa 21/08: job chưa ai claim thì cancel chốt ngay trong một transaction (job `cancelled`, run `cancelled`, document về `indexed`/`uploaded`); job đang chạy giữ nguyên cờ hợp tác; run cancelled mở lại đường reindex | ✅ | 2 buổi |
| ~~T3~~ ✅ | **`_replace_content` commit hash mới trước khi biết reindex enqueue được** — đã sửa 21/08: guard + hash + run mới commit trong MỘT transaction (hash không bao giờ tồn tại thiếu run); run còn `queued` chưa ai giữ thì được supersede (upload → sửa ngay vẫn chạy), giữa chừng thì 409; mỗi lần replace ra version mới thay vì tái dùng version của nội dung cũ | ✅ | 1–2 buổi |
| ~~T4~~ ✅ | **Outbox event kẹt `processing` vĩnh viễn** nếu dispatcher chết giữa mark và publish | Thêm mệnh đề reclaim theo tuổi vào `dispatch_pending` (an toàn vì enqueue đã dedupe) | 1 buổi |
| T5 | **Discord turn retry sau mất lease giữa chừng → gọi model 2 lần, ghi trùng cặp message** | Chỉ persist message sau khi `save_response` xác nhận ownership | 2 buổi |
| ~~T6~~ ✅ | **`sentence-transformers` (~650MB–2.5GB) trong install bắt buộc cho reranker đang tắt** — đã sửa 21/08: chuyển sang optional extra `pip install -e .[rerank]`; CI bỏ bước torch CPU; bật reranker thiếu gói sẽ báo lỗi kèm lệnh cài rõ ràng | ✅ | 1–2 buổi |
| T7 | **`PostgresDocumentService` chứa 2 bản sao pipeline ingestion đồng bộ tay** (thread vs RQ, đã có micro-drift) | Tách `IngestionPipeline` một bản duy nhất tham số hóa bằng checkpoint hook; tách upload-conflict thành service riêng | 4–5 buổi |
| T8 | **Frontend fork đôi helper** (app.js/dashboard.js) — nguồn gốc lỗi dashboard thiếu API key vừa sửa | Tách `/ui/common.js` ($, el, withApiKey, api, theme/prefs) — script tag thường, không cần build | 1 buổi |
| T9 | Gom các mục nhỏ đã xác nhận: DashboardService thay SQL trong router; đảo phụ thuộc parsers→services; `ConversationLifecycle` chung cho chat/rag; gom wiring OCR router; race trùng tên file khi upload đồng thời (cần partial unique index, gộp với T1); fencing ownership cho `fail_job`/`mark_cancelled`; fixture `memory_transport` đếm job memory-ingest toàn cục → nhạy dữ liệu sót, scope theo prefix (thấy 1 lần fail không tái hiện 19/08) | Dọn dần khi đụng vào từng vùng, không cần đợt riêng | rải rác |
| ~~T11~~ ✅ | **Test và runtime dùng chung Qdrant** — đã đóng 22/08: collection `documents` cấu hình được (`QDRANT_DOCUMENTS_COLLECTION`, mặc định `documents`); suite dùng `documents_test`, phiên đo trên DB lab dùng `documents_lab` + `rebuild_qdrant` (collection `memories` đã cô lập từ 19/08) | ✅ | 1 buổi |
| T12 | **Đánh bóng agent P2** (gom, không chặn dùng): UI hiện lại trace khi mở hội thoại cũ (messages cần trả kèm id); footer tool cho tin Discord; hủy vòng lặp khi client ngắt; map lỗi tools-với-provider-cloud thành 502 rõ nghĩa; tránh nạp memory hai lần khi bật cả «Ghi nhớ» lẫn «Công cụ»; **guard xuyên ngữ** — fact tiếng Anh vs tin Việt bị từ chối oan (an toàn nhưng mất coverage; hướng: prompt extractor v6 viết fact bằng ngôn ngữ tin gốc + re-benchmark) | Dọn khi đụng vào từng vùng | 2–3 buổi |
| T13 | **Đánh bóng auth P3-1** (gom, không chặn dùng): đổi mật khẩu + admin reset qua UI; trang quản lý user trên dashboard (hiện chỉ API); token localStorage → cân nhắc cookie httpOnly nếu mở ra ngoài LAN; member-role staleness 15' ở surface thường; ẩn/hiện điều khiển theo role còn thiếu chỗ nào thì server vẫn chặn | Dọn khi đụng vào từng vùng | 2–3 buổi |
| ~~T14~~ ✅ | **Backup chỉ sống trong phiên launcher** — đã đóng 22/08: `backup-postgres-once.bat` (`--once --force`) + Scheduled Task `LocalAICore Backup` hằng ngày 02:00 trên máy vận hành `PC-dungbt` (đường dẫn thuần ASCII sau khi dời thư mục; chạy bằng user, tạo từ prompt admin; `/Run` thử → `Last Result: 0`, dump mới). Bài học ghi `machine_split.md`: thư mục production thuần ASCII, launcher khởi động qua explorer để sống độc lập phiên | ✅ | 1 buổi |
| T15 | **`replace_chunks` không ghi `locations`, `heading_path`, `token_count`** — `chunking.py:240-252` tính locations/heading_path rồi **vứt đi** ở đường ghi (`repositories.py:97-104`), nên mọi citation production trả `heading_path: null`; `PostgresBm25Service._IndexedChunk` khai báo hai trường này nhưng luôn nhận rỗng. Kèm lệch kiểu: chunker sinh `heading_path` dạng chuỗi `"A > B"`, cột DB là JSONB `list[str]`. Phát hiện từ vòng phản biện P4-4 23/08, đã xác minh độc lập | Ghi đủ 3 cột trong cùng transaction (chốt kiểu trước) + test đi qua **đường ghi thật** — test hiện tại dựng chunk bằng tay nên không bắt được | 0.5 buổi |
| T16 | **`pyvi` chỉ ghim dải `>=0.1.1,<1.0`** (`requirements.txt:17`) — tách từ là đầu vào của BM25; bản pyvi khác trên máy khác đổi lexeme mà không có tín hiệu nào. Hiện chỉ lệch runtime, nhưng P4-4b sẽ **lưu lexeme xuống DB** nên khi đó lệch thành dữ liệu bẩn vĩnh viễn | Ghim đúng version + ghi `tokenizer_version` cạnh mọi dữ liệu dẫn xuất — **điều kiện tiên quyết của P4-4b** | 0.5 buổi |
| T10 | **Script migration SQLite hết nhiệm vụ 07/2027**: `migrate_sqlite_to_postgres.py`, `migrate_sqlite_documents_to_postgres.py`, `migrate_document_storage.py`, `audit_sqlite_readonly.py` + 2 test đi kèm bị ghim bởi cam kết giữ SQLite archive read-only 1 năm | Gỡ sau review xóa archive (sớm nhất 19/07/2027) | 1 buổi (2027) |

### P1 — Một agent, hai kênh *(2–3 tuần · giá trị người dùng lớn nhất)* — **ĐÃ ĐÓNG 19/08** (nhật ký: `docs/p1_progress.md`)

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P1-1 ✅ | **Discord RAG**: lệnh `/hoi` — 19/08 đổi tên `/docs` (câu hỏi + chọn tài liệu hoặc all) gọi `/rag/chat`, trả lời kèm nguồn rút gọn | Hỏi tài liệu trong Discord nhận câu trả lời có `[Source]` + tên file/trang | 2–3 buổi |
| P1-2 ✅ | **Condense-question**: trước retrieval, dùng model general viết lại câu hỏi nối tiếp thành câu độc lập (bỏ qua khi là lượt đầu) | Bộ eval hội thoại mới (10 cặp câu nối tiếp) đạt ≥ 80% recall | 2 buổi |
| P1-3 ✅ | **Bật memory extractor Discord** (`DISCORD_MEMORY_EXTRACTOR_ENABLED=true`) ở chế độ đề xuất | Candidate xuất hiện trong DB với proposal; không memory nào tự áp dụng | 1 buổi |
| P1-4 ✅ | **Duyệt memory trên dashboard**: bảng candidate (nội dung đề xuất, nguồn, độ tin) + nút duyệt/từ chối | Admin duyệt được từ UI; audit trail đầy đủ | 3 buổi |
| P1-5 ✅ | **Hợp nhất kho memory**: memory duyệt từ Discord đổ vào kho `/memory` (Qdrant) mà web chat dùng | Bật "Ghi nhớ" ở web → trợ lý dùng được điều học từ Discord | 2 buổi |

### P2 — Agent tự hành *(định hướng 19/08 · agent là sản phẩm, kênh chat là bề mặt)* — **ĐÃ ĐÓNG 20/08** (nhật ký: `docs/p2_progress.md`)

> Chuyển từ "người duyệt tay" sang "agent tự vận hành, người giám sát". Đổi lại là bất biến
> mới ở §1: mọi hành động tự hành phải audit được và thu hồi được. Hạ tầng P1 giữ nguyên vai
> trò: đường approve của P1-4 thành đường auto-apply, dashboard thành màn giám sát.

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P2-1 ✅ | **Memory tự áp dụng theo ngưỡng tin cậy**: candidate có confidence ≥ τ (mặc định 0.8, chỉnh qua `.env`, `off` để tắt) được tự approve qua đúng đường duyệt hiện có (`reviewed_by="agent"`, audit giữ nguyên); dưới ngưỡng vẫn vào hàng chờ duyệt; approve định tuyến create/supersede/revive nên fact đổi ý và học-lại-sau-thu-hồi đều chạy; delete-proposal luôn chờ người | Memory học từ Discord dùng được ở web không cần cú click nào (✅ live 19/08: agent áp dụng sau ~20s, search 0.534); mọi memory tự áp dụng có provenance và thu hồi được 1 click từ dashboard (✅ đã thu hồi một fact 2b bịa sai với confidence 1.0) | 2–3 buổi |
| P2-1b ✅ | **Nâng extractor theo số liệu benchmark 19/08**: `DISCORD_MEMORY_EXTRACTOR_MODEL` → `qwen3.5:9b` (settings/.env/launcher/compose); guard xác định thành điều kiện auto-apply (evidence nguyên văn trong tin gốc + fact trùng từ-nội-dung, module `discord_memory_guard.py`); τ giữ làm công tắc, không còn là tín hiệu chính | ✅ Test tái dẫn xuất đúng số đo từ kết quả benchmark đã lưu bằng chính hàm production (coverage ≥ 90%, poison ≤ 25%); hồi quy ca bịa fact sống 19/08 bị chặn; live 20/08: 9b trích đúng, guard thận trọng xuyên ngữ → rơi an toàn về hàng chờ (T12 ghi hướng prompt v6) | 1–2 buổi |
| P2-2 ✅ | **Vòng lặp agent + tool use** (function calling native qua Ollama): `/ask` (qua `DISCORD_AGENT_TOOLS_ENABLED`) và web chat (chip «Công cụ», cờ `use_tools`) thành cửa vào agent; tools = tìm tài liệu (RAG), đọc memory, trạng thái hệ thống; trace từng bước lưu bảng `agent_traces` (migration `20260819_22`), xem lại qua `GET /agent/traces/{message_id}` | ✅ Live 19/08: câu hỏi cần cả tài liệu lẫn memory → agent tự gọi docs → memory → docs, trả lời mở đầu đúng phong cách đã nhớ + dẫn đúng tài liệu (02:15, 21 bản), 7 bước trace phát lại được | 5–6 buổi |
| P2-3 ✅ | **Bộ lệnh Discord chuyên nghiệp**: ~~`/hoi`~~ → `/docs` (19/08, tham số `document`); `/memory` (điều agent nhớ về người gõ trong guild, ephemeral, filter guild/subject trên `/api/memory-review/applied`) + `/status` (tóm tắt `/health`) — 20/08 | Bộ lệnh nhất quán `/ask` `/docs` `/memory` `/status` `/ping` ✅; còn bước người thật gõ trong server thật (cần DISCORD_TOKEN, như P1-1) | 2 buổi |
| P2-4 ✅ | **Nhật ký hành động agent**: `GET /agent/activity` đọc gộp ba nguồn sử liệu có sẵn (quyết định memory, câu trả lời dùng công cụ, việc nền) thành dòng thời gian trên dashboard, kèm nút Thu hồi trên hàng còn gỡ được | ✅ Live 20/08: timeline kể đủ chuỗi agent-trả-lời → ingest → nhớ → dùng trí nhớ; thu hồi từ chính timeline hoạt động | 2 buổi |

### P3 — Đa người dùng & quản trị — **ĐÃ ĐÓNG 20/08** (nhật ký: `docs/p3_progress.md`)

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P3-1 ✅ | **Tài khoản + RBAC tối giản** (admin/member): JWT access 15' + refresh thu-hồi-được (cố ý không xoay vòng — xem nhật ký); bật bằng `LOCAL_AI_AUTH_ENABLED` (validator ép đủ secret + API key, guard fail-closed); bootstrap admin đầu tiên có khóa chống race, sau đó admin tạo user; thiết kế qua hội đồng phản biện đối kháng 34 phát hiện trước khi code | ✅ Hội thoại thuộc user (người khác nhìn vào 404); member không xóa được tài liệu chung (403, đã kiểm sống); lane API-key của bot/tool nguyên vẹn; auth tắt = zero-setup như cũ | 5–6 buổi |
| P3-2 ✅ | **Điều khiển bot từ dashboard**: status/start/stop qua đúng cơ chế `docker compose --profile discord` mà run-discord-bot.bat dùng | ✅ Trạng thái = compose ps thật nên không thể lệch; nút hiện đúng (sống 20/08); bấm Bật thật cần DISCORD_TOKEN (bước người thật) | 3 buổi |
| P3-3 ✅ | **Biểu đồ thời gian trên dashboard**: `GET /api/dashboard/timeseries` từ `request_logs`, bucket theo ngày địa phương, SVG tự vẽ không thư viện | ✅ 2 chart 14 ngày (câu hỏi+lỗi; p50/p95) cập nhật cùng auto-refresh — sống 20/08 | 2 buổi |
| P3-4 ✅ | **OCR console UI** `/ui/ocr.html` trên API có sẵn | ✅ Upload → theo dõi job (poll + progress + events) → xem kết quả trang → promote/tải zip/hủy/lịch sử, không cần curl | 3–4 buổi |

### P4 — RAG nâng cao, có đo lường *(chạy nền liên tục, mỗi mục một thí nghiệm)* — **MỞ LẠI 21/08 trên máy mạnh** (P4-1≡D1 ✅, P4-2 ✅, P4-3 ✅; còn P4-4a, P4-4b, P4-5)

> Quyết định 20/08: P4 cần vòng lặp thí-nghiệm-nhanh (re-index + eval mỗi lần
> chỉnh) — trên CPU hiện tại mỗi vòng mất nửa buổi nên gác tới khi chuyển máy.
> Chỉ số chất lượng không phụ thuộc máy nên không mất gì khi đợi; khi có máy
> mới: restore backup + pull model + đổi models.yaml (plan §8), cân nhắc nâng
> model general trước rồi mới đo baseline P4-1 một lần trên cấu hình cuối.
> ~~Hướng thi công 20/08: P4-1 → P4-4 (pyvi tách từ vào tsvector) → P4-2 → P4-3
> (+T6) → P4-5~~ — **lỗi thời 23/08**: thứ tự thực tế đã là P4-1 → P4-2 → P4-3, và
> `tsvector` bị loại (parser mặc định tách đôi từ ghép pyvi nối bằng `_`). Thứ tự
> còn lại chốt ở §9b. Eval trong CI vẫn theo phương án retrieval-only, embedding 0.6b.

| ID | Hạng mục | Giả thuyết cần kiểm chứng bằng eval | Ước lượng |
| --- | --- | --- | --- |
| P4-1 | **Mở rộng bộ eval**: 3–5 tài liệu thật + 30 câu đa tài liệu + eval trong CI (gate: không tụt quá 2 điểm) | Baseline mới thay bộ 1-tài-liệu đã bão hòa | 2 buổi |
| P4-2 | **Contextual retrieval** (Anthropic): sinh 50–100 token ngữ cảnh/chunk lúc index bằng model local. **Lane nhẹ ✅ 21/08**: cột `retrieval_context` (migration `20260821_25`), sinh context ngoài transaction chung cho cả hai đường index, embedding + BM25 cùng index context+content qua một helper, citation giữ nguyên văn, 8 test; thiết kế + runbook đo: `docs/p4_progress.md`. **Lane nặng ✅ 21/08 (`PC-dungbt`)**: ĐẠT ngưỡng — MRR tổng 0.734→0.797, MRR cross 0.590→0.799, recall cross 1.0, 0 câu hit→miss, 32.7s/tài liệu; cờ BẬT mặc định, máy nhẹ override `RAG_CONTEXTUAL_RETRIEVAL_ENABLED=false` | MRR đa tài liệu tăng ≥ 5 điểm (kỳ vọng theo paper: −49% failure) | 3 buổi |
| P4-3 ✅ | **Bật reranker** cross-encoder (`RerankerService.from_config` + `RAG_RERANKER_ENABLED` theo máy, warmup fail-fast lúc startup, CI ghim tắt, launcher tự ghim tắt khi máy thiếu extra `[rerank]`) — **ĐÓNG 21/08 (`PC-dungbt`)**: recall@5 0.915→0.976, MRR 0.797→0.858, MRR cross 0.799→0.861, 7 miss→hit / 2 hit→miss, +35ms p50 trên GPU (~990ms trên CPU → máy không GPU ghim tắt); `candidate_limit` 15 | ✅ Kết hợp P4-2: recall failure 13.4% → 2.4% trên bộ D1 (paper: −67%) | 1–2 buổi |
| P4-4a | **Gỡ tắc nghẽn rebuild BM25** — lane NHẸ, **không đụng schema**. Ba việc: (a) gọi `invalidate()` từ chính sự kiện activate version — hàm **đã có** (`postgres_bm25_service.py:79`) nhưng hiện **0 nơi gọi** trong `backend/app`; (b) bỏ truy vấn fingerprint khỏi đường query — hiện `search()` → `_ensure_index()` → `_current_fingerprint()` bắn một truy vấn DB **mỗi câu hỏi**; (c) dựng lại chỉ mục ở luồng nền, phục vụ chỉ mục cũ trong lúc dựng | Câu hỏi đầu sau mỗi lần khởi động không còn chờ rebuild (cột giữa của bảng ở §1 về ~0); mỗi query bớt 1 truy vấn DB; **D1 Δ = 0** vì không đổi thuật toán xếp hạng | 0.5–1 buổi |
| P4-4b | **Chỉ mục sparse vào PostgreSQL** thay `rank_bm25` in-process. **Thiết kế v1 (`docs/p4_4_design.md`) đã bị phản biện bác 23/08 — phải có v2 trước khi viết một dòng code** (§1, "Điều chỉnh 23/08"). v2 bắt buộc chốt: ① `int[]` song song thay `retrieval_tf jsonb` (dung lượng 1.90× → **1.06×** corpus trần, đo trên fixture D1); ② lời giải cho bộ lọc ứng viên — `&&` trên `text[]` kéo trung bình **97.5%** corpus, **59/82** câu kéo đúng 100%, vì hư từ tiếng Việt gần như phổ quát nên "bộ lọc" không lọc gì (hướng: bảng posting); ③ vá lỗ sai-âm-thầm khi `N`/`df`/`avgdl` lấy từ ba tập khác nhau lúc hàng chưa backfill xong; ④ `tokenizer_version` cạnh lexeme (⇒ **T16 là điều kiện tiên quyết**); ⑤ sửa các số sai của v1 — corpus lab là **27** chunk chứ không phải 273, `top_k` là **15** ở lane nhẹ/CI chứ không phải 45; ⑥ bỏ cấu trúc `text[] & text[]` — **toán tử này không tồn tại** trong PostgreSQL. Tổng 22 mục sửa từ báo cáo phản biện. **Hai phương án v1/v2 kèm ưu-nhược và quy tắc chọn: §9d** | Không tụt chất lượng (D1 Δ ≤ 0.02 cả ba chỉ số, đo trên DB lab); RAM không tăng theo corpus; hết chấm điểm O(corpus) mỗi query; nhất quán đa tiến trình. **Không** nhắm 2 câu miss cuối — đó là việc của tầng rerank | 0.5 buổi (đo) + 3–4 buổi (code) |
| P4-5 | **Chunk visualization** (học RAGFlow): xem chunk của tài liệu trong UI, đánh dấu chunk kém. **Đính chính 23/08: KHÔNG phụ thuộc P4-4** — `docs/p4_4_design.md` §12 nói ngược, nhưng cả 8 cột màn hình cần (`content`, `retrieval_context`, `chunk_index`, `page_start`, `page_end`, `section_title`, `block_type`, `content_hash`) **đã có sẵn** trong bảng `document_chunks`. Lane NHẸ, độc lập hoàn toàn, làm được ngay. Ghi chú: màn hình này chỉ hiện đúng `heading_path` **sau khi T15 được vá** | Người dùng tự chẩn đoán được "tại sao trả lời sai" | 3 buổi |

### P5 — Năng lực mở rộng *(tương lai, chọn lọc theo nhu cầu thật)*

> Tool use cơ bản đã chuyển lên P2-2 (trở thành lõi agent). Ở đây còn các mở rộng chọn lọc.
>
> **Quyết định 20/08: GÁC OCR và vision** cho tới khi có máy mạnh hơn (CPU/GPU
> hiện tại chưa tối ưu). Cụ thể: OCR console (P3-4) giữ nguyên như đã ship,
> không đầu tư thêm; mục vision attachments dưới đây đóng băng; bộ eval P4-1
> chỉ dùng tài liệu text-native (PDF có text layer, DOCX, TXT, MD) — không cần
> bản scan. Cấu hình `ocr.enabled` trong models.yaml giữ nguyên (chỉ chạy khi
> gặp tài liệu thiếu text layer, không tốn gì khi không dùng).

- **Tool bên ngoài cho agent** (thời tiết nội bộ? tra cứu ERP xưởng?) — chỉ khi có use case cụ thể.
- **Vision attachments**: đính ảnh vào chat (nền `vision_chat` đã có; endpoint `/vision/chat` đang 501).
- **Web search opt-in** cho câu hỏi ngoài tài liệu (học Open WebUI, mặc định tắt vì định vị riêng tư).
- **MCP client** nếu hệ sinh thái nội bộ cần nối tool ngoài (LibreChat là tham chiếu tốt).
- Fork/branch hội thoại; resumable streams đa tab (LibreChat).

### Track D — Kỹ năng AI engineer *(bổ sung 21/08 · song song các phase · tiêu chí kép: nâng chất hệ thống + xây kỹ năng AI đo được)*

> Nguồn: phân tích hướng phát triển 21/08 (hội thoại). Nguyên tắc xuyên suốt: mọi mục
> đều phải tạo ra **số liệu do chính mình thiết kế phép đo** — đó là thứ phân biệt
> AI engineer với người gọi API. Ràng buộc phần cứng chi phối thiết kế (xem bất biến
> "ngân sách inference" §1): không mục nào được chồng thêm lượt gọi model mặc định.

| ID | Hạng mục | Nội dung & tiêu chí nghiệm thu | Điều kiện máy | Ước lượng |
| --- | --- | --- | --- | --- |
| D1 | **Eval engineering** — nền của mọi mục sau | Bộ eval RAG tiếng Việt 50–100 câu trên 3–5 tài liệu thật (có nhóm câu cross-doc chủ đích); đo retrieval hit-rate, faithfulness (bám nguồn), citation accuracy; gate trong CI chặn thoái lui. Chính là **P4-1 bản retrieval-only làm-được-ngay** (embedding 0.6b, không cần re-index loop nặng) — gỡ G7; thí nghiệm P4-2/P4-3 vẫn đợi máy. **✅ ĐÓNG 21/08**: corpus 5 tài liệu snapshot + 82 câu (70 single, 12 cross; mọi `expected_source_terms` đối chiếu nguyên văn với chunk thực) + endpoint `/rag/search` retrieval-only + job CI `retrieval-eval`. Baseline ghi từ chính job CI (model 0.6b thật): **recall@5 0.866 · MRR 0.734 · doc_hit 0.768** (cross-doc: 0.75/0.59) — gate chặn thoái lui đang hoạt động; số liệu + phân tích miss: `docs/d1_retrieval_eval.md`. Đo lại chỉ khi đổi model embedding hoặc corpus | Máy hiện tại OK | 3–4 buổi |
| D2 | **Distillation extractor 9b → 2b** (QLoRA) | 9b làm teacher sinh vài nghìn cặp (tin nhắn → fact), lọc bằng guard sẵn có; fine-tune 2b trên GPU free (Colab/Kaggle — đủ cho 2b, không đụng máy nhà); nghiệm thu bằng chính benchmark 19/08: 2b-tuned phải đạt poison/coverage tương đương 9b+guard mới thay. Thất bại cũng chốt được bằng số liệu. Vai trò chiến lược: **lối thoát phần cứng** — bước phụ của agent giao được cho model nhỏ; là điều kiện mở lại D3c | GPU cloud free | 4–6 buổi |
| D3a | **Self-check không-LLM cho câu trả lời RAG** | Mở rộng tư duy guard memory (evidence verbatim + content-word overlap) sang câu trả lời: kiểm tra bám-nguồn ngay trước khi gửi, **0 lượt gọi model thêm** (mili-giây); hiệu quả chứng minh bằng D1 (điểm faithfulness trước/sau). **Phần xây ✅ 21/08 (máy nhẹ)**: `answer_grounding.py` chấm từng câu grounded/weak/ungrounded trên `content` trần (không dùng `retrieval_context`), xuyên ngữ trần ở weak + cờ `language_mismatch`; field `grounding` trên `/rag/chat` (thường + SSE `done`), chip bám nguồn trên web; `evaluate_rag` chế độ full có `grounding_rate`; 10 test không model. **Đo ✅ 21/08 (máy nặng `PC-dungbt`)**: baseline faithfulness đầu tiên ghi tại `data/evaluation/rag_multidoc_grounding_baseline.json` — grounding_rate **0.9390** (77/82), 4 weak, 1 ungrounded; đối chiếu tay 10 câu: **0 dương tính giả về độ tin cậy** (tiêu chí chính đạt) nhưng 2/3 nhãn thấp là báo oan xuyên ngữ — pool nguồn trộn Việt+Anh làm cap ngôn ngữ không bật với câu Việt dịch từ chunk bằng chứng tiếng Anh. **✅ ĐÓNG 21/08** sau vòng đo lại (máy nặng, sau sửa cap xuyên ngữ theo-nguồn-khớp-nhất của máy nhẹ): grounding_rate **0.9390** giữ nguyên nhưng *chất* nhãn thấp đổi hẳn — **0 ungrounded** (trước 1, và lần bắn duy nhất đó là báo oan), `language_mismatch` 0→**3** (cờ giờ đánh dấu đúng câu dịch từ chunk tiếng Anh); đối chiếu tay vòng 2 (toàn bộ 5 nhãn thấp + 3 grounded ngẫu nhiên): tiếp tục **0 dương tính giả về độ tin cậy** (cộng dồn hai vòng: 15 câu grounded, 0 mệnh đề bịa), nhãn thấp 2/3 nói đúng bản chất "không chấm được vì khác ngôn ngữ", còn 1 báo oan nhẹ ở mức weak (attribution trượt — ghi hồ sơ, không chặn đóng). Quyết định hành vi: **giữ "chỉ báo"** — `ungrounded` bắn 0/82 sau sửa và chưa từng có dương tính thật để thiết kế hành vi tự động quanh nó; mở lại khi đổi model/prompt/corpus làm nó bắn thật hoặc khi D5 tạo được câu bịa chủ đích. Baseline: `data/evaluation/rag_multidoc_grounding_baseline.json`; hai bảng tay + lý do đầy đủ: `docs/d3a_answer_grounding.md` | Máy hiện tại OK | 2 buổi |
| D3b | **Digest nền có luật nhường** | Agent tự tổng hợp định kỳ (tài liệu mới, memory đáng chú ý, việc nền lỗi) gửi Discord; **luật nhường**: chỉ chạy khi hệ rảnh ≥ N phút, tự dừng ngay khi có request tương tác, kích hoạt tay được (`/digest`), máy tắt thì bỏ lượt không dồn; audit + thu hồi theo bất biến P2 | Máy hiện tại OK nếu giữ luật nhường | 3 buổi |
| D3c | **Multi-step planning** — **GÁC 21/08** | Phân rã câu hỏi đa tài liệu thành nhiều lượt retrieval (đúng điểm yếu cross-doc đã thấy khi test 2 paper 20/08). Gác vì độ trễ cộng dồn 5–8 lượt gọi/câu không cứu được bằng phần cứng sẽ có. Điều kiện mở lại: **D2 xong và có máy mới**; khi mở cũng chỉ dạng có-điều-kiện (heuristic rẻ phát hiện câu cần phân rã, ~90% câu single-hop đi đường cũ) + **cap cứng** tổng lượt gọi mỗi câu | Gác | (sau) |
| D4 | **LLMOps / observability** | Hợp nhất sử liệu rời (agent_traces, request_logs, dashboard) thành trace một-câu-hỏi-một-cây: retrieval → tool call → generation, kèm token vào/ra, thời gian, prompt version; prompt quản lý như code — mỗi version có số hiệu gắn điểm eval (extractor đã qua 5 đời prompt không sử liệu) | Máy hiện tại OK (chỉ ghi metadata) | 3–4 buổi |
| D5 ✅ | **AI security — red-team prompt injection** | Nội dung untrusted (tài liệu upload, tin Discord) vào prompt agent có tool: xây bộ tài liệu bẫy đo tỉ lệ agent bị lừa **trước/sau** phòng thủ; phòng tuyến: tách "lệnh hệ thống" khỏi "dữ liệu chỉ đọc" trong prompt + mở rộng guard evidence sang RAG. Cấp thiết tăng dần vì P3 đã mở multi-user upload. **Phần xây ✅ 21/08 (máy nhẹ)**: 6 tài liệu bẫy (6 vector) + 10 case + harness `redteam_rag.py` chấm marker xác định + `InjectionDefense` (cờ mặc định TẮT, bọc passage/tool-result + 1 quy tắc, 0 lời gọi model thêm, cờ TẮT = prompt cũ nguyên byte) + 10 test không-model. **Đo ✅ 22/08 (máy nặng, phiên lab :8001)**: attack_success_rate **0.143 → 0.000** (OFF → ON; lần thủng duy nhất ở OFF là `language_flip` — model in token xác nhận), D1 và grounding với defense ON **không đổi** (0.9756/0.8581/0.8537; grounding 0.939), control RAG byte-identical; nhưng `benign_pass_rate` 0.667 ở **cả hai** vòng vì control agent `benign_dat_coc_agent` không đo được (5/6 fixture bẫy viết không dấu → agent không kéo được tài liệu) → chưa qua ngưỡng 0.9 đã chốt → **cờ vẫn TẮT**. **Lần 2 ✅ 22/08 chiều** (fixture có dấu, 12 case): attack 0.143 → **0.000** lặp lại, benign **1.0** (5/5) → **`rag.injection_defense` BẬT mặc định** (0 lời gọi model thêm, có hiệu lực khi API khởi động lại). **D5 ĐÓNG.** Sửa kèm: `rebuild_qdrant.py` (vỡ 3 chỗ, nay dùng đúng helper context+content). Baseline: `data/evaluation/redteam_baseline.json`; chi tiết `docs/d5_redteam.md` | Máy hiện tại OK | 3–4 buổi |

**Trình tự khuyến nghị** (khớp giới hạn máy phụ hiện tại):

| Giai đoạn | Mục | Vì sao |
| --- | --- | --- |
| Ngay, trên máy hiện tại | **D1 → D5**, xen D3a | Chạy chủ yếu trên logic + retrieval, gần như không thêm tải model; D1 là thước đo cho mọi mục sau |
| Song song, GPU cloud free | D2 | Không đụng máy nhà; tái dùng benchmark 19/08 làm nghiệm thu |
| Sau khi có D1 | D3b, D4 | Digest và trace cần thước đo + sử liệu để chứng minh giá trị thay vì chỉ thêm tính năng |
| Máy mạnh (đã có, 21/08) | ~~P4-2/P4-3~~ ✅, ~~phần đo D3a/D5~~ ✅ → **chỉ còn 1 việc nặng: đo `pg_column_size` + `EXPLAIN ANALYZE` cho P4-4b** (0.5 buổi). P4-4a và P4-5 là lane NHẸ hoàn toàn — không cần máy mạnh. D3c sau D2 | Máy mạnh `PC-dungbt` đang vận hành; D3c cần cả D2 lẫn máy |

---

## 5. Kiến trúc đích (không đổi xương sống, chỉ bồi)

```
Web UI ─┐                                  ┌─ Qdrant (vector index)
        ├─ FastAPI ── services ── Postgres ┤
Discord ─┘    │                            └─ Sparse index (lexeme text[] + GIN, P4-4)
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
| Việc nền của agent chặn request tương tác (Ollama 1 slot/máy) | Trung — tăng nếu thêm D3b | Bất biến ngân sách inference (§1); luật nhường của D3b: chỉ chạy khi rảnh, tự dừng khi có người hỏi |
| Prompt injection qua tài liệu/tin nhắn (untrusted input vào agent có tool) | Trung — tăng theo multi-user (P3) và mức tự hành | D5: red-team đo được + tách lệnh/dữ liệu trong prompt; chưa mở upload cho người lạ ngoài nhóm tin cậy trước khi có D5 |

## 9. Việc tiếp theo — handoff sang máy mới (chốt 21/08/2026)

> Hiện trạng bàn giao: **P0 → P3 đã đóng** (nhật ký `docs/p1..p3_progress.md`), nợ P0.5
> đợt T1–T3+T6 đã trả 21/08, plan v1.2 đã chứa Track D. Quyết định 21/08: chuyển sang
> máy mạnh hơn rồi thi công tiếp — checklist dưới đây là toàn bộ đường chuyển.

### 9a. Checklist chuyển máy (những gì git KHÔNG mang theo)

1. **Trên máy cũ, trước khi rời**: chạy backup Postgres mới (`python -m scripts.backup_postgres` từ `backend/`, hoặc xác nhận dump mới nhất < 24h trong `data/backups/postgres/local-ai-*.dump`).
2. **Chép tay sang máy mới** (tuyệt đối không commit — đúng quy tắc bảo mật sẵn có):
   - `.env` (DISCORD_TOKEN, LOCAL_AI_API_KEY, JWT secret, mật khẩu DB, các cờ memory/agent);
   - toàn bộ thư mục `data/` — trong đó `data/qdrant/` (vector index, bind-mount nên đi theo thư mục), `data/documents/` (file gốc đã upload), `data/backups/postgres/` (dump).
3. **Máy mới**: cài Docker Desktop + Ollama → clone repo → đặt `.env` và `data/` vào chỗ cũ → chạy `run-local-ai-core.bat` (launcher tự pull model theo `models.yaml`, dựng container).
4. **Restore Postgres** theo `docs/backup_restore.md` (pg_restore dump mới nhất vào container — dữ liệu Postgres nằm trong named volume nên KHÔNG tự đi theo thư mục), rồi `alembic upgrade head` từ repo root (head hiện tại: `20260821_25`).
5. **Xác minh bàn giao**: suite backend + bot xanh; mở dashboard thấy đủ lịch sử/timeline; hỏi 1 câu RAG trên tài liệu cũ có nguồn (Qdrant đi theo `data/` nên không cần re-index; nếu lệch thì reindex từng tài liệu từ UI); nếu dùng bot: bật từ dashboard như P3-2.
6. **Chốt cấu hình model TRƯỚC khi đo đạc**: máy mạnh hơn → cân nhắc nâng model general trong `models.yaml` (ghi chú P4 §4). Mọi baseline D1/P4-1 chỉ đo **một lần trên cấu hình cuối** — đổi model sau khi đo là phải đo lại.

### 9b. Thứ tự thi công (hai máy — xem `docs/machine_split.md`)

> **Quyết định 21/08 (tối)**: máy nặng `PC-dungbt` = **vận hành** (dữ liệu thật, launcher, bot, backup, cấu hình ship); máy nhẹ = **viết plan/code/test** + client qua LAN. Dữ liệu thật chỉ ở máy nặng; snapshot một chiều nặng → nhẹ. Chi tiết và quy tắc: `docs/machine_split.md` mục "Vận hành ở đâu".

> Từ 21/08 dự án chạy trên **hai máy**: máy nhẹ (daily, GPU yếu) và máy mạnh (dùng ít).
> Phân lane bằng câu hỏi thử duy nhất — "bước này có cần model SINH hoặc re-index nặng
> không?": không → làm ngay trên máy nhẹ; có → để dành máy mạnh. Mỗi máy có file
> `.machine-role` (`light`/`heavy`, đã gitignore) để phiên Claude tự route. Nhiều mục
> chẻ đôi: phần *xây* (nhẹ) làm trước ở máy nhẹ, phần *đo* (nặng) handoff sang máy mạnh.

1. **D1 — bộ eval đa tài liệu** ✅ **ĐÓNG 21/08**: hạ tầng + dataset 82 câu + baseline retrieval-only (recall@5 0.866 / MRR 0.734 / doc_hit 0.768, model `qwen3-embedding:0.6b`, đo trong chính CI) + gate chặn thoái lui đang hiệu lực. Nhật ký: `docs/d1_retrieval_eval.md`.
2. **D5 red-team + D3a self-check** — hai mục rẻ, ăn ngay vào chất lượng và an toàn. Phần *xây* (guard bám-nguồn, corpus bẫy, harness, unit test) là lane NHẸ → làm trên máy nhẹ ngay; phần *đo* (faithfulness qua model sinh, chạy tấn công thật) là lane NẶNG → máy mạnh.
3. **Mở lại P4** theo đúng thứ tự đã phân tích — mỗi mục một thí nghiệm chấm bằng D1:
   - **P4-2 contextual retrieval** ✅ **ĐÓNG 21/08** (đo trên máy nặng `PC-dungbt`): ĐẠT ngưỡng, cờ `rag.contextual_retrieval.enabled` BẬT mặc định. recall@5 0.866 → **0.915**, MRR 0.734 → **0.797**, doc_hit 0.768 → **0.842**; nhóm cross recall 0.750 → **1.000**, MRR 0.590 → **0.799**; 4 câu miss→hit, 0 câu hit→miss. Chi phí: 1 lời gọi model/chunk lúc index (27 chunk / 144s cho corpus 5 tài liệu), đường hỏi-đáp **không thêm lời gọi nào** — bất biến ngân sách inference còn nguyên. Baseline D1 đã ghi lại; CI gate chuyển sang đo bản trần theo `rag_multidoc_baseline_bare.json` vì runner không có model sinh. Nhật ký: `docs/p4_progress.md`.
   - **P4-3 reranker** ✅ **ĐÓNG 21/08** (đo trên máy nặng `PC-dungbt`): ĐẠT cả ba điều kiện, cờ `rag.reranker.enabled` BẬT mặc định với `candidate_limit` 15. recall@5 0.915 → **0.976**, MRR 0.797 → **0.858**, MRR cross 0.799 → **0.861**; **cả 7 câu miss còn lại của P4-2 thành hit**, đổi lại 2 câu tụt khỏi top-5 (vẫn đúng tài liệu, chỉ trượt chunk mang nguyên văn). Chi phí là **độ trễ, không phải lời gọi model sinh**: `/rag/search` p50 587 → 622ms (**+35ms**, trần đã chốt 300ms). Bài học ghi lại: extra `[rerank]` kéo về torch CPU-only, đo nhầm trên đó thì +990ms và mục này đã trượt — máy bật reranker phải có GPU + torch CUDA, máy khác ghim `RAG_RERANKER_ENABLED=false`. `candidate_limit` 30 kém hơn 15 ở mọi chỉ số xếp hạng (MRR/doc_hit; recall@5 hòa) lẫn tốc độ. Nhật ký: `docs/p4_progress.md`.
   - **P4-4 / P4-5** — xem "Danh sách việc chốt 23/08" ngay dưới. Đính chính 23/08: P4-4 **không** nhắm 2 câu miss cuối (`p3_khoa_brute_force`, `p3_refresh_khong_xoay`) — audit cho thấy chunk đúng đã nằm trong ứng viên, cross-encoder mới là nơi quyết định. P4-4 nhắm **G8** (RAM / rebuild / đa tiến trình), không nhắm chất lượng xếp hạng.

### 9c. Danh sách việc chốt 23/08 (thứ tự thi công, sau vòng phản biện P4-4)

> Nguyên tắc của đợt này: **việc rẻ và độc lập đi trước, thay đổi schema đi sau cùng và
> chỉ sau khi có số đo.** Sáu việc đầu không đụng schema, không cần máy mạnh, không phụ
> thuộc lẫn nhau — hỏng một việc không chặn các việc còn lại.

| # | Việc | Lane | Vì sao đi trước | Ước lượng |
| --- | --- | --- | --- | --- |
| 1 | **Vá T15** — `replace_chunks` ghi đủ `locations`/`heading_path`/`token_count` + test qua đường ghi thật | nhẹ | **Bug đang chảy máu ở production**: mọi citation trả `heading_path: null`. Không liên quan P4-4, không có lý do để đợi | 0.5 buổi |
| 2 | **Viết `docs/p4_4_design.md` v2** (22 mục sửa) + đính chính các dòng plan đã lỗi thời | nhẹ | Bản v1 không được phép làm cơ sở để code; viết v2 là việc giấy tờ, rẻ nhất trong danh sách | 0.5–1 buổi |
| 3 | **P4-4a** — gỡ tắc nghẽn rebuild (invalidate theo sự kiện, bỏ fingerprint khỏi query path, dựng nền) | nhẹ | Xoá ngay triệu chứng "câu hỏi đầu sau khởi động bị treo" mà không cần đợi P4-4b; D1 không đổi nên không cần đo lại | 0.5–1 buổi |
| 4 | **T16** — ghim `pyvi` đúng version + khái niệm `tokenizer_version` | nhẹ | Điều kiện tiên quyết của P4-4b; rẻ và không rủi ro | 0.5 buổi |
| 5 | **P4-5** chunk visualization | nhẹ | Đã xác minh độc lập với P4-4 (8/8 cột có sẵn). Hiện `heading_path` đúng thì cần #1 xong trước | 3 buổi |
| 6 | **Thêm `p50_latency_ms`/`p95_latency_ms`** vào summary của `run_multidoc_mode` | nhẹ | P4-4a/P4-4b đều hứa cải thiện độ trễ mà bộ eval hiện **không** báo cáo độ trễ — không có thước thì không nghiệm thu được | 0.5 buổi |
| 7 | ✅ **ĐÃ ĐO 23/08** (máy vận hành) → **HOÃN P4-4b** (§9d.6). Việc #8 do đó **không khởi động**; #1–#6 giữ nguyên | **nặng** (riêng số #2 mô phỏng được ở lane nhẹ — làm trước) | Năm số này quyết định hình dạng schema của P4-4b. Đo **trước** khi viết migration — đúng bài học P4-3 | 0.5 buổi |
| 8 | **P4-4b** code theo phương án đã chốt ở #7; cờ `rag.sparse_backend` mặc định `inprocess`, chỉ đổi mặc định sau khi D1 parity đạt | nhẹ (code) + nặng (đo) | Việc đắt nhất, đi cuối, và chỉ khởi động khi #2 và #7 xong | 3–4 buổi |

**Ràng buộc chốt kèm**: P4-4b không được đổi mặc định nếu D1 lệch quá 0.02 ở bất kỳ chỉ số
nào; đường `inprocess` phải sống song song cho tới khi baseline mới được ghi; và mọi baseline
đã có (D1, P4-2, P4-3, D3a, D5) chỉ đo lại **một lần** trên cấu hình cuối của P4-4b.

### 9d. P4-4b — hai phương án v1 và v2, ưu/nhược để chọn

> **Mục đích của mục này**: hai bản thiết kế cùng nhắm G8 nhưng đánh đổi ngược nhau. Mục
> này giữ **cả hai còn sống** để phiên agent trên máy vận hành (`PC-dungbt`) phân tích và
> chốt bằng số đo thật, thay vì thừa kế một lựa chọn đã bị bác. **Chưa chọn = đúng trạng
> thái hiện tại.** Bản v1 đầy đủ vẫn nằm ở `docs/p4_4_design.md`.

#### 9d.0 — Bốn nỗi đau G8 và không gian lựa chọn

Mọi phương án dưới đây được chấm trên đúng bốn nỗi đau, không thêm không bớt:

| | G8-1 RAM theo corpus | G8-2 Rebuild chặn câu hỏi đầu | G8-3 Chấm điểm O(corpus)/query | G8-4 Đa tiến trình (`--workers`) |
| --- | --- | --- | --- | --- |
| **A — P4-4a** (đã chốt ở §9c#3, không đụng schema) | ❌ | ✅ *giấu* độ trễ (dựng nền) | ❌ | ❌ |
| **B — chỉ lưu token xuống DB**, vẫn `rank_bm25` trong RAM | ❌ | ✅ *xoá* 98.1% chi phí (hết tách từ pyvi) | ❌ | ❌ |
| **v1 — mảng `text[]` + GIN** (`docs/p4_4_design.md`) | ✅ | ✅ | ⚠️ **lý thuyết có, đo thật thì không** | ✅ |
| **v2 — vá lỗi + giải bài toán chọn lọc** | ✅ | ✅ | ✅ *nếu* bộ lọc thật sự lọc | ✅ |

A và B **không loại trừ** v1/v2 — chúng rẻ, độc lập, và A đã nằm trong danh sách §9c. Câu
hỏi thật chỉ là **v1 hay v2**, và **có đáng làm bây giờ không**.

#### 9d.1 — Phương án v1 (bản `docs/p4_4_design.md`, 23/08 sáng)

Hình dạng: ba cột thêm vào `document_chunks` — `retrieval_lexemes text[]` (+ GIN),
`retrieval_tf jsonb`, `retrieval_len int`; ứng viên lọc bằng `retrieval_lexemes && $1`;
DF tính trong chính truy vấn; BM25 chấm trong app (vì `ts_rank_cd` không có IDF).

**Ưu điểm**

- **Thay đổi schema nhỏ nhất**: 3 cột trên bảng đã có, không bảng mới, không khoá ngoại mới, migration additive thuần — đúng bất biến §1.
- **Ghi cùng transaction với chunk**: lexeme/tf/len sinh ngay ở `replace_chunks`, không có trạng thái dẫn xuất lệch pha, không cần worker đồng bộ.
- **Dung lượng rẻ nhất trong các phương án có schema** — sau khi đổi `jsonb` → `int[]`: **1.06×** corpus trần (đo trên fixture D1 27 chunk: content 48 318 B; lexemes 32 658 B = 0.68×; tf `int[]` 18 560 B = 0.38×).
- **Đọc dễ, ít bề mặt lỗi**: một hàng chunk = một chunk, mọi thứ dùng để chấm điểm nằm cùng hàng.
- **Rollback rẻ**: tắt cờ `rag.sparse_backend` là quay lại `rank_bm25` ngay, không phải dọn bảng.

**Nhược điểm** (⚠ = đã đo, ✎ = vá được trong v2)

- ⚠ **Bộ lọc ứng viên không lọc.** `retrieval_lexemes && $1` kéo trung bình **97.5%** corpus, **59/82** câu kéo đúng **100%** — hư từ tiếng Việt (`của`, `là`, `và`, `khi`…) gần như có mặt ở mọi chunk. Nghĩa là **G8-3 không được giải**: vẫn chấm gần như toàn corpus, chỉ đổi chỗ chấm từ RAM sang DB→app.
- ⚠ **Vượt ngưỡng dừng dung lượng của chính nó** ở bản gốc: `retrieval_tf jsonb` đo **1.90×** corpus trần và **2.28×** ở cấu hình ship (contextual retrieval BẬT), trong khi thiết kế tự đặt ngưỡng dừng 2×.
- ⚠ **Dùng toán tử không tồn tại**: `text[] & text[]` không có trong PostgreSQL (toán tử giao mảng `&` chỉ có ở extension `intarray`, và chỉ cho `int[]`).
- ⚠ **Sai âm thầm khi backfill dở**: `N`, `df`, `avgdl` lấy từ ba tập hàng khác nhau lúc một phần chunk chưa có lexeme → điểm BM25 sai mà **không lỗi nào bắn ra**, và gate D1 hiện không đủ nhạy để bắt (một câu thoái lui nằm gọn trong dung sai 0.02).
- ✎ Thiếu `tokenizer_version` → đổi bản `pyvi` thì dữ liệu trong DB bẩn vĩnh viễn, không còn chỉ là lệch runtime (⇒ **T16**).
- ✎ Vài số sai trong tài liệu (corpus lab **27** chunk chứ không phải 273; `top_k` **15** ở lane nhẹ/CI chứ không phải 45).
- **Chi phí ghi**: ~166 mục GIN mỗi chunk (đo: 166 lexeme phân biệt/chunk) — ghi nặng hơn hẳn hiện tại, đổi lại đường đọc chưa chắc nhanh hơn (xem gạch đầu dòng đầu).

#### 9d.2 — Phương án v2 (hướng, **chưa phải thiết kế hoàn chỉnh**)

v2 = v1 đã vá 22 mục **cộng** một lời giải thật cho chọn lọc ứng viên. Phần "đã vá" là việc
chắc chắn (đổi `int[]`, thêm `tokenizer_version`, vá lỗ `N`/`df`/`avgdl`, bỏ toán tử không
tồn tại, sửa số). Phần "chọn lọc" còn **hai nhánh chưa đo**:

**v2-A — cắt lexeme phổ quát theo DF, giữ nguyên hình dạng mảng.**
Trước khi `&&`, bỏ khỏi câu hỏi những lexeme có `df/N` vượt ngưỡng (hư từ). Giữ toàn bộ ưu
điểm dung lượng và migration của v1.

- **Ưu**: rẻ nhất — không bảng mới, không đổi mô hình ghi; và **thử được trước khi cam kết bất cứ schema nào**, bằng cách mô phỏng trên chính chỉ mục RAM hiện tại.
- **Nhược / rủi ro**: **chưa đo** — chưa biết ngưỡng nào cho selectivity chấp nhận được mà không làm hỏng đúng những câu cần khớp **nguyên văn**; ngưỡng DF là một siêu tham số mới phải chỉnh theo corpus; câu hỏi toàn hư từ có thể ra tập ứng viên rỗng.

**v2-B — bảng posting (chỉ mục đảo thật).**
`chunk_lexemes(lexeme, chunk_ref, tf)` + index theo `lexeme`; ứng viên = hợp các posting
list của lexeme câu hỏi, cắt theo DF ngay trong kế hoạch truy vấn.

- **Ưu**: giải **cấu trúc** bài toán chọn lọc — đây là cách mọi công cụ tìm kiếm thật làm; DF có sẵn từ `count(*)`; mở đường cắt top-N ngay trong DB.
- **Nhược**: **dung lượng đảo ngược hoàn toàn ưu thế của v1.** Ước tính số học hàng (**chưa đo**, phải kiểm bằng `pg_total_relation_size`): 166 lexeme/chunk × 10 000 chunk = **1.66 triệu hàng**; header hàng ~24 B → heap ~80 MB + index theo lexeme ~46 MB ≈ **126 MB** cho corpus nội dung chỉ ~18 MB → **~7×**, so với ~1.06× của v1. Dùng thẳng `chunk_id String(128)` làm khoá còn tệ hơn (cần khoá thay thế kiểu số).
- **Nhược**: bảng dẫn xuất tách rời → thêm một bất biến phải giữ (posting luôn khớp chunk đang active), thêm đường xoá/ghi đè, thêm chỗ để lệch.
- **Nhược**: rollback không còn là "tắt cờ" — phải dọn bảng.

#### 9d.3 — Đối chiếu trực tiếp

| Tiêu chí | v1 (mảng, đã vá `int[]`) | v2-A (mảng + cắt DF) | v2-B (bảng posting) |
| --- | --- | --- | --- |
| Dung lượng thêm / corpus | **~1.06×** (đo) | ~1.06× (như v1) | **~7×** (ước tính, chưa đo) |
| Giải được G8-3? | **Không** (đo: kéo 97.5%) | *Có thể* — chưa đo | **Có** (theo cấu trúc) |
| Độ phức tạp migration | Thấp (3 cột) | Thấp (3 cột) | Trung bình (bảng + backfill + bất biến mới) |
| Bề mặt lệch trạng thái | Nhỏ (cùng transaction) | Nhỏ | **Lớn** (bảng dẫn xuất riêng) |
| Chi phí rollback | Tắt cờ | Tắt cờ | Tắt cờ **+ dọn bảng** |
| Siêu tham số mới | 0 | **1** (ngưỡng DF) | 0–1 |
| Thử được **trước** khi đổi schema? | Không | **Được** (mô phỏng trên chỉ mục RAM) | Không |
| Trạng thái | Đã viết đầy đủ, đã bị bác 6 điểm | Hướng, chưa đo | Hướng, chưa đo |

#### 9d.4 — Năm số máy 2 phải đo trước khi chốt

Không chọn bằng lập luận. Chốt bằng năm số này, đo trên **DB lab** (`local_ai_core_lab_20260821`; production chỉ đọc):

1. **Selectivity thật của `&&`** trên corpus vận hành hiện tại (không phải fixture 27 chunk) — bao nhiêu % chunk bị kéo, trung vị và p95, trên 82 câu D1.
2. **Selectivity sau khi cắt DF** ở vài ngưỡng (`df/N` > 0.2 / 0.3 / 0.5) — và **quan trọng nhất**: có câu nào tụt khỏi tập ứng viên không. Đo này **mô phỏng được ngay trên chỉ mục RAM hiện tại, không cần migration** → làm **đầu tiên**, vì nếu v2-A đạt thì v2-B thành thừa.
3. **`pg_column_size` thật** của `text[]` và `int[]` trên corpus vận hành (số fixture 27 chunk chỉ là chỉ dấu).
4. **`pg_total_relation_size` của bảng posting** dựng thử trên lab — kiểm con số ~7× ở trên là đúng hay ước tính sai.
5. **`EXPLAIN ANALYZE`** cả hai đường: planner có thật sự dùng GIN không, hay ở quy mô này nó chọn seq scan (rất có thể) — nếu là seq scan thì mọi lập luận về GIN đều vô nghĩa.

#### 9d.6 — KẾT QUẢ ĐO 23/08 (máy vận hành) → **HOÃN P4-4b**

Năm số ở §9d.4 đã đo xong trên `PC-dungbt` (production chỉ đọc; thí nghiệm ghi trong DB
dùng-một-lần `local_ai_core_p44_test`). Áp quy tắc §9d.5 → **nhánh 3: không làm P4-4b bây
giờ**; giữ A (P4-4a) + B (chỉ lưu token). Bảng đầy đủ, cách đo và điều kiện mở lại:
`docs/p4_progress.md`, mục "P4-4b — chọn phương án bằng số đo".

Ba con số quyết định, và **ba chỗ plan này ghi sai** (số liệu thắng, plan phải sửa):

| Ghi ở §9d | Đo thật | Hệ quả |
| --- | --- | --- |
| v1-đã-vá "~1.06× corpus" | **3.65×** ở 118 chunk, **1.89×** ở 5 000 (hội tụ) | con số cũ **bỏ quên index GIN** (riêng GIN 2.29×) và lấy từ fixture 27 chunk; `text[]` thật là 1.21× chứ không phải 0.68× |
| posting "~7× (ước tính)" | **12.32–12.64×**, ổn định mọi quy mô | ước tính bỏ qua chuỗi `lexeme` lặp mỗi hàng + index B-tree (40% tổng) |
| v2-A "*có thể* giải G8-3" | **không** — planner chọn **Seq Scan** ở mọi quy mô đã đo, **126.9 ms** ở 5 000 chunk | ở đúng ngưỡng kích hoạt của §1, v2-A **chậm hơn** chấm BM25 in-process (~50 ms) |

Cắt DF (v2-A) trượt vì **ngưỡng an toàn không ổn định giữa corpus**: production an toàn từ
df/N 0.15 (28.4%), lab 0.15 đã mất một câu và chỉ an toàn từ 0.20 → ngưỡng chung 0.20 cho
**34.7% / 40.7%**, đều trên mốc 30%. Không ngưỡng nào trong ba ngưỡng §9d.4 chỉ định
(0.2/0.3/0.5) đạt < 30%.

Mở lại khi corpus active vượt ~5 000 chunk **và** p95 `/rag/search` vượt ngân sách, **hoặc**
khi có cách chọn lọc đo được < 30% **ổn định trên ≥ 2 corpus**. Khi đó **đo lại cả năm số** —
tỷ lệ dung lượng và lựa chọn của planner đều phụ thuộc quy mô.

#### 9d.5 — Quy tắc chọn (chốt TRƯỚC khi đo, để số liệu không bị đọc theo ý muốn)

- Nếu **#2 cho thấy cắt DF hạ selectivity xuống < 30% mà không câu nào mất ứng viên đúng** → chọn **v2-A**. Rẻ nhất, giữ mọi ưu điểm của v1, giải được G8-3.
- Nếu **#2 thất bại** *và* **#4 xác nhận bảng posting ≤ 3× corpus** → chọn **v2-B**.
- Nếu **#2 thất bại** *và* **#4 ra ~7× như ước tính** → **không làm P4-4b bây giờ**: giữ A + B (§9c#3 và "chỉ lưu token"), vì lúc đó cái giá của G8-3 cao hơn chính nỗi đau, và corpus hiện tại chưa tới ngưỡng ~5 000 chunk ở §1.
- **v1 nguyên bản không được chọn trong mọi trường hợp** — nếu số liệu ủng hộ hình dạng mảng thì đó là **v2-A** (v1 + `int[]` + `tokenizer_version` + vá `N`/`df`/`avgdl`), không phải v1.
- Ràng buộc chung cho mọi nhánh: vẫn phải qua **D1 Δ ≤ 0.02** trên cả ba chỉ số, và đường `inprocess` sống song song cho tới khi baseline mới được ghi.
4. **D2 distillation** (cloud free hoặc máy mới nếu GPU đủ) → chỉ sau khi D2 đạt mới xét mở **D3c** multi-step planning (vẫn dạng có-điều-kiện + cap theo bất biến ngân sách inference).
5. **D3b digest nền + D4 LLMOps** xen kẽ sau D1; nợ còn lại (T5, T7–T9, T11–T13) dọn khi đụng vùng, T10 hẹn 2027.

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
