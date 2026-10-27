# 07 — Agent Eval v0: ghi truy xuất thật, chạy baseline 3 lần (M2)

Status: đã giao — Nhân viên của Ún 3 (phần chạy GPU chờ ticket 11 xong)
Type: task
Blocked by: 06 (đã gộp); phần chạy GPU chờ 11 (11 đang đo p50 /rag/search, mà 09 dùng số đó làm ngưỡng)

## Việc

1. Ghi kết quả truy xuất thật trên corpus lab cho 20 bài tài liệu một lần, theo định dạng fixture
   của 06. Ghi lại cấu hình retrieval vào manifest của bản ghi.
2. Baseline: 3 lần ở nhiệt độ 0 + seed, 1 lần ở 0.4. So theo từng bài; báo cáo dao động theo bài.
3. Chấm tay ít nhất 5 bài để đối chiếu bộ chấm tự động.
4. Báo cáo ghi rõ: "baseline thăm dò, chưa đủ chứng minh thống kê". Kết quả nào được trích dẫn thì
   promote vào `data/evaluation/results/kept/` và thêm một dòng vào `docs/RESULTS.md`.
5. Chạy với registry đã probe (`manifest.verified: true`) và cấu hình thật của máy, không dùng
   DATABASE_URL giữ chỗ như lần chạy thử của 06 — baseline phải gắn được với cấu hình đang ship.
6. Chạy với `PYTHONUTF8=1` (runner in tiếng Việt; console cp1252 vỡ ngay cả `--help` — fable kiểm 27/10).

## Comments
- 27/10 (opus 5.5): 20 bài tài liệu của v0 hỏi về tài liệu **giả**, không có trong corpus lab, nên
  không ghi truy xuất thật được cho chúng. Chốt cách (C): giữ viết tay cho 8 bài bẫy (doc-04, 10,
  11, 12, 17, 18, 19, 20); khoảng 12 bài tra cứu thường viết **mới** trên tài liệu thật của corpus
  lab, không lấy từ `rag_multidoc_eval.jsonl` (truy xuất đã được chỉnh theo bộ đó). Summary tách
  theo `retrieval_source`. Dataset nâng lên `agent-eval-v0.1`. Fable duyệt 12 bài mới trước khi ghi.
  top_k: nếu ghi được với 8 thì ghi 8, không thì 5 và ghi khác biệt vào manifest. Không chọn (A),
  nạp tài liệu giả vào corpus mà 09 dùng; không chọn (D), bỏ nhiễu truy xuất thật.
