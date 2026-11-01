# 48 — Nhắc việc, Ún tự nhắn trước

Status: mở
Type: task
Blocked by: —

Bản chất: hiện Ún chỉ trả lời khi được hỏi. Thêm việc hẹn giờ do chính người dùng tạo, tới giờ bot gửi tin.

Việc: bảng nhắc việc có migration kèm downgrade; bot có vòng lặp nền gọi backend qua HTTP; nhắc gửi đúng kênh và người đã tạo,
không @everyone; huỷ được; lỡ giờ khi máy tắt thì xử lý có chủ đích và ghi rõ; tôn trọng danh sách server cho phép. Mặc định tắt.
Không có việc tự phát: Ún chỉ gửi điều người dùng đã hẹn. Công cụ tạo nhắc cho agent dùng lời của chính người dùng, như `remember`.
