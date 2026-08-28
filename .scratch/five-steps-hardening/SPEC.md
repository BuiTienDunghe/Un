# Năm bước hoàn thiện memory & chat — spec thi công (28/08/2026)

Nguồn: chẩn đoán hội thoại 20 lượt guild 1542282413827424297 (26-27/08) — echo-lock,
lỗ từ vựng ca #2/#3, lỗ kho tài liệu xuyên server, dòng rác conf 0.000.
Lệnh chủ dự án: "hãy chủ động làm cả 5 bước rồi chủ động test đến khi hệ thống hoàn thiện đi".
Push: CHƯA — chờ lệnh push riêng.

## Bước 1 — Lời dặn chống tự-vọng ✅ (đo xong)

- `discord_bot/system_prompt.md` viết lại: bỏ câu riêng tư dễ vặn ngược, thêm luật
  emoji/không-kết-bằng-câu-hỏi. File được MOUNT vào container → chỉ cần restart bot.
- Quy tắc trí nhớ đặt ở `DISCORD_SPEAKER_SYSTEM_INSTRUCTION` (backend, tin system
  CUỐI) — vị trí quyết định sức nặng: đo 28/08 trên 5 câu hỏng với lịch sử nhiễm sẵn:
  baseline 1/5 → rules-cuối-file 10/15 → rules-cuối-khối-system 13/15.
  Câu "không dùng lại câu trả lời đã bị chỉ ra là sai" nhắm thẳng attractor.
- Chốt 13/15 cho prompt-only; cổng nghiệm thu cuối = 5/5 khi có sổ cái (bước 3+4).

## Bước 2 — Khoá công cụ tài liệu theo server

Bằng chứng: lượt 5 guild 2 gọi `search_documents` với truy vấn tìm thông tin cá
nhân của một thành viên, trên kho tài liệu riêng của chủ. Kho là MỘT corpus
toàn backend, không phân guild.

- Setting mới `discord_agent_tools_guild_allowlist` (chuỗi id phẩy, rỗng = mọi guild
  như cũ). `.env` đặt = `1442208819785502762` (guild nhà).
- `DiscordTurnService`: `use_tools = agent_tools_enabled AND (allowlist rỗng OR
  session.guild_id ∈ allowlist)`. Guild ngoài allowlist rơi về chat thường
  (đường degrade có sẵn, đã có test "missing agent service degrades to plain chat").

## Bước 3 — Mở từ vựng trí nhớ (v2) + vá dòng rác

Bằng chứng: lượt 12 (một thành viên khai ngày sinh của mình và của người kia —
ngày cụ thể KHÔNG ghi vào tài liệu công khai này) bị filter phán
`no_durable_fact`; trà sữa (guild 1) + 2 ca ngày sinh = 3 ca thật chết ở cửa lọc.

- Khoá mới trong `DISCORD_MEMORY_FACT_KEYS` (extractor): `user.birthday`,
  `user.favorite_drink`, `user.favorite_food` (+ types + worker `_target_memory_types`).
- Rule filter mới: câu KHẲNG ĐỊNH ngày sinh/sở thích ăn uống → candidate
  (câu HỎI vẫn rơi vào question_only như cũ — lượt 13/17/18 đúng là no_op).
- `_fact_keys_for_reason`: durable_preference += favorite_drink/favorite_food;
  reason mới của rule ngày sinh dùng vocabulary reason có sẵn phù hợp
  (không thêm reason code mới nếu tránh được — tránh đụng CHECK constraint).
- Schema version: `v1` → `v2` (settings + extractor chấp nhận). Key idempotency đổi
  theo → cho phép tái-trích lượt 12 production thành candidate v2 (cơ chế
  `create_job_and_outbox` idempotent, uq theo (turn, schema_version)).
- Vá no_op rỗng: `record_extractor_proposal` với operation="no_op" → decision="no_op"
  (terminal), không bao giờ "deferred"; `list_pending` lọc thêm canonical_fact != ''.
  Sửa dữ liệu: dòng rác lượt 7 (conf 0.000, fact rỗng) chuyển decision no_op.
- Hearsay giữ nguyên nguyên tắc: PA nói hộ ngày sinh Dũng → KHÔNG tự trích
  (trusted_subjects chỉ chứa tác giả). Ngày sinh Dũng seed tay qua candidate
  operator + approve (auditable, revert được — bất biến #6).
- Auto-apply GIỮ off; verifier GIỮ dark — cổng vẫn là benchmark --with-extractor
  chạy đêm (ngoài phạm vi 5 bước, ghi rõ trong báo cáo).

## Bước 4 — Sổ cái nạp theo guild, không chỉ theo người hỏi

Bằng chứng: PA hỏi về Dũng / Dũng hỏi điều PA khai — lọc theo người-đang-hỏi chặn
đúng ca dùng thật. Fact ledger là lời tự khai công khai + người duyệt — ranh giới
riêng tư nằm ở GUILD, không ở người hỏi.

- `list_active_context_memories`: bỏ lọc subject theo người hỏi trên đường trả lời —
  nạp fact active của guild (scope guild + member_in_guild), limit 10, mới nhất trước.
  Cách ly XUYÊN GUILD giữ nguyên tuyệt đối (attrib-04 tiếp tục pin).
- Cập nhật test 0c + case eval attrib-03 theo hợp đồng mới (ghi chú đổi ngữ nghĩa
  vào memory_design §13); attrib-04 (xuyên guild) không đổi.

## Bước 5 — Sổ gốc (job 1) + tra lịch sử (job 2)

Ba quyết định mở, chốt bằng số đo đếm thụ động (2 ngày, 2 guild, bot ≈ nửa lưu lượng):

1. **§9.3 is_bot = CÓ GHI**, cột `is_bot` đánh dấu. Lý do: tầng tóm tắt cần lời bot
   để giữ mạch hội thoại; rủi ro "ảo giác thành bằng chứng" chặn ở chỗ khác — trích
   xuất memory KHÔNG BAO GIỜ ăn dòng bot (filter đã có reason bot_or_system_message),
   search_history trả nguyên văn kèm nhãn người nói.
2. **§5.3 content_original**: `content` là ô sửa được (bản mới nhất); `content_original`
   NULL đến lần sửa đầu tiên thì giữ bản đầu vĩnh viễn; `edited_at`. Bất biến #3 áp
   cho CẤU TRÚC — ghi rõ trong docstring migration.
3. **§9.5 xoá**: `deleted_at` soft-delete theo sự kiện xoá của Discord (bot bắt
   on_raw_message_delete); search loại `deleted_at IS NOT NULL`. Hard-delete theo
   người (per author_id) làm được bằng DELETE thẳng vì FTS là chỉ mục theo-dòng,
   không cần rebuild — script vận hành sẽ bổ sung sau, thiết kế ghi tại đây.

Thi công:
- Migration `discord_channel_messages`: guild_id, channel_id, thread_id?,
  discord_message_id UNIQUE, author_id, author_display_name, is_bot, content,
  content_original?, content_tokens tsvector('simple' trên tokenize_vietnamese),
  sent_at (SUY TỪ SNOWFLAKE lúc ghi — §5.2), reply_to_message_id?, edited_at?,
  deleted_at?, created_at. Index GIN(content_tokens) + (guild_id, channel_id, sent_at).
  Bảng RIÊNG khỏi discord_session_turns (§5.1 — hàng đợi ≠ sổ).
- Bảng `discord_channel_policies`: (guild_id, channel_id) unique, listening_enabled,
  enabled_by, enabled_at, disabled_at — audit bất biến #6; upsert "env" khi endpoint
  thấy kênh lần đầu (env vẫn là nguồn bật/tắt như hiện tại).
- Endpoint bot-facing (require_api_key, theo khuôn discord_sessions.py):
  POST /api/discord/history/messages (ghi), POST .../messages/{id}/edit,
  POST .../messages/{id}/delete. Bot gọi fire-and-forget từ on_message (cạnh
  listener.record — nuốt lỗi, không bao giờ chặn trả lời) + handler edit/delete mới.
- Tìm kiếm: Postgres FTS (phương án (c) §13.5 — tăng dần, KHÔNG rebuild, không có
  vách 4.6s; đo latency khi test). Service mới theo khuôn "service thứ hai" §6.1,
  guild filter nằm trong SQL.
- Công cụ `search_history(query, author?, days?)`: thêm vào AGENT_TOOLS + guide;
  guild_id do SERVER bơm qua tool_context (respond_with_context → run → _execute_tool),
  không bao giờ tin guild_id từ model. Web path không có tool_context → công cụ trả
  lỗi "chỉ dùng trong Discord". Ngân sách công cụ net-zero (§8: search_memory đã xoá).
- Eval: 3 case PENDING "job2" (recall-verbatim-01/02, recall-para-02) nối vào máy
  thật — cổng §13.4 verbatim Recall@5 ≥ 0.90.

## Soi lỗi đối kháng 28/08 — 29 phát hiện xác nhận, xử lý

16 điểm sửa ngay trong commit này (allowlist fail-closed với sentinel `*`,
tách cổng ghi sổ khỏi file đếm, 9 câu hearsay thân tộc lọt lookbehind + mẫu
"là ngày <số>", tombstone cho xoá-đến-trước-ghi, remap dữ liệu trong downgrade
migration 29, savepoint chống race bảng chính sách, kẹp `days`, chặn id lỗi,
salt snowflake eval, nâng ngân sách nạp sổ cái 10→50, kill-switch
`listening_enabled` có hiệu lực, chỉ ghi kênh công-khai-với-@everyone, giữ
tham chiếu task fire-and-forget, fail-open sự kiện raw khi cache trượt, lộ
`author_id` cho công cụ, tẩy PII khỏi mọi file commit + viết lại lịch sử
local trước push).

3 điểm HOÃN có chủ ý:
1. Hai lần sửa tin liên tiếp có thể ghi ngược thứ tự (thiếu token
   `edited_timestamp` xuyên các chặng) — hiếm ở cỡ 3 server; thiết kế sửa đã
   ghi trong báo cáo soi lỗi.
2. Job v1 tồn đọng gặp worker cấu hình v2 sẽ chết theo vòng retry thay vì
   fail terminal có mã lỗi — ĐO trước deploy 28/08: bảng jobs chỉ có
   28 completed, 0 queued/retrying → không có nạn nhân; refactor để sau.
3. Khối sổ cái nạp theo recency thay vì thứ tự ổn định (subject, fact_key) —
   chấp nhận vì trần 50 gần như không bao giờ cắt ở cỡ hiện tại.

## Nghiệm thu cuối — KẾT QUẢ 28/08 (~02:45 +07)

1. ✅ Suite backend **716** + root **65** xanh; `alembic check` sạch; eval 21 ca:
   18 PASS · 2 FIXED · 1 KNOWN-FAIL chủ ý (tripwire dense).
2. ✅ Tái-trích lượt 12 dưới v2 TRÊN PRODUCTION: filter `personal_fact` →
   extractor 9b đề xuất `create user.birthday` đúng chủ thể người nói
   (conf 1.000, deferred) và KHÔNG trích ngày sinh người kia từ lời nói hộ
   (trusted-subject giữ). Approve qua API thật; fact người còn lại seed đường
   operator (candidate `operator-20260828`, revert được từ dashboard).
3. ✅ Endpoint sổ gốc sống: ghi ✓ / xoá ✓ / thiếu khoá → 401 ✓.
4. ✅ **3/3 qua đường ống production** (phiên MỚI kênh smoke guild 2, không
   lịch sử): hỏi hộ người khác ✓, hỏi sinh nhật mình ✓, hỏi bằng tài khoản
   chủ ✓ — bot dẫn nguồn "trí nhớ dài hạn đã được xác nhận". Replay mức
   model: lịch sử nhiễm độc 13/15 (baseline 1/5), phiên sạch 9/9.
5. ✅ Bot container rebuild + nối Gateway; đếm thụ động vũ trang 2 kênh; ghi
   sổ gốc chạy cạnh bộ đếm (49 tin/2 ngày trong file đếm). Phiên smoke
   `smoke-final-check` giữ lại làm audit, xoá lúc nào cũng được.

Còn treo sau ngày này: ~~pha `--with-extractor`~~ → **XONG rạng sáng 28/08**:
xây pha model-thật vào runner (chuỗi target theo-guild), 2 vòng đo. Vòng 1
P=0.89/R=0.40 chỉ đúng nút thắt (tầng lọc regex) + tóm lỗi verifier thiếu
`think:false` (content rỗng → mọi verdict unknown — sẽ vô hiệu tự-áp-dụng nếu
bật mù). Mở 6 nhóm mẫu lọc + 12 dòng fixture → Vòng 2 **P=0.94 · R=0.80 ·
forged=0 · verifier 16/16 entailment (+contradiction đúng ca sai)** — GATE
§13.4 ĐẠT. Verifier BẬT trong .env; tự-áp-dụng = 1 dòng threshold chờ chủ dự
án. Kèm: `search_history` chế độ không-query → N tin mới nhất (tóm tắt gần
đây). Vẫn hoãn: tầng 3/Gemini; 3 điểm soi-lỗi ở trên; tripwire dense.
