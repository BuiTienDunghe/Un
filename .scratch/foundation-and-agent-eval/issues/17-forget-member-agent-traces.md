# 17 — `forget_member` phải xoá cả trích đoạn của thành viên trong agent_traces

Status: chờ — sau ticket 16 (Nhân viên của Ún 1)
Type: task
Blocked by: 16

## Vì sao

Nhân viên 1 phát hiện khi thiết kế ticket 16 (27/10): `backend/scripts/forget_member.py` không xoá
`agent_traces`, trong khi trace của hội thoại Discord chứa trích đoạn tin nhắn của thành viên (kết quả
`search_history`: ai nói, lúc nào, nội dung). Người dùng yêu cầu "quên tôi" thì nội dung của họ vẫn còn
trong trace của hội thoại khác cho tới khi hội thoại đó bị xoá. Bảng rút gọn của ticket 16 không có nội
dung, nên không làm khoảng hở này rộng thêm.

## Việc

1. Đọc `forget_member.py` và tìm mọi nơi nội dung của một thành viên có thể nằm: `agent_traces.content`,
   `agent_traces.arguments` (`author_id`), và mọi bảng khác chưa được quét.
2. Chọn cách: xoá hẳn bước trace chứa nội dung của thành viên, hay thay nội dung đó bằng một dấu
   "[đã xoá theo yêu cầu]". Ghi lựa chọn vào Comments trước khi code.
3. Test Postgres: tạo trace có trích đoạn của thành viên A và B; quên A; trace không còn chuỗi nào của A,
   phần của B còn nguyên.

## Comments
