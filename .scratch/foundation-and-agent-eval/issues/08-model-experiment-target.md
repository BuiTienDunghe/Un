# 08 — Chọn mục tiêu cho thí nghiệm model (M3)

Status: xong — chủ dự án chọn B, nhánh 0 trước (27/10)
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

- 27/10 (fable 5.1): xong, xem `m3-target.md`. Ba ứng viên có bộ đo: A reranker lần 3, B đổi
  embedding sang e5-large (bắt đầu bằng nhánh 0: chỉ dẫn truy vấn, không tải, không re-index), C D2
  chưng cất extractor. Fable nghiêng B; muốn model tự train thì C. Điều kiện chung: chạy một lần lặp
  control cùng cấu hình trên 788 câu trước treatment. Mọi lần tải model cần chủ dự án duyệt.
