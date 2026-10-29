# Ticket 20 — kiểm trước khi gộp N1 lên main (Agent Eval v0.8, đủ 66 bài): đăng ký trước

Viết trước lần chạy. Chủ dự án chọn (29/10, trả lời "1" cho đề xuất của opus): đưa N1 lên main cùng phiếu #3-C, chạy đủ bộ bài
cô lập trước khi gộp.

## Bản chất

Đợt phân xử chỉ chấm 19 câu có văn bản dán. Lần chạy này chấm cả 66 câu, để chắc rằng việc đưa cách mới lên không làm đổi câu
trả lời nào khác. Câu nào cũng đã có một lần chạy cũ làm mốc. Nếu code mới đúng như thiết kế, mọi câu trả lời phải giống mốc
từng chữ.

## Commit

`717e4d3` (`int/20-n1-main`) = N1 đã đo `d40d4e0` + main `928f1cf`. Phần code giống hệt `d40d4e0` (diff `backend/` rỗng). So
với main, code chỉ khác ở `pastes.py` (phiếu #3-C và N1), một khoá manifest và test. Bộ test backend giữ im: 951 qua. Có 10
lỗi và 4 hỏng ở 4 tệp, cũng hỏng y như vậy trên main (worktree thiếu môi trường).

## Cách chạy

qwen3.5:9b, nhiệt độ 0, seed 42, `num_ctx` 16 384, `--probe --gpu-shared no --unload-between-tasks`, GPU riêng, đủ 66 bài.
Run id `v0.8-n1-gate-full`, worktree `meas-717e4d3`. Dừng nếu GPU ≥ 85 °C, có chương trình khác dùng GPU, hoặc hạn tuần
≥ 35 %. Ước ~12 phút.

## Mốc so sánh

| Bài | Mốc | Vì sao giống |
|---|---|---|
| 19 bài dán (doc-39..57) | `v0.8-arb-n1` (`d40d4e0`) | cùng code, cùng bộ bài v0.8 |
| 47 bài không dán | `v0.7-3d-iso-base-full` (`94e321f`) | N1 không chạm tin không dán. Ticket 27 không bắn ở bài nào trong 62 bài của main (đo 29/10). Ba băm và 62 bài cũ không đổi |

## Luật

- **P**: ba băm (`tools_sha256` `153209…a75e500`, guide, system prompt) bằng hai mốc; bộ bài v0.8 đủ 66 bài; cô lập; manifest
  có `paste_inline.max_tokens` = 12 288.
- **G1**: 66/66 câu trả lời và chuỗi lệnh công cụ giống mốc từng byte.
- **Đạt G1** → gộp `int/20-n1-main` vào main, sau khi fable duyệt diff gộp và báo cáo.
- **Trượt G1** → không gộp. Báo cáo liệt kê từng bài khác, kèm vết. Chủ dự án quyết.

Dự đoán của opus: G1 đạt, 66/66. Điểm: 47 bài không dán giống mốc; 19 bài dán 18/19 như `v0.8-arb-n1`.

`analyze.py` cùng thư mục tính mọi điều trên.
