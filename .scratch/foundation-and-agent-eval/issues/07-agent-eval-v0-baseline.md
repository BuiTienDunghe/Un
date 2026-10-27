# 07 — Agent Eval v0: ghi truy xuất thật, chạy baseline 3 lần (M2)

Status: chờ
Type: task
Blocked by: 06; cần stack Postgres + Qdrant của Ún và Ollama

## Việc

1. Ghi kết quả truy xuất thật trên corpus lab cho 20 bài tài liệu một lần, theo định dạng fixture
   của 06. Ghi lại cấu hình retrieval vào manifest của bản ghi.
2. Baseline: 3 lần ở nhiệt độ 0 + seed, 1 lần ở 0.4. So theo từng bài; báo cáo dao động theo bài.
3. Chấm tay ít nhất 5 bài để đối chiếu bộ chấm tự động.
4. Báo cáo ghi rõ: "baseline thăm dò, chưa đủ chứng minh thống kê". Kết quả nào được trích dẫn thì
   promote vào `data/evaluation/results/kept/` và thêm một dòng vào `docs/RESULTS.md`.

5. Chạy với registry đã probe (`manifest.verified: true`) và cấu hình thật của máy, không dùng
   DATABASE_URL giữ chỗ như lần chạy thử của 06 — baseline phải gắn được với cấu hình đang ship.

## Comments
