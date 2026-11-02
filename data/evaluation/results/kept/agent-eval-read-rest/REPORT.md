# Code tự đọc nốt tài liệu trên v0-long.2 (03/11/2026)

Bản cuối commit `d7fd69d`, Ollama 0.40.13, Qwen 9B, nhiệt độ 0, seed 42, gỡ model trước mỗi bài, 3 vòng công cụ, cùng ngày, một lần chạy cho mỗi nhánh. Bộ bài tự viết, không phải benchmark công bố. Đối chứng dài `ctx-off` chạy ở `4fc1db4`; phần đối chứng không đổi code từ đó, và hai lần đối chứng v0 trùng nhau từng bài.

| Nhánh | Bài đạt | Dữ kiện | Trung vị | Lâu nhất |
|---|---|---|---|---|
| ctx-01..07, tắt | 0/7 | 4/25 | 7,2 s | 13,9 s |
| ctx-01..07, chỉ khi model tự trả lời (`ctx-rest`) | 4/7 | 17/25 | 12,1 s | 13,8 s |
| Thêm khi hết vòng (`ctx-rest-forced`) | 5/7 | 22/25 | 12,9 s | 24,4 s |
| Thêm sửa lời dặn ghi chú (`ctx-final`) | 6/7 | 24/25 | 12,5 s | 28,1 s |

66 bài v0: đối chứng 55 và 55, bật 56; doc-36 lên, không bài nào xuống. Bước này chạy ở 2 bài: doc-24 (4,5 s thành 10,6 s, vẫn đúng) và doc-36 (9,5 s thành 15,8 s, từ sai thành đúng). Trung vị 4,42 s cả hai.

- Lời dặn ghi chú sửa sau khi xem kết quả ctx-05..07 của chính bộ này, và mẫu nhận biết "bỏ cuộc" cũng viết từ bộ này, nên 6/7 chưa phải số trên dữ liệu chưa từng thấy.
- Bộ chấm được sửa để lượt đọc do code thực hiện tính là đã đọc và không chấm tham số của nó; bước `tools_required` vì thế không còn tách được "model tự đọc" khỏi "code đọc hộ". Vết có trường `by_code`.
- ctx-07 còn sai: thiếu "9 ngày" của Sao Mai.
- Bài trong bộ dài 12 đoạn; chưa đo trên tài liệu hàng trăm trang, nơi 8 phần và 90 giây có thể không đủ, và lúc đó câu trả lời nêu phần chưa đọc.
- Chưa bật: `agent.read_rest` tắt trong `models.yaml`.
