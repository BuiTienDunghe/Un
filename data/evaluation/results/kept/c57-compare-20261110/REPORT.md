# Bản cũ (main `3eac7f6`, 9B) so với bản mới của Codex (`c57aa3e`, chỉ model nhỏ) — 10/11/2026

Đăng ký trước: mục 10/11 trong `docs/SO_DO.md`, viết trước khi chạy. Ollama 0.40.13 suốt mọi lượt.
GPU RTX 5060 Ti, không lượt nào bị dừng (nhiệt cao nhất 75 °C). Bản mới chạy từ worktree tách riêng,
`DISCORD_MEMORY_EXTRACTOR_MODEL=` rỗng trong tiến trình (chốt chặn của nhánh từ chối tag 9B trong `.env` thật).

## Agent Eval v0 (66 bài, nhiệt độ 0, seed 42, dỡ model giữa từng bài)

| Lượt | Code | Model | Đạt | Trung vị/bài | p90/bài | VRAM đỉnh |
|---|---|---|---:|---:|---:|---:|
| A | main | qwen3.5:9b | 57 | 4,4 s | 8,1 s | 6.950 MiB |
| C | main | qwen3.5:2b | 47 | 2,1 s | 4,7 s | 3.376 MiB |
| B | `c57aa3e` | qwen3.5:2b (`general-small-v1`) | 47 | 2,0 s | 4,5 s | 3.376 MiB |

- C → B: 0 bài đổi kết quả. Code mới không đổi gì ở Agent Eval (nhớ công cụ tắt mặc định).
- A → B: mất 15, được 5 (McNemar chính xác hai phía p ≈ 0,04). Mất: doc-10, 27, 31, 36, 45, 52, 56, 57;
  hist-02, 03, 04, 08; nt-01, nt-02 (bài không được gọi công cụ); stat-02. Được: doc-19, 20, 26, 33, 55.
- Trùng khớp số 08/11 (57 và 47).

## OCR — 10 ảnh tự tạo của Codex (`data/benchmarks/ocr_evidence/v1`)

7 ảnh có văn bản chuẩn (887 chữ/số sau khi bỏ ký hiệu trình bày); 3 ảnh mới không có, chỉ dùng cho câu hỏi.
Thước "thô" là thước đã đăng ký; thước "chữ và số" thêm sau khi thấy số (lý do ngay dưới).
VRAM là đỉnh từng lượt riêng; bản cũ dùng lại 9B đã nạp cho OCR, bản mới nạp 2B, Ovis, LFM3 riêng — tổng khi chạy cùng lúc chưa đo.
"Thô" so cả ký hiệu; "chữ và số" bỏ thẻ HTML, dấu `#`, `|`, tab và dấu câu — vì Ovis trả bảng dạng HTML,
9B tách cột bằng tab, văn bản chuẩn dùng `|`, nên số thô phạt cách trình bày chứ không phải đọc sai.

| Bản | Model | Sai thô | Sai chữ và số | Giây/ảnh (trung vị) | VRAM đỉnh |
|---|---|---:|---:|---:|---:|
| cũ `ocr-v2` | qwen3.5:9b | 3,38% | 0/887 | 2,10 | 7.046 MiB |
| cũ `ocr-v1` (lùi) | glm-ocr eot-v1 | 12,16% | 83/887 | 0,91 | 3.880 MiB |
| mới `ocr-ovis-v1` | OvisOCR3 Q8 | 41,86% | 2/887 | 1,79 | 1.658 MiB |
| mới `ocr-small-v1` | glm-ocr eot-v1 | 12,68% | 88/887 | 0,91 | 3.880 MiB |

Hai lỗi của Ovis là dấu thật, cùng ảnh `shipment_table`: "VĂN CHUYỂN" (đúng: VẬN), "Tuyên" (đúng: Tuyến).

28 câu hỏi trên 10 ảnh:

| Đường | Đạt |
|---|---:|
| Cũ, xấp xỉ: 9B đọc toàn văn bản OCR của chính nó rồi trả lời | 27/28 (sai "Ai phụ trách dự án Hải Âu?" dù OCR chép đúng dòng đó; 4/4 câu cần từ chối đều từ chối) |
| Mới: `ocr_evidence_eval` nguyên bản (Ovis + LFM3 đọc bằng chứng) | 28/28 |

Bộ ảnh và bộ chấm do Codex viết, 3 ảnh mới đã được Codex xem để chỉnh cách gom cột: đây là kiểm hồi quy, không phải bài kiểm độc lập.
Đường cũ được cho cả văn bản trong một lần hỏi, rộng tay hơn đường RAG thật.

## Test trên `c57aa3e`

Backend 2.214 đạt, 4 hỏng do môi trường của tôi (`REDIS_URL` chưa trỏ container test, `/health` báo degraded);
chạy lại 4 bài với `REDIS_URL` đúng: đạt. Bộ gốc 242 đạt, 1 bỏ qua. Migration tới `20261109_39` sạch.

## Kiểm một khẳng định của Codex

Codex viết chốt chặn trí nhớ cũ chấp nhận "Tôi thích cà phê đen" từ câu "Hãy nhớ tôi không thích cà phê đen".
Chạy `memory_guard` của main: `fact_overlap` = True nhưng `negation_clause_hit` = True, nên `auto_apply_allowed` = False.
Chốt cũ không tự lưu câu sai đó; nó chỉ đẩy sang hàng chờ duyệt. Lợi thế của trí nhớ v2 ở đây là không cần duyệt, không phải sửa một lỗi đang tự lưu sai.

## Tệp

`progress.jsonl` (thời gian, VRAM, nhiệt từng lượt), `analysis.json`, `ae/*/` (manifest, summary, từng bài),
`ocr/*.json` (văn bản OCR và câu trả lời), `tests/*.xml`, `scripts/` (kịch bản chạy và phân tích).
