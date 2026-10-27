# 24 — Đo harness bằng benchmark uy tín có điểm công bố

Status: đang làm — BFCL V4 phần offline, **cách A** (28/10 01:05): không tái lập Qwen3-8B; dựng venv + bộ chạy bài BFCL qua harness Ún; chỉ so trước/sau trên cùng thước
Type: research
Blocked by: —

## Vì sao

Chủ dự án (28/10 00:30): "mọi benchmark đều phải lấy từ nguồn uy tín và có điểm số được chứng nhận, khi đó số đo
mới có giá trị". Agent Eval (48 bài tự viết, dữ liệu giả) không so được với ai → giữ làm test hồi quy; khẳng định
chất lượng harness phải dùng benchmark có paper/leaderboard, và **tái lập một số đã công bố** cho model cùng cỡ
trước khi đo thay đổi của mình (cùng tinh thần H-pack: e5-large phải ra 0,6112 ± 0,02 trên VieQuAD).

## Khảo sát (đang làm)

Ứng viên: BFCL, τ-bench/τ²-bench, GAIA, AgentBench, StableToolBench, LongBench v2, RULER, HELMET, FRAMES, CRAG,
RAGTruth, MTEB (VieQuAD), VMLU, ... — tiêu chí: đo thứ harness quyết định (gọi công cụ, nhiều bước, đọc dài, RAG
trung thực), có leaderboard/điểm tham chiếu cho model 7–14B mở, chạy được offline với Ollama, có tiếng Việt hay không.

## Comments
- 28/10 00:50 (chủ dự án): "bắt đầu với BFCL V4 phần offline. Duyệt tải repo BFCL (gorilla) và model qwen3:8b vào
  Ollama để tái lập số đã công bố trước."
- 28/10 00:55 (opus 5.5): đã clone nông `ShishirPatil/gorilla` vào `C:\Users\dungbt06\tools\gorilla-6ea5797` (ngoài
  repo; commit 6ea5797, 2026-03-23; 224 MB; chưa chạy gì). Đang `ollama pull qwen3:8b`. Đọc README: chạy với server có
  sẵn bằng `--skip-server-setup` + `LOCAL_SERVER_ENDPOINT/PORT` hoặc `REMOTE_OPENAI_BASE_URL`; handler nội bộ của
  Qwen3-8B (FC) (`bfcl_eval/model_handler/local_inference/qwen_fc.py`, `model_config.py:948`) dựng prompt bằng
  tokenizer HF rồi gọi endpoint completions. Cần thêm, **chưa duyệt**: (1) venv riêng cho `bfcl_eval` (32 phụ thuộc
  trong `pyproject.toml`, gồm sentence-transformers → torch, faiss-cpu; bỏ phần vllm vì không chạy trên Windows);
  (2) tệp tokenizer của `Qwen/Qwen3-8B` từ HF (vài MB). Rủi ro tái lập: leaderboard chạy bf16 qua vLLM, Ollama
  `qwen3:8b` là Q4 và có thể áp template riêng ở endpoint completions — chênh phải ghi như một phép đo.
  GPU đang nhường cho dự án decision model tới 02:55; mọi lần chạy BFCL sau đó hoặc sáng mai.
- 28/10 01:00: `ollama pull qwen3:8b` xong — digest `500a1f067a9f`, 5,2 GB (bản mặc định của Ollama, lượng tử Q4);
  chưa nạp lên GPU (GPU đang nhường).
- 28/10 01:05 (chủ dự án, sau khi hỏi "nếu đã có thông số qwen3 8b rồi thì cần gì test lại nữa"): "Chọn A: bỏ tái
  lập Qwen3-8B. Dựng môi trường BFCL và bộ chạy bài BFCL qua harness của Ún, chỉ so trước/sau trên cùng thước."
  Hệ quả: không tải tokenizer Qwen3-8B; `qwen3:8b` (5,2 GB) còn trong Ollama, xoá khi chủ dự án muốn. Số BFCL của Ún
  **không** đặt cạnh bảng xếp hạng; chỉ dùng để so hai phiên bản harness trên cùng model, cùng cấu hình. Bộ chạy có
  sẵn của BFCL gửi bài thẳng cho model (đo model) → phải viết bộ chạy riêng cho bài đi qua harness Ún (đo harness).
