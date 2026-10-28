# Chẩn đoán, không đăng ký trước (opus, 28/10/2026 22:36–22:37)

Ba lần chạy một bài, sau năm lần chạy đã đăng ký (nền r1, r2, +1 r1, r2, nền đủ 62 bài), để kiểm một nghi ngờ: câu trả lời
của một bài phụ thuộc bài chạy ngay trước nó. Cùng cách chạy lạnh (`run_cold.sh`), t0, seed 42, `--tasks` một bài.

| Lần chạy | Commit | Kết quả |
|---|---|---|
| `diag-base-doc41-alone` | `73bb621` (nền) | trùng từng chữ `diag-nudge-doc41-alone`; khác doc-41 trong chuỗi 15 bài ở cả nền và +1, khác lần đủ 62 bài |
| `diag-nudge-doc41-alone` | `2866758` (+1) | như trên |
| `diag-base-doc51-alone` | `73bb621` (nền) | đạt, không lỗi; trong chuỗi 15 bài ở nền, doc-51 hỏng cả hai lần (model viết lệnh công cụ sai cú pháp, Ollama trả 500) |

Đọc: cùng code, cùng bài, chạy riêng thì giống nhau giữa hai nhánh; chạy trong chuỗi thì khác theo những gì chạy trước.
Không dùng cho luật của `PREREGISTRATION.md`.
