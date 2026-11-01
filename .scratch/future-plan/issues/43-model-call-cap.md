# 43 — Trần số lần gọi model mỗi lượt

Status: mở
Type: task
Blocked by: —

Bản chất: `README.en.md` luật 5 hứa ngân sách cố định, nhưng chưa có gì chặn ngoại lệ thứ tư. Thêm kiểm soát để lời hứa
do code giữ.

Việc: đếm lần gọi model sinh trong một lượt ở đường chat, RAG, agent; test đỏ khi vượt trần suy từ `max_steps` + các ngoại
lệ đã nêu. Không đổi hành vi hiện tại: mọi lượt hợp lệ vẫn chạy như cũ. Trần vượt khi chạy thật thì ghi vết, chọn chặn
hay chỉ ghi và nêu lý do. Xong khi cố tình thêm một lần gọi thì test đỏ, và README nêu đúng cơ chế.
