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

Chưa làm: nút/lệnh duyệt trên Discord (bot chưa gọi các cổng trên); công cụ `ask_user` (hỏi lại khi thiếu dữ kiện); đo tỉ lệ hỏi thừa
(chưa đo); đo cô lập so với mốc 41 (không đổi gì trong prompt hay danh sách công cụ khi tắt nên chưa cần, nhưng chưa chạy Agent Eval).

Lưu ý cho sau: `scripts/agent_eval.py` băm `registry.schemas()` còn model thật được đưa `AgentService._offered_schemas()`. Hôm nay hai
danh sách giống hệt (chưa công cụ nào mang cờ). Ngày một công cụ như `remember` bị gắn cờ, `tools_sha256` của Agent Eval sẽ chứa một công cụ
mà model thật (khi tắt duyệt) không thấy, nên so với mốc 41 phải đổi eval dùng `_offered_schemas()`.
