# 48 — Nhắc việc, Ún tự nhắn trước

Status: mở
Type: task
Blocked by: —

Bản chất: hiện Ún chỉ trả lời khi được hỏi. Thêm việc hẹn giờ do chính người dùng tạo, tới giờ bot gửi tin.

Việc: bảng nhắc việc có migration kèm downgrade; bot có vòng lặp nền gọi backend qua HTTP; nhắc gửi đúng kênh và người đã tạo,
không @everyone; huỷ được; lỡ giờ khi máy tắt thì xử lý có chủ đích và ghi rõ; tôn trọng danh sách server cho phép. Mặc định tắt.
Không có việc tự phát: Ún chỉ gửi điều người dùng đã hẹn. Công cụ tạo nhắc cho agent dùng lời của chính người dùng, như `remember`.

## Đã làm (nhánh claude/48-reminders-ca5159)

Bảng `discord_reminders` (migration `20261101_37`, cộng thêm, có downgrade). `backend/app/discord/reminders.py` giữ mọi luật;
`remind_tool.py` là công cụ của agent (cổng như `remember`: người dùng tự dặn, có nêu giờ, nội dung là lời của họ);
`routers/reminders.py` là cửa HTTP cho bot; `discord_bot/reminders.py` chỉ gửi. Cờ `DISCORD_REMINDERS_ENABLED` (mặc định tắt) ở cả hai phía.

Quyết định đã chọn, đổi được:
- Lỡ giờ: trễ dưới 5 phút gửi như thường; 5 phút đến 24 giờ gửi kèm ghi chú "Trễ … hẹn lúc …"; từ 24 giờ trở lên đánh dấu `missed`, không gửi, `/reminders list` còn hiện thêm 1 ngày.
- Gửi hỏng: thử lại cách 1 phút, tối đa 3 lần; kênh xoá, mất quyền, sai server, server rời danh sách thì bỏ ngay (`failed`).
- Giao ít nhất một lần: bot giữ phiếu nhận trong bộ nhớ và nộp lại mỗi nhịp tới 1 giờ, nên backend khởi động lại không gây gửi đôi; chỉ khi chính bot dừng giữa lúc gửi và lúc backend nhận phiếu thì sau 10 phút nhắc được gửi lại.
- Quên: `forget_member` xoá mọi lời nhắc của người đó (bước 6b); bảng có khoá ngoại tới lượt hội thoại (xoá theo), không lưu tên hiển thị.
- Cổng đọc lời người dùng: câu nhờ lịch sự ("có thể … không", "được không") tính là nhờ; câu trả lời giờ sau khi Ún hỏi lại được đọc cùng yêu cầu ngay trước đó (cùng người, trong 15 phút) nhưng chính câu trả lời phải có mốc giờ.
- Giới hạn: 500 ký tự, 20 lời nhắc chờ mỗi người mỗi server, 3 lời mỗi tin nhắn, từ 30 giây đến 90 ngày.
- Tạo chỉ qua chat với Ún; `/reminders list|cancel` để xem và huỷ.
