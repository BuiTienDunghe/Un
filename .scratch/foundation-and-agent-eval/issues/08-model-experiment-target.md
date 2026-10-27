# 08 — Chọn mục tiêu cho thí nghiệm model (M3)

Status: đã giao — fable 5.1 của Ún
Type: research
Blocked by: —

## Vì sao

M3 chỉ làm **một** thí nghiệm model. Mục tiêu phải chọn từ các bộ đo thành phần, không chọn từ
Agent Eval: bộ trích trí nhớ không nằm trên đường đi của agent, còn reranker thì nằm khuất dưới
`search_documents`.

## Việc (chỉ đọc, không dùng GPU, không sửa code)

1. Gom số liệu sẵn có: `docs/RESULTS.md`, `data/evaluation/results/kept/`, `data/benchmarks/`,
   `backend/scripts/evaluate_rag.py`, `memory_e2e_eval.py`, `benchmark_discord_memory_extractor.py`,
   `training/common/eval_*.py`, `.scratch/reranker-finetune/`, `.scratch/d2-distillation/`.
2. Liệt kê mọi ứng viên khả thi (reranker, chưng cất bộ trích trí nhớ, embedding, OCR, …). Với mỗi
   ứng viên: bằng chứng nó là nút thắt (số + file), giả thuyết, tập đo, điều kiện dừng, ước lượng
   GPU/thời gian, rủi ro. Nêu lý do lần fine-tune reranker 07/09 trượt và điều kiện để không lặp lại.
3. Đề xuất một ứng viên, ghi rõ là ý kiến.
4. Điều kiện tiên quyết cho ticket 09: `split_manifest --check` + `leak_check` xanh
   (`training/README.md:44`), và script train phải được commit **trước** khi chạy GPU.

## Đầu ra

`.scratch/foundation-and-agent-eval/m3-target.md`. Đây là file duy nhất ticket này được tạo, và
được tạo thẳng trong checkout chính (điều phối sẽ commit).

## Comments
