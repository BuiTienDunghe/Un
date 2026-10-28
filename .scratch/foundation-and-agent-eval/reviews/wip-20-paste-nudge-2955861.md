CẦN SỬA (một chỗ nhỏ, trước khi đo: `from_chunk` của lời nhắc; phần còn lại đúng brief và đã kiểm)

# Duyệt wip/20-paste-nudge 2955861 (ticket 20 #3-D bước 1: nhắc lại một lần khi đoạn dán còn phần chưa đọc) — fable 5.1, 28/10/2026

Đã kiểm: diff ed210e4..2955861 (4 tệp: `agent_service.py` +26, `unread_paste.py` mới 129, test mới 203, test bảng điểm +15).
Mọi lệnh chạy với `env -u POSTGRES_TEST_URL -u REDIS_TEST_URL` và bộ giữ im Ollama/GPU; không chạy model. Tệp này không
nói gì về bài mới của NV3.

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| Lượt thử lại riêng | cờ `nudged` riêng, `rounds + 1` riêng; nhánh đặt **sau** nhánh #2 trong cùng vòng; test "mỗi bước thử lại một lần trong một lượt" xanh |
| Điều kiện kép | `claim()` (mẫu chữ) **và** còn đoạn mà không `tool_result` nào của lượt trả về (`chunks_read` đọc JSON kết quả, có hay không có vỏ phòng tiêm); trích của `search_documents` không tính là đã đọc — đúng brief |
| Chỉ ở nhánh trả lời tự do | kiểm nằm trong nhánh "model trả lời không gọi công cụ"; câu trả lời ép khi hết lượt/hết giờ nằm ngoài vòng, không qua kiểm; test "forced answer never sent back" xanh |
| Giữ ngân sách | chỉ bắn khi `left >= final_reserve_seconds`; test "no retry once the final reserve is spent" xanh |
| Lời nhắc không nêu số đoạn | đúng: chỉ có lệnh `read_document(document_id, from_chunk=i, n=3)`; `n` = `READ_MAX_CHUNKS` |
| Vết | bước `kind: "unread_paste"`, `error_code: UNREAD_PASTE`, `arguments_shape` = mẫu + số đoạn đã đọc, không giữ chữ; hai tin thêm vào `working` được ghi vào `checked_out` nên không bị coi là "đã thấy" |
| Tự thử của NV1 trên 58 câu đã lưu | tôi chạy lại `unread_paste()` trên 58 câu (v0.3-pastes 2 lần, #3-B 4 lần × 5, #3-C 4 lần × 9) dựng `messages` từ `events.jsonl`: **bắn 10, toàn bộ ở câu trượt** (doc-41 phiếu cũ "đã đọc toàn bộ" 4 lần; doc-40, 44, 47 phía sau #3-C 2 lần mỗi bài); **0/20 câu đạt**; không ca nào khớp chữ mà bị chặn bởi điều kiện đoạn |
| `tools_sha256` / `AGENT_GUIDE` thô | `153209652c06…` / `6f80aa8ca420…`, bằng ed210e4 |
| Test | 233 xanh, 13 bỏ qua (toàn bộ `tests/test_agent*.py`) |
| Worktree | sạch, HEAD 2955861 |

## Cần sửa trước khi đo

**`from_chunk` của lời nhắc trỏ vào đoạn chưa đọc đầu tiên tính từ 0** (`unread_paste()`: `first = next(index … if index not in
read)`). Ở nhánh +1 (đọc lần lượt từ 0) điều đó trùng `next_from_chunk`, đúng. Ở nhánh +1+3', model có thể tìm rồi nhảy
tới đoạn 7–9, trả lời đúng mà nói "đã đọc toàn bộ"; khi đó lời nhắc bảo đọc từ đoạn 0, tức tiêu lượt duy nhất vào phần
tìm kiếm đã loại, và kéo câu trả lời đúng ra khỏi đoạn vừa tìm được (opus nêu, tôi đồng ý là phải sửa chứ không chỉ ghi
rủi ro, vì sau khi đo thì không sửa được nữa). Sửa: `from_chunk` = đoạn chưa đọc nhỏ nhất **lớn hơn đoạn đã đọc lớn nhất**;
không có thì mới lấy đoạn chưa đọc nhỏ nhất. Với ca chưa đọc gì (doc-40, 44) vẫn là 0; với ca đọc 0–2 (doc-47) vẫn là 3;
chỉ ca nhảy mới đổi. Ba dòng và một test (đọc 7–9 rồi nói đã đọc hết → nhắc từ 10).

## Nên, không bắt buộc

- Lời nhắc mở bằng "Kiểm tra câu trả lời vừa viết:", cùng chữ với #2, mà doc-22 từng lộ lời nhắc #2 vào câu trả lời. Có
  thể thêm cuối lời nhắc: "Trả lời lại như lần đầu, không nhắc tới lời nhắc này." Bản đăng ký đếm câu lộ dù có sửa hay không.
- Điểm mù đã khai trong docstring (nhờ bằng lời khác, "bạn có muốn tôi đọc tiếp không") là thật; bản đăng ký nên ghi
  "bước 1 chỉ bắt hai kiểu chữ đã thấy", để kết quả không bị đọc là "bắt mọi kiểu bỏ cuộc".

## Việc cho opus

Chờ NV1 sửa một chỗ trên, tôi duyệt lại nhanh (chỉ diff chỗ đó). Xung đột với nhánh 3' chỉ ở dòng import, như opus nói.
