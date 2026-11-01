# 46 — Hỏi lại khi thiếu thông tin, xin duyệt trước khi làm

Status: mở
Type: task
Blocked by: 41, 44

Bản chất: hai cơ chế khác nhau. Hỏi lại là model thiếu dữ kiện; xin duyệt là code dừng việc nhạy cảm chờ người bấm.

Việc: duyệt nằm ở code, trạng thái chờ lưu được, công cụ khai báo cần duyệt hay không; `remember` chưa đổi cho tới khi chủ
dự án quyết. Hỏi lại đo tỉ lệ hỏi thừa trên bài đã có đủ dữ kiện. Mặc định tắt. Đo cô lập so với mốc 41.

## Đã làm (nhánh wip/46-ask-approve) — chỉ phần xin duyệt

Công cụ khai báo `requires_approval=True` (`AgentTool`); vòng agent không tự chạy mà giao cho `AgentService.approvals`
(`app/services/approvals.py` giữ từ vựng chung, `app/discord/approvals.py` giữ luật). Lượt dừng với câu trả lời do code viết
(`stop_reason` `awaiting_approval`), lệnh gọi lưu ở bảng `discord_approvals` (migration `20261102_38`, cộng thêm, có downgrade).
Cờ `DISCORD_APPROVALS_ENABLED` mặc định tắt. Cổng HTTP cho bot: `/api/discord/approvals` (list, approve, deny).
Chưa gắn cờ cho công cụ thật nào; `remember` giữ nguyên.

Quyết định đã chọn, đổi được:
- Người duyệt = người nói trong lượt hội thoại (đọc từ lượt, không từ model), cùng server. Người khác bị từ chối, hàng không đổi.
- Hết hạn 10 phút (`DISCORD_APPROVAL_TTL_SECONDS`). Cơ sở dữ liệu từ chối "duyệt" muộn ngay trong câu UPDATE, không cần ai quét.
- Duyệt = một câu UPDATE có điều kiện `pending -> running`, nên bấm hai lần chỉ chạy một lần. Tiến trình chết giữa chừng thì sau 10 phút
  hàng thành `failed (interrupted)` và không bao giờ chạy lại (không biết công cụ đã chạy hay chưa).
- Lệnh gọi lưu đúng JSON model viết, hiển thị nguyên (quá 1 500 ký tự thì từ chối, không cắt), và chạy đúng JSON đó.
- Gặp lệnh cần duyệt đầu tiên thì dừng; lệnh không cần duyệt đứng trước đã chạy, lệnh sau nó bỏ.
- Sau khi duyệt, kết quả công cụ trả về cho bên gọi (bot); model không được gọi lại. Ngữ cảnh riêng của lượt (`readable_documents`, đoạn dán) không qua được chỗ dừng.
- Tắt: công cụ cần duyệt không được đưa cho model và không chạy; danh sách công cụ và tin gửi model giữ nguyên.
- `forget_member` bước 6c xoá theo người được hỏi; hàng còn theo lượt (CASCADE).

## Đã làm thêm (nhánh 46-finish) — nút Discord và `ask_user`

- Bot: `discord_bot/approvals.py`, `ApprovalView` (Duyệt / Từ chối) gắn vào câu trả lời xin duyệt, và `/approvals`. Tắt mặc định bằng
  `DISCORD_APPROVALS_ENABLED` (cùng biến với backend, compose chuyển cho bot). Tắt thì không đăng ký lệnh, không gọi cổng nào. Bật thì chỉ
  câu trả lời mang chữ `Mã duyệt:` mới tốn một lượt `GET`; nút tìm phiếu theo `source_turn_id` (cổng danh sách giờ trả thêm trường này).
- Chỉ người được hỏi bấm được; người khác được báo riêng, không gọi cổng. Bấm lần đầu tắt cả hai nút (bấm thứ hai không gọi gì); hết hạn thì
  nút tắt; lệnh gọi hiện nguyên văn trong khối mã, mọi tin của phần này gửi với `AllowedMentions.none()`.
- `ask_user` (`app/services/ask_user.py`, cờ `AGENT_ASK_USER_ENABLED`, tắt mặc định): gọi thành công là lượt kết thúc bằng đúng câu hỏi
  (`AgentTool.ends_turn`, `stop_reason` `asked_user`), nên tối đa một lần mỗi lượt. Chưa gắn cờ duyệt cho công cụ thật nào; `remember` giữ nguyên.
- Ghi chú thấp của bản duyệt: (1) `_run` giờ ghi log khi không đóng được hàng; (3) chữ "xoá hội thoại" sửa; (4) bảng điểm hiện
  `awaiting_approval`/`asked_user` khi có; (5) câu xin duyệt chỉ chỗ bấm; `agent_eval.py` băm `_offered_schemas()`. Ghi chú (2) cần DB thật,
  chưa kiểm ở nhánh này.

Chưa làm: đo tỉ lệ hỏi thừa của `ask_user` (chưa đo, chưa chạy Agent Eval); đo cô lập so với mốc 41 (khi tắt không đổi gì trong prompt hay
danh sách công cụ — `tools_sha256` giữ nguyên trong test — nhưng chưa chạy Agent Eval). Chỉ kiểm được trên Discord thật: nút hiện đúng trên
tin thật, người khác bấm vào nút của người khác, nút tắt khi hết hạn, `/approvals` hiển thị, nút sau khi bot khởi động lại (nút nằm trong
bộ nhớ bot nên hết tác dụng; `/approvals` đưa phiếu về).
