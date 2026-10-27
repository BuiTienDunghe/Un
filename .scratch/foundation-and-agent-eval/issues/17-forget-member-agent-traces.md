# 17 — `forget_member` phải xoá cả trích đoạn của thành viên trong agent_traces

Status: chờ duyệt — Nhân viên của Ún 1, nhánh `wip/17-forget-member-traces`
Type: task
Blocked by: 16

## Vì sao

Nhân viên 1 phát hiện khi thiết kế ticket 16 (27/10): `backend/scripts/forget_member.py` không xoá
`agent_traces`, trong khi trace của hội thoại Discord chứa trích đoạn tin nhắn của thành viên (kết quả
`search_history`: ai nói, lúc nào, nội dung). Người dùng yêu cầu "quên tôi" thì nội dung của họ vẫn còn
trong trace của hội thoại khác cho tới khi hội thoại đó bị xoá. Bảng rút gọn của ticket 16 không có nội
dung, nên không làm khoảng hở này rộng thêm.

## Việc

1. Đọc `forget_member.py` và tìm mọi nơi nội dung của một thành viên có thể nằm: `agent_traces.content`,
   `agent_traces.arguments` (`author_id`), và mọi bảng khác chưa được quét.
2. Chọn cách: xoá hẳn bước trace chứa nội dung của thành viên, hay thay nội dung đó bằng một dấu
   "[đã xoá theo yêu cầu]". Ghi lựa chọn vào Comments trước khi code.
3. Test Postgres: tạo trace có trích đoạn của thành viên A và B; quên A; trace không còn chuỗi nào của A,
   phần của B còn nguyên.

## Comments

### 27/10 — Nhân viên của Ún 1: khảo sát (trên main c8be3ee, đã có 16)

Bản chất: "quên tôi" trước đây chỉ xoá những gì được ghi theo tên người: tin nhắn gốc, lượt hỏi, ký
ức. Nhưng bot còn CHÉP lời của người đó sang những chỗ không ghi tên ai: lịch sử hội thoại, và dấu vết
các lần bot tra cứu. Muốn quên cho thật thì phải tìm lại các bản chép đó, và chỉ tìm chắc được những bản
chép nguyên văn.

Nơi lời của thành viên A còn lại sau `forget_member` cũ:

| # | Chỗ | Tìm được chính xác không |
|---|---|---|
| 1 | `messages` vai user của hội thoại Discord: `request_text` nguyên văn | Được, nhưng không có cột tác giả và turn không giữ id message. Đối chiếu `content == turn.request_text`, TRƯỚC khi xoá turn |
| 2 | `agent_traces.content` của `search_history`: mục JSON có `author_id` / `speaker` / `message` | Được theo `author_id` khi parse được JSON; kết quả bị cắt theo ký tự thì không parse được |
| 3 | `agent_traces.arguments`: `author_id` của A; `query` có thể chứa lời A | `author_id`: được; `query`: chỉ khi trùng nguyên văn |
| 4 | câu trả lời của bot (`messages` vai assistant, bước `final`) trích hoặc diễn giải lời A | Chỉ trích NGUYÊN VĂN; diễn giải thì không phát hiện được |

Không phải lo: title của hội thoại Discord (không đặt); `request_logs` và `agent_trace_summaries` không
có nội dung.

**Điều phối chốt:** Q1 (C) — sửa theo mục khi parse được, nội dung không parse được mà còn dấu vết của
A thì thay cả. Q2 (b) — giữ dòng `messages` của A, thay nội dung; câu trả lời của bot chỉ thay đoạn trích
nguyên văn từ 20 ký tự, và ghi rõ trong output lẫn docs rằng lời diễn giải không phát hiện được. Q3 (i) —
`content_sha256` của bước bị sửa đặt về NULL.

### 27/10 — Nhân viên của Ún 1: đã làm

- `backend/app/stores/member_redaction.py` (cạnh `postgres_auxiliary_store`), thuần, không DB:
  `QuoteIndex` (mọi cửa sổ 20 ký tự trong lời của A), `redact_quotes`, `redact_history_result` (mục của A
  thành dấu; kết quả bị cắt mà còn `author_id` hoặc lời A thì thay cả), `redact_arguments`. Lớp bọc
  injection-defense được nhận theo dạng (dòng `<<<…>>>`), nên tầng stores không import services.
- `scripts/forget_member.py`, bước 8: đọc lời của A (tin nhắn kênh trong guild, cùng `request_text`) TRƯỚC
  bước 6–7; quét các hội thoại gắn với phiên của guild; viết đè trong CÙNG transaction với các lệnh xoá;
  đặt NULL `content_sha256` của bước bị sửa nội dung. Dry-run đếm `conversation_messages` /
  `agent_trace_steps`; `remaining` đếm lại bằng đúng lời đã đọc, còn sót thì exit 1; output có `limits`.
- `docs/memory_design.md`: ghi phạm vi mới và giới hạn "không phát hiện được lời diễn giải".
- Mục của B, kể cả khi B trích lời A, được giữ nguyên. Điều này nhất quán với việc `forget_member` không
  đụng tin nhắn gốc của B.

| Kiểm | Kết quả |
|---|---|
| `tests/test_member_redaction.py` (không DB): chung một kết quả, kết quả tràn, bị cắt giữa JSON, trích một phần 20 ký tự, 19 ký tự và lời diễn giải KHÔNG bị bắt, tham số | 9 xanh |
| `tests/test_forget_member_copies.py` (DB): dry-run đếm 2 + 3 và không đổi gì; quên A thì không còn chuỗi nào của A, phần của B nguyên vẹn; hash các bước bị sửa thành NULL; quên B thì A còn nguyên | 4 xanh |
| Kiểm ngược: tắt nhánh che `search_history` | 4/4 đỏ |
| `test_discord_condensation_service.py` (đường `forget_member` cũ) | xanh |

Giới hạn còn lại:
- Lời diễn giải không bắt được.
- Một câu chung chung dài từ 20 ký tự trở lên mà A từng viết sẽ bị che cả khi bot dùng nó không phải để trích A; đây là che thừa, phía an toàn.
- Việc xoá turn của A theo `author_id` vẫn không lọc theo guild, như code cũ; tôi chưa đổi.

### 27/10 — Nhân viên của Ún 1: sửa theo lượt duyệt của fable

Fable chỉ ra một chỗ sót: câu trả lời của bot được lưu trên MỌI turn (`discord_repositories.py:422`), kể
cả turn của B. Nếu bot trả lời B mà trích lời A, đoạn trích đó còn lại vì bước 6 chỉ xoá turn của A.

- `_copies` quét thêm `response_text` của các turn trong guild mà tác giả không phải A (kể cả tác giả
  NULL), bằng `redact_quotes`. Dry-run, `remaining` và `copies_rewritten` có thêm `turn_responses`.
- Test DB: turn của B có câu trả lời trích A thì đoạn trích thành dấu, phần của B giữ nguyên; một câu
  trả lời khác của B không trích A thì giữ nguyên từng chữ.
- Docs ghi thêm: lời dùng để dò gồm cả câu hỏi của A với bot, nên có thể che thừa; bảng dò có thể tốn vài
  chục MB với người viết rất nhiều.

| Kiểm | Kết quả |
|---|---|
| `test_forget_member_copies.py` + `test_member_redaction.py` | 13 xanh |
| Kiểm ngược: tắt quét `response_text` | 2/4 test DB đỏ (dry-run và quên A), đúng hai test kiểm chỗ này |

Việc bước 6 không lọc theo guild đã thành ticket 19 (chủ dự án chốt `--all-guilds`), không làm ở đây.
