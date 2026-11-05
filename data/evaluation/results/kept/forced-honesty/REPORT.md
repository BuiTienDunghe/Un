# Rà và sửa harness trước khi đo BFCL đầy đủ (06/11/2026)

Ollama 0.40.13, Qwen 9B, nhiệt độ 0, seed 42, gỡ model trước mỗi bài, cùng ngày, một lần chạy mỗi nhánh. BFCL là 33 bài rút từ BFCL v4 (`ticket24-design.md`), Agent Eval là 66 bài tự viết: cả hai là số tự đo, không đặt cạnh bảng xếp hạng.

## Đã sửa

| Chỗ | Trước | Sau | Ai tìm ra |
|---|---|---|---|
| Bộ chạy BFCL ghi lần gọi | Chỉ ghi lần gọi chạm tới một công cụ của bài; tên bịa bị mất, `irrelevance_70` gọi `calculate` (công cụ của Ún, không có trong bài) mà vẫn được chấm đạt | Ghi đúng mọi lần gọi model viết ra, như bộ chạy gốc của BFCL; bộ chạy thành `bfcl-run-v2` | người duyệt độc lập |
| BFCL và bộ chấm trên Windows | Chết ở dòng tiếng Việt đầu tiên (bộ chạy) và ở tệp kết quả đầu tiên (bộ chấm) | Tự dùng UTF-8 | lần chạy 06/11 |
| Agent Eval đếm "hết lượt công cụ" | Lần ghi chú khi đọc văn bản dài / đọc nốt tài liệu bị đếm là hết lượt; cột đối chiếu coi `tool_call_error` là lỗ hổng | Đếm đúng lần trả lời ép buộc | tôi |
| Agent Eval và cách ép khuôn | Bộ đo không chuyển tiếp lời gọi ép khuôn, nên kiểm tra "hứa mà không làm" chạy khác bản thật | Chuyển tiếp | tôi |
| Câu trả lời ép buộc khi hết lượt | Chỉ dặn "trả lời ngay bằng những gì đã thu thập", model khẳng định cả điều chưa tra (BFCL 174) | Dặn thêm: chỉ khẳng định điều đã thấy, việc chưa làm thì nói chưa làm | báo cáo 02/11 |
| Nhắc việc: hẹn trùng | "cảm ơn, hôm nay mệt quá" sau một lời dặn nhắc làm code hẹn thêm lần nữa | Chỉ đọc chính tin nhắn này | người duyệt |
| Nhắc việc: hẹn khi không ai nhờ | Câu trích lời người khác, câu có số mà không có giờ cũng bị ép thành lời nhắc | Khuôn dữ liệu có thêm ô "có thật sự nhờ không" do model trả lời | người duyệt |
| Nhắc việc: gọi hỏng vẫn tính | `remind` bị từ chối (giờ sai dạng) vẫn được coi là đã hẹn | Chỉ lần gọi thành công mới tính | người duyệt |
| Đọc nốt tài liệu gặp lỗi | Lỗi kho dữ liệu hoặc model ở bước này làm chết cả lượt, mất câu trả lời đã có | Bỏ phần đọc thêm, giữ câu trả lời | người duyệt |

## Số đo

| Bộ | Đối chứng | Sau sửa | Đổi |
|---|---|---|---|
| BFCL 33 bài, bộ chạy v2 | 25/33 | 25/33 | cùng 8 bài hỏng; lượt chạm trần 3 vòng: 3 và 3 |
| Agent Eval 66 bài | 57 | 57 (`a8436b4`), 57 (`5d1d16c`) | không bài nào đổi |
| Nhắc việc, model thật, lời dặn Discord: 11 câu nhờ | — | 11/11 hẹn đúng giờ | |
| Cùng đó, 5 câu không nhờ | 1/5 bị hẹn nhầm (lần đầu) | 0/5 | câu sửa được viết sau khi thấy lần hỏng |

- Mốc BFCL cũ 26/33 là của bộ chạy v1, chấm sai `irrelevance_70`; mốc đúng là 25/33.
- Câu dặn cho lần trả lời ép buộc không đổi điểm ở cả hai bộ: ở đây chỉ chứng minh là nó không gây hại.
- Nhắc việc đo trên 16 câu tự đặt, không có lịch sử trò chuyện thật.

## Chưa làm, chờ chủ dự án

| Việc | Lợi | Hại / chi phí |
|---|---|---|
| H1: giữ kết quả công cụ qua các lượt ở đường chat thật | +1 bài BFCL đo 02/11 (128); sửa được mất mã ở lượt sau | Phải lưu kết quả công cụ trong DB (quyền riêng tư: có thể chứa tin nhắn), ~12 % token |
| H2: trần 4 vòng thay 3 | +1 bài BFCL đo 02/11 (180) | Mỗi lượt có thể lâu thêm một vòng; cần đo Agent Eval |
| Bắt "nói đã làm mà không gọi" cho mọi công cụ (BFCL 174 lượt 5) | Đúng lỗi thật | Không có cổng nhận biết chung; chỉ `remind` có |
| Kiểm tham số tập trung theo lược đồ | Vết ghi đúng thứ đã chạy | Từ chối thẳng thì model yếu mất một vòng |
| Ghi chú "chưa làm" ở đường trả lời ép buộc khi kiểm tra hứa chưa kịp chạy (người duyệt #4) | | Cổng chữ có thể báo nhầm nếu không hỏi model |
| Số liệu trong ghi chú đọc tài liệu được tính là "đã thấy" (#7) | | Bộ kiểm số dễ dãi ở bài tài liệu dài |

Dữ liệu: `bfcl/ctl`, `bfcl/forced` (đối chứng là `65b0cf1` với câu dặn gỡ ra, nhánh `wip/ctl-no-forced-honesty`), `ae-ctl` (`74b6947`), `ae-forced` (`a8436b4`), `ae-head` (`5d1d16c`).
