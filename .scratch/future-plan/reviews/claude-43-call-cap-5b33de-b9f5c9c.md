GỘP ĐƯỢC

# Duyệt `claude/43-call-cap-5b33de` (b9f5c9c) — trần số lần gọi model mỗi lượt

Duyệt độc lập theo `git diff main...claude/43-call-cap-5b33de`, mở code xung quanh, chạy test. Không sửa code.

## Bản chất

Nhánh này đặt một "máy đếm" ở cửa ra vào của model: mỗi lượt chat, RAG hay agent mở một sổ với số lần
được phép, mọi lần gọi model sinh chữ đi qua router đều ghi vào sổ đang mở, và nếu vượt số thì ghi vết và
cảnh báo chứ không chặn. Tôi tìm xem có đường nào gọi model mà sổ không thấy, có chỗ nào mở sổ ở một luồng
rồi gọi model ở luồng khác (sổ sẽ rỗng mà test vẫn xanh), và trần suy ra có khít không. Không thấy lỗi nào
có kịch bản hỏng cụ thể.

## Đã kiểm

| Điểm kiểm | Kết quả | Bằng chứng |
|---|---|---|
| Mọi lần gọi model sinh trong một lượt đều qua chỗ đếm | Đúng | Chỉ 7 chỗ gọi `router.chat/chat_tools/stream_chat` trong lượt (số dòng theo worktree nhánh): chat_service.py:155, 206; rag_service.py:119, 187, 210; agent_service.py:418, 525 — tất cả nằm trong `with turn_call_budget` (chat_service.py:148, 205; rag_service.py:182, 205; agent_service.py:343). Discord đi qua `respond_with_context` → `_respond` nên cũng được đếm. |
| Đường stream | Đúng | `count_generation_call()` chạy lúc gọi `stream_chat` (model_router.py:229), trước khi trả iterator; `with` chỉ bọc lệnh gọi là đủ. |
| Lan truyền ContextVar qua luồng | Không có rủi ro | Sổ được mở ngay trong hàm gọi model, cùng luồng. Luồng duy nhất chạy lượt agent (`routers/chat.py:30`) dùng `copy_context()` và sổ vẫn mở bên trong `run`. Không có ThreadPool/to_thread nào gọi model. |
| Trần agent `max_steps + 3` khít | Đúng | Vòng lặp: `rounds` chỉ tăng 1 lần cho lỗi parse (`call_retried`) và 1 lần cho con số lạ (`retried`), cộng câu trả lời ép ở cuối → tối đa `max_steps + 3`; lượt trả lời trong vòng lặp thì không có lệnh ép. Test đẩy đến đúng trần với `max_steps` 1 và 3. |
| `run` → `_run` | Không tác dụng phụ | Không có lớp con, không có chỗ nào gán `run`/`_run` của AgentService (agent_eval.py:482 gọi `agent.run`). Chữ ký giữ nguyên. |
| Lồng sổ chat(0) ↔ agent | Đúng | Sổ agent mở sau nên nhận hết lần gọi; sổ chat ở chế độ agent không ghi gì. Test `test_the_agent_in_a_chat_turn_leaves_the_count_to_itself` xác nhận. |
| README luật 5 | Đúng với code | "ghi vết, không chặn", trần 1 / 2 / `max_steps + 3`, test đỏ khi vượt hoặc trần thừa (3 bài assert bằng đúng trần). |

Test đã chạy (không DB, Ollama tắt tiếng, CUDA ẩn): `test_call_budget.py` + `test_agent_answer_check.py` +
`test_agent_tool_call_error.py` + `test_agent_progress.py` — 50/50 xanh.

## Ghi chú không chặn

- call_budget.py:14 nói "the eval" không bị đếm — sai nhỏ: agent_eval gọi `agent.run`, sổ mở bên trong nên
  vẫn đếm (vô hại, đếm xong không ai đọc). "Discord pre-turn condensation" cũng không tồn tại trong code hiện
  tại (condensation là worker nền).
- Lần thử lại ở tầng client (retry transport trong OllamaClient) nằm dưới router nên không đếm; docstring đã nói
  rõ, README viết "every generation call" rộng hơn một chút.
- call_budget.py:28 dùng `logging` chuẩn trong khi services dùng loguru; cảnh báo vẫn ra stderr qua handler
  mặc định, chỉ khác định dạng.
