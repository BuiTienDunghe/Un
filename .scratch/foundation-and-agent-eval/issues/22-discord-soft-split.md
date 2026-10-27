# 22 — Tách mềm Discord: lõi không import gì của Discord; Discord là một gói tự cắm vào

Status: chờ thiết kế (fable 5.1) — code sau ticket 20 #1 (registry)
Type: task
Blocked by: 20 #1 bước (1) registry (Discord đăng ký công cụ qua đó)

## Quyết định của chủ dự án (28/10 01:45)

"Discord: cách B, tách mềm trong cùng repo — lõi (agent, RAG, tài liệu, web) không import gì từ Discord; bot và
trí nhớ Discord thành một gói riêng, đăng ký công cụ của mình qua registry."

## Hiện trạng (đo 28/10)

| Đo | Số |
|---|---|
| Code Discord trong `backend/app` | 21 file, 7 336 / 23 020 dòng (32%) |
| Bảng DB / migration Discord | 10 bảng, 12 migration |
| Lõi vướng Discord | `services/agent_service.py:21` (`history_hit_payload` cho `search_history`); `services/answer_grounding.py:28-29` (`STOPWORDS`, `fold` mượn từ `discord_memory_guard`); `main.py` (32 chỗ nhắc Discord, nối dây) |
| Thuộc về trí nhớ Discord, đang nằm ngoài tên `discord_*` | `routers/memory_review.py`, `workers/memory_tasks.py`, có thể cả outbox / job worker |
| Bot (`discord_bot/`) | đã chỉ nói chuyện qua HTTP, không import `app` |

## Phạm vi

1. Đồ dùng chung đang nằm nhầm trong file Discord (vd `STOPWORDS`, `fold`) dời về lõi (`app/utils/` hoặc chỗ hợp).
2. Gói Discord riêng (vd `backend/app/discord/`): services, repositories, routers, schemas, workers của Discord
   và trí nhớ Discord. **Không đổi bảng, không migration** — chỉ dời code; tên bảng giữ nguyên.
3. Công cụ Discord (`search_history`, sau này `read_messages_around`) do gói Discord **đăng ký** vào registry của
   ticket 20; lõi agent không biết chúng. Chỉ khai báo khi `tool_context` có guild (lựa chọn D2 của ticket 20
   tự thành).
4. Nối dây Discord gom vào một hàm của gói (vd `register(app, settings)`), `main.py` gọi một lần.
5. Test tĩnh: không module lõi nào import `app.discord` (giống test "postgres không import services" của 05).
6. Hành vi không đổi: bộ test đầy đủ xanh; Agent Eval lạnh trùng câu trả lời (gỡ model trước mỗi lần).

## Câu hỏi thiết kế (fable trả lời trước khi code)

- Ranh giới chính xác: file nào là lõi, file nào thuộc Discord (outbox, job_queue, condensation, history,
  sessions, `forget_member`, `member_redaction` của ticket 17)?
- Thứ tự commit để mỗi commit lùi lại được và không xung đột với ticket 20 đang sửa `agent_service.py`/`main.py`.
- `alembic` và `models.py`: model Discord ở lại `postgres/models.py` (một metadata) hay sang gói (cần import để
  Alembic thấy)? Ưu/nhược.
- Đường cũ (`app.services.discord_*`) có cần lớp re-export tạm không (script, test, `tools/`)?
- Trí nhớ web (`memory_service`, Qdrant `memories`) ở lại lõi — ghi rõ ranh giới với trí nhớ Discord (R7 cũ).

## Comments
