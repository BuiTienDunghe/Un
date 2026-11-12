# Dự đoán trước khi chạy (đợt 2 ghi tệp, 12/11/2026)

Viết trước khi chạy, chưa thấy kết quả.

Cơ sở: cả bộ trên đợt 1 (`4cb3ba2` khi chưa commit) ra backend 2.400 đạt, 14 xfail, 1 bỏ qua; gốc 250 đạt, 1 bỏ qua.

Đợt 2 thêm `backend/tests/test_local_file_writes.py`: 32 hàm test, 54 ca tính cả parametrize (đếm bằng tay).
Không thêm hay bỏ test nào ở tệp khác.

| Bộ | Nếu mọi thứ đúng | Dự đoán thật |
|---|---|---|
| Backend đủ bộ | 2.454 đạt, 14 xfail, 1 bỏ qua | **Lần chạy đầu có vài ca mới hỏng.** Code và test đợt 2 chưa từng được chạy, chỉ được đọc qua hai vòng duyệt. Các test cũ không đổi |
| Gốc đủ bộ | 250 đạt, 1 bỏ qua | Như bên trái |

Thứ tự chạy:
1. Chạy nhanh tệp test mới và `test_frontend.py` (không database), để bắt lỗi sớm.
2. Sửa nếu đỏ.
3. Chạy cả bộ có database.

Lần nào cũng ghi vào sổ đo.
