# 30 — Lệnh /docs kiểm server

Status: xong code — gộp main (30/10); chưa thử trên Discord thật, chưa push
Type: bug
Blocked by: —

## Vì sao

`/docs` của bot tra thẳng kho tài liệu mà không xem người gõ ở server nào. Ô chọn tài liệu còn hiện tên tệp. Lối `@Ún`
đã có danh sách server được phép (`DISCORD_AGENT_TOOLS_GUILD_ALLOWLIST`), lối này thì chưa. Ticket 29 ghi lại lỗi; fable
xác nhận. Trong cơ sở dữ liệu thật có 2 server từng dùng bot.

## Việc

1. Bot đọc cùng danh sách đó. Quy ước giữ như backend: `*` là mọi server, còn lại là danh sách cách nhau bằng dấu phẩy,
   trống hoặc sai thì không server nào được.
2. Server ngoài danh sách: `/docs` từ chối trước khi tra, chỉ người gõ thấy; ô chọn tài liệu trả rỗng.
3. Tin nhắn riêng với bot: từ chối luôn, kể cả khi danh sách là `*`, vì không có server để kiểm.
4. Khi bot khởi động, ghi vào log số server được phép, để biết danh sách đã điền hay chưa mà không phải mở `.env`.
5. Bot chạy qua compose phải nhận được biến này. Tài liệu ghi rõ danh sách giờ chặn cả `/docs`.

## Nghiệm thu

- Mỗi hành vi có bài kiểm tra, và bài đó đỏ khi gỡ phần sửa.
- Server trong danh sách chạy `/docs` như cũ.

## Không làm

Kiểm ở backend (cách B). `/rag/chat` và danh sách tài liệu vẫn mở cho ai có khoá API; web không đổi. Tách tài liệu theo
người là ticket 21.

## Comments
- 30/10 (opus 5.5): commit `09e2658`, phiên duyệt độc lập GỘP ĐƯỢC (`reviews/wip-30-docs-guild-gate-09e2658.md`). Gỡ từng phần trong 8 phần của bản sửa thì bài kiểm tra đỏ.
- Ghi nhận, không chặn:
  - `DISCORD_AGENT_TOOLS_ENABLED=false` không tắt `/docs`; đã ghi trong `.env.example`.
  - `followup.send(ephemeral=True)` sau defer công khai (`discord_bot/main.py:622, 634`) có thể đang hiện công khai. Chuyện cũ, chưa kiểm trên Discord thật.
  - `control.py:59-75` không cắt chú thích cùng dòng trong `.env`, nên `=111 # nhà` làm bot chạy từ panel tắt `/docs` còn backend vẫn nhận `111`. Lỗi có sẵn.
