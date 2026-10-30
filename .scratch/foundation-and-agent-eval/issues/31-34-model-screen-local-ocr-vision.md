# 31–34 — Đổi model trên web, công cụ giờ và tính toán, OCR và vision trên máy

Status: xong code — gộp main (30/10); chưa thử ảnh và `/docs` trên Discord thật, chưa push
Type: task
Blocked by: —

## Bản chất

Chủ dự án muốn đổi model ngay trên web, muốn Ún biết giờ và tính đúng, và muốn OCR, vision phục vụ model trên máy thay vì dựa vào API.

## Quyết định

- 31: lựa chọn nằm ở `data/model_choice.env`, launcher nạp thành shell pin; `model_versions.yaml` và bài đánh giá không đổi.
- 32, 34: `current_time`, `calculate`. Cùng phạm vi server với mọi công cụ.
- 33: `ocr-v2` và `vision-v1` là Qwen 9B trên máy. Chủ dự án bỏ hướng Haiku: "nếu dùng api thì không cần làm".

## Đo OCR (30/10, văn bản tự viết có đáp án, xuống cấp giả lập)

| Trang | `ocr-v1` sai ký tự | `ocr-v2` sai ký tự |
|---|---|---|
| Giữ riêng, 7 trang | 9,0–35,1% | 0–0,42% |
| Dày chữ 8 pt | 17,5% | 0,21% |

Chưa đo scan thật hay chữ viết tay. Script ở scratchpad phiên, không vào repo.

## Treo

- Mô tả ảnh nằm trong câu hỏi của lượt nên bộ trích trí nhớ đọc được khi bật.
- Thiếu theo Anthropic "Building effective agents": trí nhớ do agent tự ghi, tra web. Cả hai cần chủ dự án quyết.
- Chữ trong ảnh trên trang đã có chữ vẫn chưa được OCR (chỉ chạy khi trang dưới 80 ký tự).
- `data/vram_budget.md` và vài chú thích còn nói glm-ocr.

## Comments
- 30/10 (opus 5.5): fable duyệt `eba3794..8b42231`: GỘP ĐƯỢC, 3 mục chặn của ticket 31 đã sửa (`reviews/wip-31-34.md`). Sửa thêm trước khi gộp: bộ lọc "không có chữ" nuốt nhầm trang thật, phép thử đuổi model thường trú, câu CHANGELOG sai.
