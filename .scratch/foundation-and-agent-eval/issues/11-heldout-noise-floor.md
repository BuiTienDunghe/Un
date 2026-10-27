# 11 — Đo dao động trên 788 câu held-out (tiền đề M3, dùng cho mọi ứng viên)

Status: đã giao — Nhân viên của Ún 2
Type: task
Blocked by: — (stack Ún đã bật 27/10)

## Vì sao

Ticket 09 chỉ giữ thay đổi khi cải thiện "vượt mức dao động đã đo". Nhưng trên 788 câu held-out
chưa từng có lần lặp nào cùng cấu hình (`m3-target.md`, mục "Bộ đo nào phân giải được gì"): 0,7843 /
0,7919 / 0,7906 là ba cấu hình khác nhau. Việc này cần cho cả ba ứng viên A/B/C, nên làm trước khi
chủ dự án chọn.

## Việc

1. Lặp lại **đúng cấu hình** của `data/evaluation/heldout_retrieval_v1/results/heldout-ctxON-rerankerON-20260908-055318.json`
   (cấu hình đang ship: ctx ON, reranker ON), **2 lần**, bằng `training/common/eval_stack.py` +
   `eval_heldout.py` (stack heldout cổng 8200). Trước khi chạy, so cấu hình/fingerprint mà lần chạy
   mới sẽ dùng với cấu hình ghi trong file 08/09; lệch thì dừng và báo, không chạy.
2. Nếu DB heldout không còn ở trạng thái ctx ON (phải nạp lại) thì dừng và báo điều phối, không tự
   nạp lại.
3. Báo cáo: Acc@1 / Acc@3 / recall@5 / MRR của mỗi lần; **số câu đổi kết quả** ở hạng 1 giữa các lần
   (so từng câu); chênh lớn nhất. Đây là sàn dao động của bộ 788.
4. Thêm vào `docs/RESULTS.md` hai dòng còn thiếu cho các lần 08/09 (`heldout-ctxON-rerankerON-20260908-055318`,
   `heldout-heading-ctx-rerankerON-20260908-010012`) và dòng cho các lần lặp mới, theo đúng định dạng
   bảng held-out đang có (khoảng dòng 300–310).

## Cách chạy

Worktree riêng (`coordination.md`). Worktree không có `.env`: tạo `.env` tối thiểu từ `.env.example`,
không chép khoá. Không dùng DB `local_ai_core_test` (bộ test đầy đủ đang chạy trên đó) và không dùng
DB `local_ai_core` (dữ liệu thật). Ollama dùng chung với Nhân viên 3 (chạy thử tối đa 3 bài agent),
không sao.

## File được đụng

Kết quả mới trong `data/evaluation/heldout_retrieval_v1/results/` (được track), `docs/RESULTS.md`.

## Nghiệm thu

Hai file kết quả mới, cùng cấu hình với 08/09 (ghi phần so cấu hình vào Comments); bảng dao động
theo từng câu; RESULTS.md có đủ dòng.

## Comments
