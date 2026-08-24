# P4-5 — Chunk visualization: thiết kế để duyệt TRƯỚC khi code

**Ngày:** 25/08/2026 · **Trạng thái:** CHỜ DUYỆT — chưa có dòng code nào
**Bài học áp dụng:** RAGFlow (plan §10 — "chunking giải thích được"); bất biến #8 (chốt schema trước khi viết); nghiệm thu đã ghi ở plan §4c#4.

---

## 1. Bài toán

Khi hệ trả lời sai, người dùng không có cách nào nhìn vào bên trong: tài liệu bị
cắt thành đoạn nào, đoạn nào được index, ranh giới cắt nằm đâu. Đồng thời hai
KPI đang trượt (MRR 0.858 / doc_hit 0.854, mục tiêu 0.90) đều đã được chẩn đoán
là bệnh **biên chunk** (`p4_progress.md`: rerank kéo chunk lân cận lên trên
chunk mang nguyên văn) — không nhìn thấy biên thì không sửa được.

Dữ liệu cần thiết **đã có đủ** sau T15/T17: 9 cột trên `document_chunks`
(content, retrieval_context, chunk_index, page_start/end, section_title,
block_type, content_hash, heading_path, locations, token_count) — 75/118 chunk
active mang heading thật, locations đã backfill.

## 2. Phạm vi — tách làm hai phase, ship phase 1 trước

| | Phase 1 — CHỈ XEM | Phase 2 — ĐÁNH DẤU |
| --- | --- | --- |
| Giá trị | Trả lời "tại sao sai" — đủ dùng một mình | Ghi lại "đoạn này tệ" làm việc sau |
| Schema | **Không đổi gì** | Một bảng mới (additive, có downgrade) |
| Ước lượng | 2–2.5 buổi | +1.5–2 buổi |

Lý do tách: phần chỉ-xem không đụng schema nên rủi ro gần bằng không; phần đánh
dấu kéo theo một quyết định lưu trữ (mục 5) đáng được chốt riêng. Nếu duyệt cả
hai, vẫn ship phase 1 trước để có thứ dùng được sớm.

## 3. API — Phase 1

**`GET /documents/{document_id}/chunks?limit=50&offset=0`** *(mới, đọc-only,
không cần API key — cùng mức với `GET /documents` và `/status` hiện có)*

```json
{
  "document_id": "doc_…", "version_id": "ver_…", "version_number": 3,
  "filename": "mphatlalatsane_facilitators_manual.pdf",
  "total_chunks": 36, "total_tokens": 14520,
  "chunks": [
    {
      "chunk_id": "chunk_…", "chunk_index": 0,
      "content": "…nguyên văn đoạn…",
      "retrieval_context": "…context P4-2 sinh, hoặc null…",
      "token_count": 384,
      "page_start": 1, "page_end": 2,
      "heading_path": ["Session 1", "Step 3"],
      "section_title": "Step 3",
      "block_type": "paragraph | table | mixed",
      "locations": [{"page": 1, "start": 120, "end": 890}],
      "content_hash": "sha256…"
    }
  ]
}
```

Quy ước:
- Chỉ trả **version active** (đúng predicate BM25 snapshot). Tài liệu chưa
  index → 409 kèm thông điệp; không tồn tại → 404.
- `heading_path` trả **mảng** (đúng cột JSONB); UI tự join " > " khi hiển thị —
  giữ một dạng dữ liệu chuẩn, dạng chuỗi chỉ là chuyện trình bày.
- Phân trang mặc định 50 (corpus lớn nhất hiện tại 50 chunk/tài liệu; tài liệu
  1 000 trang tương lai không làm nghẽn một response).
- Service mới `ChunkInspectionService` (routers → services → repositories, đúng
  cấu trúc §5 của plan; **không** nhét SQL vào router — tránh lặp lỗi T9).

## 4. UI — Phase 1

Một trang mới `app/frontend/chunks.html` + `chunks.js` (script tag thường,
không build step — đúng khuôn ocr.html). Vào từ dashboard: mỗi tài liệu trong
bảng có nút "Chunks".

Bố cục một cột, mỗi chunk một thẻ:

```
┌─────────────────────────────────────────────────────┐
│ #0 · trang 1–2 · 384 token · paragraph              │  ← metadata dòng 1
│ Session 1 › Step 3                                  │  ← heading_path (mờ nếu null)
│ ─────────────────────────────────────────────────── │
│ [context retrieval — nền vàng nhạt, nếu có]         │  ← phần model sinh (P4-2)
│ Nguyên văn đoạn chunk…                              │  ← content
└─────────────────────────────────────────────────────┘
```

- **Ranh giới cắt là thứ phải nhìn thấy được**: giữa hai thẻ liên tiếp in phần
  **overlap trùng nhau** (so `locations`: đoạn cuối thẻ trước xuất hiện lại ở
  đầu thẻ sau) bằng nền xám — đây chính là chỗ chẩn đoán bệnh biên chunk.
- Chunk `block_type=table` render nội dung trong `<pre>` (bảng markdown giữ cột).
- Thanh đầu trang: tên file, version, tổng chunk/token, ô lọc theo từ khoá
  (lọc client-side trên trang đã tải — không thêm endpoint search).
- Không gọi model, không đụng đường `/rag/*` — bất biến #7 giữ nguyên.

## 5. Phase 2 — "đánh dấu chunk kém": quyết định lưu trữ

**Vấn đề then chốt:** `replace_chunks` **xoá và tạo lại** toàn bộ hàng chunk
mỗi lần re-index. Một cột `flag` trên `document_chunks` sẽ **mất sạch đánh dấu
sau mỗi lần re-index** — sai lặng lẽ, đúng kiểu lỗi T15. Vì vậy:

**Đề xuất: bảng mới `chunk_feedback`** (additive, có downgrade):

| Cột | Kiểu | Ghi chú |
| --- | --- | --- |
| id | PK | |
| chunk_uid | String(128), index | uuid5(doc:version:index) — ổn định trong một version |
| document_id | FK documents, CASCADE | để liệt kê theo tài liệu |
| content_hash | String(64) | **cầu nối qua re-index**: version mới, chunk nội dung y hệt → tra lại được đánh dấu cũ |
| label | String(32) | v1 chỉ một giá trị: `"bad"` — enum mở sau nếu cần |
| note | Text, nullable | lý do tuỳ chọn |
| created_at | timestamptz | |

- Đánh dấu **sống qua re-index** ở mức tra-cứu-theo-content_hash (chunk đổi nội
  dung thì đánh dấu cũ không còn áp — đúng ngữ nghĩa: nội dung khác là đoạn khác).
- API: `POST /documents/{id}/chunks/{chunk_id}/feedback` (cần API key + admin,
  như mọi endpoint ghi) · `DELETE` để gỡ · GET chunks trả kèm `feedback` khi có.
- Migration một bảng, `downgrade` = drop bảng — đúng bất biến #3.

## 6. Nghiệm thu (khớp plan §4c#4, cụ thể hoá)

Phase 1:
1. `GET /documents/{id}/chunks` trả đủ 9 cột + phân trang; 404/409 đúng trường hợp.
2. Với sổ tay 45 trang: `heading_path` khác null ở các chunk có mục thật;
   chunk bảng hiện `block_type=table` và giữ dạng bảng.
3. Overlap giữa hai chunk liên tiếp nhìn thấy được trên UI.
4. Test 3 tầng: service (phân trang, active-only) · endpoint (404/409/200) ·
   một test tô overlap ở mức dữ liệu (locations giao nhau).
5. `D1 Δ = 0` hiển nhiên (không đụng retrieval) — không cần đo lại.

Phase 2: đánh dấu → re-index cùng nội dung → đánh dấu còn; đổi nội dung chunk
→ đánh dấu không còn áp; downgrade migration chạy sạch.

## 7. Điều cố tình KHÔNG làm

- Không sửa thuật toán chunking trong mục này — chỉ **nhìn**. Sửa biên chunk là
  thí nghiệm eval-gated riêng, sau khi màn hình chỉ ra bệnh cụ thể.
- Không thêm endpoint search/filter server-side — corpus hiện 118 chunk, lọc
  client-side là đủ; thêm khi có số chứng minh cần.
- Không WebSocket/live-update — trang tĩnh tải một lần.
- Không framework frontend mới — vanilla JS như ba trang hiện có.
