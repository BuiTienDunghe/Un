GỘP ĐƯỢC

# Duyệt `wip/46-ask-approve` (9759cd0) — cổng duyệt công cụ

Đọc `git diff main...wip/46-ask-approve` và code quanh đó; chạy `tests/test_agent_approvals.py` + `tests/test_discord_register.py`
không DB: 36 qua, 1 bỏ (bài cần Postgres thật). Không lỗi chặn.

## Bản chất

Nhánh này thêm một "phòng chờ": công cụ nào được đánh dấu cần duyệt thì vòng agent không chạy mà cất lệnh gọi vào bảng, trả lời người
dùng bằng câu do code viết, rồi chờ đúng người đã nhờ bấm đồng ý. Mọi lối vào chỗ chạy công cụ đều có một câu kiểm "đã duyệt chưa",
nên dù model gọi thẳng, gọi lại, hay tắt cờ, công cụ cũng không chạy lậu. Hiện chưa có công cụ nào mang dấu này, nên bật hay tắt
đều chưa đổi gì với người dùng thật.

## Đã kiểm, đúng như nhánh nói

| Câu hỏi | Kết quả | Bằng chứng |
|---|---|---|
| Công cụ chạy lậu được không | Không | `agent_service.py:641` chặn trong `_run_tool` (lối chung duy nhất; `_execute_tool`, vòng lặp, MCP đều qua đây); chỉ `run_approved`:616–622 đặt `approved=True`, và nó kiểm lại công cụ còn mang cờ |
| Người duyệt lấy từ đâu | Từ lượt, không từ model | `turn_service.py:631` đặt `turn_id` phía server; `approvals.py:160` (`load_turn_identity`) đọc `author_id` từ hàng `discord_session_turns`; model không có đường ghi `tool_context` (không router nào nhận `tool_context` từ client) |
| Bấm hai lần | Chạy một lần | `move()` là UPDATE có điều kiện `status='pending'`, `rowcount==1`; Postgres READ COMMITTED đánh giá lại WHERE sau khoá hàng |
| Hết hạn | Không chạy | `before_expiry=True` đưa `expires_at > now` vào cùng câu UPDATE; `decide()` còn kiểm trước đó |
| Quên người | Xoá theo `requester_id` mọi trạng thái + FK CASCADE theo lượt | `forget_member.py` bước 6c, `_member_guilds`, `_counts` |
| Cổng HTTP | Sau `admin_guard` + `require_api_key` cấp router (cả GET danh sách) | `routers/approvals.py:15`, giống `reminders.py:14` |
| Migration | Cộng thêm, có downgrade, `down_revision = 20261101_37` là head hiện tại của main | `ls alembic/versions` ở main dừng ở 37; nhánh 49 không thêm migration |
| Tắt thì giữ nguyên | Đúng | `_offered_schemas()` lọc trên `registry.tools()` cùng thứ tự với `schemas()`; không công cụ nào mang cờ nên danh sách giống hệt; `ApprovalService` được dựng nhưng không chạm DB |

## Điểm cần biết (không chặn)

1. **Thấp — `backend/app/discord/approvals.py:313`.** `_run` bỏ qua kết quả `move(running → done/failed)`. Kịch bản: công cụ chạy quá
   `RUNNING_LEASE` (10 phút), một lời gọi `expire_due` song song đánh hàng thành `failed/interrupted`, công cụ xong thì không đóng được
   hàng; bot vẫn nhận kết quả, hàng ghi sai. Bất biến "không chạy hai lần" vẫn giữ.

2. **Thấp — chưa tự kiểm phần cần DB.** Bài `test_postgres_deleting_the_turn_takes_its_approval_and_forget_member_clears_the_rest`
   bị bỏ theo điều kiện duyệt (không DB). CASCADE thật và `forget_member` chạy thật chưa được tôi xác nhận; chỉ đọc văn bản migration.

3. **Thấp — chữ "a deleted conversation" ở `models.py:493`, migration `:36`, `docs/current_architecture.md`.** Kế thừa nguyên văn từ
   nhắc việc (`models.py:466`). Thực tế `DiscordConversationSession.backend_conversation_id` chỉ có Index, không FK tới `conversations`
   (`models.py:355`), và trong `app/` không chỗ nào xoá `discord_session_turns` ngoài `forget_member`. CASCADE chỉ phát huy khi ai đó
   xoá lượt; xoá hội thoại web không kéo theo.

4. **Thấp — `backend/scripts/agent_eval_scorecard.py:46`.** `STOP_REASONS` thiếu `awaiting_approval`. Hôm nay không tới được (eval không
   có `turn_id` → `NOT_A_DISCORD_TURN` thành lỗi công cụ, không phải điểm dừng). Đặt cạnh "Lưu ý cho sau" trong ticket.

5. **Thấp — trải nghiệm khi chưa có nút.** Câu trả lời nêu `Mã duyệt` 8 ký tự nhưng cổng HTTP đòi UUID đầy đủ (`decide()` gọi
   `UUID(approval_id)`); bot sau này phải tra danh sách để đổi mã. Lượt kế tiếp người dùng nói "ừ, làm đi" thì model gọi lại công cụ →
   tạo phiếu duyệt mới (khác `turn_id`), không khớp phiếu cũ. Ticket đã nói là quyết định có chủ ý.

## Ticket có nói quá không

Không. Ticket và CHANGELOG ghi rõ: chưa công cụ thật nào mang cờ, chưa nút Discord, chưa `ask_user`, chưa đo. Câu "cơ sở dữ liệu
từ chối duyệt muộn ngay trong câu UPDATE" đúng về cơ chế, với lưu ý `now` là đồng hồ Python đưa vào, không phải `now()` của DB —
cùng nguồn với lúc ghi `expires_at` nên không lệch.
