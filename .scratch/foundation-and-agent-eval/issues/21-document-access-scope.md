# 21 — Tài liệu không có chủ: agent ở web đọc được mọi tài liệu, kể cả PDF của dự án Nghiên cứu người khác

Status: để sau — chủ dự án chọn hoãn (30/10)
Type: research
Blocked by: —

## Vì sao

Nhân viên 1 phát hiện khi thiết kế ticket 20 #1 (28/10), opus kiểm lại: bảng `documents` không có cột chủ
sở hữu; trong `postgres/models.py` chỉ `research_projects` có `owner_user_id` (dòng 1206, chú thích "khi bật
[tài khoản], member chỉ thấy dự án của mình"). `search_documents` tra toàn bộ corpus đã index
(`repositories.py:205` `active_versions` không lọc). Nếu chế độ tài khoản bật và có nhiều thành viên, thì qua
agent (và có lẽ qua `/rag`), thành viên này đọc được PDF thuộc dự án Nghiên cứu của thành viên khác — trong khi
màn Nghiên cứu ẩn dự án đó. Có từ trước, không do ticket 20.

## Câu hỏi cho chủ dự án

Kho tài liệu là **dùng chung** cho mọi thành viên (khi đó ghi rõ trong docs, và PDF Nghiên cứu là ngoại lệ cần
xét), hay **theo người** (khi đó cần cột chủ + lọc ở mọi đường tra: agent, `/rag`, Nghiên cứu)?

## Comments
- 30/10 00:30 (opus 5.5): chủ dự án chọn **để sau**: chỉ có hại khi có nhiều tài khoản thật. Ticket giữ nguyên, chưa ai làm.
