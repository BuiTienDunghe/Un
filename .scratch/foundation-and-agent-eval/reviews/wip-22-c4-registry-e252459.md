GỘP ĐƯỢC

# Duyệt wip/22-c4-registry e252459 (ticket 22 C4: registry cắm được, search_history sang gói) — fable 5.1, 28/10/2026

Đã kiểm: diff ec4d843..e252459 (18 tệp; đọc trọn `agent_service.py`, `app/discord/agent_tools.py`,
`__init__.py`, `agent_eval.py`, `test_discord_boundary.py`, bản đăng ký trước). Mọi lệnh chạy với
`env -u POSTGRES_TEST_URL -u REDIS_TEST_URL` và bộ giữ im Ollama/GPU; không chạy model.

## Ba phép kiểm độc lập của tôi

| Kiểm | Kết quả |
|---|---|
| `tools_sha256` của (core_tools + `agent_tools.register`) so với `AGENT_TOOLS` trên `main` | **bằng nhau**: `153209652c06…a75e500`; thứ tự 4 công cụ y hệt (10/15/20/30) |
| `declared()` so với `_DECLARED` trên `main` | bằng nhau (sha `a79b41b6…`) → `arguments_shape` và `tool_declared` trong bảng rút gọn (16) không đổi |
| Thân `SearchHistory.__call__` so với `AgentService._search_history` trên `main`, sau khi đổi `service.` → `self.` | trùng từng chữ (so bằng script, không bằng mắt) |

Và: 164 test xanh (registry 5 + boundary + register + 10 bộ agent/eval); shim đã xoá, không tệp nào còn nhắc
tên; không chỗ nào trong `backend`, `tests`, `tools`, `training` còn đọc `AGENT_TOOLS`/`TOOL_NAMES`/`_DECLARED`
hay truyền `history_service=`.

## Chỗ lệch so với thiết kế của tôi: không có `DEFAULT_REGISTRY` cấp module

NV1 đúng, thiết kế của tôi kém hơn. Một singleton bị gói Discord sửa lúc khởi động làm test phụ thuộc thứ
tự chạy (một test đăng ký công cụ thì agent của test sau thấy). `AgentService(registry=None)` tự tạo
`core_tools()` mới; muốn dùng chung thì truyền `registry=` rõ ràng — `main.py` một instance,
`register_services()` cắm vào đúng instance đó; eval dựng một registry cho cả lần chạy và đưa vào mọi
agent. Test `each_agent_has_its_own_registry_unless_one_is_shared_on_purpose` ghim đúng tính chất này. Chấp
nhận, và sửa dòng tương ứng trong `ticket22-design.md` khi opus gộp (tôi không sửa file thiết kế lúc này
để khỏi lệch với bản opus đang cầm).

## Các điểm khác

- `register(tool, order)` báo lỗi khi trùng tên: đúng — tránh một gói ghi đè công cụ lõi lặng lẽ.
- `schemas()/names()/declared()` tính mỗi lần gọi: đúng yêu cầu "đăng ký muộn vẫn thấy"; chi phí không đáng
  kể (4 mục).
- `SearchHistory` là callable giữ `history_service`: `AgentService` không còn thuộc tính Discord nào; nhánh
  "không guild / không backend" → `TOOL_UNAVAILABLE_HERE` giữ nguyên câu, nên hist-08..10 web không đổi.
- `agent_eval`: `tools_sha256` và schema của bộ chấm đọc từ chính registry mà agent chạy — đúng điều kiện tôi
  đặt ở thiết kế; D1 giữ (web vẫn thấy `search_history`), nên phép "trùng 48/48" của bản đăng ký là kiểm được.
- Boundary test bỏ hẳn "nợ `search_history`": agent/chat/rag nạp không kèm module Discord nào — tức luật
  của ticket 22 giờ đã đứng trọn, không còn ngoại lệ ngoài `main.py` và `discord_memory_constants`.
- Bản đăng ký trước: điều kiện "hash bằng nhau trước khi so" + dự đoán 48/48 trùng chữ + trace trùng — đúng
  hình dạng tôi yêu cầu ở C4; lần đo gom vào đợt chung.

## Việc cho opus

- Gộp được; C4 là thứ ticket 22 cần để tuyên bố "lõi không import gì từ Discord" — sau C4, C6 (docs) đã có
  phần (c59d319), chỉ cần cập nhật dòng về shim (NV1 đã làm trong C4).
- Khi gộp: `ticket22-design.md` mục "Hình dạng registry cho C4" sửa "DEFAULT_REGISTRY cấp module" thành
  "mỗi AgentService một registry riêng, chia sẻ khi truyền rõ" — một dòng, để thiết kế khớp code.
- Đợt đo chung: chạy A (main ngay trước C4) rồi C4 cùng buổi, lạnh, theo bản đăng ký.
