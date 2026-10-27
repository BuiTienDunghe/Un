# 11 — Đo dao động trên 788 câu held-out (tiền đề M3, dùng cho mọi ứng viên)

Status: đã gộp vào main (27/10), opus 5.5 duyệt (chỉ dữ liệu + RESULTS.md); số đã điền vào m3-preregistration.md
Type: task
Blocked by: — (stack Ún đã bật 27/10)

## Vì sao

Ticket 09 chỉ giữ thay đổi khi cải thiện "vượt mức dao động đã đo". Nhưng trên 788 câu held-out
chưa từng có lần lặp nào cùng cấu hình (`m3-target.md`, mục "Bộ đo nào phân giải được gì"): 0,7843 /
0,7919 / 0,7906 là ba cấu hình khác nhau. Việc này cần cho cả ba ứng viên A/B/C, nên làm trước khi
chủ dự án chọn.

## Việc

1. Lặp lại **đúng cấu hình** của `data/evaluation/heldout_retrieval_v1/results/heldout-ctxON-rerankerON-20260908-055318.json`
   (cấu hình đang ship: ctx ON, reranker ON), **2 lần**, bằng `training/common/eval_stack.py` +
   `eval_heldout.py` (stack heldout cổng 8200). Trước khi chạy, so cấu hình/fingerprint mà lần chạy
   mới sẽ dùng với cấu hình ghi trong file 08/09; lệch thì dừng và báo, không chạy.
2. Nếu DB heldout không còn ở trạng thái ctx ON (phải nạp lại) thì dừng và báo điều phối, không tự
   nạp lại.
3. Báo cáo: Acc@1 / Acc@3 / recall@5 / MRR của mỗi lần; **số câu đổi kết quả** ở hạng 1 giữa các lần
   (so từng câu); chênh lớn nhất. Đây là sàn dao động của bộ 788.
4. Thêm vào `docs/RESULTS.md` hai dòng còn thiếu cho các lần 08/09 (`heldout-ctxON-rerankerON-20260908-055318`,
   `heldout-heading-ctx-rerankerON-20260908-010012`) và dòng cho các lần lặp mới, theo đúng định dạng
   bảng held-out đang có (khoảng dòng 300–310).

## Cách chạy

Worktree riêng (`coordination.md`). Worktree không có `.env`: tạo `.env` tối thiểu từ `.env.example`,
không chép khoá. Không dùng DB `local_ai_core_test` (bộ test đầy đủ đang chạy trên đó) và không dùng
DB `local_ai_core` (dữ liệu thật). Ollama dùng chung với Nhân viên 3 (chạy thử tối đa 3 bài agent),
không sao.

## File được đụng

Kết quả mới trong `data/evaluation/heldout_retrieval_v1/results/` (được track), `docs/RESULTS.md`.

## Nghiệm thu

Hai file kết quả mới, cùng cấu hình với 08/09 (ghi phần so cấu hình vào Comments); bảng dao động
theo từng câu; RESULTS.md có đủ dòng.

## Comments

**Nhân viên của Ún 2, 27/10.**

### So cấu hình trước khi chạy

Đã so trước khi chạy, không có chỗ nào lệch.

| Mục | Lần 08/09 (`heldout-ctxON-rerankerON-20260908-055318`) | Lần lặp 27/10 |
|---|---|---|
| Phiên bản (`/models` → registry.loaded) | general-v0 / embedding-v0 / reranker-v0 | general-v0 / embedding-v0 / reranker-v0, không fallback |
| `rag` | contextual_retrieval true, reranker true, hybrid | giống hệt |
| Lệnh | (không ghi lại) | `eval_stack --profile heldout --start --contextual --reranker`, rồi `eval_heldout --label ctxON-rerankerON` |
| Code | cây f88380f (1.1.0, commit cuối trước 05:53 08/09); trạng thái chưa commit lúc đó thì không biết được | 18c69fc |
| `.env` | `.env` thật | `.env` tối thiểu, chỉ 4 dòng chép từ `.env.example`: DATABASE_URL, OLLAMA_BASE_URL, QDRANT_URL, REDIS_URL. `.env` thật không có biến RAG_/QDRANT_/MODEL_ nào, và DATABASE_URL trùng bản mẫu (so bằng máy, không in giá trị) |

Code thay đổi từ f88380f tới 18c69fc:
- `models.yaml`: không đổi.
- `model_versions.yaml`: chỉ đổi OCR và bản ứng viên reranker-vi-v1; ba bản ghi general/embedding/reranker-v0 giữ nguyên.
- Đường truy vấn: `ollama_client.py` và `model_router.py` chỉ đổi phần vision/OCR; `model_registry.py` thêm phép thử OCR lúc khởi động. Không có file nào của rag/retrieval/reranker thay đổi.

DB `local_ai_core_drill_heldout` (đọc ở chế độ read-only):

| Dấu vân tay | Giá trị |
|---|---|
| Tài liệu | 2 926 indexed + 19 failed |
| Mảnh | 7 792, trong đó 7 511 có `retrieval_context` |
| Qdrant `documents_drill_heldout` | 7 792 điểm, 1 024 chiều |
| Phiên bản lược đồ (alembic) | `20260828_32`. Code có thêm `_33`, `_34`, nhưng hai bản này chỉ tạo bảng research mới; không nâng lược đồ, API vẫn chạy |
| Lần ghi cuối vào mảnh / phiên bản / lần nạp | 2026-09-07 21:54:30 UTC (= 04:54 ngày 08/09: lần nạp lại có ngữ cảnh) |
| `documents.updated_at` / `last_accessed_at` lớn nhất | 2026-09-07 22:53:18,91 UTC, trùng tới phần trăm giây với `created_at` của file 08/09 |

Kết luận: không ai ghi vào DB này sau lần đo 08/09, nên không cần nạp lại. Giới hạn: 281 mảnh
không có ngữ cảnh. Không có cách nào so chúng với trạng thái ngày 08/09, chỉ biết từ đó tới nay
không mảnh nào được ghi lại. Mỗi lần gọi `/rag/search` đều ghi `last_accessed_at` (lần 08/09 cũng vậy).

### Kết quả (27/10)

Hai lần chạy liền nhau: 16:34–17:36 và 17:36–18:36. Không có lỗi HTTP, cả 788 câu đều đo được.

| Lần | Acc@1 | Acc@3 | recall@5 | MRR | nDCG@5 | p50 ms |
|---|---:|---:|---:|---:|---:|---:|
| 08/09 `…-20260908-055318` | 0.7919 | 0.9670 | 0.9822 | 0.8769 | 0.9034 | 4 388 |
| lặp 1 `…-20261027-173610` | 0.7919 | 0.9683 | 0.9822 | 0.8768 | 0.9033 | 4 622 |
| lặp 2 `…-20261027-183624` | 0.7919 | 0.9683 | 0.9822 | 0.8768 | 0.9033 | 4 548 |
| **Chênh lớn nhất** | **0** | **0.0013 (1 câu)** | **0** | **0.0001** | **0.0001** | 234 |

So từng câu:

| Cặp | Câu đổi hạng | Hạng 1 mất / được | Top-3 mất / được | Top-5 mất / được |
|---|---:|---:|---:|---:|
| lặp 1 ↔ lặp 2 | 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 08/09 ↔ lặp 1 | 2 | 0 / 0 | 0 / 1 | 0 / 0 |
| 08/09 ↔ lặp 2 | 2 | 0 / 0 | 0 / 1 | 0 / 0 |

- Lặp 1 và lặp 2 giống nhau ở mọi trường của từng câu, chỉ khác độ trễ.
- So với 08/09 có 2 câu đổi: `3dc7f622…` từ hạng 4 lên 3, và `f35f4833…` từ hạng 2 xuống 3 (lần này trả 3 tài liệu thay vì 2). Giữa hai lần đã đổi code (f88380f → 18c69fc, đường truy vấn không đổi) và Ollama (bây giờ 0.40.8; file 08/09 không ghi bản nào). Chưa tách được nguyên nhân nào gây ra 2 câu này.

**Hệ quả cho ticket 09.** Dao động khi lặp lại gần như bằng 0, nên không dùng được làm ngưỡng: lệch
1 câu cũng "vượt dao động". Giới hạn thật là cỡ mẫu. Ngưỡng nên là phép thử theo cặp (McNemar) trên
từng câu, như đã ghi trong `m3-target.md` (+3,2–5,5 điểm Acc@1). Chọn ngưỡng nào là việc của điều phối.

**Lệch so với ticket.**
- Không thêm dòng vào bảng reranker có sẵn. Tôi tạo một bảng mới cùng cột ngay dưới bảng đó, cột đầu là "Configuration". Lý do: bảng reranker so hai reranker trên chỉ mục *không* có ngữ cảnh. Gộp vào thì một bảng sẽ chứa hai chỉ mục khác nhau.
- Không tra ra nhãn `heading-ctx` (08/09 01:00) nghĩa là gì. Chỉ mục đó đã bị ghi đè lúc 04:54 cùng ngày, file chỉ ghi `contextual_retrieval: false`. RESULTS.md ghi đúng như vậy.

**Ghi chú phụ.**
- Lỗi in: `eval_stack --contextual` vẫn in "contextual=OFF". Nó in spec, không in giá trị ghi đè. `/models` xác nhận `contextual_retrieval: true`.
- Độ trễ 27/10 có thể chịu ảnh hưởng vì Ollama dùng chung với Nhân viên 3.
