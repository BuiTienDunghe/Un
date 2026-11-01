# Vì sao mốc Agent Eval tụt từ 58 xuống 54 (ticket 41, 02/11/2026)

Mọi lần chạy: 66 bài, Qwen 9B, nhiệt độ 0, seed 42, gỡ model trước mỗi bài.

| Phiên bản | Commit | Ngày chạy | Đạt |
|---|---|---|---|
| Mốc cũ | `717e4d3` | 29/10 | 58 |
| Cùng commit đó | `717e4d3` | 02/11 | 55 |
| Trước ticket 32 | `eba3794` | 02/11 | 55 |
| Sau `current_time` | `a5f6cf6` | 02/11 | 51 |
| Sau `calculate` | `8b42231` | 02/11 | 54 |
| Trước ticket 39 | `1b1f3bf` | 02/11 | 54 |
| Main | `bd27676` | 01/11 | 54 |

Cùng code, 29/10 ra 58 và 02/11 ra 55, chỉ 12/66 câu trùng chữ. Vậy 3 bài tụt do môi trường đổi, không do code.
`717e4d3` và `eba3794` chạy cùng ngày trùng 65/66 câu, nên các ticket giữa hai commit không làm đổi kết quả.
Do code chỉ còn 55 → 54. Chưa xác định phần nào của môi trường đã đổi.
