# Không gian Nghiên cứu — việc backend / pipeline còn thiếu

Bản 11/10 đã có đủ endpoint trong `spec.md`. Dưới đây là chỗ UI đang chạy ở mức "trung thực nhưng chưa đủ"
vì dữ liệu phía sau chưa có, hoặc chỗ làm thô cần tinh.

## Dữ liệu còn thô

- [ ] **Ô trích dẫn trên trang** (`GET /documents/{id}/pages/{n}/boxes`) luôn trả `[]`: chunker lưu `locations`
      dạng `{page, start, end}` (độ lệch ký tự), không có bbox. Để popup trích dẫn của Chat (Phần 1) và chip
      `[Paper · tr.N]` tô được vùng đoạn, cần map `start..end` → rect qua `page.get_text("words")` lúc index
      (hoặc tính lười trong `document_pages.py` từ `selected_text` + words). Nhánh bbox trong code đã sẵn.
- [ ] **Tác giả** chỉ lấy dòng đầu dưới tiêu đề (ví dụ "Ashish Vaswani ∗"): bài nhiều cột tác giả bị cụt.
      Gộp các dòng cùng cỡ chữ cho tới dòng có "@" / "University" / "Abstract".
- [ ] **Venue** chưa trích (`null`): dò chân trang 1 ("31st Conference on …", "CVPR 2024", "arXiv preprint").
- [ ] **Thumbnail hình/bảng** trong panel Mục lục: outline chỉ có nhãn + trang; muốn ảnh thật thì cắt bbox
      của block ảnh (`page.get_images` / `get_image_rects`) → endpoint `pages/{n}/figures/{k}.png`.
- [ ] `heading_path` của chunk vẫn dính `**` markdown (lỗi chunker cũ, ghi ở web-ui-v2/backend-todo.md) → chip
      nguồn trong panel chat hiện "**Attention Is All You Need**".

## Chạy nền / hiệu năng

- [ ] Tóm tắt chạy đồng bộ 30–120 s/paper trong request (timeout 180 s). Nếu chọn hướng B ở
      `decisions-open.md` #4 thì cần task worker + cột `summary_status`.
- [ ] Cache ảnh trang ở `data/documents/<id>/pages/` không có dọn dẹp: 15 trang × 2 dpi ≈ 5 MB/paper.
      Gắn vào `cleanup_worker` (xoá khi document bị xoá đã có vì nằm trong thư mục document).
- [ ] `GET /research/projects/{id}` trả toàn bộ papers + edges một lần; > 200 paper nên phân trang.

## Test còn thiếu

- [ ] Lớp DB của `ResearchService` (CRUD, cascade khi xoá project/document, UNIQUE dedup khi thả lại cùng PDF)
      — mới kiểm bằng tay trên API thật 11/10, chưa có test tự động với Postgres.
- [ ] `/research/chat` end-to-end với `mock_ollama` (hiện chỉ test router với dịch vụ giả).
- [ ] `test_postgres_cleanup_lifecycle::test_postgres_log_and_ocr_retention_execute_only_due_rows` đỏ khi chạy
      cả bộ, xanh khi chạy riêng (11/10) — nhạy thứ tự/thời gian, không liên quan code mới; chưa truy.
