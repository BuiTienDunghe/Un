# 38 — Một cửa sổ cho cả hệ thống, decided nhả hết máy khi rảnh

Status: xong trên nhánh — chủ dự án chọn C và 3 (31/10)
Type: task
Blocked by: —
Liên quan: ticket 36.

## Bản chất

Mỗi việc nền từng có cửa sổ riêng và chỉ nói vào cửa sổ đó, nên đóng là mất dấu vết. Dịch vụ decided đã tự tắt sau 23:18 ngày 30/10 mà không ai biết vì sao. Decided khi "ngủ" cũng chỉ cất một phần.

## Quyết định

- Một tiến trình quản lý (`tools/supervisor.py`), chạy ngay trong cửa sổ launcher. Bot Discord không nằm trong đó: nó có bảng điều khiển riêng.
- Log gộp ra cửa sổ và tách tệp theo việc, theo ngày, 30 ngày, ở `data/logs/services/`.
- Tệp này giữ lâu hơn màn hình nên được che: giá trị trong `.env` có tên kết thúc bằng KEY, TOKEN, SECRET, PASSWORD; mật khẩu trong URL; chuỗi truy vấn ở dòng truy cập.
- Tắt thoát sạch (mã 0) thì không chạy lại, vì worker tự thoát khi cấu hình bảo không có việc. Hỏng thì chạy lại; 5 lần hỏng nhanh liên tiếp thì dừng và báo.
- Mọi việc nằm chung một job của Windows, nên tiến trình quản lý chết kiểu gì cũng kéo theo tất cả.
- Decided: tiến trình cửa không nạp thư viện model; model ở tiến trình con, thoát khi rảnh. Model không lên được trả 503, worker chờ; một tin làm model lỗi trả 500, tin đó vào hàng duyệt ở 0%.
- Worker decided chỉ in khi có việc hoặc khi trạng thái chờ đổi, để không làm ồn cửa sổ chung.

## Đo

Trước khi sửa, 31/10, câu tự viết, card rảnh, đã trừ 650 MiB nền:

| Trạng thái | Card | RAM |
|---|---|---|
| Thức | 4.621 MiB | 1.619 MiB |
| Ngủ kiểu cũ | 459 MiB | 1.584 MiB |
