# 04 — Một cơ chế bật bot, panel hết 401 (M1d)

Status: đã gộp vào main (27/10), fable 5.1 duyệt
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
- 27/10 (opus 5.5, chốt): B3 — giữ hai cơ chế nhưng thấy nhau và không chạy trùng. Backend tự quét
  psutil, **không** import `discord_bot.control` (giữ bất biến bot↔backend chỉ qua HTTP); một test ở
  `tests/` gốc khẳng định hai bộ nhận biết phân loại giống nhau. Bộ lọc docker của panel lọc thêm
  label project. 401: c1, env thắng `.env` như server. Compose: 10 biến chuyển sang dạng chỉ tên,
  PERSISTENT giữ `:-true` có comment (d1). `.bat`: e2 (`-m tools.discord_bot_control`). Lệch cấu
  hình giữa bot trên máy (đọc cả `.env`) và bot container (13 biến): để chủ dự án quyết (B1 chỉ
  compose / B2 chỉ tiến trình trên máy).

### 27/10 — Nhân viên của Ún 1: đã làm

Bản chất: trước đây bảng điều khiển trên máy và dashboard web giống hai người gác cửa không nhìn
thấy nhau. Một người có thể báo "không có ai" trong khi người kia vừa cho bot vào, và thế là hai
bot cùng trả lời mỗi tin nhắn. Giờ cả hai cùng nhìn thấy cả hai loại bot, và không bên nào chịu bật
thêm một con thứ hai. Bảng điều khiển cũng gửi đúng khoá mà server đòi, nên hết bị từ chối.

| Phần | Đã làm |
|---|---|
| Dashboard thấy bot trên máy | `bot_control_service.py`: `host_bot_pids()` tự quét psutil, không import bot. `status()` giữ nguyên giá trị `state`, thêm `runner` = host / docker / host+docker |
| Không chạy trùng | `start()` từ chối khi đã có bot trên máy; `stop()` từ chối khi chỉ có bot trên máy. Router trả 409 `BOT_RUNNING_ON_HOST` |
| Giao diện | `bot.js` (điều phối cho phép): ghi "trên máy" / "docker"; hai bot cùng chạy thì chấm đỏ kèm câu cảnh báo; bot trên máy thì chỉ còn nút "Kiểm tra lại" |
| Panel lọc docker theo project | `compose_project_name()` theo đúng thứ tự của compose (env, rồi `.env`, rồi tên thư mục đã chuẩn hoá), đối chiếu với `docker compose config` |
| 401 | `_backend_headers()`: biến môi trường có mặt thì thắng `.env`, kể cả khi rỗng, đúng như pydantic-settings (đã đo). Comment ghi rõ thứ tự này cố ý khác `_backend_base_url` |
| Compose | 10 biến chuyển sang dạng chỉ tên; PERSISTENT giữ `:-true` kèm comment. Bài test mới ghi tên ngoại lệ tường minh. Test của 03 chỉ quét các trường `Settings`, nên trước đây không thấy service bot |
| `.bat` | `pythonw -m tools.discord_bot_control` từ gốc repo |

| Kiểm | Kết quả |
|---|---|
| Bộ test ở gốc (bot + tools, cùng bài chống lệch mới và 5 bài mới) | 71 xanh |
| Bài chống lệch, khi cố tình bỏ cách xử lý dễ dãi với cwd ở phía backend | đỏ ở PID 12, 13 |
| Bài 401, khi bỏ `headers=` | 3 bài đỏ |
| Test compose của bot, chạy trên khối cũ | đỏ, liệt kê đủ 10 biến |
| `docker compose --profile discord config discord-bot` | dựng được; biến chuyển tiếp lấy từ `.env`, thiếu thì `null` |
| `.venv` cũ (bản cài editable trỏ vào chỗ đã xoá) | chạy dạng file thì `No module named 'discord_bot'`; `-m` từ gốc thì import được |
| `node --check bot.js` | qua |
| DB test: `test_bot_control_and_timeseries` (4 bài mới, cùng assert trạng thái đã đổi), `test_dashboard_api`, `test_api_key_auth`, `test_compose_defaults`, 18:24 | 79 xanh |

Chưa kiểm: mở panel thật bằng `.bat` (cần màn hình); bật hay tắt bot thật (cần token và Discord);
giao diện trên trình duyệt.

Để chủ dự án quyết sau: hai kiểu bot vẫn chạy hai bộ cấu hình khác nhau. Bot trên máy đọc toàn bộ
`.env`; bot container chỉ nhận 13 biến trong `docker-compose.yml`. Hai hướng gộp là B1 (chỉ dùng
compose) hoặc B2 (chỉ dùng tiến trình trên máy); ưu và nhược ghi ở tin nhắn phân tích ngày 27/10.
