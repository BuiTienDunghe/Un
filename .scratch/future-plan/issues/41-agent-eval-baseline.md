# 41 — Chấm lại Agent Eval trên main

Status: opus làm
Type: task
Blocked by: —

Bản chất: sau đợt 28–40 chưa có điểm nào còn hiệu lực. Chấm toàn bộ, mỗi bài chạy như thể một mình, để có mốc so cho
mọi việc sau.

Cách làm: worktree riêng từ main, `agent_eval.py --unload-between-tasks`, cùng cấu hình mốc v0.8. Lưu vào
`data/evaluation/results/kept/`, thêm vào bảng điểm. Xong khi có số, danh sách bài hỏng và nguyên nhân từng nhóm.
