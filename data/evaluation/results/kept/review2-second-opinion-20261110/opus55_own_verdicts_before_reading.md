# Kết luận riêng TRƯỚC khi đọc "Bằng chứng đã có" / "Các hướng sửa" (opus, ed60401)

1 CÓ THẬT, nặng. turn_service.py:602-604; speaker_context.py:55-79 không có created_at (đã chạy: AttributeError cả 2 lớp).
  Kích hoạt: barrier khác None (migration :38 gieo cho mọi tenant cũ; mọi sửa/xoá tin trong kênh nghe cũng gieo) + tin @Ún là reply (bất kỳ reply nào, kể cả not_found).
  Hậu quả: 500 -> bot BackendUnavailableError -> "Backend is unavailable" (main.py:578-580). Lượt nằm running, hết lease 120s -> recover_stale requeue,
  nhưng không ai execute lại (chỉ bot của chính lượt đó gọi execute) -> head mồ côi -> mọi lượt sau trong kênh chờ 360s rồi "did not become ready" — kẹt tới khi control stop/restart (cancel_open).
  Tác dụng phụ trước khi nổ: prepare_turn đã chạy (lưu/quên).
  Sửa: lọc trong _resolve_reply_target (có ORM row): bot target dùng originating_turn.created_at (không phải delivery), kiểm thêm retracted; trả status rõ thay vì None. + catch-all trong execute -> fail().

2 CÓ THẬT, thấp-vừa. auth.py:148, conversations.py:16, research.py:44 dùng role trong JWT; ≤15 phút; chỉ khi auth bật. Sửa: một hàm effective_role đọc DB, cache theo request.

3 CÓ THẬT về logic, mức thấp: _safe_replay (542-554) và nhánh gửi lại (649-650, 707-718) chỉ xét barrier. Tombstone không kèm barrier chỉ khi invalidate_in reader=None (__deleted__).
  Bot bỏ qua answer khi status=completed (main.py:402-404); nhánh gửi lại gần như không tới được vì không ai execute lại head mồ côi. Nhưng nếu sửa lỗi kẹt bằng cách cho execute lại -> nhánh này sống lại -> phải sửa cùng lúc.

4 CÓ THẬT, cửa sổ rất hẹp (ms giữa chat_service.py:125 và :126), cần chính user gửi nhớ+quên song song. Sửa: lấy sent_at từ đồng hồ Postgres trong cùng transaction snapshot (đọc clock trước khi đọc state).
  Liên quan: so đồng hồ app (Windows) với barrier (Postgres trong Docker) — API chạy trên host, compose không có service API.

5 CÓ THẬT, thấp: auth_service.py:138-142 đếm rồi update, READ COMMITTED, không khoá. Gỡ được bằng X-API-Key (SERVICE role admin). Sửa: advisory lock (như bootstrap) hoặc SELECT ... FOR UPDATE các dòng admin (không dùng FOR UPDATE với count).

6 CÓ THẬT: ocr_job_service.py:211-214 xoá trong lúc chạy; _run :102 mkdir lỗi -> except -> finally _save (upsert, postgres_auxiliary_store.py:390) -> job hiện lại "failed"; GPU vẫn chạy hết trang hiện tại; _active giữ.
  Sửa: đặt cờ deleted/cancel, worker kiểm trước mỗi _save; _save bỏ qua nếu deleted; rmtree sau khi worker dừng.

7 CÓ THẬT: :212-213 chỉ rmtree khi job trong RAM. Sửa: dựng root từ runs_path/job_id sau khi kiểm job_id khớp ^ocr_[0-9a-f]{32}$ và resolve() nằm trong runs_path.

8 CÓ THẬT: ocr.py:18 dpi không giới hạn; OcrJobOptions (ocr_schema.py:4-7) không được dùng -> page_range/output_format cũng không kiểm. Sửa: Query(ge=72, le=400) + max_length page_range.
  Liên quan: _select_pages (:146-154) dựng cả tập trước khi kiểm biên (đã chạy: "1-5000000" trên PDF 3 trang 6 s, 281 MiB); create() đọc file không giới hạn kích thước (:47) khác documents (50 MB); render_pages giữ mọi trang PNG trong RAM.

9 CÓ THẬT: ocr_reader.py:51 next() lấy luật đầu; :21 regex chỉ +84/0. Đã chạy: hỏi "điện thoại và email" bỏ khối email; +1/+44/"84 9.." bị loại; nhãn "ĐT:", "Di động:", "Hotline" bị loại.

Lỗi mới:
A. Head mồ côi: mọi lối thoát khỏi vòng execute của bot ngoài failed/cancelled/completed (5xx, timeout, 409, giao hỏng retryable, complete hỏng) để lượt running/queued không ai claim -> kẹt kênh. Chỉ đọc.
B. Sửa tin của chính bot (tin tiến độ ⏳ bị edit thành câu trả lời) trong kênh nghe -> record_edit -> invalidate_in(reader) -> dời barrier kênh -> lịch sử lượt trước bị cắt, lượt đang xếp hàng thành STALE. record_edit không lọc is_bot, không so nội dung. Chỉ đọc.
C. _select_pages O(n) trước kiểm biên (đã chạy).
D. OCR create không giới hạn kích thước file.
E. Admin tạo dự án research với owner None (research.py:101) -> mất quyền khi bị hạ.
