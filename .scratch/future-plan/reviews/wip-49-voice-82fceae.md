GỘP ĐƯỢC

# Duyệt `wip/49-voice` (82fceae) — nghe tin thoại Discord

Đọc `git diff main...wip/49-voice` và code quanh đó; chạy `tests/test_voice_server.py`, `tests/test_discord_voice.py`,
`tests/test_supervisor.py`, `tests/test_decided_server.py` (63 qua) và `backend/tests/test_voice_router.py` (13 qua), không GPU,
không tiến trình con thật. Không lỗi chặn. Một điểm trung bình phải đóng **trước khi gắn model thật**.

## Bản chất

Nhánh này xây đường ống: bot lấy tệp ghi âm, đưa cho backend, backend đưa cho một "cửa" nhỏ trên máy, cửa gọi một tiến trình con giữ
model nghe rồi trả chữ về; chữ đó đi vào lượt như người dùng gõ. Model nghe chưa chọn nên tiến trình con hiện chỉ báo lỗi, và cả
chuỗi tắt khi chưa đặt địa chỉ cửa và danh sách server. Chỗ cần biết: giới hạn thời lượng chỉ được kiểm ở bot, dựa vào con số do
máy khách của người gửi tự khai, nên khi có model thật, một tệp 8 MB dài hàng chục phút vẫn lọt tới card.

## Đã kiểm, đúng như nhánh nói

| Câu hỏi | Kết quả | Bằng chứng |
|---|---|---|
| Tắt mặc định gửi gì ra ngoài, mở tiến trình nào | Không | Bot: danh sách rỗng → trả lời lịch sự trước `voice.read()` (`main.py:175`); backend: `VOICE_URL` trống → 501 trước `httpx.post` (`voice.py:28`); supervisor: `needs=("VOICE_URL","")` với `bool(value)` → không chạy khi trống |
| Danh sách server | Dùng lại `parse_docs_guild_allowlist`/`docs_allowed`; DM bị từ chối | `main.py:112,175,199` |
| Kích thước | Ba phía: bot `size` (`:177`), backend `len(audio)` sau giải base64 (`voice.py:33`, trường base64 ≤ 12 M ký tự ⇒ ≤ 9 MB), cửa `Content-Length` + đọc đủ (`voice_server.py:116–130`) | |
| Tệp tạm, đường dẫn | Đường dẫn do cửa tự tạo (`NamedTemporaryFile`), máy khách chỉ gửi byte; `/transcribe` so khớp tuyệt đối; xoá trong `finally`; `log_message` tắt | `voice_server.py:66–76,109` |
| Cửa | Chỉ `127.0.0.1:8378`, không xác thực — giống `decided_server` | `voice_server.py:155` |
| `ModelProcess` | `classify` → `ask({"text": ...})` ghi đúng dòng JSON cũ; `name` mặc định "decided"; test decided xanh | `decided_server.py:142–148` |
| Con chết ngay (stub `_load` raise) | Pump đặt `None` → `ModelUnavailable` tức thì → 503 → 502 → bot xin lỗi; không treo 150 s | `decided_server.py:127–129,164` |
| Thời hạn lồng nhau | cửa 150 < backend 170 < bot 180 | |
| Bản chép là tin người dùng | Đúng bản chất: người nói chính là tác giả tin, khác ảnh (chữ của bên thứ ba cần bọc "dữ liệu, không phải lệnh"); cắt 4 000 ký tự; không vào sổ lịch sử vì `message.content` rỗng | `main.py:185,861` |
| discord.py API | `Attachment.is_voice_message()`, `.duration` có từ 2.3; cài 2.7.1, pin `>=2.4` | |

## Điểm cần biết

1. **Trung bình — thời lượng chỉ kiểm ở bot, từ số do máy khách khai.** `discord_bot/main.py:177` dùng `voice.duration` = `duration_secs`
   mà ứng dụng của người gửi ghi vào lúc tải lên. Backend (`voice.py`) và cửa (`voice_server.py:30`, chính dòng ghi chú "không tin bot")
   chỉ kiểm byte. Kịch bản: một tệp opus 8 MB ở 32 kbps (~30 phút) gửi kèm `duration_secs=10` qua được bot, tới tiến trình con, giữ card
   tới khi `REPLY_TIMEOUT_SECONDS` 150 s giết nó, rồi lần sau phải nạp lại từ đầu. Hôm nay không chạy được vì `_transcribe` là stub; bộ
   giải mã để đo thời lượng thật nằm đúng chỗ đó. Việc cần làm trước khi gắn model: đo thời lượng ở con (hoặc ở cửa) và từ chối quá
   180 s. Không chặn gộp vì tính năng tắt và chưa có model.

2. **Thấp–trung bình — khảo sát trộn hai cột ở dòng Qwen3-ASR** (`voice-survey.md:28`). Tra thẻ HF 02/11: 1,7B đạt 6,62 trên bộ
   "Fleurs†" mở rộng (có tiếng Việt); 0,6B đạt 7,57 trên bộ FLEURS lõi 12 ngôn ngữ (**không** có tiếng Việt), còn trên Fleurs† là
   **10,37**. Cặp đúng để so là 6,62 / 10,37. Cách C (0,6B) đang trông gần 1,7B hơn nguồn cho phép; đổi được quyết định giữa A–E.
   Các dòng khác đã tra lại (Zipformer: giấy phép và 4 số VLSP đúng; EraX: "khoảng 12%" sơ bộ, chưa bảng, đúng; PhoWhisper: BSD-3,
   844 giờ, 5 cỡ đúng; trang GitHub không nói large dựa trên v2 — có thể từ bài báo, chưa tra).

3. **Thấp — hành vi khi tắt có đổi một câu.** Danh sách rỗng: tin thoại trả lời Ún nay nhận `VOICE_NOT_ENABLED` thay vì
   "Hãy gắn kèm câu hỏi sau @Ún." như main. Không mạng, không tiến trình; chỉ là câu chữ.

4. **Thấp — `tools/voice_server.py:74`.** Ghi chú "the temp folder's cleanup gets it" sai trên Windows: `%TEMP%` không tự dọn. Trường
   hợp thực tế hẹp: `_stop()` đợi con chết trước khi `finally` chạy nên thường xoá được; chỉ sót khi `child.wait(timeout=20)` hết hạn mà
   `kill()` chưa giải phóng tay cầm tệp.

5. **Chưa kiểm trên Discord thật** (khảo sát tự nhận): tin thoại gửi dạng *trả lời* có đưa Ún vào `message.mentions` để qua cổng
   `mentioned_in` hay không. Nếu không, toàn bộ đường kích hoạt không tới được.

## Ticket có nói quá không

Không. CHANGELOG, README và khảo sát đều ghi "chưa chọn model nên chưa chạy thật", "chưa thử trên Discord thật". Câu "Quá 8 MB hoặc
180 giây ... Ún đáp một câu lịch sự" đúng từ phía bot nhưng với mức tin cậy ở điểm 1.
