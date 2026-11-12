# Dự đoán trước khi chạy cả bộ (12/11/2026)

Viết trước khi chạy, chưa thấy kết quả.

Cơ sở so sánh: lần chạy đủ bộ trên `4936223` ngày 11/11 cho backend 2.341 đạt, 14 xfail, 0 bỏ qua; gốc 250 đạt, 1 bỏ qua.
Từ `4936223` tới `b0f146d` chỉ thêm một mục sổ đo, không đổi code.

Thay đổi lần này:
- Thêm `backend/tests/test_local_files.py`: 60 ca. Khi chạy nhẹ có 59 đạt, 1 bỏ qua; bài bỏ qua là symlink, vì máy này không cho tạo symlink nếu không có quyền.
- Sửa `agent_service.py`, `chat_service.py`, `routers/chat.py`, `settings.py`, `main.py`. Khi cờ tắt, các sửa đổi này không được làm đổi kết quả của test nào đang có.

Dự đoán:

| Bộ | Đạt | xfail | Bỏ qua | Hỏng |
|---|---|---|---|---|
| Backend đủ bộ | 2.400 | 14 | 1 | 0 |
| Gốc đủ bộ | 250 | 0 | 1 | 0 |

Nếu backend lệch số này thì đó là một phát hiện, phải tìm nguyên nhân trước khi commit.
