ĐÚNG SỐ (số liệu và bốn lần chạy không đổi so với f535414, đã kiểm ở `report-arb-f535414.md`; hai chỗ sửa lời ở e707140 đúng với vết và với code)

# Duyệt báo cáo đợt phân xử N1 / C7 — bản e707140 (chỉ sửa `REPORT.md`) — fable 5.1, 29/10/2026

`git diff f535414 e707140` chỉ chạm `REPORT.md` (+11 −4). Mọi con số giữ nguyên; kết luận ĐÚNG SỐ và xác nhận kiểm nguồn gốc ở
`report-arb-f535414.md` vẫn áp dụng.

| Chỗ sửa | Kiểm | Kết quả |
|---|---|---|
| p5: "#2 bắn một lần ở doc-47 dưới N1; ba con số của câu trả lời cuối đều có trong văn bản; câu đầu không được giữ; nguyên nhân '54 triệu' là suy luận chưa kiểm" | vết: `answer_check` `unsupported_figures: 1`, không có nội dung câu đầu; 18.000.000, 36.000.000, 54.000.000 đều có nguyên văn trong `doc-47`; "54 triệu" không có | đúng; bản cũ nói "model tự tính" như sự thật là sai, bản mới nói đúng mức vết cho phép |
| Giới hạn: chat thật có tới 40 tin lịch sử trong phép ước, trần thực tế thấp hơn ~36 000 ký tự | `take_pastes` ước cả `shown` tới tin cuối; `history_limit` của chat_service | đúng về cơ chế |
| Giới hạn: Discord chặn tin ở 10 000 ký tự nên N1 không bao giờ bật ở đó | `discord/schema.py:40` `max_length=10_000`; `is_paste` đòi > 10 000 | đúng |
| Đã đọc trọn bốn câu đạt của C7 (49, 50, 55, 57), không đoán | tôi đọc độc lập, cùng kết luận | ✓ |
