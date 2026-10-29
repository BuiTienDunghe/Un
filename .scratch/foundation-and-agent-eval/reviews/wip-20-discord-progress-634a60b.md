GỘP ĐƯỢC (hai chỗ opus hỏi đều ổn: không có đường nào đăng tin thứ hai, và `allowed_mentions` khi sửa tin bằng đúng khi trả lời; còn hai ca hiếm ghi lại để biết, không chặn)

# Duyệt wip/20-discord-progress 634a60b (ticket 20 #4 phía bot, cách D2: một tin "⏳" theo nhãn bước, rồi thành câu trả lời) — fable 5.1, 30/10/2026

Đã kiểm: diff 0cc0e68..634a60b (4 tệp: `progress_message.py` mới +172, `main.py` ±180, `api_client.py` +47, test +553). Đọc trọn
module mới và thân `answer_mention`; đối chiếu discord.py 2.7.1 đã cài và endpoint `/turns/{id}/progress` ở backend (có sẵn
từ 0cc0e68). Không chạy bot thật.

## Hai chỗ opus nhờ soi

**1. Lần giao lại có đăng trùng không?** Không có đường nào từ D2 tạo tin thứ hai:
- `_write` chỉ `reply` khi `self.message is None`; post hỏng → `_given_up = True`, không post lại; sửa hỏng vì `NotFound` → bỏ
  hẳn; sửa hỏng lý do khác → giữ tin, lần poll sau sửa lại (không post mới).
- `replace()` gọi `stop()` trước (giữ khoá, chờ post đang bay xong rồi mới huỷ task) nên không có ghi nào sau khi câu trả lời đã về.
- `replace()` sửa hỏng → `_delete_quietly` rồi trả `None`, caller gửi chunk 0 như hôm nay. `fail()`/`discard()` cũng vậy.
- Giao lại theo nghĩa backend (`fail_discord_turn(retryable=True)`) không đổi: bot vẫn raise và kết thúc `on_message`, không có
  vòng giao lại trong bot; `delivered` chỉ thử lại lời xác nhận, không gửi lại nội dung (đúng chú thích sẵn có).
- Ca hiếm còn lại, nêu để biết: Discord nhận lệnh sửa nhưng HTTP trả lỗi → bot xoá tin đã thành câu trả lời rồi gửi lại; nếu
  lệnh xoá cũng hỏng thì chunk 0 xuất hiện hai lần. Xác suất hai lỗi liên tiếp, chấp nhận.

**2. `allowed_mentions` khi sửa có bằng khi trả lời không?** Bằng. discord.py 2.7.1, `http.handle_message_parameters`:
- Trả lời hôm nay: `reply(text, mention_author=False)`, không truyền `allowed_mentions`, bot không đặt mặc định ở `Client` →
  payload = `AllowedMentions().to_dict()` rồi `replied_user = False`.
- Sửa tin: `edit(content, allowed_mentions=AllowedMentions(replied_user=False))`, `previous_allowed_mentions` là `None` →
  payload = cùng dict đó. Nếu sau này `Client` có mặc định thì cả hai đường đều gộp với nó (`merge`), vẫn bằng nhau.
- Khác biệt duy nhất là của Discord, không phải của code: người được @ trong một tin **sửa** không nhận thông báo. Opus đã
  ghi; chưa ai thấy tận mắt.

## Kiểm còn lại

| Kiểm | Kết quả |
|---|---|
| Đường không đổi | `/ask`, `/docs`, DM, cờ tắt: diff không chạm; `on_message` chỉ gọi `answer_mention(..., ProgressMessage(message))` |
| Lượt xong trong 2 s | task ngủ `first_post_seconds` trước khi ghi; `stop()` trước khi `prepare` trả về → không post. Test có |
| Nhãn | `get_discord_turn_progress` trả `label` chỉ khi `running`; poll hỏng giữ nhãn cũ; chưa có nhãn → "Ún đang làm…"; endpoint backend đọc bộ nhớ, không DB, timeout 5 s riêng |
| Khoảng cách hai lần sửa ≥ 1,5 s | `_space_out` lặp tới khi đủ (sửa cho tick 15,6 ms của Windows ở commit 634a60b); `_written_at` chỉ cập nhật khi ghi thành công |
| Lượt hỏng/huỷ/quá giờ | `BackendClientError` → `progress.fail(str(error))` = sửa tin thành đúng câu lỗi hôm nay, không sửa được thì reply như cũ |
| `completed` (giao trùng đã xử lý) hoặc lỗi bất ngờ | `discard()` xoá tin; lỗi bất ngờ vẫn raise như cũ |
| `delivered` ghi đúng id | tin được sửa đi vào `sent[0]`, id của nó là id tin "⏳" — đúng, vì đó là tin người dùng thấy |
| Lượt requeued | `watch(replacement_id)` chỉ đổi nguồn nhãn, không khởi động lại đồng hồ |
| Test | worktree sạch, HEAD 634a60b; bộ root `tests/`: 95 xanh, 1 bỏ qua |

## Ghi chú, không chặn

- Ca mồ côi: `reply` tạo được tin trên Discord nhưng HTTP trả lỗi → bot không biết id, `_given_up`, tin "⏳" ở lại mãi. Cùng
  họ với "tắt bot giữa lượt" mà opus đã nêu. Nếu thấy phiền thì một việc sau: khi bot khởi động, xoá tin "⏳" của chính nó còn
  sót trong kênh (tìm theo tiền tố), không thuộc lượt này.
- Bốn điều "chưa thấy tận mắt" của opus là hành vi Discord, đúng với tài liệu discord.py; cần một lần bấm thử trên server thật
  trước khi tin hẳn, chủ dự án làm được trong một phút.
