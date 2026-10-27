# 22 — Tách mềm Discord: lõi không import gì của Discord; Discord là một gói tự cắm vào

Status: thiết kế xong (fable, `ticket22-design.md`); 5 lựa chọn điều phối chốt; C1 giao Nhân viên 2, C2–C3 sau khi gộp ticket 20 #1, C4 Nhân viên 1
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
- 28/10 00:40 (opus 5.5, theo ý fable; chủ dự án uỷ quyền chọn các chi tiết kỹ thuật): (1) `routers/bot.py` +
  `bot_control_service` sang gói; (2) model Discord **ở lại** `models.py` (một metadata, không chạm Alembic); (3) một
  shim duy nhất `discord_history_service` tới C4; (4) **D1** trong 22 (giữ khai báo như cũ, để C4 kiểm "Agent Eval
  trùng"), D2 đo riêng trên v0.3 sau; (5) C4 do Nhân viên 1 làm ngay sau khi ticket 20 #1 gộp. Nợ ghi lại, không
  sửa lần này: 25 trường settings Discord, chuỗi tuyến job trong `jobs/routing`, ba dịch vụ lõi đếm bảng Discord.
- 28/10 (Nhân viên của Ún 2), nhánh `wip/22-discord-split` từ main 00fcdfb:
  - **C1** (1806cea): `STOPWORDS` và `fold` dời sang `app/utils/vi_text.py`; `answer_grounding` import từ đó;
    `discord_memory_guard` import lại cả hai, nên mọi chỗ đang dùng tên cũ vẫn chạy, và đó vẫn là cùng một object.
  - **C5** (50e62b7): `tests/test_discord_boundary.py`, 8 bài.
    - Kiểm mã nguồn: không module lõi nào import `app.discord`. Kiểm này chỉ có tác dụng từ C2, khi
      `app/discord/` có thật.
    - Kiểm lúc chạy, có tác dụng ngay: import một module lõi trong một interpreter mới thì không nạp module
      Discord nào. Ngoại lệ duy nhất là `discord_memory_constants`, vì model ở lại lõi.
    - Riêng agent, chat và rag còn nạp `discord_history_service`. Đó là món nợ `search_history`, C4 sẽ xoá.
    - Kiểm đột biến: cho `answer_grounding` import lại từ guard, hoặc thêm một lệnh import `app.discord` nằm
      trong hàm, thì đều đỏ.
  - Kèm b83c45e: 3 test `--collection-base` của ticket 09 đỏ trên main khi chạy cả bộ, và cả trên CI, vì dựng
    `Settings` mà không có `DATABASE_URL`. Test giờ tự đặt một URL giả.
  - Bộ test chạy không có `POSTGRES_TEST_URL`: backend 795 bài qua, 450 bài bỏ qua; bộ test gốc 74 bài qua.
    Chưa chạy với DB test.
