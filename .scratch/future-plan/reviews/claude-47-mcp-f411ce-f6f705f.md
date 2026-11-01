CẦN SỬA

# Duyệt `claude/47-mcp-f411ce` (f6f705f) — MCP client, cắm công cụ ngoài

Duyệt độc lập theo `git diff main...claude/47-mcp-f411ce`, mở code xung quanh, chạy test và hai kịch bản
thử riêng (server giả). Không sửa code. Số dòng lấy từ `backend/app/services/mcp_tools.py` trong worktree.

## Bản chất

Ún chạy một chương trình lạ làm "người giúp việc", nói chuyện với nó qua hai ống (ghi vào / đọc ra). Module hứa
ba điều: chương trình hỏng thì chỉ mất công cụ của nó, không mất lượt; không bao giờ treo; và lời nó viết chỉ là
dữ liệu. Hai điều đầu có lỗ: một câu trả lời sai khuôn lúc khởi động làm cả backend không lên được, và nếu
chương trình còn sống nhưng ngừng đọc ống vào thì Ún đứng chờ vô hạn, kéo theo mọi lượt khác dùng công cụ đó và
cả lúc tắt máy. Phần còn lại (mặc định tắt, allowlist, môi trường trống, cắt kết quả) đúng như hứa.

## Lỗi chặn

### 1. Schema sai khuôn từ server làm backend không khởi động — mức: cao

`schema_for` (mcp_tools.py:227, 232) gọi `.items()` trên `inputSchema.properties` và lặp qua `required` mà
không kiểm kiểu. `register` (mcp_tools.py:310) gọi nó ngoài mọi `try`; `except ValueError` ở :313 chỉ bọc
`registry.register`. main.py:265 gọi `register` trong lifespan, không bọc.

Kịch bản (đã chạy, server giả trả `"properties": [1]`): `register` ném `AttributeError` → lifespan hỏng →
backend không lên. `"properties": "q"` cũng vậy; `"required": 7` ném `TypeError`. Trái với docstring
"misconfigured ... is logged and left out" và CHANGELOG "server không chạy được ... lượt vẫn trả lời".
Sửa: kiểm `isinstance` cho `properties`/`required` (như đã làm với `inputSchema`), hoặc bọc `schema_for` trong
cùng `try` với log cảnh báo.

### 2. Ghi vào ống của server còn sống nhưng ngừng đọc → treo vô hạn, giữ khoá — mức: cao

`_request` (mcp_tools.py:141) gọi `_send` **trước** khi bật `Timer` (:146); `_send` (:132) `write` + `flush`
không có hạn. Khi ống đầy (server không đọc stdin) thì `write` chặn mãi, và `_lock` (:181) vẫn bị giữ.
Không có trần kích thước cho `arguments` chuyển tiếp (:262), nên một tham số lớn từ model đủ làm đầy ống.

Kịch bản (đã chạy 3 lần, mỗi lần bọc trong `timeout` ngoài khác nhau): server giả trả lời lần gọi 1 rồi
`sleep` 600 s không đọc stdin; lần gọi 2 với tham số lớn hơn bộ đệm ống:

| Bước | Đo được |
|---|---|
| Lần gọi 2 sau 10 s | vẫn chặn, `call_timeout_seconds: 2` không có tác dụng (timer chưa bật) |
| `close()` (chính là việc lifespan làm lúc tắt) | chặn ở `stdin.close()` (:199) cho tới khi bị giết từ ngoài |
| Thời điểm thoát | 57,6 / 117,5 / 297,6 s — luôn ≈ 2,5 s trước hạn của `timeout` bao ngoài 60 / 120 / 300 s |

Tức là trong code không có đường thoát: ống chỉ vỡ khi tiến trình bị giết từ bên ngoài. Hệ quả: lượt agent
đó treo vô hạn thay vì 90 s; mọi lượt khác gọi công cụ của server này xếp hàng sau khoá; tắt backend cũng
treo. Sửa: ghi trên luồng riêng có hạn (hoặc ghi không chặn + hạn), và/hoặc cắt `arguments` theo một trần
ký tự; `close()` nên terminate trước rồi mới đóng stdin.

## Không chặn, có kịch bản

- **`call_timeout_seconds` không có trần, và không nhìn ngân sách lượt** (mcp_tools.py:81). `result_max_chars`
  bị kẹp 200–6000 nhưng `call_timeout` chỉ có sàn 1,0 — `100000` được nhận (đã thử). Với mặc định: một lần gọi
  hỏng = `START_TIMEOUT` 10 s + `call_timeout` 15 s + terminate 2 s ≈ 27 s trong lượt 90 s. `deadline.request_timeout`
  có sẵn mà không dùng. Đề nghị kẹp trần (ví dụ 30 s) và lấy `min` với thời gian còn lại của lượt.
- **Đọc không giới hạn** (mcp_tools.py:126–127, 92). Một dòng không có xuống dòng, hoặc server xả notification liên
  tục giữa các lần gọi, làm `Queue` (không `maxsize`, không ai rút giữa hai lần gọi) và bộ nhớ lớn vô hạn
  trong suốt vòng đời process.
- **Chỉ cắt `description`** (mcp_tools.py:230). `enum`, `title`, `default`, `examples`, `items`/`properties` lồng
  nhau đi thẳng tới model không cắt — mục tiêu "chỗ giấu lệnh" của chính docstring chưa kín. Kịch bản: server đặt
  10 kB chữ vào `prop["title"]`.
- **Tên công cụ trùng sau khi chuẩn hoá** (mcp_tools.py:216): `-`→`_` và cắt 64 ký tự khiến hai công cụ hợp lệ
  thành một tên; `registry.register` ném `ValueError`, công cụ thứ hai bị bỏ lặng (chỉ có log).
- **Tiến trình con cấp hai trên Windows**: `terminate()`/`kill()` không chạm tới cháu; command là `cmd /c ...` hay
  `npx` thì server thật vẫn chạy sau `close()` (đọc code, chưa chạy thử).
- **Phạm vi lời hứa "không có khoá API"**: đúng với biến môi trường (`_BASE_ENV`, đã có test). Nhưng `Popen` không
  đặt `cwd`, server chạy cùng thư mục và cùng user với backend nên vẫn đọc được tệp trên đĩa. CHANGELOG nên nói rõ
  đó là rào về môi trường, không phải về đĩa.

## Đã kiểm và đúng

| Điểm | Kết quả |
|---|---|
| Mặc định tắt = không có subprocess | `main.py:262` chỉ import/`register` khi `agent_mcp_enabled`; `register([])` trả rỗng không spawn. |
| Allowlist | Runner gắn cố định tên trong `allowed_tools`; model chỉ thấy tên `mcp_<server>_<tool>`; tên ngoài danh sách → `UNKNOWN_TOOL`. |
| Môi trường con | Chỉ `_BASE_ENV` + `env` khai; test với `ANTHROPIC_API_KEY` giả xác nhận không rò. |
| Treo trên stdout / chết giữa lượt | Timer + `close()` → `McpError` → `TOOL_FAILED`, lượt vẫn trả lời (test xanh). |
| Cắt kết quả | Chữ cắt theo `result_chars`, JSON bao quanh ≤ +400, vẫn là JSON hợp lệ; cùng mức 6000 với `web_tools`. |
| Đồng thời | `_lock` tuần tự hoá mọi lệnh trên một server; `_next_id` dưới khoá. |
| Shell injection | `Popen(list)` không `shell=True`. |

Test đã chạy (không DB, Ollama tắt tiếng, CUDA ẩn): `test_agent_mcp_tools.py` 21/21 xanh; hai kịch bản thử
riêng ở trên (schema sai khuôn, ống vào đầy) là script ngoài repo.
