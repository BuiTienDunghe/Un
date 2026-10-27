# 24 — Đo harness bằng benchmark uy tín có điểm công bố

Status: đang khảo sát (agent phụ, nguồn chính thống)
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
