# Nhật ký thi công P1 — Một agent, hai kênh

**Phạm vi:** P1-1 (Discord RAG), P1-2 (condense-question), P1-3 (memory extractor chế độ đề xuất), P1-4 (duyệt memory trên dashboard), P1-5 (hợp nhất kho memory) theo `docs/DEVELOPMENT_PLAN.md`.
**Cách làm:** mỗi hạng mục qua ba bước — thiết kế bằng agent đọc code thật, phản biện đối kháng độc lập, rồi mới thi công. Mọi quyết định dưới đây ghi kèm **lý do**, vì sáu tháng nữa lý do quan trọng hơn diff.

---

## P1-2 — Condense-question trước retrieval

**Vấn đề:** người dùng hỏi nối tiếp ("Nó chiếm bao nhiêu VRAM?") thì retrieval nhận nguyên đại từ "nó" — cả BM25 lẫn dense đều không biết "nó" là gì. Đây là khoảng trống G5.

**Cách giải:** trước retrieval, nếu lượt này là lượt nối tiếp (có `conversation_id` do client gửi và hội thoại đã có tin nhắn), gọi model general một lần để viết lại câu hỏi thành dạng độc lập; retrieval **và** dòng `Question:` trong prompt trả lời dùng bản viết lại, còn transcript lưu đúng câu người dùng gõ.

### Quyết định và lý do

| Quyết định | Lý do |
| --- | --- |
| Điều kiện bỏ qua là **cấu trúc**, không phải prompt: lượt đầu (`created=True`) và cuộc gọi không có store/conversation không bao giờ condense | Đường single-turn giữ nguyên từng byte — toàn bộ 47 case eval cũ và mọi test hiện có không đổi hành vi. Bất biến "thay đổi RAG phải qua eval" được thỏa bằng cấu trúc thay vì lời hứa |
| Bản viết lại cũng thay vào dòng `Question:` của prompt trả lời | Model trả lời **không thấy lịch sử** (RAG là single-question by design) — nếu chỉ sửa retrieval mà giữ "Nó chiếm bao nhiêu VRAM?" trong prompt, retrieval đúng nhưng câu trả lời vẫn hỏng vì model không biết "nó" là gì |
| Transcript lưu câu gốc | Lịch sử hội thoại phải phản ánh điều người dùng thực sự nói; bản viết lại được phơi ra trường `retrieval_question` trong response/SSE meta để debug và để harness eval khẳng định được |
| Mọi lỗi condense → dùng câu gốc, không bao giờ hỏng lượt | Ollama chết thì RAG degradation về single-question như cũ; lỗi thật của model sẽ tự lộ ở cuộc gọi trả lời. Cắt luôn kết quả thoái hóa: rỗng, >512 ký tự, hoặc y hệt câu gốc |
| Chặn trần sinh chữ `num_predict=128`, `temperature=0` | Phần cứng này ~5 token/giây — một câu hỏi viết lại không có quyền chạy quá vài giây. `ModelRouter.chat` nhận thêm tham số `options` keyword-optional nên không caller nào hiện có đổi hành vi |
| Cửa sổ lịch sử 6 tin nhắn, mỗi tin cắt 500 ký tự | 3 cặp hỏi–đáp giải mọi đại từ thực tế; câu trả lời RAG dài, không cắt thì prompt-eval phình vô ích trên máy chậm |
| Công tắc `rag.condense_enabled` trong models.yaml | Tri thức vận hành nằm cạnh các nút RAG khác; tắt được ngay không cần sửa code |

### Bộ eval hội thoại (`data/evaluation/rag_conversation_eval.jsonl`)

10 cặp tiếng Việt nhắm vào fixture xưởng in có sẵn. Nguyên tắc soạn: **turn2 phải mơ hồ nếu đứng một mình** — đại từ ("nó", "anh ấy", "thiết bị đó") hoặc tỉnh lược ("còn X thì sao"). Phản biện bắt được 4 câu turn2 phiên bản đầu còn rò vị ngữ trùng nguyên văn fixture (BM25 tự tìm được không cần condense) — đã viết lại cả 4.

Harness (`evaluate_rag.py --conversation-dataset`) đo **hai lần mỗi cặp**:
1. **Baseline:** turn2 gửi đứng một mình (không conversation → tự bỏ qua condense) — đo xem câu hỏi thô tự tìm được không.
2. **Thật:** turn1 rồi turn2 trong cùng hội thoại — đo condense.

Nghiệm thu = recall ≥ 8/10 **và** recall thật > recall baseline. Không có vế thứ hai thì con số 8/10 có thể chỉ là BM25 ăn may trên từ khóa sót lại — gate sẽ không chứng minh tính năng.

### Bằng chứng nghiệm thu

Chạy sống 19/08 trên backend thật (DB test, Ollama thật), report
`data/evaluation/results/rag-conversation-20260819-013649.json`:

| Chỉ số | Condense | Baseline (turn2 đứng một mình) |
| --- | --- | --- |
| Recall@5 | **10/10 (100%)** — vượt gate ≥ 80% | 10/10 |
| MRR | **0.950** | 0.787 |

Recall@5 bão hòa ở cả hai phía vì corpus eval chỉ có một tài liệu (~15 chunk,
top-5 phủ 1/3 corpus — đúng giới hạn G7 đã ghi trong plan). **MRR mới là chỉ số
phân biệt**: câu đại từ thô xếp đúng chunk hạng 5 (c01) và hạng 3 (c02, c06),
condense đưa cả ba lên hạng 1–2. Gate của harness từ đó là
`recall ≥ 0.8 AND (recall > baseline OR mrr > baseline_mrr)` — lần chạy này ĐẠT.

Chất lượng viết lại đọc được bằng mắt trong report: "Gọi cho anh ấy qua số nào?"
→ "Gọi cho anh Đức Khoa qua số nào?"; "Nó chiếm khoảng bao nhiêu VRAM?" →
"Mô hình qwen3.5:9b chiếm khoảng bao nhiêu VRAM?". Test: 5 test mới trong
`backend/tests/test_rag_condense.py`; toàn suite 493 pass.

---

## P1-1 — Lệnh `/hoi` trên Discord

> **Cập nhật 19/08 (định hướng agent-first, P2-3):** lệnh đổi tên `/hoi` → `/docs`, tham số
> `tailieu` → `document` — bộ lệnh tiếng Anh nhất quán với `/ask`, `/ping`. Bảng dưới ghi
> lý do chọn tên gốc tại thời điểm P1-1, giữ nguyên làm sử liệu.

**Vấn đề:** bot chỉ gọi `/chat` — nửa giá trị RAG (hỏi tài liệu, có dẫn nguồn) không đến được kênh chat chính. Đây là khoảng trống G3.

### Quyết định và lý do

| Quyết định | Lý do |
| --- | --- |
| Tên lệnh `hoi` (ASCII), không phải `hỏi` | discord.py cho phép unicode, nhưng người gõ "hoi" không dấu có thể không thấy lệnh "hỏi" trong command picker; plan cũng ghi nguyên văn `/hoi` |
| Chọn tài liệu bằng **autocomplete** trên tham số tùy chọn `tailieu`; bỏ trống = tất cả | `GET /documents` không có filter server-side nên lọc `status=="indexed"` phía bot; cache 30 giây vì autocomplete có ngân sách 3 giây của Discord. Autocomplete **không cưỡng chế** giá trị, nên chuỗi gửi lên được giải lại: đúng ID → đúng tên → substring duy nhất → mơ hồ thì báo danh sách |
| Gọi thẳng `/rag/chat`, **không** qua pipeline FIFO turn | RAG là single-question by design — lịch sử không vào prompt, nên đảm bảo thứ tự FIFO không mua được gì; executor của pipeline chạy chat_service chứ không phải rag_service |
| Ở chế độ persistent sessions (mặc định): truyền `backend_conversation_id` của session kênh | Hội thoại session đã bị web sidebar ẩn sẵn — mỗi lần `/hoi` mà tạo hội thoại mới thì sidebar web đầy rác. Citation cũng được lưu bền miễn phí nhờ P0-3. Session hỏng → degrade về gọi đứng một mình, đúng mẫu phục hồi của `/ask` |
| Timeout dùng `turn_execute_timeout_seconds` (180s), không phải 45s mặc định | Retrieval + trả lời đầy đủ ở ~5 token/giây vượt xa 45s; cơ chế override per-request đã có sẵn và có test ghim |
| Footer nguồn gom theo file nhưng **giữ nguyên số thứ tự** `[1,3] file.pdf · trang 5` | Câu trả lời trích `[Source n]` theo vị trí — đánh số lại là gãy ánh xạ. Tên file được escape markdown để `bao_cao*.pdf` không thành chữ nghiêng |
| `INSUFFICIENT_CONTEXT` (422) → thông báo tiếng Việt thân thiện, ephemeral | Người dùng Discord không cần thấy mã lỗi HTTP |

### Bằng chứng nghiệm thu

- 9 test client mới (`tests/test_discord_rag_command.py`): payload/scope/timeout dài
  180s, ánh xạ lỗi INSUFFICIENT_CONTEXT/QDRANT_UNAVAILABLE, parse nguồn bỏ dòng hỏng,
  footer gom nhóm giữ số thứ tự, escape markdown. Root suite 59 pass.
- Đường backend mà `/hoi` gọi (`/rag/chat` + conversation session) chính là đường
  vừa được eval sống ở P1-2 xác nhận.
- Bước còn lại cần người thật: chạy `run-discord-bot.bat` để bot đăng ký lệnh mới
  với Discord rồi gõ `/hoi` trong server — cần `DISCORD_TOKEN` và guild thật,
  nằm ngoài khả năng tự động hóa của phiên này.

---

## P1-3 — Memory extractor chế độ đề xuất

**Vấn đề:** pipeline memory đã được xây và test kỹ (150-case benchmark) nhưng chưa từng bật. "Agent có trí nhớ" vẫn nằm trên giấy (G2 — bước đầu).

**Phát hiện quan trọng khi khảo sát:** đây là hạng mục **vận hành**, không phải code. Chuỗi runtime cần 4 mắt xích mà bản cài mặc định thiếu 3:

```
turn hoàn tất → completion service (cần flag INGESTION)  ← có sẵn trong API
             → outbox event → outbox dispatcher           ← KHÔNG ai chạy
             → RQ queue memory_extract → memory worker    ← KHÔNG ai chạy
             → model extractor qwen3.5:2b                 ← CHƯA pull
```

### Quyết định và lý do

| Quyết định | Lý do |
| --- | --- |
| Dispatcher + worker chạy trên **host**, khởi động bởi launcher, gated theo flag trong .env | Compose profile `workers` cần docker build nhiều phút — phá đường một cú click. Mẫu cửa sổ có tiêu đề + taskkill đã dùng cho backup/cleanup worker |
| Worker mới `scripts/memory_worker.py` dùng `SimpleWorker` | RQ Worker mặc định fork — Windows không fork được; SimpleWorker là đúng cái bộ test RQ integration đã chạy trên host này |
| Pull `qwen3.5:2b` (~2.7GB) thay vì trỏ extractor sang 9b có sẵn | Toàn bộ benchmark 150 case (30×3 lặp, các gate an toàn) chỉ validate trên 2b — đổi model là vứt bằng chứng chất lượng đi. Launcher chỉ pull khi flag extractor bật, bản cài thường không tốn 2.7GB |
| `DISCORD_MEMORY_EXTRACTOR_TIMEOUT_SECONDS=120` | Benchmark ghi nhận call chậm nhất 93.7s; mặc định 60s sẽ cắt oan đúng những case khó |
| "Chế độ đề xuất" = bật flag, **không cần code mới** | Candidate hạ cánh ở `validation_status='pending'`, `decision='deferred'`, đề xuất nằm trong `normalized_output`; grep xác nhận **không tồn tại** đường code nào ghi vào `discord_memories` hay đặt `decision='applied'` — không gì tự áp dụng được kể cả muốn |
| conftest.py ép cả hai flag `false` trong test | Máy vận hành bật proposal mode không được đổi nhánh code mà bộ test đi qua — cùng bài học với `LOCAL_AI_API_KEY` ở P0-2 |
| `.env.example` giữ `false` | Bản cài mới không được tự bật tính năng ghi nhớ người dùng — quyền riêng tư là opt-in |

### Bằng chứng nghiệm thu

Chạy sống 19/08, lái đúng chuỗi production trên backend thật (DB test):
resolve session → enqueue turn ("Hãy nhớ rằng tôi ưu tiên câu trả lời ngắn gọn…")
→ execute (9b trả lời thật) → complete kèm delivery ack → `outbox_dispatcher --once`
(published 1 event) → `memory_worker --burst` (job OK sau 26.7s, extractor 2b thật).

Khẳng định bằng SQL:

| Kiểm tra | Kết quả |
| --- | --- |
| `discord_memory_candidates` bản ghi mới nhất | `filter_decision=candidate`, `reason_code=explicit_remember`, `validation_status=pending`, `decision=deferred` |
| `normalized_output` | có `extractor_proposal` + audit đầy đủ (latency 26.4s — trong hạn 120s; prompt v5, json_schema mode) |
| `select count(*) from discord_memories` | **0** — không memory nào tự áp dụng |

---

## P1-4 — Duyệt memory trên dashboard

**Vấn đề:** proposal mode (P1-3) sinh candidate nhưng không ai duyệt được — thiếu đúng cái cổng con người.

### Quyết định và lý do

| Quyết định | Lý do |
| --- | --- |
| Service riêng `DiscordMemoryReviewService`, không nhét vào worker service | Duyệt là hành động của con người qua HTTP, worker là pipeline nền — trộn hai vòng đời vào một class là mầm god-object (bài học T7) |
| Approve dùng lại `create_active_version` có sẵn trong repository | Hàm này được viết sẵn cho đúng việc này (idempotent theo payload, tự đặt `decision='applied'`, tự `attach_source` audit) và đã có test foundation — viết lại là vứt bằng chứng |
| Reject chỉ ghi `decision='rejected'` + `reviewed_at/reviewed_by`, không xóa gì | Audit trail là mục đích của proposal mode; bảng candidate có sẵn hai cột reviewed_* từ thiết kế gốc |
| Hai phase trong approve: DB commit trước, mirror (có gọi model embed) chạy NGOÀI transaction | Bất biến "không transaction nào ôm qua lời gọi model". Mirror hỏng → `index_status='failed'`, approve lại chỉ chạy lại mirror (create_active_version idempotent) |
| UI đặt ngay trong dashboard, dùng `postJson` kèm X-API-Key | Approve/reject là endpoint ghi → bị guard P0-2; lỗi 401 chỉ dẫn người dùng sang Cài đặt → Bảo mật |

## P1-5 — Hợp nhất kho memory

**Cầu nối:** khi duyệt, `canonical_fact` được mirror vào kho `/memory` (Qdrant + bảng `memories`) — đúng kho mà web chat «Ghi nhớ» tìm kiếm.

| Quyết định | Lý do |
| --- | --- |
| ID mirror định danh `mem_dc_<uuid discord memory>` | Retry sau lỗi ghi đè cùng một entry thay vì chồng bản sao; nhìn ID biết ngay nguồn gốc Discord |
| `MemoryService.upsert_with_id` mới (embed → qdrant upsert → create-or-update row) | Giữ tri thức Qdrant/store trong MemoryService; upsert Qdrant tự idempotent, row rơi về update khi đã tồn tại |
| `importance` = `confidence` của extractor | Không bịa thang mới; confidence 0.93 của extractor chính là mức tin của đề xuất |

### Bằng chứng nghiệm thu (P1-4 + P1-5)

- 7 test API mới (`backend/tests/test_memory_review_api.py`): list chỉ hiện candidate có proposal; approve → memory active + `index_status='indexed'` + candidate `applied/accepted` + reviewed_at/by; **mirror xuất hiện trong `/memory/search`**; approve idempotent (2 lần → 1 memory); reject ghi quyết định không xóa và chặn approve về sau; 404 cho id lạ; **test nghiệm thu P1-5 nguyên văn**: `/chat` với `use_memory=true` inject đúng điều học từ Discord vào ngữ cảnh model.
- Hai endpoint approve/reject vào danh sách WRITE_REQUESTS của test guard API key.
- Bằng chứng sống: xem mục "Kiểm tra lại toàn bộ P1" bên dưới.

---

## Kiểm tra lại toàn bộ P1 — end-to-end sống 19/08

Chạy lại **toàn chuỗi production bằng model thật** trên backend sống (DB test, Qdrant thật, Ollama thật):

| Bước | Hạng mục | Kết quả |
| --- | --- | --- |
| 1 | Turn Discord qua API (resolve → enqueue "Hãy nhớ rằng tôi ưu tiên câu trả lời ngắn gọn bằng tiếng Việt" → execute 9b → complete + ack) | `completed` |
| 2 | `outbox_dispatcher --once` → `memory_worker --burst` (extractor **qwen3.5:2b thật**, 23.9s) | Candidate `pending/deferred`, proposal "User prefers Vietnamese.", confidence 1.0 |
| 3 | **P1-4**: mở dashboard thật, panel "Đề xuất ghi nhớ chờ duyệt" hiện đúng candidate (nội dung + evidence + nguồn + độ tin), bấm nút **Duyệt** | Xong sau 7s (gồm embed thật), panel tự refresh về rỗng, badge ẩn |
| 4 | **P1-5**: kho memory sau duyệt | `discord_memories`: `active/indexed`; mirror `mem_dc_*` trong bảng `memories`; collection Qdrant `memories` 1024-dim |
| 5 | `/memory/search` với câu hỏi **khác hẳn văn bản lưu** ("Người dùng muốn tôi dùng ngôn ngữ gì khi trả lời?") | Trả về đúng memory, score 0.509 — semantic thật, không phải khớp chuỗi |
| 6 | `/chat` với `use_memory=true`, hỏi "Tôi từng dặn bạn điều gì về cách trả lời?" — **9b thật** | Trả lời: *"…hãy sử dụng tiếng Việt vì đó là ngôn ngữ bạn ưu tiên"* — trợ lý web dùng đúng điều học từ Discord |
| 7 | Suite chốt (tuần tự, không chạy chồng) | Backend **506 passed, 1 skipped, 0 failed** · root **59 passed** · compileall/node sạch |

Artifact của lần kiểm được dọn ngay sau đó (conversation + memory mirror + điểm Qdrant), riêng collection `memories` giữ lại ở trạng thái rỗng 1024-dim — đúng chiều cho runtime.

### Phát hiện quan trọng trong lúc kiểm: test làm bẩn Qdrant dùng chung

Vòng kiểm này phát hiện collection `memories` đang ở **3 chiều với 13 điểm rác test** — do bộ test (embed mock 3 chiều) và runtime dùng **chung một Qdrant với cùng tên collection**. Hệ quả thật: mọi `/memory/add` với model thật (1024 chiều) sẽ 500 `QdrantDimensionMismatchError` vĩnh viễn. Đã sửa tận gốc:

- Setting mới `qdrant_memories_collection` (mặc định `memories`), truyền vào `QdrantStore`.
- `conftest.py` ép `QDRANT_MEMORIES_COLLECTION=memories_test` — test không bao giờ chạm collection runtime nữa.
- Xóa collection bẩn (xác minh 13/13 điểm là nội dung test trước khi xóa).

Bài học vận hành tự rút: **không chạy hai bộ test đồng thời trên một DB test** (test migration hạ cấp schema sẽ đá nhau — hai lần chạy chồng cho 1 và 14 failure ảo; chạy tuần tự: 0 failure).

---

## Việc ngoài kế hoạch ghi nhận trong đợt này

- **T4 (reclaim outbox `processing`)**: phát hiện `outbox_dispatcher_service.py` đã được sửa sẵn trong cây làm việc (chưa commit, không rõ từ phiên nào). Đối chiếu với thiết kế T4 trong sổ nợ: đúng hướng, đúng lý do (dispatcher chết giữa mark và publish thì event phải được đòi lại sau `reclaim_seconds`; re-publish an toàn vì enqueue đã dedupe). **38 test outbox pass** → giữ lại, tính T4 là xong.
