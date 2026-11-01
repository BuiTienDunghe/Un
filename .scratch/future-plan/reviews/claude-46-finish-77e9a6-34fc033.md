GỘP ĐƯỢC

Nhánh `claude/46-finish-77e9a6` (34fc033), đọc `git diff main...` và mã xung quanh, chạy test không DB, 02/11/2026.

## Bản chất

Bot chỉ là cái nút: ai bấm, bấm cái gì, đều gửi về backend kèm danh tính Discord thật của người bấm, và backend mới là nơi quyết định (đúng người chưa, còn hạn không, đã xử lý chưa). Nên dù nút bị bấm sai, bấm hai lần, hay bot khởi động lại, công cụ vẫn chỉ chạy nhiều nhất một lần và chỉ khi người được hỏi đồng ý. `ask_user` thì đơn giản hơn: gọi là lượt kết thúc, nên không có vòng lặp hỏi mãi.

## Đã kiểm, không thấy lỗi

| Mục | Kết quả |
|---|---|
| Chỉ người được hỏi bấm được | Bot: `discord_bot/approvals.py:90-94` so `interaction.user.id` (từ tương tác Discord, không từ chữ) với `requester_id`; backend `app/discord/approvals.py:277` từ chối `APPROVAL_NOT_YOURS` nếu `actor_id` khác; danh sách `GET` lọc theo `author_id` (`pending_for`) |
| Bấm hai lần | `_pressed` + tắt nút + `view.stop()` (`approvals.py:108-127`); hai view của cùng phiếu (tin gốc + `/approvals`): backend `move(pending→running)` một lệnh có điều kiện, lần sau nhận 409 và hiện riêng |
| Nút hết hạn | `timeout=seconds_left`, `on_timeout` tắt nút; người lạ bấm không gia hạn timeout (đã đọc `discord/ui/view.py:591-596`: chỉ gia hạn sau khi `interaction_check` qua); backend vẫn kiểm `expires_at` khi bấm; sau khi bot khởi động lại nút chết, `/approvals` lấy lại (đã ghi doc) |
| Chữ xin duyệt không ping/inject | Mọi tin của phần này `AllowedMentions.none()`; `_notice` và `ask_user` chèn ZWSP sau `@` (đã kiểm byte `​`); backend chạy JSON đã lưu, không phải chữ hiển thị |
| `Mã duyệt:` giả | `offer_buttons` (`approvals.py:139-153`) chỉ tốn một `GET` cho phiếu của chính người đó, lọc `source_turn_id == turn_id`; một lượt chỉ có phiếu khi cổng đã dừng lượt bằng chính câu thông báo, nên model hay người dùng viết "Mã duyệt:" không gắn được nút vào phiếu nào |
| Đường tắt không đổi | Bot: không đăng ký lệnh, `offer_approvals` thoát sớm; backend: `ask_user` chỉ đăng ký sau cờ, `ends_turn` mặc định False; `tools_sha256` giữ nguyên hằng `93410c…` ở cả test cũ lẫn test mới |
| `ask_user` không lặp, không mất lượt | Thành công → trả ngay câu hỏi (`agent_service.py:550-562`), model không được gọi lại; lỗi tham số → `BAD_ARGUMENTS`, vòng chạy tiếp; lệnh gọi trước nó vẫn chạy, sau nó bị bỏ (đã ghi doc) |
| `source_turn_id` trong API | Chỉ thêm trường vào payload; test qua TestClient khớp `TURN`; migration chỉ đổi chú thích, không đổi revision |
| Test không DB | backend 59 qua 1 skip (`test_ask_user`, `test_agent_approvals`, `test_agent_eval_scorecard`, 2 bài `test_agent_eval`); gốc `tests/test_discord_bot_approvals.py` 21 qua |

## Ghi chú, không chặn

- **thấp** — `discord_bot/main.py:836-838` và `discord_bot/approvals.py:126`: tham số tới 1 500 ký tự (`ARGUMENTS_MAX_CHARS`) cộng hàng rào kéo dài theo chuỗi dấu huyền có thể vượt 2 000 ký tự một tin; `followup.send` ném `HTTPException` không được bắt (vòng `for` của `/approvals`, và chỗ gửi kết quả sau khi bấm), các phiếu sau trong danh sách không hiện. Chỉ xảy ra khi model viết hàng trăm dấu huyền liền nhau vào tham số; chưa có công cụ thật nào cần duyệt.
- Nghi ngờ, chưa kiểm được ngoài Discord thật — `discord_bot/approvals.py:32-36` (`fenced`): theo hiểu biết của tôi Discord chỉ nhận đúng ```` ``` ```` và đóng ở ```` ``` ```` đầu tiên gặp, nên hàng rào dài hơn không ngăn được tham số chứa ```` ``` ```` thoát khỏi khối mã; phần sau sẽ hiện dạng markdown (bot được phép hiện liên kết ẩn `[chữ](url)`). Không ping được (`AllowedMentions.none()`) và backend chạy JSON đã lưu, nên nếu đúng cũng chỉ là hiển thị khác chữ thật.
- Ghi nhận, không phải lỗi của nhánh: đường trả lời thường của bot (`discord_bot/client.py`) không đặt `allowed_mentions`, nên ZWSP là lớp bảo vệ duy nhất cho câu thông báo và câu hỏi của `ask_user`.
- Chỉ kiểm được trên Discord thật (nhánh tự ghi): nút hiện đúng trên tin, tin bị tách nhiều phần thì nút ở phần cuối.
