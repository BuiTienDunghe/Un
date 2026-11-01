CẦN SỬA

# Duyệt nhánh `claude/48-reminders-ca5159` (e13aff3) — nhắc việc

Đọc `git diff main...claude/48-reminders-ca5159` và code xung quanh (`forget_member.py`, `turn_service.py`,
`models.py`, `api_client.py`); chạy `backend/tests/test_discord_reminders.py`, `test_discord_register.py`,
`tests/test_discord_bot_reminders.py` trong worktree (72/72 qua, không cần DB); chạy thử hàm cổng với vài câu
tiếng Việt (dưới).

## Bản chất

Phần gửi nhắc làm đúng: tắt mặc định, chỉ server được phép, chỉ người đặt huỷ, gửi đúng kênh, không ping ai ngoài
người đặt. Hai chỗ hỏng nằm ở hai đầu vòng đời. Đầu vào: cái "cổng" đọc lời người dùng để chắc họ thật sự nhờ nhắc
chỉ nhìn một tin nhắn, nên câu nhờ lịch sự ("có thể ... không?") bị coi là câu hỏi, và khi công cụ bảo model hỏi
lại giờ thì câu trả lời giờ của người dùng cũng bị từ chối vì không còn chữ "nhắc tôi" — người dùng bị kẹt. Đầu ra:
khi một thành viên xin xoá mọi dấu vết, script xoá không biết đến bảng nhắc việc, nên lời họ dặn và tên họ vẫn nằm
lại, và tới giờ bot vẫn gọi tên họ trong kênh.

## Lỗi chặn

### 1. `forget_member` và xoá hội thoại không xoá nhắc việc — CAO, chặn

- `backend/scripts/forget_member.py:6-28` liệt kê 8 bước xoá (vector, nguồn, mệnh đề, trí nhớ, ứng viên, lượt, tin kênh,
  bản chép); không bước nào đụng `discord_reminders` (grep `reminder` trong script: 0 kết quả).
- Bảng không có khoá ngoại: `source_turn_id` là cột UUID trần (`backend/alembic/versions/20261101_37_discord_reminders.py:38`,
  `backend/app/postgres/models.py:467`), nên xoá lượt (bước 6) hay xoá hội thoại (`postgres_auxiliary_store.py:258`,
  cascade theo FK) đều không chạm tới hàng nhắc.
- Hàng giữ `creator_id`, `creator_display_name`, `text` (lời nguyên văn của thành viên). `creator_display_name` được
  lưu (`reminders.py:102,116`) nhưng không nơi nào đọc (`reminder_payload` không trả) — dữ liệu cá nhân giữ không để làm gì.
- Kịch bản: thành viên dặn "nhắc tôi 9h sáng mai họp", rồi xin quên (`forget_member --apply`). Script báo xong. 9h sáng mai
  `claim_due` (`reminders.py:277`) vẫn trả hàng đó, bot gửi `<@member> ⏰ Nhắc việc: họp` vào kênh. Lời và tên họ còn
  trong DB vô thời hạn.
- Sửa gợi ý: thêm bước xoá `discord_reminders` theo `(guild_id, creator_id)` vào `forget_member.py` (và `_member_guilds`);
  cân nhắc FK `source_turn_id → discord_session_turns.id ON DELETE SET NULL` hoặc xoá theo turn khi xoá hội thoại.

## Không chặn

### 2. Cổng chỉ đọc một tin nhắn: câu nhờ lịch sự và lượt trả lời giờ đều bị từ chối — TRUNG BÌNH

- `backend/app/discord/remind_tool.py:38` `_QUESTION = \bcó\b.*\bkhông\s*[?]?$`; `:68-70` `asked_for_reminder`;
  `:142-145` từ chối và bảo model "Hỏi họ muốn được nhắc lúc nào".
- Kết quả chạy thử `asked_for_reminder`:

| Câu người dùng gõ | asked | names_a_time |
|---|---|---|
| `Ún có thể nhắc tôi 3 giờ chiều mai gọi mẹ không?` | False | True |
| `Nhắc tôi 3 giờ chiều mai gọi mẹ có được không?` | False | True |
| `nhắc tôi gọi mẹ` | True | False |
| `3 giờ chiều mai` (trả lời câu hỏi giờ của Ún) | False | True |

- Kịch bản A: cách nhờ phổ biến "có thể ... không?" bị coi là hỏi tính năng → `BAD_ARGUMENTS` "chưa dặn nhắc".
- Kịch bản B (do chính công cụ dẫn tới): "nhắc tôi gọi mẹ" → công cụ bảo hỏi giờ → người dùng trả lời "3 giờ chiều
  mai" → lượt mới không có "nhắc tôi" → lại `BAD_ARGUMENTS` "chưa dặn nhắc". Không có cách nào hoàn tất ngoài việc
  người dùng gõ lại cả câu. Gợi ý: cho cổng đọc thêm lượt người dùng liền trước (cùng session) khi lượt đó đã qua
  `asked_for_reminder`, hoặc bỏ `_QUESTION` khi câu có "có thể/giúp/hộ".

### 3. Cửa sổ gửi đôi rộng hơn tài liệu nói — THẤP

- `discord_bot/reminders.py:23` `ACK_ATTEMPTS = 3`, `:130-138` thử báo nhận 3 lần, nghỉ 0,1–0,3 s, rồi bỏ. Hàng ở lại
  `sending`; sau `LEASE` 10 phút (`reminders.py:38`) được giao lại và gửi lần hai.
- Tài liệu (`docs/current_architecture.md`, docstring) chỉ nhận "bot chết sau khi gửi". Thực tế: backend khởi động lại
  vài giây đúng lúc gửi (restart container, deploy) cũng đủ → ping hai lần sau 10 phút. Gợi ý: giữ danh sách id đã gửi
  trong bot và thử báo nhận lại ở các tick sau, hoặc kéo dài backoff.

## Đã kiểm và đúng

| Mục | Kết quả |
|---|---|
| Cờ tắt | backend không đăng ký `remind` (`app/discord/__init__.py:114`), danh sách công cụ mặc định không đổi (test); bot không tạo task, không có lệnh `/reminders`; route mới tồn tại nhưng trả 409 `REMINDERS_DISABLED` |
| Bot ↔ backend | chỉ HTTP qua `LocalAgentClient` (claim, sent, failed, list, cancel) |
| Chỉ người đặt huỷ | `ReminderService.cancel` so `creator_id` với `requester_id` do bot lấy từ `interaction.user.id`; route chỉ bot gọi được |
| Đúng kênh | `thread_id or channel_id` lấy từ phiên, không từ model; bot kiểm `channel.guild.id == guild_id` trước khi gửi |
| Không ping tập thể | `AllowedMentions(everyone=False, roles=False, users=[creator])` + `neutralize_mentions` chèn zero-width vào `@everyone`, `@here`, `<@` trong nội dung |
| Allowlist | kiểm ở tạo, liệt kê, huỷ, claim (đánh `failed`), và ở bot trước khi gửi; `*` → None → mọi server, rỗng → không server nào |
| Múi giờ | `at` không tz → gắn UTC+7; lưu `timestamptz` UTC; so `due_at <= now` với `now` từ Python UTC, không phụ thuộc đồng hồ container; model được dặn gọi `current_time` (giờ VN) trước |
| Claim/ack | `with_for_update(skip_locked)`, `finish` chỉ sửa hàng đang `sending`; 3 lần thử cách 1 phút rồi `failed`; quá 24 h → `missed` không gửi |
| Migration | `20261030_36 → 20261101_37`, chỉ thêm bảng + 2 index; downgrade xoá đúng thứ tự |
| Auth | `require_api_key` trên router + `admin_guard` khi include, giống các router Discord khác |
| Nội dung nhắc chèn vào đâu | chỉ vào tin Discord (đã trung hoà mention) và `/reminders list` (ephemeral); không quay lại model ở lượt sau; `text` phải lấy mọi con số và phần lớn từ ngữ từ lời người dùng (`fact_is_their_own`, `remember_tool.py:63-69`) |

## Đã chạy

- 72 passed trên ba tệp test (backend reminders, register, bot reminders), 1,2 s, không DB.
- Script thử hàm cổng (ngoài repo) cho bảng ở mục 2.
- Chưa chạy trên Discord thật, chưa chạy `SqlReminderStore` trên PostgreSQL (nhánh cũng tự nhận vậy).
