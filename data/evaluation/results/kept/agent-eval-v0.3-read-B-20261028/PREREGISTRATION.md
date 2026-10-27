# Agent Eval v0.3 — #1-B: công cụ đọc, lời dặn như cũ — đăng ký trước (28/10/2026, 00:33, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm
công bố.

## Vì sao đo lần này

Lần đo #1 (`../agent-eval-v0.3-read-20261028/`, 34/48) cho thấy 4/5 bài đọc dài đạt, nhưng 40 bài cũ tụt
từ 34 xuống 29 mà không bài nào gọi `read_document`. Lần đó đổi cùng lúc lời dặn (thêm một câu nhắc đọc
tiếp) và mô tả công cụ. #1-B chỉ bỏ câu trong lời dặn (`1f9a4d4`, `AGENT_GUIDE` trùng từng byte bản trên
main) và giữ nguyên mọi thứ khác, để thử xem câu đó có phải thứ làm xáo bài cũ không. Điều phối chọn cách
này (B) lúc 00:30.

## So cái gì

| | Code | Kết quả đã có |
|---|---|---|
| A — mốc v0.3 | baseline của Nhân viên 3 (`12d7935` trên nhánh này) | 35/48; 40 bài cũ 34; bài đọc dài 0/5 |
| #1 | `199475a`: công cụ đọc + câu nhắc trong lời dặn | 34/48; 40 bài cũ 29; bài đọc dài 4/5 |
| #1-B | `wip/20-agent-reading` sau commit này: công cụ đọc, lời dặn như main | đo bây giờ |

Thước đo: tổng /48; 40 bài cũ; 5 bài đọc dài (doc-33..37).

## Quy trình

Như lần #1: cây sạch; trước MỖI lần chạy gỡ `qwen3.5:9b` qua API (`keep_alive: 0`) và ghi `/api/ps`; t0,
seed 42, `--probe`; hai lần lạnh `v0.3-read-B-r1-cold`, `v0.3-read-B-r2-cold`. Xong thì gỡ `qwen3.5:9b`,
theo luật nhường GPU.

## Quyết định (đặt trước khi thấy kết quả)

- Nếu #1-B giữ **≥ 4/5 bài đọc dài** VÀ **40 bài cũ ≥ 33** thì đề xuất ship #1-B.
- Nếu không thì làm (C): đo nhiều seed cho cả trước lẫn sau, để có dải dao động.
- Tính theo r1. Nếu r1 khác r2 thì báo, và tính theo phía xấu hơn.

## Dự đoán (sai thì báo; không sửa bài, tiêu chí hay bộ chấm sau khi thấy kết quả)

- Không dự đoán con số. Hai rủi ro ngược chiều nhau:
  - mô tả công cụ vẫn đổi, nên bài cũ vẫn có thể xáo;
  - thiếu câu nhắc thì agent có thể ít gọi `read_document` hơn, và bài đọc dài tụt dưới 4/5.
- r1 trùng r2 từng chữ.

## Ghi chú cho bộ chấm (để v0.4 xét, không sửa bây giờ)

Ở lần #1, doc-12 và doc-19 trượt vì câu trả lời viết "không thể tìm thấy" và "không trả về thông tin từ
file". Ý vẫn là "không tìm thấy", nhưng mẫu của bộ chấm không khớp. Đây là **nghi lỗi bộ chấm**, và vẫn
được tính là trượt trong mọi con số ở đây.
