# Kế hoạch tương lai của Ún (01/11/2026)

Chủ dự án 01/11: thêm cả 14 mục; 1–9 thì opus 5.5 của Ún chủ động làm và giao nhân viên. 10–14 chỉ nằm trong kế
hoạch, chưa làm. Mỗi mục n là ticket số 40+n. Hiện trạng đã kiểm code ngày 01/11.

| Mục | Ticket | Việc | Hiện trạng | Đợt |
|---|---|---|---|---|
| 1 | 41 | Chấm lại Agent Eval, có mốc cô lập mới | Mốc 55/62 hết hiệu lực | 0 |
| 2 | 42 | Chạy BFCL qua harness | Có clone và thiết kế, chưa có bộ chạy | 1 |
| 3 | 43 | Trần số lần gọi model, có test | Chưa có; luật 5 đã nêu 3 ngoại lệ | 1 |
| 4 | 44 | Đếm độ dài ngữ cảnh, bỏ kết quả công cụ cũ | Lịch sử lấy theo số tin | 2 |
| 5 | 45 | Đọc hết văn bản rất dài theo từng phần | Quá ~36 nghìn ký tự chỉ trả phiếu | 2 |
| 6 | 46 | Hỏi lại khi thiếu thông tin, xin duyệt trước khi làm | Chưa có công cụ riêng | 2 |
| 7 | 47 | MCP, cắm công cụ ngoài | Chưa có | 1 |
| 8 | 48 | Nhắc việc, Ún tự nhắn trước | Bot không có vòng lặp nền | 1 |
| 9 | 49 | Giọng nói | Chưa có; model phải tải | 3 |
| 10 | 50 | Server Brain | Có khoảng nửa khung (29/09); thiếu dữ liệu thật | sau |
| 11 | 51 | OCR scan thật, chữ viết tay, ảnh trong trang | Mới đo văn bản tự viết | sau |
| 12 | 52 | D2 chưng cất bộ trích trí nhớ | Chưa bắt đầu; `.venv-train` đã xoá | sau |
| 13 | 53 | Đo e5-large | Đã đóng gói ở `wip/09-e5-full`, chưa đo | sau |
| 14 | 54 | Decided trên tin thật (ticket 36) | Mới thử 48 tin tự viết | sau |

## Thứ tự

- Đợt 0: mốc trên main trước khi có thay đổi nào, vì mọi so sánh sau đều cần nó.
- Đợt 1: bốn việc ít đụng nhau. Đợt 2: ba việc cùng sửa đường agent, làm sau khi đợt 1 gộp.
- Đợt 3: giọng nói, tới bước tải model thì hỏi chủ dự án.

## Luật làm việc

- Dừng khi hạn mức tuần đạt 100 % (chủ dự án nâng 02/11) hoặc GPU trên 85 °C. Hạn mức reset 04/11 10:00 giờ máy.
- Không dùng GPU khi chủ dự án đang chơi game hoặc phiên Quản lý xin GPU.
- Mỗi việc một worktree và nhánh riêng. Nhân viên không gộp main, không push, không bật/tắt container.
- Không tải trên 200 MB, không đọc `.env`, không đưa dữ liệu train lên repo.
- Mọi tính năng mới mặc định tắt cho tới khi có số đo. Thay đổi hành vi agent phải đo cô lập so với mốc 41.
- Ollama tự cập nhật (log 31/10 21:03). Cùng commit, cùng cấu hình mà 29/10 ra 58, 02/11 ra 55. So hai nhánh phải chạy cùng
  phiên bản Ollama và cùng ngày, chạy lại đối chứng; không so với số của ngày khác.
- Chỉ opus gộp, sau khi một người khác duyệt. Bộ test có cơ sở dữ liệu chỉ opus chạy, vì hai phiên dùng chung DB
  test sẽ tự khoá lẫn nhau.

## Quyết định opus chọn thay chủ dự án (chủ dự án bảo chủ động, đổi được)

- BFCL cắm ở vòng lặp, nhiệt độ 0, seed 42, tập 33 bài của `ticket24-design.md`: chỉ cách này đo được harness.
- Công cụ của Ún bị thay bằng hàm của bài trong lượt BFCL, để số đo sạch; ghi rõ trong báo cáo.
