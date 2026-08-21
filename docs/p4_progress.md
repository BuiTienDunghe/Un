# Nhật ký Phase P4 — RAG nâng cao, có đo lường

Mỗi mục P4 là **một thí nghiệm**: thiết kế ngắn → code với cờ tắt → đo bằng bộ
eval D1 (`docs/d1_retrieval_eval.md`) → chỉ bật mặc định khi số liệu chứng minh
(bất biến plan §1). Phân lane theo `docs/machine_split.md`: phần *xây* (code,
unit test) là lane nhẹ, phần *đo* (sinh context, re-index) là lane nặng.

## P4-2 — Contextual retrieval (Anthropic)

**Trạng thái 21/08/2026: ĐÓNG — ĐẠT ngưỡng, cờ BẬT mặc định.** Thí nghiệm chạy
trên máy nặng `PC-dungbt` (RTX 5060 Ti 16GB, Ryzen 7 7700, 31GB RAM) với
`qwen3.5:9b` sinh context và `qwen3-embedding:0.6b` đo retrieval. Kết quả: MRR
tổng **+0.068**, MRR cross **+0.208**, recall cross đạt **1.0000**, 4 câu
miss→hit và **0 câu hit→miss**. Baseline D1 đã ghi lại theo cấu hình mới.

> **Bổ sung 21/08 (máy nhẹ):** cờ bật mặc định kéo theo máy nhẹ cũng sinh context lúc
> index (32.7s/tài liệu trên RTX 5060 Ti → nhiều phút/tài liệu trên GTX 1650 Ti). Thêm
> override theo máy `RAG_CONTEXTUAL_RETRIEVAL_ENABLED` (`.env`, không commit) qua một
> `ChunkContextService.from_config` dùng chung cho API lẫn RQ worker — máy nhẹ đặt
> `false`, máy mạnh để theo `models.yaml`. Quyết định: `docs/machine_split.md`.

### Thiết kế (và lý do từng quyết định)

Bài gốc: [Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)
— prepend 50–100 token ngữ cảnh vào từng chunk trước khi index, cho **cả**
embedding lẫn BM25: −49% retrieval failure (−67% kèm reranking).

| Quyết định | Lý do |
| --- | --- |
| Điểm chèn: **giữa `chunk_pages` và `replace_chunks`**, chung cho cả hai đường index (thread `_run_index` và RQ `index_for_worker`) qua một hàm `_contextualize` | Một điểm chèn duy nhất, không nhân đôi logic (tránh nới rộng nợ T7 — hai bản sao pipeline); chạy khi CHƯA mở session nào → giữ bất biến "không transaction ôm qua lời gọi model" |
| Context lưu ở **cột mới `document_chunks.retrieval_context`** (nullable, migration `20260821_25` có downgrade), KHÔNG nhét vào `content` | `content` là văn bản trích dẫn nguyên văn — citation-grounded là định vị của dự án; NULL nghĩa là "index bản trần" nên mọi version cũ vẫn hợp lệ, không phải re-index gì khi nâng cấp |
| Embedding input và BM25 token đều đi qua **một helper `combined_retrieval_text(context, content)`** | Khuyến nghị của bài là contextual embedding + contextual BM25 **đi đôi**; một helper duy nhất thì hai chỉ mục không bao giờ lệch nhau |
| Dense retrieval **không đổi gì ở phía đọc** | `_dense` vốn đọc `content` từ PostgreSQL (Qdrant chỉ giữ vector + metadata), nên citation tự động sạch |
| Sinh context bằng model **general** (`qwen3.5:9b`), prompt tiếng Việt yêu cầu trả lời cùng ngôn ngữ tài liệu, nhắc tên riêng/mã số/số liệu định danh | Corpus và câu hỏi eval là tiếng Việt; tên riêng + mã số chính là thứ BM25 khớp được |
| Tài liệu trong prompt cắt ở `document_char_cap` (mặc định 12.000 ký tự, lấy phần đầu) | Giữ prompt trong cửa sổ 16384 token của 9b; phần đầu giữ khung tài liệu (tiêu đề, mở bài) |
| Lỗi model ở một chunk → chunk đó `retrieval_context=NULL`, ingestion **không fail** | Version cũ phải sống tới khi version mới thành công; thiếu context chỉ là mất phần cải thiện, không phải mất tài liệu |
| Cờ `rag.contextual_retrieval.enabled` trong models.yaml, **mặc định false**; tự thân nó không thêm lời gọi model nào lúc TRẢ LỜI | Bất biến "ngân sách inference": chi phí nằm trọn ở lúc index (N lời gọi/tài liệu), đường hỏi-đáp giữ nguyên số lượt gọi |
| Chi phí ghi log có cấu trúc: `chunk_context_done` (số chunk, giây, số lời gọi, số lỗi) | Tiêu chí P4 đòi ghi giây/tài liệu và số lượt gọi |
| Tiến độ hiển thị tái dùng stage `chunking` (band 35→44%) | Không thêm giá trị stage mới nào cho UI/console phải học |

### Đã kiểm chứng bằng test (8 test, `backend/tests/test_chunk_context.py`)

- Sinh context đủ, đúng thứ tự; prompt chứa văn bản tài liệu; cap tài liệu hoạt động.
- Một chunk lỗi model → degrade về NULL, các chunk khác vẫn có context, ingestion hoàn tất.
- Cờ tắt → passthrough, **0** lời gọi model (có test khẳng định gọi model khi cờ tắt là AssertionError).
- Xuyên suốt upload→index: context vào đúng cột DB + đúng embedding input + BM25 tìm được chunk bằng từ CHỈ có trong context — còn `content` trong kết quả **không** chứa context.

### Runbook thí nghiệm (máy NẶNG) — ✅ đã chạy 21/08/2026, kết quả ở bảng dưới

Giữ nguyên để mục P4-3/P4-4 lặp lại được đúng quy trình. Một điều runbook chưa
lường trước và đã xử lý khi thi hành: bật cờ mặc định làm **gate CI đỏ**, vì
runner không có model sinh nên nó dựng chỉ mục trần rồi so với baseline
contextual. Cách chữa (đã áp dụng, không hạ tolerance, không sửa dataset): job CI
tắt cờ tường minh và gate theo baseline trần riêng — xem `docs/d1_retrieval_eval.md`.

```powershell
# 0. Chuẩn bị: API + Ollama đang chạy, suite xanh, D1 sanity khớp baseline ±0.02
cd backend
python -m scripts.evaluate_rag --multidoc-dataset ..\data\evaluation\rag_multidoc_eval.jsonl --retrieval-only
# 1. Bật cờ: models.yaml → rag.contextual_retrieval.enabled: true, restart API
# 2. Re-index 5 tài liệu corpus (ra version mới, version cũ sống tới khi xong):
#    POST /documents/index cho từng document_id của corpus (lấy id từ GET /documents)
#    Ghi lại: giây/tài liệu + số lời gọi từ log event=chunk_context_done
# 3. Đo lại:
python -m scripts.evaluate_rag --multidoc-dataset ..\data\evaluation\rag_multidoc_eval.jsonl --retrieval-only
# 4. Quyết định theo ngưỡng đã chốt:
#    ĐẠT  (MRR tổng +>=0.03 HOẶC MRR cross +>=0.05, VÀ single không tụt quá 0.02)
#      -> giữ enabled: true, ghi baseline mới:
#         python -m scripts.evaluate_rag --multidoc-dataset ..\data\evaluation\rag_multidoc_eval.jsonl --retrieval-only --write-baseline ..\data\evaluation\rag_multidoc_baseline.json
#         + ghi chú "baseline đổi vì P4-2" vào docs/d1_retrieval_eval.md, commit cả hai
#    KHÔNG ĐẠT -> trả enabled: false, re-index lại 5 tài liệu (về bản trần),
#         ghi kết quả âm ĐẦY ĐỦ vào bảng dưới — kết quả âm có số liệu vẫn là kết quả
# KHÔNG chỉnh dataset, KHÔNG hạ tolerance để qua gate.
```

**Bảng trước/sau (đo 21/08/2026 trên `PC-dungbt`, retrieval-only, 82 câu):**

| Metric | Trước (baseline 21/08) | Sau P4-2 | Δ |
| --- | --- | --- | --- |
| recall@5 tổng | 0.8659 | **0.9146** | **+0.0488** |
| MRR tổng | 0.7341 | **0.7967** | **+0.0626** |
| doc_hit tổng | 0.7683 | **0.8415** | **+0.0732** |
| recall@5 cross | 0.7500 | **1.0000** | **+0.2500** |
| MRR cross | 0.5903 | **0.7986** | **+0.2083** |
| doc_hit cross | 0.5833 | 0.7500 | +0.1667 |
| recall@5 single | 0.8857 | 0.9000 | +0.0143 |
| MRR single | 0.7588 | 0.7964 | +0.0376 |
| doc_hit single | 0.8000 | 0.8571 | +0.0571 |
| Câu miss→hit / hit→miss | (11 miss nền) | **4 miss→hit · 0 hit→miss** (còn 7 miss) | — |
| Giây index/tài liệu · lời gọi | — (cờ tắt) | **32.7s/tài liệu · 1 lời gọi/chunk** (27 chunk, 144.0s sinh context, 0 lỗi) | — |

> Cột "Trước" là baseline CI đã ghi 21/08. Lần chạy sanity ngay trước thí nghiệm
> trên chính máy này cho 0.8659 / 0.7287 / 0.7683 — khớp baseline trong ±0.02
> (chỉ MRR lệch −0.0055), nên hai cột so được cùng-điều-kiện. Diff theo từng câu
> ở dưới lấy từ lần sanity đó vì nó có kết quả per-case.

**Ngưỡng chốt trước khi đo — đối chiếu:** MRR tổng +0.0626 (cần ≥0.03) ✅ ·
MRR cross +0.2083 (cần ≥0.05) ✅ · nhóm single **không tụt điểm nào**, cả ba chỉ
số đều tăng ✅ → **ĐẠT**, giữ `enabled: true`.

**4 câu miss→hit:** `ca_health_do_tuoi_backup`, `xd_point_id_qdrant_uuid5`,
`xd_reindex_that_bai_version_cu`, `xd_vai_tro_sqlite_cu`. Ba trong bốn câu là
nhóm `cross` thuộc đúng cụm nhiễu Qdrant point/version và SQLite legacy đã dự
đoán — context "tài liệu này là gì, đoạn này nằm ở đâu" gỡ đúng chỗ nó nhắm.
**Không có câu nào hit→miss.**

**7 câu còn miss:** `ca_ai_duoc_dung_sqlite3`, `ca_lam_moi_sau_phase`,
`ca_test_guard_import`, `ca_vai_tro_ollama`, `ca_worker_launcher`,
`vi_qdrant_point_id`, `vi_vector_superseded_giu_lai` — headroom còn lại để P4-3
reranker nhắm vào.

**Đánh đổi thấy được trong dữ liệu:** 16 câu lên hạng, 5 câu tụt từ hạng 1 xuống
hạng 2 (`ca_alembic_head_o_dau`, `p3_refresh_khong_xoay`, `p3_require_admin_db`,
`vi_activation_superseded`, `xa_khoi_dong_docker`) — vẫn trúng trong top-5 nên
recall không đổi, chỉ MRR chịu một phần. Ròng vẫn dương rất rõ; ghi lại để P4-3
biết cụm nào đang bị context làm nhiễu nhẹ.

**Chi phí index (log `chunk_context_done`, không có lỗi nào):**

| Tài liệu | chunk | giây sinh context | lời gọi | tổng giây re-index |
| --- | --- | --- | --- | --- |
| backup_restore.md | 5 | 66.5 | 5 | 70.6 |
| current_architecture.md | 2 | 6.9 | 2 | 9.1 |
| p3_progress.md | 8 | 27.1 | 8 | 32.3 |
| versioned_ingestion.md | 2 | 12.1 | 2 | 14.1 |
| xuong_in_anh_duong.txt | 10 | 31.4 | 10 | 37.3 |
| **Tổng** | **27** | **144.0** | **27** | **163.4** |

`backup_restore.md` đắt bất thường (13.3s/chunk so với ~3–6s ở các tài liệu sau)
vì nó là tài liệu đầu tiên, gánh luôn phần nạp `qwen3.5:9b` (6.6GB) vào VRAM. Bỏ
nó ra thì còn ~3.5s/chunk. Đường hỏi-đáp **không thêm lời gọi model nào** — đúng
bất biến ngân sách inference: toàn bộ chi phí nằm ở lúc index.

**Bất biến version còn nguyên:** sau re-index mỗi tài liệu có version 2 `active`
với 27/27 chunk có context, version 1 `superseded` giữ bản trần — không có
khoảnh khắc nào tài liệu mất index.

---

## P4-3 — Reranker cross-encoder

**Trạng thái 21/08/2026: ĐÓNG — ĐẠT ngưỡng, cờ BẬT mặc định** (`candidate_limit`
15, đo trên `PC-dungbt` với `torch 2.9.1+cu128`). recall@5 **+0.061**, MRR
**+0.061**, MRR cross **+0.063**; cả 7 câu miss còn lại của P4-2 thành hit, đổi
lại 2 câu tụt; độ trễ `/rag/search` p50 **+35ms**. Khác P4-2 ở chỗ quyết định:
chi phí rơi vào **lúc hỏi**, nên thứ phải canh là **độ trễ**, không phải số lời
gọi model — và chính điều đó suýt làm mục này trượt (xem phần CPU vs GPU).

### Thiết kế (và lý do từng quyết định)

Bài Anthropic dùng cho P4-2 báo −49% retrieval failure, **−67% khi kèm
reranking** — phần "kèm reranking" chính là mục này. Reranker là cross-encoder
đọc *cặp* (câu hỏi, đoạn) nên chấm được mức liên quan mà embedding hai tháp
không thấy; đổi lại nó phải chạy trên từng ứng viên nên chi phí tuyến tính theo
`candidate_limit`.

| Quyết định | Lý do |
| --- | --- |
| Điểm chèn: **cuối `PostgresRetrievalService.retrieve`**, sau RRF, trước khi trả về | Cả `/rag/search` lẫn `/rag/chat` đều đi qua đúng hàm này, nên hai đường **không thể lệch** — bộ eval D1 chấm `/rag/search` sẽ mô tả đúng cái người dùng nhận ở `/rag/chat`. Đã khoá bằng test (`test_rerank_paths.py`), không phải bằng lời hứa |
| `candidate_limit` mở rộng cả tầng lấy ứng viên (`candidate_limit * 3` thay vì `top_k * 3`) | Reranker chỉ sắp lại thứ hạng, không tìm thêm được gì: đoạn đúng mà tầng dưới không lấy về thì rerank vô nghĩa. Nới ứng viên là điều kiện cần để rerank có việc mà làm |
| Cờ `rag.reranker.enabled` trong models.yaml + override theo máy `RAG_RERANKER_ENABLED` qua `RerankerService.from_config` | Đúng khuôn `ChunkContextService.from_config` (P4-2) — một idiom resolver cho mọi cờ theo máy. Ở đây lý do phân kỳ mạnh hơn P4-2: reranker cần extra `[rerank]` (PyTorch ~2GB), máy không cài **phải** ghim `false` thay vì sửa file dùng chung |
| **Warmup lúc khởi động** (`RerankerService.warmup()` gọi trong `main.py`) | Hai lý do. (1) Máy bật cờ mà quên `pip install -e .[rerank]` phải biết **lúc dựng server**, không phải lúc người dùng hỏi — đó là lỗi triển khai, và `RerankerUnavailableError` nói thẳng cách sửa. (2) Lần gọi đầu vốn gánh cả phần nạp model; để nó rơi vào một câu hỏi xui sẽ bóp méo chính p95 mà ngưỡng P4-3 đang dựa vào |
| Lỗi reranker → **503 `RERANKER_UNAVAILABLE`**, không âm thầm trả kết quả chưa sắp | Degrade im lặng làm bộ eval đo một đằng, sản phẩm phục vụ một nẻo. Có test khẳng định cả hai endpoint cùng 503 |
| Ghi log `rerank_done` (số ứng viên, top_k, ms) mỗi câu | Tiêu chí P4-3 là độ trễ, nên phần ms thêm vào phải **quy được trách nhiệm**, không chỉ nhìn tổng `/rag/search` |
| Bất biến ngân sách inference (§1): **không thêm lời gọi model SINH nào** | Cross-encoder là model chấm điểm nhỏ chạy in-process, không phải model sinh. Số lượt gọi generation của một câu hỏi giữ nguyên. Nhưng đó không phải cái cớ để lờ chi phí — phần mili-giây thêm vào được đo và gate ở dưới |
| CI ghim **cả hai** cờ (contextual + reranker) về `false` bằng một bước tường minh, fail nếu không tìm thấy khoá | Runner không có model sinh lẫn extra `[rerank]`. Bước này khớp khoá bất kể giá trị hiện tại, nên đổi mặc định không làm nó thành no-op; đổi tên/di chuyển khoá thì job đỏ ngay thay vì lặng lẽ đo sai cấu hình |
| Không re-index | Rerank xảy ra lúc hỏi, chỉ mục không đổi — khác hẳn P4-2 |

### Đã kiểm chứng bằng test (14 test, không tải weight nào)

- `test_reranker_service.py` (11): resolver theo models.yaml / override hai
  chiều / thiếu block; `candidate_limit` chặn đúng số ứng viên được chấm; model
  chỉ nạp **một lần** qua nhiều câu; warmup nạp sẵn, warmup báo lỗi rõ khi thiếu
  extra, warmup là no-op khi cờ tắt; lỗi runtime thành `RerankerUnavailableError`.
- `test_rerank_paths.py` (3): `/rag/search` trả **thứ tự cross-encoder** chứ
  không phải thứ tự retrieval; `/rag/chat` trích **đúng danh sách** mà
  `/rag/search` trả (khoá bất biến hai-đường-không-lệch); reranker hỏng thì cả
  hai endpoint cùng 503 `RERANKER_UNAVAILABLE`.
- Cross-encoder thật được thay bằng fake tiêm qua `model_loader`; `conftest` ghim
  `RAG_RERANKER_ENABLED=false` để suite không bao giờ tải ~500MB weight.

### Ngưỡng chốt TRƯỚC khi đo

**ĐẠT** khi cả ba điều kiện cùng đúng:

1. MRR tổng **+≥0.02** *hoặc* MRR cross **+≥0.03**;
2. nhóm `single` **không tụt quá 0.02**;
3. latency **p50 của `/rag/search` tăng ≤300ms** trên chính máy này.

Điều kiện (3) là điểm khác P4-2: một cải thiện chất lượng mua bằng độ trễ mà
người dùng cảm thấy được thì không phải cải thiện. Theo dõi riêng **7 câu còn
miss** sau P4-2 (`ca_ai_duoc_dung_sqlite3`, `ca_lam_moi_sau_phase`,
`ca_test_guard_import`, `ca_vai_tro_ollama`, `ca_worker_launcher`,
`vi_qdrant_point_id`, `vi_vector_superseded_giu_lai`) và **5 câu bị context đẩy
từ hạng 1 xuống hạng 2** (`ca_alembic_head_o_dau`, `p3_refresh_khong_xoay`,
`p3_require_admin_db`, `vi_activation_superseded`, `xa_khoi_dong_docker`) — nếu
reranker đúng là thứ bổ khuyết cho contextual thì hai cụm này là nơi nó phải ăn
điểm.

**Mốc trước (contextual ON, reranker OFF, đo 21/08 trên `PC-dungbt`):**
recall@5 0.9146 · MRR 0.7967 · doc_hit 0.8415 · cross recall 1.0000 / MRR 0.7986
· single 0.9000 / 0.7964 / 0.8571 · **latency p50 587ms, p95 617ms** (82 câu,
khớp `rag_multidoc_baseline.json` với Δ=0.0000 cả ba chỉ số).

### Kết quả (đo 21/08/2026 trên `PC-dungbt`, retrieval-only, 82 câu) — **ĐẠT**

| Metric | Trước (contextual ON, rerank OFF) | Sau P4-3 (`candidate_limit=15`) | Δ |
| --- | --- | --- | --- |
| recall@5 tổng | 0.9146 | **0.9756** | **+0.0610** |
| MRR tổng | 0.7967 | **0.8581** | **+0.0614** |
| doc_hit tổng | 0.8415 | **0.8537** | **+0.0122** |
| recall@5 cross | 1.0000 | 1.0000 | +0.0000 |
| MRR cross | 0.7986 | **0.8611** | **+0.0625** |
| doc_hit cross | 0.7500 | 0.8333 | +0.0833 |
| recall@5 single | 0.9000 | **0.9714** | **+0.0714** |
| MRR single | 0.7964 | **0.8576** | **+0.0612** |
| doc_hit single | 0.8571 | 0.8571 | +0.0000 |
| Câu miss→hit / hit→miss | (7 miss nền) | **7 miss→hit · 2 hit→miss** (còn 2 miss) | — |
| **latency `/rag/search` p50** | **587ms** | **622ms** | **+35ms** |
| latency `/rag/search` p95 | 617ms | 643ms | +26ms |
| latency riêng bước rerank | — | p50 65ms · p95 67ms | — |

**Đối chiếu ngưỡng chốt trước khi đo:** MRR tổng +0.0614 (cần ≥0.02) ✅ · MRR
cross +0.0625 (cần ≥0.03) ✅ · nhóm single không tụt điểm nào, cả ba chỉ số đều
tăng ✅ · p50 +35ms (trần 300ms) ✅ → **ĐẠT cả ba điều kiện**, bật mặc định.

**Cả 7 câu miss còn lại của P4-2 đều thành hit** — `ca_ai_duoc_dung_sqlite3`,
`ca_lam_moi_sau_phase`, `ca_test_guard_import`, `ca_vai_tro_ollama`,
`ca_worker_launcher`, `vi_qdrant_point_id`, `vi_vector_superseded_giu_lai`.
Đúng giả thuyết: những câu này thất bại vì chủ đề trùng lấn giữa các tài liệu
kỹ thuật, mà đó chính là thứ cross-encoder đọc cặp (câu hỏi, đoạn) phân biệt
được còn embedding hai tháp thì không.

**2 câu hit→miss — đọc kỹ trước khi coi là thoái lui:** `p3_khoa_brute_force`
(hạng 1 → ra khỏi top-5) và `p3_refresh_khong_xoay` (hạng 2 → ra khỏi top-5).
Cả hai là câu `single` trên `p3_progress.md` đòi **hai** cụm nguyên văn nằm
trong **cùng một chunk**. Truy nguyên `p3_khoa_brute_force`: chunk chứa đủ hai
cụm là chunk 2, còn cross-encoder lại đẩy chunk 3 và 4 (lân cận, cùng tài liệu,
cùng chủ đề khóa tài khoản) lên trên. Nói cách khác reranker vẫn chọn đúng *tài
liệu* và đúng *vùng nội dung* — `doc_hit` nhóm single không đổi — nó chỉ trượt
đúng cái chunk mang nguyên văn. Đây là chỗ cách chấm nghiêm ngặt của D1 (khớp
nguyên văn) và cách chấm ngữ nghĩa của cross-encoder không cùng nhìn một hướng.
Không chỉnh dataset để làm đẹp số; ghi lại làm headroom cho P4-4 (Postgres FTS +
pyvi, vốn nhắm thẳng vào khớp nguyên văn) và cho P4-5 chunk visualization.

Ròng: **7 câu được, 2 câu mất** — và ngay cả 2 câu mất vẫn giữ đúng tài liệu.

### `candidate_limit`: đo 15 và 30, chọn **15**

| | `candidate_limit=15` | `candidate_limit=30` |
| --- | --- | --- |
| recall@5 tổng | 0.9756 | 0.9756 |
| MRR tổng | **0.8581** | 0.8453 |
| doc_hit tổng | **0.8537** | 0.8415 |
| MRR cross | **0.8611** | 0.8056 |
| doc_hit cross | **0.8333** | 0.7500 |
| latency p50 `/rag/search` | **622ms (+35)** | 660ms (+73) |
| latency riêng rerank p50 | **65ms** | 103ms |

Chọn 15 vì nó **thắng ở mọi chỉ số chất lượng và rẻ hơn** — không có đánh đổi
nào để cân nhắc. Đáng chú ý là *vì sao* 30 lại tệ hơn: recall giữ nguyên
(0.9756) nhưng thứ hạng xấu đi, tức 15 ứng viên thêm vào không mang theo đáp án
nào mới, chỉ mang thêm mồi nhiễu đủ giống để cross-encoder xếp lên trên đáp án
đúng. Nới ứng viên không miễn phí kể cả khi bỏ qua độ trễ.

### Cross-encoder trên CPU vs GPU — vì sao phải đo lại

Lần đo đầu suýt kết luận **KHÔNG ĐẠT**: `pip install -e .[rerank]` kéo về
`torch 2.13.0+cpu` (bản mặc định trên PyPI cho Windows), nên cross-encoder chạy
CPU và `/rag/search` p50 vọt lên 1577ms — **+990ms**, gấp hơn ba lần trần 300ms.

Đo một cross-encoder CPU trên máy có RTX 5060 Ti là đo sai cấu hình: plan §9a.6
đòi chốt cấu hình *trước* khi đo, và `machine_split.md` xếp P4-3 vào lane NẶNG
đúng vì nó dùng GPU. Sau khi cài bản CUDA (`torch 2.9.1+cu128`, Blackwell
sm_120) và đo lại, **chất lượng y hệt từng con số** (cross-encoder chấm điểm xác
định, không phụ thuộc thiết bị) còn độ trễ về +35ms.

| | CPU (`torch 2.13.0+cpu`) | GPU (`torch 2.9.1+cu128`) |
| --- | --- | --- |
| rerank p50 | 957ms | **65ms** |
| `/rag/search` p50 | 1577ms (+990) | **622ms (+35)** |
| warmup lúc khởi động | 34.0s (gồm tải weight lần đầu) | 7.8s |
| chất lượng | recall 0.9756 · MRR 0.8581 | recall 0.9756 · MRR 0.8581 |

Hai hệ quả ghi lại cho người sau: (1) `[rerank]` extra **không** tự cho bản
CUDA — máy muốn bật reranker phải cài torch từ index cu128 trở lên, nếu không
sẽ trả giá ~1 giây mỗi câu hỏi; (2) 990ms so 35ms là 28×, nên đây không phải
thứ tinh chỉnh được bằng cách giảm `candidate_limit` — máy không có GPU nên
ghim `RAG_RERANKER_ENABLED=false`.
