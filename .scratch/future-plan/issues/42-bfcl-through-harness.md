# 42 — Chạy BFCL qua harness

Status: mở
Type: task
Blocked by: —

Bản chất: cho bài gọi công cụ công khai đi qua đúng vòng lặp agent của Ún, để so hai phiên bản harness trên cùng thước.

Thiết kế ở `.scratch/foundation-and-agent-eval/ticket24-design.md`. Đã chọn: cắm ở vòng lặp, nhiệt độ 0, seed 42, 33 bài,
công cụ Ún bị thay bằng hàm của bài. Clone BFCL ở `C:\Users\dungbt06\tools\gorilla-6ea5797`, không sửa clone.

Việc: chỗ nối `registry=` trong `agent_service` có test; bộ chạy; script chấm đăng ký model lúc chạy; thử 1–2 bài nếu GPU
được opus cho phép. Không đặt số cạnh bảng xếp hạng. Xong khi chạy đủ 33 bài ra được tệp mà bộ chấm BFCL đọc được.
