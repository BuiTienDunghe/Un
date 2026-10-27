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

- 27/10 (từ Nhân viên 2, ticket 03): service `discord-bot` trong `docker-compose.yml` có 14 mặc định
  trùng với mặc định trong `discord_bot/main.py` (không phải Settings). Xử lý cùng ticket này, cùng
  quy tắc: một nơi giữ mặc định.
- 27/10 (từ Nhân viên 1, ticket 02): `discord-bot-control.bat` chạy `tools\discord_bot_control.py`
  bằng `pythonw`. Trên một `.venv` cũ chưa chạy launcher mới lần nào, bảng điều khiển sẽ không hiện
  mà cũng không báo lỗi (hết hack sys.path, `import discord_bot` hỏng). Thêm vào `.bat` một bước kiểm
  import; thiếu thì báo "chạy run-local-ai-core.bat trước".
