# Kế hoạch phát triển tổng thể — Local AI Core

**Phiên bản:** 1.2 · **Ngày:** 15/08/2026 · **Cập nhật:** 19/08 (agent-first) · 21/08/2026 (track D — kỹ năng AI + ngân sách inference) · **Trạng thái:** Đang hiệu lực
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
| T11 | **Test và runtime dùng chung Qdrant**: collection `memories` đã cô lập bằng `QDRANT_MEMORIES_COLLECTION` (19/08, sau khi test 3-dim làm hỏng đường ghi memory thật); collection `documents` hiện chỉ an toàn nhờ test dùng fake store — chưa có guard tường minh | Cô lập tên collection `documents` cho test giống memories, hoặc guard chiều vector khi tạo | 1 buổi |
| T12 | **Đánh bóng agent P2** (gom, không chặn dùng): UI hiện lại trace khi mở hội thoại cũ (messages cần trả kèm id); footer tool cho tin Discord; hủy vòng lặp khi client ngắt; map lỗi tools-với-provider-cloud thành 502 rõ nghĩa; tránh nạp memory hai lần khi bật cả «Ghi nhớ» lẫn «Công cụ»; **guard xuyên ngữ** — fact tiếng Anh vs tin Việt bị từ chối oan (an toàn nhưng mất coverage; hướng: prompt extractor v6 viết fact bằng ngôn ngữ tin gốc + re-benchmark) | Dọn khi đụng vào từng vùng | 2–3 buổi |
| T13 | **Đánh bóng auth P3-1** (gom, không chặn dùng): đổi mật khẩu + admin reset qua UI; trang quản lý user trên dashboard (hiện chỉ API); token localStorage → cân nhắc cookie httpOnly nếu mở ra ngoài LAN; member-role staleness 15' ở surface thường; ẩn/hiện điều khiển theo role còn thiếu chỗ nào thì server vẫn chặn | Dọn khi đụng vào từng vùng | 2–3 buổi |
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

### P4 — RAG nâng cao, có đo lường *(chạy nền liên tục, mỗi mục một thí nghiệm)* — **MỞ LẠI 21/08 trên máy mạnh** (P4-1≡D1 ✅, P4-2 ✅, P4-3 ✅; còn P4-4, P4-5)

> Quyết định 20/08: P4 cần vòng lặp thí-nghiệm-nhanh (re-index + eval mỗi lần
> chỉnh) — trên CPU hiện tại mỗi vòng mất nửa buổi nên gác tới khi chuyển máy.
> Chỉ số chất lượng không phụ thuộc máy nên không mất gì khi đợi; khi có máy
> mới: restore backup + pull model + đổi models.yaml (plan §8), cân nhắc nâng
> model general trước rồi mới đo baseline P4-1 một lần trên cấu hình cuối.
> Hướng thi công từng mục đã phân tích sẵn trong hội thoại 20/08: thứ tự
> P4-1 → P4-4 (pyvi tách từ vào tsvector) → P4-2 → P4-3 (+T6) → P4-5; eval
> trong CI theo phương án retrieval-only với model embedding 0.6b.

| ID | Hạng mục | Giả thuyết cần kiểm chứng bằng eval | Ước lượng |
| --- | --- | --- | --- |
| P4-1 | **Mở rộng bộ eval**: 3–5 tài liệu thật + 30 câu đa tài liệu + eval trong CI (gate: không tụt quá 2 điểm) | Baseline mới thay bộ 1-tài-liệu đã bão hòa | 2 buổi |
| P4-2 | **Contextual retrieval** (Anthropic): sinh 50–100 token ngữ cảnh/chunk lúc index bằng model local. **Lane nhẹ ✅ 21/08**: cột `retrieval_context` (migration `20260821_25`), sinh context ngoài transaction chung cho cả hai đường index, embedding + BM25 cùng index context+content qua một helper, citation giữ nguyên văn, 8 test; thiết kế + runbook đo: `docs/p4_progress.md`. **Lane nặng ✅ 21/08 (`PC-dungbt`)**: ĐẠT ngưỡng — MRR tổng 0.734→0.797, MRR cross 0.590→0.799, recall cross 1.0, 0 câu hit→miss, 32.7s/tài liệu; cờ BẬT mặc định, máy nhẹ override `RAG_CONTEXTUAL_RETRIEVAL_ENABLED=false` | MRR đa tài liệu tăng ≥ 5 điểm (kỳ vọng theo paper: −49% failure) | 3 buổi |
| P4-3 ✅ | **Bật reranker** cross-encoder (`RerankerService.from_config` + `RAG_RERANKER_ENABLED` theo máy, warmup fail-fast lúc startup, CI ghim tắt, launcher tự ghim tắt khi máy thiếu extra `[rerank]`) — **ĐÓNG 21/08 (`PC-dungbt`)**: recall@5 0.915→0.976, MRR 0.797→0.858, MRR cross 0.799→0.861, 7 miss→hit / 2 hit→miss, +35ms p50 trên GPU (~990ms trên CPU → máy không GPU ghim tắt); `candidate_limit` 15 | ✅ Kết hợp P4-2: recall failure 13.4% → 2.4% trên bộ D1 (paper: −67%) | 1–2 buổi |
| P4-4 | **Postgres FTS thay BM25 in-process** (tsvector + GIN + unaccent) | Không tụt chất lượng; RAM không tăng theo corpus; nhất quán đa process | 3–4 buổi |
| P4-5 | **Chunk visualization** (học RAGFlow): xem chunk của tài liệu trong UI, đánh dấu chunk kém | Người dùng tự chẩn đoán được "tại sao trả lời sai" | 3 buổi |

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
| D5 | **AI security — red-team prompt injection** | Nội dung tài liệu/tin Discord là untrusted input đi thẳng vào prompt của agent có tool. Xây bộ tài liệu bẫy (chỉ thị độc nhúng văn bản/bảng, Việt + Anh) đo tỉ lệ agent bị lừa **trước/sau** phòng thủ; phòng tuyến: tách "lệnh hệ thống" khỏi "dữ liệu chỉ đọc" trong prompt + mở rộng guard evidence sang RAG. Cấp thiết tăng dần vì P3 đã mở multi-user upload | Máy hiện tại OK | 3–4 buổi |

**Trình tự khuyến nghị** (khớp giới hạn máy phụ hiện tại):

| Giai đoạn | Mục | Vì sao |
| --- | --- | --- |
| Ngay, trên máy hiện tại | **D1 → D5**, xen D3a | Chạy chủ yếu trên logic + retrieval, gần như không thêm tải model; D1 là thước đo cho mọi mục sau |
| Song song, GPU cloud free | D2 | Không đụng máy nhà; tái dùng benchmark 19/08 làm nghiệm thu |
| Sau khi có D1 | D3b, D4 | Digest và trace cần thước đo + sử liệu để chứng minh giá trị thay vì chỉ thêm tính năng |
| Máy mạnh (đã có, 21/08) | ~~P4-2/P4-3~~ ✅ → P4-4 FTS+pyvi, P4-5, phần đo D3a/D5; D3c sau D2 | Máy mạnh `PC-dungbt` đã vận hành; D3c cần cả D2 lẫn máy |

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
   - **P4-4** Postgres FTS + pyvi → **P4-5** chunk visualization. Headroom P4-4 nhắm: 2 câu còn miss (`p3_khoa_brute_force`, `p3_refresh_khong_xoay`) — cả hai đòi khớp **nguyên văn** hai cụm trong cùng một chunk, đúng thứ FTS mạnh hơn cross-encoder ngữ nghĩa.
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
