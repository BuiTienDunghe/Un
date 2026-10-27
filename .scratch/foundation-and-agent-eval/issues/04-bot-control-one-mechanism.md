# 04 — Một cơ chế bật bot, panel hết 401 (M1d)

Status: chờ
Type: task
Blocked by: 02 (cùng đụng `tools/discord_bot_control.py`)

## Vì sao

Panel tkinter bật bot bằng một tiến trình thường (`discord_bot/control.py:572`), trong khi dashboard
web chỉ hỏi `docker compose ps` (`backend/app/services/bot_control_service.py:30`). Vì vậy dashboard
không thấy bot do panel bật. Ngoài ra panel gọi `/turns/cancel-open` mà không kèm `X-API-Key`, nên bị
401 khi máy có khoá (đã ghi nhận 13/09, `control.py` khoảng dòng 391 — cần kiểm lại).

## Việc

Liệt kê mọi cách bật/tắt bot (panel, dashboard, `run-discord-bot.bat`, compose) rồi chọn **một** cơ
chế làm nguồn sự thật cho trạng thái; nếu vẫn giữ hai cơ chế thì cả hai phải thấy được nhau. Viết
các lựa chọn vào Comments trước khi code. Sửa lỗi 401.

## Comments
