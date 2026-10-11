# Không gian Nghiên cứu (Research Space) — spec thực thi

Status: in progress (11/10/2026). Phần 1 của gói thiết kế (app chính, 10 màn) đã ship từ 16/09 (`cccea32`).
Gói mới `Redesign web interface xanh.zip` (11/10) chỉ thêm **Phần 2** này + một mục nav "Nghiên cứu".

Nguồn thiết kế: `design_handoff_local_ai_core_v2/README.md` mục "Phần 2" + prototype
`design_handoff_local_ai_core_v2/Research Space v3.dc.html` (tham chiếu, không chép mã) + ảnh
`design_handoff_local_ai_core_v2/screenshots/handoff/r01…r08.png`. Cả gói nằm NGOÀI repo (gitignore).

Hợp đồng chung của frontend (Router / Shell / components / test) ở `.scratch/web-ui-v2/spec.md` — đọc trước.

## Quyết định đã chốt (phiên 11/10)

| Việc | Quyết định | Lý do |
|---|---|---|
| Paper là gì | Một **Document** sẵn có (bảng `documents`) + một dòng `research_papers` trỏ tới nó | Tải lên, OCR, chunk, `/rag/chat` theo `document_ids`, trích dẫn có `page`/`heading_path` đều đã chạy; không dựng pipeline thứ hai |
| Hiển thị PDF | Ảnh trang PNG render từ máy chủ (PyMuPDF đã có) + **lớp chữ** `words` đặt chồng để bôi đen được | Không dùng pdf.js: repo không có vendor JS, test cấm `fetch(` thô và khóa danh sách script |
| Hỏi paper / hỏi cả dự án | `POST /research/chat` SSE, bên trong gọi `rag_service.stream_response(document_ids=…)` như `/rag/chat` | Cùng sự kiện `meta/token/done/error`; frontend dùng `Shell.stream` (mới, shell.js) |
| Tóm tắt AI | Một lượt gọi Ollama ra JSON (mẫu `discord_memory_extractor`: `format` = JSON schema, `think:false`), vai trò `general`, cache JSONB trên dòng paper; **gọi tay** (nút / mở panel lần đầu), không chạy nền | Model 9b mất 30–120 s; chưa có worker cho việc này; kết quả lưu lại nên chỉ tốn một lần |
| So sánh | Không có endpoint; UI dựng 4 hàng từ `summary` của các paper đã tick (như prototype) | Không có dữ liệu nào ngoài tóm tắt |
| Cụm & kết nối | Bảng + CRUD **thủ công**; AI tự gộp cụm / gán nhãn quan hệ **để chờ chủ dự án chốt** | Cần đọc toàn kho bằng LLM, chưa có mốc đo đúng/sai |
| Tham chiếu `[n]` → paper trong kho | **Chờ chốt** (Crossref/OpenAlex cần Internet; hệ chạy LAN offline) | xem `decisions-open.md` |
| Font | Font hệ thống (quyết định Phần 1), không tải Be Vietnam Pro | giữ nguyên |
| Phím tắt | `⌘` = `ctrlKey \|\| metaKey`; nhãn hiện "Ctrl" trên Windows | máy chủ dự án chạy Windows |
| Bố cục | View gọi `Shell.setLayout("full")` trong `mount` → shell ẩn sidebar 264 + header 58; router tự trả về `"app"` khi sang view khác | Prototype tự vẽ kho paper / tab bar / rail và tính bề rộng ô từ viewport |
| Quyền | Member thấy và dùng được (nav không `admin`); dự án lọc theo chủ sở hữu khi bật tài khoản (như `conversations`); ghi cần `require_api_key` như mọi route ghi | README xếp "Nghiên cứu" cạnh Tài liệu/Ghi nhớ (mục member) |

## Khung đã sửa sẵn trong shell (xong, 11/10)

- `shell.js`: nav `{name:"research", label:"Nghiên cứu", icon:"book"}` giữa Tài liệu và Ghi nhớ;
  `Shell.setLayout("full"|"app")` (class `.app.layout-full` trong `styles.css`);
  `Shell.stream(path, body, {signal, on(type, data), hints})` — luồng SSE dùng chung (chat.js đã chuyển sang dùng).
- `styles.css`: token `--c1…--c5`, `--paper`, `--ink`, `--ink-2` cho cả hai chủ đề.
- `index.html`: `<link views/research.css>` + `<script views/research.js>` sau documents.
- `backend/tests/test_frontend.py`: `VIEWS` có `research`; ngân sách `fetch(` thô: common 2 / shell 2 / còn lại 0.

## Cấu trúc file

```
backend/app/frontend/views/research.js     một IIFE, Router.register("research", {admin:false, mount, update, unmount})
backend/app/frontend/views/research.css    style riêng, tiền tố class `rs-`
backend/app/routers/research.py            APIRouter(prefix="/research")
backend/app/services/research_service.py   CRUD + metadata + outline + summary + export
backend/app/schemas/research_schema.py
backend/app/postgres/models.py             + 5 bảng dưới
backend/alembic/versions/20261011_33_research_space.py   down_revision "20260828_32"
backend/app/routers/documents.py           + GET source / pages/{n}.png / pages/{n}/words / pages/{n}/boxes
backend/tests/test_research_*.py, test_document_pages.py
```

## Routes frontend

```
#/research                      → tab Tổng quan của dự án gần nhất (hoặc màn tạo dự án đầu tiên)
#/research/<projectId>          → Tổng quan
#/research/<projectId>/p/<paperId>[?page=n&tool=summary]   → mở paper trong tab
```
Trạng thái phiên lưu `localStorage` khóa `lac.research` theo project: `tabs[]`, `active`, `split`, `second`,
`tool`, `collapsed{}`, `hl`, `showAnno`, `sync`. `last_page` lưu lên máy chủ (PATCH paper, debounce 2 s).

## Dữ liệu (Postgres, additive-only, khai báo trong `postgres/models.py`)

| Bảng | Cột |
|---|---|
| `research_projects` | id `prj_…`, owner_user_id (nullable, như conversations), name, description, insights JSONB nullable, insights_at, created_at, updated_at |
| `research_clusters` | id `clu_…`, project_id FK cascade, name, color_index 1..5, position int |
| `research_papers` | id `pap_…`, project_id FK cascade, document_id FK `documents` cascade, short_name, title, authors, venue, year int, arxiv_id, doi, url, cluster_id FK set null, status `unread\|reading\|read`, stars 0..5, last_page int default 1, note_md text, tags JSONB [str], summary JSONB nullable, summary_model, summary_at, outline JSONB nullable, metadata_at, added_at, updated_at; UNIQUE(project_id, document_id) |
| `research_annotations` | id `ann_…`, paper_id FK cascade, page int, rects JSONB [{x,y,w,h}] tỉ lệ 0..1 theo trang, color str (#hex), quote text, note text nullable, section nullable, created_at, updated_at |
| `research_edges` | id `edg_…`, project_id FK cascade, a_paper_id FK cascade, b_paper_id FK cascade, type `builds\|competes\|backbone`, explain, quote, quote_src, confidence float nullable, source `manual\|ai`, created_at |

## Hợp đồng API (UI gọi đúng như sau)

Lỗi: `HTTPException(status, detail={"error_code", "message"})`. Mã mới: `RESEARCH_PROJECT_NOT_FOUND`,
`RESEARCH_PAPER_NOT_FOUND`, `RESEARCH_ANNOTATION_NOT_FOUND`, `RESEARCH_SUMMARY_MISSING` (404),
`RESEARCH_SOURCE_UNAVAILABLE` (409, tệp gốc đã xoá), `RESEARCH_FETCH_UNSUPPORTED` (501, thêm theo link/DOI),
`RESEARCH_NOT_INDEXED` (409, hỏi paper chưa lập chỉ mục), `DOCUMENT_PAGE_NOT_FOUND` (404).
Read = `read_guard`; ghi = thêm `Depends(require_api_key)`. Không route nào `require_admin`.

### Tài liệu (dùng chung với Phần 1 — `views/documents.js`, `views/chat.js` đã gọi)
| Endpoint | Trả về |
|---|---|
| `GET /documents/{id}/source` | `FileResponse` tệp gốc, `Content-Disposition: inline; filename=…`; 409 `RESEARCH_SOURCE_UNAVAILABLE` nếu `source_available=false` |
| `GET /documents/{id}/pages/{n}.png?dpi=110` | PNG trang n (1-based), dpi ∈ [50, 220], mặc định 110; cache đĩa `data/documents/<id>/pages/<n>@<dpi>.png`; 404 `DOCUMENT_PAGE_NOT_FOUND` |
| `GET /documents/{id}/pages/{n}/words` | `{page, width, height, words:[{x0,y0,x1,y1,text,block,line}]}` tỉ lệ 0..1 (PyMuPDF `get_text("words")`); PDF scan không có chữ → `words: []` + `has_text:false` |
| `GET /documents/{id}/pages/{n}/boxes?chunk_id=` | `{boxes:[{x,y,w,h}]}` 0..1 — từ `DocumentChunk.locations` nếu có bbox, không thì `[]` |
| `GET /documents/{id}` (hoặc trường mới trong list) | thêm `total_pages` (từ IngestionRun hoặc đếm bằng fitz) |

### Dự án
| Endpoint | Hợp đồng |
|---|---|
| `GET /research/projects` | `[{id, name, description, paper_count, read_count, updated_at}]` mới nhất trước |
| `POST /research/projects {name, description?}` | 201 project |
| `GET /research/projects/{id}` | `{id, name, description, insights, insights_at, clusters:[{id,name,color_index,position}], papers:[PaperRow], edges:[Edge], updated_at}` |
| `PATCH /research/projects/{id} {name?, description?}` · `DELETE` (204; papers xoá, documents giữ) | |
| `POST /research/projects/{id}/insights` | sinh `{overview, central, trend, gap}` bằng LLM từ các `summary.brief` + tiêu đề; cache; 409 `RESEARCH_SUMMARY_MISSING` nếu chưa paper nào có tóm tắt |
| `POST /research/projects/{id}/clusters {name, color_index}` → 201 · `PATCH /research/clusters/{id}` · `DELETE` (papers về `cluster_id:null`) | |
| `POST /research/projects/{id}/edges {a_paper_id, b_paper_id, type, explain?, quote?, quote_src?}` → 201 · `DELETE /research/edges/{id}` | |
| `GET /research/projects/{id}/bibtex` | `text/plain` BibTeX dựng từ metadata (`@article{short_name, title, author, year, eprint}`) |

`PaperRow` = `{id, document_id, short_name, title, authors, venue, year, arxiv_id, doi, url, cluster_id, status, stars,
last_page, tags, total_pages, annotation_count, has_summary, document_status, indexed: bool,
stages: {ocr: "done"|"running"|"failed"|"pending", metadata: …, outline: …, summary: …}, added_at, updated_at}`.
`stages.ocr` suy từ `document_status` (indexed → done; processing/uploaded → running; failed → failed).

### Paper
| Endpoint | Hợp đồng |
|---|---|
| `POST /research/projects/{id}/papers` multipart `files[]` (nhiều PDF) | mỗi tệp: tạo Document qua **đúng service** mà `POST /documents` + `POST /documents/index` dùng (gọi hàm, không gọi HTTP), rồi tạo paper; trích metadata ngay (fitz `metadata` + trang 1: tiêu đề = dòng cỡ chữ lớn nhất, `arXiv:\d{4}\.\d{4,5}` → arxiv_id + year, tác giả = dòng dưới tiêu đề); `short_name` = từ đầu của tiêu đề trước dấu `:` (≤ 24 ký tự). Trả `201 [PaperRow]`. Trùng nội dung với document đã có trong dự án → trả paper cũ (không tạo đôi). |
| `POST /research/projects/{id}/papers {document_id}` | gắn tài liệu đã có → 201 PaperRow |
| `POST /research/projects/{id}/papers {url\|doi\|title}` | 501 `RESEARCH_FETCH_UNSUPPORTED` "Máy chủ chạy offline; tải PDF rồi thả vào." |
| `GET /research/papers/{id}` | PaperRow + `summary`, `summary_model`, `summary_at`, `outline`, `note_md`, `annotations:[Annotation]` |
| `PATCH /research/papers/{id}` | `{status?, stars?, last_page?, note_md?, tags?, cluster_id?, short_name?, title?, authors?, venue?, year?, arxiv_id?, doi?, url?}` → 200 PaperRow; ít nhất 1 khóa |
| `DELETE /research/papers/{id}` | 204 — gỡ khỏi dự án, **giữ** Document |
| `POST /research/papers/{id}/summary` | sinh (lại) tóm tắt, đồng bộ, timeout 180 s → 200 `{summary, summary_model, summary_at}`; 409 `RESEARCH_NOT_INDEXED` nếu chưa có chữ. `summary` = `{brief, problem, idea, result, limits, input, compute, datasets, code, questions:[3 câu]}` tiếng Việt; đầu vào = `selected_text` các trang (ưu tiên 3 trang đầu + 2 trang cuối, trần ~12 000 ký tự) |
| `GET /research/papers/{id}/outline` | `{toc:[{title, page, level}], figures:[{label, page}]}` — `fitz.get_toc()`; rỗng thì dò heading theo cỡ chữ (span size ≥ 1,15× cỡ thân, ≤ 80 ký tự); figures = lần đầu xuất hiện `^(Fig\.?\|Figure\|Table)\s*\d+` ở đầu dòng mỗi trang; cache vào `outline` |
| `GET /research/papers/{id}/annotations` · `POST {page, rects, color, quote, note?, section?}` → 201 · `PATCH /research/annotations/{id} {note?, color?}` · `DELETE` → 204 | |
| `GET /research/papers/{id}/export.md` | `text/markdown`: tiêu đề, meta, tóm tắt (nếu có), highlight theo trang («quote» — ghi chú — tr. N), ghi chú tự do |
| `POST /research/chat` body `{scope:"paper"\|"project", id, question, quote?, conversation_id?, top_k?}` | SSE như `/rag/chat`; `document_ids` = 1 paper hoặc toàn bộ paper **đã index** của dự án (trần 100); `quote` được ghép vào câu hỏi dạng «Đoạn trích: "…"\n\nCâu hỏi: …»; sự kiện `meta` thêm `papers: {document_id: {paper_id, short_name, color_index}}` để UI đổi trích dẫn thành chip `[Paper · tr.N]`; 409 `RESEARCH_NOT_INDEXED` nếu không paper nào index |

## Màn hình (frontend) — bám README Phần 2 + prototype, tóm tắt những chỗ cần chốt hành vi

- **Chưa có dự án**: màn trống giữa (logo + "Tạo dự án nghiên cứu đầu tiên" + input tên + nút). Có dự án → mở dự án gần nhất (`lac.research.lastProject`).
- **Sidebar 268**: nút ← (`#/chat`), bộ chọn dự án (dropdown: danh sách + "Tạo dự án mới…" + "Đổi tên" + "Xoá dự án" có confirm), ô tìm (lọc client theo short/title/authors), segmented 4 lọc trạng thái, nhóm theo cụm (paper không cụm → nhóm "Chưa xếp cụm" màu `--text-3`), tick so sánh, thanh tiến trình khi `stages` chưa xong (poll `GET project` 5 s khi còn paper đang xử lý), thẻ "N paper đã chọn · Bỏ · So sánh", footer Thêm paper + đổi theme (`applyTheme` của common.js, lưu `prefs.theme` như Cài đặt).
- **Tab bar 44**: Tổng quan + tab paper; Chia đôi / Cuộn đồng bộ (tỉ lệ cuộn) / Tập trung / ?. Giữ pane đã mount (`hidden`) khi đổi tab để không mất vị trí cuộn.
- **Ô đọc**: toolbar như prototype (hẹp < 520 → menu ⋯ dropdown); vùng trang: mỗi trang một `<div class="rs-page">` tỉ lệ `total_pages` chưa biết → 1:1.3; ảnh `pages/{n}.png` tải **lười** (IntersectionObserver, ±2 trang) qua `Shell.fetchBlob` → `URL.createObjectURL` (thu hồi khi gỡ); lớp chữ `words` tải cùng lúc, mỗi word một `<span>` trong suốt định vị tuyệt đối → bôi đen bằng chuột thật; highlight = rects từ các word trong vùng chọn (gộp theo dòng); zoom 60–200% đổi bề rộng trang (ảnh render dpi 110 cố định, phóng bằng CSS; ≥150% tải lại dpi 160). Trang hiện tại = trang chiếm giữa viewport → "k / N" + `last_page`.
- **Menu bôi đen**: Highlight (lưu annotation màu đang chọn) · Ghi chú (highlight + mở panel notes, focus ô ghi chú của annotation mới) · Hỏi AI (panel chat + khối trích dẫn, câu mặc định "Giải thích đoạn này bằng tiếng Việt") · Dịch ("Dịch đoạn này sang tiếng Việt") · Chép (`copyText`). Phím Ctrl+H/E/A/T khi đang có vùng chọn.
- **Ghi chú lề**: card 200px ở phải trang tại y của rect đầu, chỉ khi ô ≥ 640 và annotation có `note`.
- **Thẻ `[n]` tham chiếu**: KHÔNG làm (chờ chốt) — không vẽ nút giả.
- **"Hỏi về hình này"**: KHÔNG làm (chờ chốt).
- **Panel**: 7 công cụ như README. Tóm tắt: chưa có → nút "Tạo tóm tắt AI" (+ tự gọi nếu paper đã index và người dùng mở panel lần đầu — chỉ một lần, hiện skeleton + "Đang đọc N trang…"); lỗi → errorState thử lại. So sánh: từ summary; thiếu summary → ô "chưa có tóm tắt · Tạo". Hỏi paper / Hỏi cả dự án: lịch sử trong phiên (không lưu máy chủ), chip trích dẫn từ `meta.sources` + `meta.papers` (bấm → mở paper đó, nhảy `page`); "Lưu vào ghi chú" nối vào `note_md`. Mục lục & hình: từ `/outline`, bấm → cuộn tới trang. Thông tin: segmented trạng thái, sao, bảng meta (sửa tại chỗ: short_name/title/authors/venue/year/arxiv), tag, Sao chép BibTeX (dựng client), Tải PDF (`/documents/{id}/source`), Gỡ khỏi dự án (confirm).
- **Tổng quan**: tiêu đề + meta; "AI đọc gì từ kho này" = `insights` (chưa có → nút "Phân tích kho" gọi POST insights; chưa paper nào có tóm tắt → giải thích); Tiếp tục đọc = 3 paper `status=reading` theo `updated_at`, % = `last_page/total_pages`; Cụm chủ đề (card; menu ⋯ đổi tên/màu/xoá; nút "+ Cụm"); Kết nối = `edges` (xổ ra explain/quote; nút "+ Kết nối" → dialog chọn A, B, loại, giải thích); trống → emptyState nói rõ "AI chưa tự gán — thêm tay".
- **Thêm paper**: dialog như prototype; ô link → 501 → hiện câu của máy chủ; thả nhiều PDF → `Uploads`-style tiến trình từng tệp (XHR có `authHeaders`? → KHÔNG: dùng `Shell.api` với `FormData`, không tiến trình byte; hiện "đang tải…" từng tệp).
- API chưa có (404/405/501 không mã) → `missingApiState` như Phần 1, không giả vờ.

## Kiểm tra

1. `node --check` + `pytest backend/tests/test_frontend.py`.
2. Backend: pytest các file `test_research_*`, `test_document_pages.py`; test cần Postgres/Docker thì nói rõ nếu Docker không chạy (đừng im lặng skip).
3. Mở `/ui/#/research` với máy chủ giả (scratchpad) và/hoặc API thật, chụp 1440×900 so với `r01…r08`.

## Bổ sung 11/10 (chiều): luồng chat lưu được — hướng B trong decisions-open #8

Chủ dự án chốt **B**: mỗi paper (và mỗi dự án, cho "Hỏi cả dự án") có **nhiều luồng** chat, lưu máy chủ, đổi tên / xoá
được. Luồng = một dòng trỏ tới một `conversations` sẵn có (tin nhắn + nguồn trích dẫn đã được `rag_service` lưu ở đó).

### Bảng `research_threads` (migration `20261011_34`, down_revision `20261011_33`)
id `thr_…` · project_id FK cascade · paper_id FK cascade **nullable** (null = luồng của dự án) · conversation_id
String nullable, index (null cho tới tin đầu tiên) · title String(200) nullable · created_at · updated_at ·
last_message_at nullable. Index (project_id), (paper_id).

### API
| Endpoint | Hợp đồng |
|---|---|
| `GET /research/threads?scope=paper\|project&id=<paperId\|projectId>` | `[Thread]` mới nhất trước (theo `last_message_at` rồi `created_at`) |
| `POST /research/threads {scope, id, title?}` | 201 Thread (`conversation_id: null`) |
| `GET /research/threads/{id}` | Thread + `messages: [{role, content, model_used, created_at, sources:[ConversationMessageSource + paper_id, short_name, color_index, page (= page_start)]}]`; `messages: []` khi chưa có conversation |
| `PATCH /research/threads/{id} {title}` → 200 Thread · `DELETE` → 204 (xoá luôn conversation phía sau qua service hội thoại) | |
| `POST /research/chat` thêm `thread_id?` | có `thread_id` → dùng `thread.conversation_id` làm `conversation_id`; sau khi luồng tạo conversation mới thì ghi `conversation_id`, `last_message_at = now`, và `title` = câu hỏi đầu cắt 80 ký tự nếu `title` null; `meta` thêm `thread_id`. Không `thread_id` → như cũ. Thread không thuộc scope/id gửi kèm → 422 `RESEARCH_THREAD_MISMATCH`; không có → 404 `RESEARCH_THREAD_NOT_FOUND` |
`Thread` = `{id, scope, project_id, paper_id, conversation_id, title, message_count, created_at, updated_at, last_message_at}`.
Quyền: read_guard / `require_api_key` cho ghi như các route research khác; kiểm chủ sở hữu dự án như hiện có.

### Frontend (panel Hỏi paper / Hỏi cả dự án)
- Đầu panel: hàng **luồng**: tiêu đề luồng hiện tại (600, cắt 1 dòng) + nút ⋯ (dropdown: danh sách luồng với tiêu đề,
  "N tin · thời gian tương đối", đổi tên, xoá có confirm) + nút "+ Luồng mới" (28px).
- Mở panel: `GET /research/threads` theo scope; chọn luồng dùng gần nhất (`lac.research` lưu `threadByKey`) hoặc mới
  nhất; `GET /research/threads/{id}` → dựng lại tin nhắn, chip trích dẫn từ `sources` (thứ tự `[n]` = thứ tự
  `sources`, trang = `page`). Chưa có luồng → panel trống với gợi ý; gửi tin đầu tiên thì `POST /research/threads`
  rồi gửi `thread_id`. Sau tin đầu, tải lại danh sách để lấy `title` máy chủ đặt.
- Khoá state chat: `${scope}:${id}:${threadId}`; Abort khi đổi luồng. 404 không mã → `missingApiState`.
- Giữ nguyên sửa trước đó: bấm chip trích dẫn chỉ nhảy trang, **không** đổi panel.
