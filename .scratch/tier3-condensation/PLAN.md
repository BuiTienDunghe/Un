# Kế hoạch sau ngày 28/08 — tự-áp-dụng, tầng tóm tắt, và nợ sổ sách

> **Trạng thái 28/08 tối: B và C ĐÃ LÀM XONG** (xem memory_design §13.8).
> Tầng 3 hạ cánh đủ bộ — 2 bảng, worker nền, đường đọc, mục dashboard, 12
> test, và một lỗi thật bắt được khi chạy trên dữ liệu thật (lời bot suýt
> thành trí nhớ: 10 mệnh đề → 2 sau khi vá). Nợ sổ sách xong cả ba điểm +
> `scripts.forget_member` + cảnh báo tồn đọng. Còn lại của kế hoạch này:
> **việc A** (chờ chủ dự án đổi 1 dòng .env rồi quan sát 1 tuần) và **việc D**
> (cấm khởi công sớm). Tầng 3 ship TỐI: cần `DISCORD_CONDENSATION_ENABLED=true`
> **và** `GEMINI_API_KEY` — thiếu cái nào worker cũng nói rõ rồi thoát.

Trạng thái nền: jobs 0-5 + benchmark §13.4 ĐẠT (P=0.94 · R=0.80 · forged=0 ·
verifier 16/16). Verifier BẬT. Sổ gốc đang ghi. Tự-áp-dụng chờ 1 dòng .env.

## Việc A — Vòng nghiệm thu tự-áp-dụng (tuần này, gần như 0 code)

Mục tiêu: chuyển bot từ "nhớ khi được duyệt" sang "tự nhớ có kiểm soát",
bằng quan sát chứ không bằng niềm tin.

1. A1. Để 2-5 câu khai thật đi qua pipeline (sở thích, biệt danh, ngày sinh) —
   verifier giờ chấm verdict trên từng ứng viên. Chủ dự án xem hàng duyệt:
   verdict có khớp trực giác không.
2. A2. Chủ dự án đổi `DISCORD_MEMORY_AUTO_APPLY_THRESHOLD=off → 0.8`
   (classifier an toàn không cho agent sửa file .env — đúng ranh giới).
   Điều kiện tự-áp ĐỦ: threshold + guard tất định + verdict entailment;
   delete luôn chờ người.
3. A3. Sau 3-5 ngày: soát `reviewed_by='agent'` trên dashboard — một lần
   revert là một điểm dữ liệu; >1 sai/tuần → nâng threshold hoặc đòi
   candidate_strength=strong.

Cổng đóng việc A: 1 tuần chạy tự-áp không có ca sai nào phải revert.

## Việc B — Tầng 3: tóm tắt định kỳ (ý tưởng gốc của chủ dự án) — ~3 buổi

Ba chốt cũ: §9.7 bảng lô + UI v2 · §9.4 đường đọc · benchmark verifier ✅ (đã mở).
Trigger thay sàn 24h: **≥ 20 tin chưa xử lý mỗi kênh** (§13.5).

### B1. Quyết định đã chốt từ trước, giữ nguyên
- Model: **Gemini 2.5 Flash** (chủ dự án đã quyết 27/08 — "không có gì nhạy
  cảm, tôi muốn gemini làm"); key qua header + che secret log (0d) đã xong.
  Mất mạng vô hại nhờ bảng lô có trạng thái; KHÔNG fallback model local ở v1
  (giữ invariant #7 — GPU là của đường trả lời).
- Chỉ kênh guild-public mới vào sổ gốc (guard 28/08) → chỉ chúng được tóm tắt.

### B2. Schema (additive + downgrade, bất biến #3)
Bảng `discord_condensations`: guild_id, channel_id, span_start/end_message_id,
span_start/end_at, message_count, speaker_ids (mảng — phục vụ xoá-theo-người
§9.5: bản tóm tắt chứa ai thì xoá người đó = xoá/regenerate cả span),
model, prompt_version, content, status (pending/completed/failed/stale/deleted),
error, created_at/updated_at. UNIQUE (channel_id, span_start_message_id).

### B3. Worker nền (không đụng đường trả lời — bất biến #7)
Vòng lặp trong memory worker (hoặc script riêng khuôn backup_worker): mỗi X
phút, per (guild, channel): đếm tin sổ gốc mới hơn span đã tóm gần nhất; ≥20
→ tạo dòng pending (giữ chỗ, idempotent) → gọi Gemini NGOÀI transaction
(bất biến #2) → ghi content + completed. Prompt bắt buộc giữ gán lời
("A nói…, B nói…" theo author_id — §7.5) và cấm suy diễn ngoài span.

### B4. Đường đọc (§9.4) — v1 tối giản, đo rồi mới nới
Nạp BẢN TÓM TẮT MỚI NHẤT của đúng kênh phiên vào khối system (sau attribution,
trước quy tắc — thứ tự đã đo §13.7), trần ~300 token. KHÔNG trích fact từ bản
tóm tắt (fact ledger chỉ ăn lời nói trực tiếp — chặn ảo giác Gemini thành
"sự thật đã xác nhận"). search_recap/tool để v2 nếu số đo đòi.

### B5. UI v2 (§9.7 — invariant #6)
Dashboard thêm mục Tóm tắt: xem theo kênh, nút xoá + regenerate. Tóm tắt dùng
ngay không chờ duyệt (khác fact) NHƯNG luôn hiện diện + thu hồi được.
Tin trong span bị Discord xoá → đánh dấu stale → regenerate bỏ tin đã xoá.

### B6. Eval trước khi bật (khuôn §13.4)
Thêm ~5 ca vào bộ e2e: (1) span 20 tin → summary chứa các ý chính định danh
đúng người nói; (2) không rò nội dung tin-đã-xoá sau regenerate; (3) không
bịa điều không có trong span; (4) trigger đếm đúng ngưỡng 20; (5) mất mạng
→ lô failed, không kẹt pipeline. Cổng bật: 5/5 + soát tay 3 bản tóm tắt thật.

Thứ tự thi công B: migration+worker (1 buổi) → đường đọc+dashboard (1 buổi)
→ eval+chạy thật+bật (1 buổi).

## Việc C — Nợ sổ sách (1 buổi, làm xen khi chờ A/B)
1. Script `scripts.forget_member` — xoá-cứng theo người trọn gói: sổ gốc,
   fact ledger, candidates, condensation spans chứa người đó, mirror Qdrant.
2. 3 điểm soi-lỗi hoãn (SPEC 28/08): token thứ tự sửa tin; job v1 tồn đọng
   fail-terminal; thứ tự ổn định khối nạp sổ cái.
3. Cảnh báo tồn đọng (>500 tin chưa tóm tắt / job failed) vào
   check_operational_alerts.

## Việc D — Chờ số liệu, KHÔNG làm trước
- Dense retrieval: chỉ khi paraphrase Recall@5 thật < 0.60 (tripwire
  recall-para-02 đang gác).
- Mở từ vựng tiếp: theo ca thật (quy trình một-đêm đã chứng minh).
- Đo lại tải khi lưu lượng tiến về 100 tin/ngày/server.

## Ngoài mảng trí nhớ (backlog cũ, chưa xếp lịch)
T5 retry lease · T7 hợp nhất ingestion · T12/T13 đánh bóng · D2 distillation.
