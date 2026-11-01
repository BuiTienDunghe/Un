# Mốc Agent Eval v0.8 mới (ticket 41, 01/11/2026)

Commit `bd27676`, Qwen 9B, nhiệt độ 0, seed 42, gỡ model trước mỗi bài, GPU không dùng chung, 66 bài, 10 phút.

| Lần chạy | Commit | Đạt |
|---|---|---|
| Mốc cũ `v0.8-n1-gate-full` | `717e4d3` | 58/66 |
| Mốc này | `bd27676` | 54/66 |

Chỉ 3/66 câu trả lời trùng chữ, nên có thay đổi tác động rộng giữa hai commit. Chưa xác định thay đổi nào.

| Đổi chiều | Bài | Quan sát |
|---|---|---|
| Hỏng mới | doc-25 | Không tra tài liệu, trả lời là không có thông tin. Lỗi thật |
| Hỏng mới | doc-20, doc-26 | Trả lời đúng, thiếu trang hoặc tên tệp trích dẫn |
| Hỏng mới | doc-55 | Thiếu dữ kiện `Hoa Sữa` |
| Hỏng mới | doc-19 | Trả lời trung thực "không thể tìm thấy file"; khuôn của bộ chấm không khớp cách viết này |
| Hỏng mới | hist-10 | Hỏi lại tên server |
| Đạt mới | doc-17, doc-30 | |
| Hỏng cả hai | doc-22, hist-05, doc-33, doc-36, hist-11, doc-57 | |

Đây là số tự chấm, chỉ dùng so các phiên bản của Ún.
