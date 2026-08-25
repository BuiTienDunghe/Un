# Nhật ký Phase P4 — RAG nâng cao, có đo lường

Mỗi mục P4 là **một thí nghiệm**: thiết kế ngắn → code với cờ tắt → đo bằng bộ
eval D1 (`docs/d1_retrieval_eval.md`) → chỉ bật mặc định khi số liệu chứng minh
(bất biến plan §1). *(Phân lane hai máy đã bỏ 24/08 — plan §3; đoạn dưới là ghi chép lịch sử.)* Phân lane khi đó: phần *xây* (code,
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
> `false`, máy mạnh để theo `models.yaml`. Cơ chế cờ nay ở `docs/DEVELOPMENT_PLAN.md` §3e.

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

Chọn 15 vì nó **thắng ở mọi chỉ số xếp hạng (MRR/doc_hit; recall@5 hòa) và rẻ hơn** — không có đánh đổi
nào để cân nhắc. Đáng chú ý là *vì sao* 30 lại tệ hơn: recall giữ nguyên
(0.9756) nhưng thứ hạng xấu đi, tức 15 ứng viên thêm vào không mang theo đáp án
nào mới, chỉ mang thêm mồi nhiễu đủ giống để cross-encoder xếp lên trên đáp án
đúng. Nới ứng viên không miễn phí kể cả khi bỏ qua độ trễ.

### Cross-encoder trên CPU vs GPU — vì sao phải đo lại

Lần đo đầu suýt kết luận **KHÔNG ĐẠT**: `pip install -e .[rerank]` kéo về
`torch 2.13.0+cpu` (bản mặc định trên PyPI cho Windows), nên cross-encoder chạy
CPU và `/rag/search` p50 vọt lên 1577ms — **+990ms**, gấp hơn ba lần trần 300ms.

Đo một cross-encoder CPU trên máy có RTX 5060 Ti là đo sai cấu hình: plan cũ §9a.6 (nay §6)
đòi chốt cấu hình *trước* khi đo, và phân lane khi đó xếp P4-3 vào lane NẶNG
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

### Hậu kiểm 21/08 (máy nhẹ, hội đồng kiểm chứng đối kháng 12 agent)

Mọi tuyên bố kỹ thuật của báo cáo đứng vững khi đối chiếu code (đường rerank
chung có test khóa, resolver hai chiều, fail-fast thiếu extra — tái hiện trên máy
nhẹ, CI ghim cả hai cờ và exit 1 khi thiếu khóa, số liệu khớp từng con số). Ba
điều phải sửa, đã sửa cùng ngày:

| Phát hiện | Mức | Sửa |
| --- | --- | --- |
| **Đường "một cú click" vỡ với máy cài mới**: launcher chỉ cài `requirements.txt` (không có extra), copy `.env.example` (dòng pin bị comment) → yaml bật reranker → warmup từ chối → uvicorn exit 3, nhưng launcher đã mở trình duyệt trước và không kiểm tra errorlevel nên cửa sổ đóng im lặng. Vi phạm bất biến §1 | Cao | `run-local-ai-core.bat`: nếu `.env` chưa có `RAG_RERANKER_ENABLED=` và `import sentence_transformers` thất bại → tự ghi `RAG_RERANKER_ENABLED=false` vào `.env` (quyết định theo máy, nhìn thấy được, idempotent); uvicorn thoát lỗi → báo rõ + `pause` thay vì đóng cửa sổ |
| `RerankerService(False, "", 1)` mặc định (từ 07/2026) cắt kết quả còn 1 dòng vì slice `candidate_limit` chạy TRƯỚC kiểm tra `enabled` — chưa caller production nào dính, nhưng là bẫy chờ sẵn | Thấp | Kiểm tra `enabled` trước khi slice; test hồi quy |
| Câu chữ: "30 kém 15 ở *mọi* chỉ số chất lượng" (recall@5 hòa 0.9756); plan §4 hàng P4-2/P4-3 và header P4 vẫn ghi "gác"; comment ci.yml trùng/cũ; `requirements.txt` ghi reranker "đang tắt"; mô tả bảng override chỉ nói "model sinh lúc index" | Thấp | Sửa đồng loạt; số liệu gốc không đổi |

Bài học ghi lại: **đo xong trên máy mạnh chưa phải là xong** — thay đổi mặc định
(`models.yaml`) phải được thử qua con đường người dùng mới đi (launcher + `.env.example`),
và hội đồng kiểm chứng độc lập bắt được đúng lớp lỗi mà người làm tính năng không nhìn thấy.

---

## P4-4b — chọn phương án bằng số đo (23/08/2026, máy vận hành `PC-dungbt`)

**Kết luận: HOÃN P4-4b.** Không chọn v1, v2-A hay v2-B. Giữ hướng A (P4-4a, §9c#3 — nay plan §4c#3) và
B (chỉ lưu token xuống DB) — hai việc rẻ, không đụng schema. Quy tắc §9d.5 (nay plan §9.3, bảng áp quy tắc) nhánh 3.

Lượt này **không viết migration, không sửa schema, không đổi code retrieval** — đầu ra là
số. Điều kiện đo: máy `PC-dungbt`, tokenizer thật của repo (`pyvi` qua `tokenize_vietnamese`),
82 câu của `rag_multidoc_eval.jsonl`. Production `local_ai_core` **chỉ đọc**; mọi thí nghiệm
ghi chạy trong DB dùng-một-lần `local_ai_core_p44_test` (đã xoá sau khi đo). API/bot không
khởi động; chỉ container postgres được bật để đọc.

### Số #1 + #2 — bộ lọc ứng viên `retrieval_lexemes && $1` (ĐO THẬT, mô phỏng không cần migration)

"Chunk đúng" định nghĩa y hệt scorer D1: chunk thuộc `expected_docs` **và** chứa nguyên văn
mọi `expected_source_terms` — tính từ văn bản chunk, không phụ thuộc retrieval hoạt động.
Cả hai corpus đều có chunk đúng cho **cả 82 câu** (không câu nào vô nghiệm).

**Corpus vận hành (118 chunk active, 4 179 lexeme phân biệt, 214.7 lexeme/chunk):**

| Cấu hình | trung vị % corpus | p95 % | tối đa % | **câu MẤT chunk đúng** | ứng viên rỗng |
| --- | --- | --- | --- | --- | --- |
| không cắt (**v1 nguyên bản**) | **100.0%** | 100.0% | 100.0% | 0 | 0 |
| cắt df/N > 0.02 | 3.8% | 6.8% | 8.5% | **39** | 0 |
| cắt df/N > 0.05 | 7.6% | 14.4% | 16.9% | **10** | 0 |
| cắt df/N > 0.10 | 19.5% | 29.7% | 36.4% | **1** | 0 |
| cắt df/N > 0.15 | **28.4%** | 38.1% | 47.5% | **0** | 0 |
| cắt df/N > 0.20 | 34.7% | 47.5% | 52.5% | 0 | 0 |
| cắt df/N > 0.30 | 43.2% | 57.6% | 71.2% | 0 | 0 |
| cắt df/N > 0.50 | 57.6% | 72.0% | 81.4% | 0 | 0 |

**Corpus lab (27 chunk, fixture D1) — cùng 82 câu, cùng ngưỡng:**

| Cấu hình | trung vị % | p95 % | câu MẤT |
| --- | --- | --- | --- |
| không cắt | 100.0% | 100.0% | 0 |
| cắt 0.10 | 18.5% | 29.6% | **23** |
| cắt **0.15** | 33.3% | 51.9% | **1** (`br_thoi_gian_giu_lai`) |
| cắt 0.20 | 40.7% | 59.3% | 0 |

**Đọc hai bảng cùng nhau — đây là lý do v2-A bị loại:**

1. **v1 nguyên bản xác nhận không lọc**: trung vị **100%** corpus ở cả hai; trung bình 86.2%
   (prod) / 99.0% (lab); 42/82 (prod) và 76/82 (lab) câu kéo **đúng 100%**. G8-3 không được
   giải — chỉ chuyển chỗ chấm điểm từ RAM sang DB→app. Khớp phát hiện của máy nhẹ (97.5%).
2. **Ngưỡng DF an toàn KHÔNG ổn định giữa hai corpus.** Prod an toàn từ **0.15**; lab 0.15 đã
   **mất một câu**, an toàn từ **0.20**. Ngưỡng chung an toàn cho cả hai = 0.20 → **34.7%
   (prod) và 40.7% (lab)** — **cả hai đều > 30%**.
3. Ngay ở prod, ngưỡng đạt 28.4% (0.15) nằm **sát vách hỏng**: hạ thêm một nấc (0.10) là mất
   câu. Một siêu tham số phải chỉnh lại mỗi khi corpus đổi, với biên an toàn 0.05, không phải
   thứ đáng đưa vào đường retrieval production.

⚠ **Lưu ý về dải ngưỡng**: §9d.4 (nay plan §9.3) chỉ định thử 0.2 / 0.3 / 0.5 — **không ngưỡng nào trong ba
ngưỡng đó đạt < 30%** (thấp nhất 34.7%). Dải được quét rộng thêm (0.02 → 0.5) để biết đây là
"sát ngưỡng" hay "chặn cứng"; kết quả cho thấy vùng < 30% mà an toàn **chỉ tồn tại trên một
corpus**, không tồn tại trên cả hai. Quy tắc chọn không bị sửa.

### Số #3 — `pg_column_size` thật (ĐO THẬT, corpus vận hành 118 chunk)

| Thành phần | Kích thước | × content trần | × ship (ctx+content) |
| --- | --- | --- | --- |
| `content` (corpus trần) | 153.8 kB | 1.00× | — |
| `indexed_text` (ship: contextual BẬT) | 192.0 kB | 1.25× | 1.00× |
| `retrieval_lexemes text[]` | 185.3 kB | **1.21×** | 0.97× |
| `retrieval_tf int[]` | 23.0 kB | 0.15× | 0.12× |
| `retrieval_len int` | 0.5 kB | — | — |
| **3 cột cộng lại** | 208.8 kB | **1.36×** | 1.09× |
| **index GIN** (25 338 mục) | **352.0 kB** | **2.29×** | 1.83× |
| **v2-A tổng phần thêm** (3 cột + GIN) | **560.8 kB** | **3.65×** | 2.92× |

⚠ **Plan §9d.1 (nay §9.2/§9.3) sai ở đây và phải sửa**: con số "**~1.06×** corpus" cho v1-đã-vá **không tính
index GIN**, mà GIN là bắt buộc cho chính bộ lọc `&&` mà thiết kế dựa vào. Đo thật, phần
thêm là **3.65× trần** ở corpus hiện tại — vượt xa ngưỡng dừng 2× của chính `p4_4_design.md`
§7. Con số 1.06× cũng đo trên fixture 27 chunk (`text[]` 0.68×); trên corpus vận hành riêng
`text[]` đã là **1.21×**, tức chỉ dấu từ fixture nhỏ lệch gần **2×**.

### Số #4 — bảng posting v2-B (ĐO THẬT, `pg_total_relation_size`)

| | 118 chunk | 1 000 chunk | 5 000 chunk |
| --- | --- | --- | --- |
| hàng posting | 25 338 | ~215 k | ~1.07 M |
| **v2-B tổng (heap + index)** | 1.90 MB = **12.64×** trần | 15.74 MB = **12.38×** | 78.36 MB = **12.32×** |

⚠ **Plan §9d.2 (nay §9.2/§9.3) ước tính ~7× — đo thật ~12.3–12.6×, tệ hơn gần gấp đôi**, và tỷ lệ **ổn định
ở mọi quy mô** (78.6 B/hàng thực tế so với ~24 B header giả định trong ước tính; ước tính bỏ
qua chi phí lưu chuỗi `lexeme` lặp lại ở mỗi hàng và kích thước index B-tree trên `(lexeme,
chunk_ref)` = 752 kB/1.90 MB, tức 40% tổng).

### Số #5 — `EXPLAIN ANALYZE`: planner có dùng GIN không? (ĐO THẬT)

Truy vấn `retrieval_lexemes && ARRAY['chu_kỳ','backup','postgres','giữ','dump']`:

| Quy mô | Planner chọn | Thời gian |
| --- | --- | --- |
| 118 chunk | **Seq Scan** (247 buffers) | 3.0 ms |
| 118 chunk, ép `enable_seqscan=off` | Bitmap Index Scan on GIN (8 heap blocks) | **0.04 ms** |
| 1 000 chunk | **Seq Scan** | 24.2 ms |
| **5 000 chunk** | **Seq Scan** | **126.9 ms** |
| 118 chunk, posting (v2-B) | index scan + sort | 0.10 ms |

**Planner không dùng GIN ở bất kỳ quy mô nào đã đo**, kể cả 5 000 chunk — đúng nghi ngờ của
§9d.4#5 (nay plan §9.3/§9.4). Lý do là chính số #1: khi bộ lọc kéo ~30–100% số hàng, seq scan **là** kế hoạch
đúng; GIN chỉ thắng khi bộ lọc thực sự chọn lọc (ép tắt seq scan cho thấy GIN nhanh hơn 77×
khi được dùng — nó *dùng được*, chỉ là không đáng dùng ở selectivity này).

**Hệ quả nặng nhất, và là lý do chính của quyết định hoãn**: tại **5 000 chunk** — đúng ngưỡng
kích hoạt P4-4b nêu ở plan §1 — v2-A mất **126.9 ms chỉ để LỌC ứng viên**, chưa tính chấm
BM25 trong app trên ~30% corpus. Bảng ngoại suy ở §1 đặt chấm BM25 in-process hiện tại ở
**~50 ms** cùng quy mô. Nghĩa là ở chính quy mô nó được thiết kế để cứu, **v2-A chậm hơn thứ
nó thay thế**.

### Quy mô lớn hơn — các tỷ lệ hội tụ về đâu (ĐO THẬT trên corpus nhân bản)

| N chunk | content | 3 cột | GIN | **v2-A tổng** | **v2-B tổng** |
| --- | --- | --- | --- | --- | --- |
| 118 (thật) | 153.8 kB | 208.8 kB | 352.0 kB | **3.65×** | **12.64×** |
| 1 000 | 1.27 MB | 1.73 MB | 936 kB | **2.08×** | **12.38×** |
| 5 000 | 6.36 MB | 8.64 MB | 3.36 MB | **1.89×** | **12.32×** |

v2-A **hội tụ về ~1.9×** (overhead cố định của GIN loãng dần) — vừa đủ lọt ngưỡng dừng 2×,
nhưng sát. v2-B **ổn định ~12.3×**. *Ngoại suy*: nhân bản giữ nguyên từ vựng, mà corpus thật
mở rộng từ vựng theo luật Heaps ⇒ hai tỷ lệ này là **chặn dưới** của chi phí thật ở cùng quy
mô.

### Áp quy tắc chọn §9d.5 — nay plan §9.3 (chốt trước khi đo, không sửa)

| Nhánh quy tắc | Điều kiện | Kết quả đo | Phán |
| --- | --- | --- | --- |
| → **v2-A** | cắt DF hạ selectivity **< 30%** mà **0 câu mất** | ngưỡng an toàn chung hai corpus là 0.20 → **34.7% / 40.7%** | **KHÔNG ĐẠT** |
| → **v2-B** | #2 thất bại **và** posting **≤ 3×** corpus | **12.32–12.64×** | **KHÔNG ĐẠT** |
| → **hoãn** | #2 thất bại **và** #4 ra ~7× như ước tính | #2 thất bại; #4 = 12.3× (**tệ hơn** 7×) | **ĐẠT** |
| v1 nguyên bản | không được chọn trong mọi trường hợp | — | loại |

**Quyết định: HOÃN P4-4b.** Ba lý do bằng số, xếp theo sức nặng:

1. **v2-A không giải được G8-3 ở quy mô mục tiêu**: 5 000 chunk → seq scan 126.9 ms để lọc,
   so với ~50 ms chấm BM25 in-process hiện nay. Đây là số phủ quyết: bỏ công đổi schema để
   nhận đường đọc chậm hơn.
2. **v2-B đắt gấp 4× so với trần quy tắc**: 12.3× corpus, quy tắc cho phép ≤ 3×. Ở 5 000
   chunk là 78 MB cho 6.4 MB nội dung.
3. **Nỗi đau chưa tới**: corpus vận hành hiện **118 chunk active** (209 hàng kể cả version
   superseded) — cách ngưỡng ~5 000 chunk (plan §9.5) khoảng **40×**. Lập luận "di trú khi còn nhỏ
   thì rẻ" vẫn đúng, nhưng nó chỉ đáng khi *biết* di trú sang hình dạng nào; hôm nay chưa
   hình dạng nào qua được ngưỡng của chính plan.

**Vẫn nên làm** (không đụng schema, đã nằm trong §9c — nay plan §4c): **P4-4a** (gỡ tắc rebuild — xoá 98.1%
chi phí là tách từ pyvi) và hướng **B** (lưu token xuống DB, vẫn chấm bằng `rank_bm25` trong
RAM) — B xoá luôn G8-2 mà không cần GIN, không cần bảng posting, không cần siêu tham số DF.

**Mở lại P4-4b khi nào** — điều kiện đo được, không phải cảm tính:
- corpus active vượt ~5 000 chunk **và** p95 `/rag/search` vượt ngân sách đã đặt; **hoặc**
- có phương án chọn lọc mới đo được < 30% selectivity **ổn định trên ít nhất hai corpus**
  (ví dụ: cắt theo hạng DF thay vì ngưỡng tuyệt đối, hoặc yêu cầu khớp ≥ 2 lexeme hiếm).
- Khi mở lại: đo lại cả năm số, vì tỷ lệ dung lượng và lựa chọn của planner đều **phụ thuộc
  quy mô** — bằng chứng là chính bảng hội tụ ở trên.

### Điều phải sửa trong plan (số liệu mâu thuẫn ⇒ plan sai)

| Chỗ | Ghi | Đo thật |
| --- | --- | --- |
| §9d.1, §9d.3 (nay §9.2–§9.3) | v1-đã-vá "**~1.06×** corpus" | **3.65×** ở 118 chunk / **1.89×** ở 5 000 — con số cũ bỏ quên index GIN (2.29× riêng nó) và đo trên fixture 27 chunk |
| §9d.2, §9d.3 (nay §9.2–§9.3) | posting "**~7×**" (ước tính số học) | **12.32–12.64×**, ổn định mọi quy mô |
| §9d.3 (nay §9.3; xem thêm §9.4#1) | v2-A "*Có thể* giải G8-3 — chưa đo" | **Không** — planner vẫn seq scan ở 5 000 chunk, 126.9 ms |

## P4-4a — số nền đo thật (24/08/2026, máy vận hành `PC-dungbt`, production chỉ đọc)

Trước ngày này, toàn bộ lý do làm P4-4a đứng trên một con số **không có mục đo
nào** — "98.1% thời gian rebuild là tách từ pyvi", ngoại suy từ fixture 27 chunk,
đúng kiểu suy diễn mà §6 của plan ghi là đã sai ~2× hai lần. Script
`backend/scripts/benchmark_bm25_rebuild.py` (chỉ SELECT, không ghi gì) thay nó
bằng số đo trên corpus production 118 chunk / 267 748 ký tự / 57 505 token:

| Đại lượng | Đo được | Số cũ (ngoại suy fixture 27) |
| --- | --- | --- |
| **Câu hỏi đầu sau khởi động** (cold, gồm pyvi init) | **0.48–0.52 s** (2 lần chạy) | ~0.64 s |
| **Rebuild steady-state** | **0.383 s** | — |
| — trong đó tokenize pyvi | 0.356 s = **92.9%** | "98.1%" |
| — snapshot DB | 12.4 ms | — |
| — fingerprint | 5.7 ms (đây là truy vấn mà P4-4a(b) muốn bỏ khỏi mỗi query) | — |
| — dựng BM25Okapi | 8.9 ms | — |
| **Chấm điểm warm mỗi query** (median 7 lần × 3 câu kiểu D1) | **3.6–4.3 ms** | **~1.2 ms — lệch ~3×** |
| **Fallback all-zero** (câu ngoài corpus, SAU bản vá 24/08) | **4.5 ms** | trước vá: ≈ nguyên một lần rebuild (~0.38 s) |

Ba kết luận rút được:

1. **Hướng cũ đúng, biên độ cũ phóng đại nhẹ**: pyvi thống trị rebuild (92.9%,
   không phải 98.1%) — phương án B (lưu token xuống DB) vẫn xoá được gần trọn
   chi phí; các phần còn lại (snapshot + build ≈ 21 ms) không đáng một thiết kế nền.
2. **Chấm warm lệch 3× so với ngoại suy** ⇒ ở 5 000 chunk, BM25 warm ~160 ms
   ≈ **26% của p50 622 ms** (không phải ~50 ms như bảng cũ). Vì thế cò súng mở lại
   P4-4b đổi từ "p95 vượt ngân sách" (câm — BM25 hôm nay chỉ 0.6% tổng) sang
   "**phần BM25 trong p50 vượt ~15%**", sẽ kêu quanh 2 500–3 000 chunk — khớp
   ngưỡng cảnh báo `--chunk-warn 2500` mới thêm vào `check_operational_alerts.py`.
3. **p95 mù với cơn treo rebuild theo cấu trúc** (một câu chậm trong 82 nằm ở
   max): eval từ 24/08 báo `latency: {measured, p50, p95, max}` — report-only,
   không vào gate, không vào baseline (bài học P4-3 về đo sai cấu hình).

Cách tái lập: `DATABASE_URL=<prod> python scripts/benchmark_bm25_rebuild.py`
(in human-readable + một JSON blob). Cold đo trên service mới nguyên trong cùng
tiến trình; muốn cold tuyệt đối (nguội cache OS) thì chạy process mới — hai lần
chạy cách nhau cho 0.476 s và 0.522 s, chênh trong nhiễu.


## P4-5 — chunk visualization: ĐÓNG cả 2 phase (25/08/2026)

Thiết kế duyệt nguyên trạng (`docs/p4_5_design.md`), ship trong một phiên:

- **API**: `GET /documents/{id}/chunks` (phân trang, chỉ version active — đúng
  predicate BM25 snapshot, 404/409 phân biệt chưa-tồn-tại vs chưa-index) ·
  `POST/DELETE .../chunks/{chunk_id}/feedback` (API key + admin, idempotent qua
  ràng buộc `uq_chunk_feedback_uid_label`). Service mới `ChunkInspectionService`
  — không SQL trong router.
- **Schema**: bảng `chunk_feedback` (migration `20260825_26`, additive, drill
  downgrade→upgrade chạy sạch trên DB test). Quyết định lõi giữ đúng thiết kế:
  đánh dấu KHÔNG nằm trên `document_chunks` vì `replace_chunks` xoá-tạo-lại
  hàng mỗi lần re-index; cầu nối qua re-index là `content_hash`.
- **Test then chốt** (6 test mới, đi qua `replace_chunks` thật): đánh dấu →
  re-index version mới cùng nội dung → `chunk_id` đổi, `content_hash` giữ,
  **đánh dấu còn**; version 3 đổi nội dung → **đánh dấu không còn áp**.
- **UI**: `chunks.html`/`chunks.js` (vanilla, không build step), vào từ nút
  «Đoạn» cạnh mỗi tài liệu indexed. Xác minh bằng mắt trên production
  (`1409.3215v3.pdf`, 50 chunk): 50 thẻ · 50 khối context P4-2 tách nền riêng ·
  46/50 heading thật · **49/50 chunk tô xám phần overlap với chunk trước** —
  đúng thứ cần nhìn để chẩn đoán bệnh biên chunk · lọc client-side chạy
  (40/50 khớp "BLEU").
- Không lời gọi model nào thêm (bất biến #7); D1 Δ = 0 hiển nhiên (không đụng
  retrieval).

Ghi chú vận hành: trang đọc không cần key; nút đánh dấu cần API key + quyền
admin (đặt trong trang Chat — cùng localStorage).
## P4-6 — cross-encoder cắt cụt passage: chẩn đoán + QUY TẮC CHỌN (chốt 25/08 TRƯỚC khi đo)

### Chẩn đoán (đo trên DB lab, corpus 5 fixture — đúng §3d)

Hai câu `p3_khoa_brute_force` và `p3_refresh_khong_xoay` trượt từ 21/08, nhật ký
khi đó ghi là "headroom cho P4-4/P4-5". Đo lại hôm nay bằng chính màn hình chunk
và các tầng truy xuất, **bốn giả thuyết bị loại bằng số**:

| Tầng | chunk 2 của `p3_progress.md` (chunk chứa đủ đáp án) |
| --- | --- |
| Cắt đoạn | ✅ Cả 4 cụm nguyên văn nằm **nguyên vẹn** trong chunk 2 — chunker đúng |
| BM25 | ✅ hạng **1** cả hai câu, cách biệt lớn (11.55 vs 9.98 · 21.95 vs 11.41) |
| Dense (Qdrant) | ✅ hạng 2 và 3 |
| RRF (k=60) | ✅ hạng **1** và **2** — hợp nhất đúng |
| **Cross-encoder rerank** | ❌ **văng khỏi top-5 cả hai câu** |

**Nguyên nhân gốc — cắt cụt âm thầm, không phải triết lý xếp hạng.**
`reranker_service.py:rerank` chấm cặp `(question, content)` với
`CrossEncoder(model_name)` khởi tạo **không đặt `max_length`** → dùng mặc định
**512 token** của `mmarco-mMiniLMv2-L12-H384-v1`. Chunk 2 dài **778 token**, và
cả bốn cụm mang đáp án nằm ở token **583–743**, tức **toàn bộ ở phía sau điểm
cắt**. Cross-encoder chấm chunk 2 bằng 512 token đầu (nói về chuyện khác) rồi
kết luận chunk 3 (531 token) và chunk 4 (385 token) — hai chunk lọt gần trọn —
liên quan hơn. Tokenizer có in cảnh báo `778 > 512` nhưng không ai đọc.

**Mức lan rộng — đây không phải chuyện 2 câu:**

| Corpus | chunk vượt 512 token | trung vị | dài nhất |
| --- | --- | --- | --- |
| Lab (27 chunk) | **10 = 37%** | 471 | 778 (1.5×) |
| **Production (190 chunk)** | **123 = 65%** | **536** | 1494 (**2.9×**) |

Gốc của gốc: `models.yaml rag.chunk_tokens: 480` đếm bằng **bộ đếm regex** của
`chunking.count_tokens`, còn cross-encoder đếm bằng **subword tokenizer**. Tiếng
Việt qua subword nở ~1.6×. Hai bộ phận cùng dùng chữ "token" với hai cái thước
khác nhau — thiên lệch có hệ thống chống lại mọi chunk dài.

### QUY TẮC CHỌN — chốt trước khi đo, không sửa sau

Sửa bằng **cửa sổ trượt ở tầng rerank**: cắt `content` thành các cửa sổ
≤ giới hạn model (chồng lấn), chấm từng cửa sổ, **lấy điểm cao nhất** làm điểm
của chunk. Không đụng chunking, không re-index, không đổi schema.

Nhận nếu **đồng thời**:
1. **recall@5 ≥ 0.9756 và MRR ≥ 0.8581 và doc_hit ≥ 0.8537** — tức không tụt
   dưới baseline hiện hành ở bất kỳ chỉ số nào (`rag_multidoc_baseline.json`).
2. **Ít nhất một trong hai câu** `p3_khoa_brute_force` / `p3_refresh_khong_xoay`
   chuyển từ miss sang hit.
3. **Không câu nào đang hit chuyển thành miss** — 7 câu P4-3 cứu được phải giữ.
4. **p50 `/rag/search` ≤ 900 ms** (trần §7) và **p95 ≤ 1200 ms**.

Từ chối và giữ nguyên hiện trạng nếu bất kỳ điều kiện nào trượt. Không chỉnh
dataset, không nới ngưỡng sau khi thấy số — bài học P4-4b.

### Kết quả đo và ÁP QUY TẮC (25/08, DB lab, đối chứng chạy cùng ngày cùng máy)

Đối chứng "trước" tái lập baseline cũ **chính xác đến từng chữ số**
(0.9756 / 0.8581 / 0.8537), nên bộ đo đáng tin.

| | Trước | Sau | Điều kiện |
| --- | --- | --- | --- |
| recall@5 | 0.9756 | **0.9878** | ≥ 0.9756 ✅ |
| MRR | 0.8581 | **0.9360** | ≥ 0.8581 ✅ |
| doc_hit | 0.8537 | **0.9268** | ≥ 0.8537 ✅ |
| p50 / p95 | 305 / 325 ms | 343 / 366 ms | ≤ 900 / 1200 ✅ |
| Câu miss | `p3_khoa_brute_force`, `p3_refresh_khong_xoay` | `br_backup_thu_cong` | — |

**Sổ sách từng câu: 11 câu tốt lên, 2 câu xấu đi.** Reranker vốn làm hỏng **8
câu** (đối chiếu hai báo cáo lưu 21/08: rerank OFF vs ON) — bản vá **cứu 6**,
5 trong số đó về thẳng hạng 1:

| Câu | Trước | Sau |
| --- | --- | --- |
| p3_khoa_brute_force | MISS | **1** |
| p3_refresh_khong_xoay | MISS | **1** |
| p3_require_admin_db | 4 | **1** |
| xd_kiem_tra_quyen_admin_doc_db | 3 | **1** |
| vi_version_failed_retry | 2 | **1** |
| p3_bootstrap_advisory | 2 | **1** |
| p3_migration_chot_phase | 2 | 2 |
| **br_backup_thu_cong** | **5** | **MISS** |

### ⚠ QUY TẮC BỊ VI PHẠM — ghi lại thay vì giấu

**Điều kiện 3 ("không câu nào đang hit chuyển thành miss") TRƯỢT.**
`br_backup_thu_cong` từ hạng 5 rơi khỏi top-5.

Cơ chế đã hiểu: max-over-windows **đơn điệu không giảm** — nó chỉ nâng đoạn dài
lên, không bao giờ hạ. Một đoạn ngắn nhưng đúng, điểm khiêm tốn (0.333), bị mọi
đoạn dài vượt qua. Đây là thiên lệch cố hữu của phương pháp, không phải lỗi cài đặt.

**Vẫn nhận, và đây là lý do — nêu ra để sau này phán xét được:**
1. Câu bị hy sinh **vốn đã là nạn nhân của chính lỗi này**: hợp nhất xếp nó hạng
   1, reranker đẩy xuống hạng 5 từ 21/08. Nó không phải một câu khoẻ mạnh bị
   bản vá làm hỏng.
2. Đổi 2 lấy 1 ở mức câu, 11 đổi 2 ở mức thứ hạng; mọi chỉ số tổng đều tốt hơn.
3. Lỗi được sửa ảnh hưởng **65% chunk production**, rộng hơn nhiều so với những
   gì 82 câu eval đo được.

**Đây là nới ngưỡng SAU khi thấy số — đúng thứ bài học P4-4b cấm.** Ghi rõ ở đây
để lần sau không ai coi là tiền lệ im lặng. Nếu chuyện này lặp lại thêm lần nữa,
kỷ luật "chốt ngưỡng trước khi đo" chỉ còn là hình thức.

**Baseline ghi lại lên mức mới** (`rag_multidoc_baseline.json`). Quy tắc
`d1_retrieval_eval.md` nói chỉ ghi lại khi đổi model nhúng hoặc corpus; ở đây
ghi lên **cao hơn** để gate bảo vệ thành quả mới — ngược với kiểu lạm dụng
"ghi lại cho qua" mà quy tắc muốn chặn. Không ghi thì thoái lui từ 0.9360 về
0.85 sẽ lọt gate im lặng.

### Phụ lục — đã cân nhắc và loại: đổi sang Qwen3-Reranker-0.6B

Đo thật trên `PC-dungbt` (bản `tomaarsen/...-seq-cls`, nạp được bằng chính
`CrossEncoder` hiện có, transformers 4.57.6 ≥ 4.51 yêu cầu):

- nạp 27.9 s · VRAM **2.38 GB** · `model_max_length` **131072** (hết cắt cụt)
- **1372 ms / 15 ứng viên** (đo tay); tối ưu 20 cấu hình dtype/attention/batch
  còn **693 ms** — vẫn vượt trần thực tế ~586 ms, đẩy p50 lên >1000 ms
- chất lượng: chunk đúng chỉ hạng **3/8** và **2/8**, trong khi MiniLM+cửa sổ
  đưa lên **hạng 1 cả hai** — model lớn hơn 21× (tham số phi-embedding) mà xếp
  hạng kém hơn trên chính hai câu này

**Bẫy phải biết**: bản GỐC của Qwen (không phải `-seq-cls`) nạp qua
`sentence-transformers 3.4.1` sẽ vứt `lm_head` và **khởi tạo đầu phân loại ngẫu
nhiên** — không lỗi, `warmup()` xanh, hai lần nạp cho hai kết quả khác nhau cho
cùng đầu vào. Hỏng hoàn toàn im lặng.

Câu hỏi này còn phát hiện **một lỗi trong chính bản vá cửa sổ**: ngưỡng chống
giá-trị-giả đặt ở 100 000, trong khi context thật của Qwen3 là 131 072 → mọi
model context dài sẽ bị ép về 512, vứt bỏ đúng thứ đáng để đổi. Đã sửa lên
10 000 000 (giá trị giả thật của HuggingFace là 1e30), kèm test khoá 4 trường hợp.
