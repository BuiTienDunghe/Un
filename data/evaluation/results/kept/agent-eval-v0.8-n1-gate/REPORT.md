# Ticket 20 — kiểm trước khi gộp N1 lên main: báo cáo

Đo đúng bản đăng ký `0de310f`, 29/10 10:31–10:40, `717e4d3`, đủ 66 bài, cô lập, GPU riêng, nóng nhất 80 °C. Số tính bằng
`analyze.py` cùng thư mục (`analysis.json`).

## Bản chất

Đưa cách mới lên không làm đổi câu trả lời nào ngoài dự kiến. 66 câu trả lời giống hệt mốc từng chữ: 19 câu có văn bản dán
giống đợt phân xử, 47 câu hỏi thường giống lần chạy cũ. Theo luật đã ghi trước, bản này được gộp lên main, sau khi fable duyệt.

## Kết quả

| Mục | Kết quả |
|---|---|
| Điều kiện P | đủ 9/9 |
| G1: 66/66 giống mốc (câu trả lời và lệnh công cụ) | **đạt**, 0 bài khác |
| Lỗi | không |

| Bộ bài | Điểm bản gộp | Mốc |
|---|---|---|
| 19 bài dán | 18 | 18 (`v0.8-arb-n1`) |
| 47 bài không dán | 40 | 40 (`v0.7-3d-iso-base-full`) |
| 66 bài v0.8 | 58 | — |

**So với main hiện tại trên cùng 62 bài v0.7, cô lập** (thêm, ngoài luật): main 45/62 (`v0.7-27-main-after-full`, phiếu #3);
bản gộp 55/62 (40 bài không dán + 15/15 bài dán cũ). Cả 10 câu đổi đều là câu có văn bản dán; 47 câu còn lại giống nhau.

## Giới hạn

- Một lần chạy. Câu trả lời trùng mốc từng chữ, nên không có độ lệch nào để đọc.
- Agent Eval là test hồi quy nội bộ, không phải khẳng định chất lượng.
- Phần lịch sử dài và Discord: như trong báo cáo phân xử.
