# 07 — Agent Eval v0: ghi truy xuất thật, chạy baseline 3 lần (M2)

Status: phần code + 12 bài mới (v0.1) xong trên `wip/07-agent-eval-baseline`; chờ fable duyệt 12 bài, rồi chờ 11 xong mới ghi truy xuất + chạy baseline
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

**27/10 — Nhân viên của Ún 3: phần code, chưa chạy gì trên GPU, Ollama hay API lab.**

- **Phát hiện trước khi viết code:** 20 bài tài liệu của v0 hỏi về tài liệu giả, không có trong
  corpus lab. Ghi truy xuất thật cho các câu đó sẽ làm mất đáp án. opus chốt phương án (C): giữ 8 bài
  bẫy viết tay, viết **mới** 12 bài tra cứu trên tài liệu thật của lab (doc-21 đến doc-32), không lấy
  câu từ `rag_multidoc_eval.jsonl`. Dataset nâng lên `agent-eval-v0.1`, sha256 `4e1c192b…`.
- Corpus lab (DB `local_ai_core_lab_20260821`, đọc chỉ-đọc 27/10): 5 tài liệu đang dùng với 27
  đoạn. Đó là `backup_restore.md`, `current_architecture.md`, `p3_progress.md`,
  `versioned_ingestion.md` và `xuong_in_anh_duong.txt` (hư cấu). Ngoài ra có 28 bản ghi `trap_*`
  đã xoá. 12 bài mới gồm 9 bài trên xưởng in, 2 bài trên `p3_progress.md`, 1 bài trên
  `versioned_ingestion.md` (hỏi tiếng Việt, tài liệu tiếng Anh).
- **Agent chỉ đọc 400 ký tự đầu của mỗi đoạn** (`agent_service._dump` → `_clip(content, 400)`).
  Cả 12 bài đều có đáp án hoặc `evidence` trong 400 ký tự đầu của đoạn nguồn, đã kiểm trên nội dung
  đọc từ DB lab. Công cụ ghi cũng kiểm đúng phần 400 ký tự này.
- **Ghi lại cho ticket 10:** 400 ký tự đầu của `backup_restore.md` đoạn 0–1 giống nhau, và của
  `p3_progress.md` đoạn 0–2 cũng giống nhau (cùng phần mở đầu tài liệu). Khi nhận các đoạn đó, agent
  chỉ thấy lại phần mở đầu; nội dung riêng của từng đoạn không bao giờ tới được model.
- top_k: `rag.max_context_chunks` chỉ đọc từ `models.yaml`, không có biến môi trường đổi được. Vì
  vậy bản ghi có tối đa 5 đoạn, agent xin 6 đến 8 đoạn sẽ chỉ nhận 5. Đã ghi vào README và
  `retrieval_manifest.json`.
- Code:
  - `agent_eval.py --probe [--env-file]`: dùng `ProductionProbes` thật, bật cả khi
    `MODEL_STARTUP_PROBES=false`. Từ chối chạy (exit 2) nếu `general` không phải con trỏ đã xác
    minh. Manifest ghi `probed`, `registry_fallback`, `env_file`.
  - `agent_eval_record_retrieval.py`: gọi `/rag/search` của API lab (cổng 8100) một lần cho mỗi bài
    `pending`, ghi `chunks` cùng `retrieval_manifest.json`. Một truy vấn hỏng là không ghi gì cả.
  - Runner từ chối chạy bài `pending`. Summary có thêm `by_retrieval_source`.
- Test: 63 passed (`test_agent_eval_record.py` + `test_agent_eval.py` + `test_model_router.py`),
  không cần stack, GPU hay Postgres.
- Chưa làm: ghi truy xuất, baseline 3 lần ở t0+seed và 1 lần ở t0.4, chấm tay ≥5 bài, RESULTS.md.
  Tất cả chờ fable duyệt 12 bài và opus báo 11 xong.
