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
