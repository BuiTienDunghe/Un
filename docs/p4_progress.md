# Nhật ký Phase P4 — RAG nâng cao, có đo lường

Mỗi mục P4 là **một thí nghiệm**: thiết kế ngắn → code với cờ tắt → đo bằng bộ
eval D1 (`docs/d1_retrieval_eval.md`) → chỉ bật mặc định khi số liệu chứng minh
(bất biến plan §1). Phân lane theo `docs/machine_split.md`: phần *xây* (code,
unit test) là lane nhẹ, phần *đo* (sinh context, re-index) là lane nặng.

## P4-2 — Contextual retrieval (Anthropic)

**Trạng thái 21/08/2026: CODE XONG (lane nhẹ) — cờ TẮT mặc định — thí nghiệm đo
lường chờ máy nặng** (phiên code chạy trên container cloud không GPU, không kéo
được model sinh; xem "Runbook thí nghiệm" dưới).

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

### Runbook thí nghiệm (máy NẶNG — theo BƯỚC 4 đã giao)

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

**Bảng trước/sau (điền khi đo trên máy nặng):**

| Metric | Trước (baseline 21/08) | Sau P4-2 | Δ |
| --- | --- | --- | --- |
| recall@5 tổng | 0.8659 | — | — |
| MRR tổng | 0.7341 | — | — |
| doc_hit tổng | 0.7683 | — | — |
| recall@5 cross | 0.7500 | — | — |
| MRR cross | 0.5903 | — | — |
| Câu miss→hit / hit→miss | (11 miss nền: xem d1_retrieval_eval.md) | — | — |
| Giây index/tài liệu · lời gọi | — (cờ tắt) | — | — |

Kỳ vọng cụ thể trên bộ miss hiện tại: cụm nhiễu chéo Qdrant point/version
(`vi_qdrant_point_id`, `xd_point_id_qdrant_uuid5`…) và cụm `ca_*` chủ đề trùng
lấn là đúng dạng lỗi mà context "tài liệu này là gì, đoạn này nằm ở đâu" nhắm
sửa — theo dõi riêng các câu này trong cột miss→hit.
