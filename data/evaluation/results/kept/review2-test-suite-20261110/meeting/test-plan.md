# Kế hoạch test chung review2 (vòng 3)

Người gộp: Fable (`claude-fable-5-2`). Chờ Opus ký duyệt. Nguồn: `fable-plan.md`, `opus-plan.md`, hai bản phản biện, `DECISIONS.md`. Chỗ nào các bản mâu thuẫn thì theo `DECISIONS.md`.

**Bản chất:** mỗi lỗi thành một tình huống "nếu người dùng làm X thì phải thấy Y". Ca đang hỏng mang dấu "biết là hỏng" và phải hỏng vì đúng lỗi đó; khi lỗi được sửa bằng bất kỳ cách hợp lệ nào, ca đó phải tự xanh. Ca nào không viết được như vậy thì để ngoài bộ, có ghi lý do.

## 1. Nguyên tắc

**Dấu xfail**
1. Viết `@pytest.mark.xfail(strict=True, raises=KnownBug, reason="review2 <mã>: …")`. `KnownBug(AssertionError)` đặt trong `review2_support.py`, chỉ được ném ở dòng kiểm triệu chứng (helper `known_bug(điều_kiện, lời)`). Tiền đề dùng `assert` thường, nên tiền đề hỏng là đỏ thật.
2. R1: chỉ bắt đúng `AttributeError` tại lời gọi execute rồi đổi thành `KnownBug`. Không dùng `raise_server_exceptions=False` cho ca R1.
3. Chỉ tham số đang sai mang dấu, qua `pytest.param(..., marks=...)`.
4. Một ca, một mã. Mỗi ca kiểm kết quả (HTTP, dòng DB, prompt gửi model, tệp trên đĩa), không kiểm cơ chế.
5. Với mỗi ca xfail, người viết vá tạm bằng `monkeypatch` trong một lần chạy tạm để thấy XPASS, không sửa tệp ứng dụng, rồi ghi nhật ký. Ca không vá được thì chạy không dấu, chép dòng lỗi, và ghi rõ "chưa thấy lật".

**Cô lập**
- N2, R3: tạo vết xoá mà **không dời mốc kênh**, bằng cách *sửa* một tin chưa vào sổ và chưa được "nhớ" (vết nằm ở `__deleted__`). Lấy "mốc kênh không đổi" làm tiền đề. Xoá kèm guild/kênh thì dời mốc, không dùng cho các ca này.
- A: tạo lượt mồ côi bằng đường riêng (giao tin hỏng, bot chết, hết hạn chờ, lỗi chèn vào bước chuẩn bị), không mượn crash của R1.
- F: có ca đối chứng không lệch đồng hồ (F-0) cùng kịch bản, để ca lệch chỉ hỏng vì lệch.

**Mức chạy**

| Ký hiệu | Mức | Container |
|---|---|---|
| P | Python thuần, `OcrJobService` với `tmp_path` và store giả | không |
| M | app nhỏ `FastAPI()` + router OCR + store giả (mẫu `test_ocr_evidence_api.py:31`) | không |
| D | service trên Postgres thật | có |
| H | `TestClient(app)` + Postgres (`v2client`, hoặc `client` + `auth_on`) | có |
| B | bot với `FakeBackend` | không |
| T | tích hợp: `DiscordConversationGateway` + `LocalAgentClient` thật nối app thật qua `httpx.ASGITransport`, Discord giả | có |

**Giả lập**
- *Đồng hồ:* lệch ±30 giây, chỉ phía ứng dụng: thay `datetime` cấp module của `app.discord.repositories`, `app.services.chat_service` và `_utc_now` của store. Lệnh quên gọi thật nên mốc theo giờ Postgres. Không ghi tay `barrier_at`. Đồng hồ Discord: dựng snowflake lệch ±30 giây.
- *5xx:* backend: chèn lỗi vào `build_discord_speaker_context`, hoặc cho `OllamaClient.chat` ném ở lần đầu; client dựng `TestClient(client.app, raise_server_exceptions=False)` không `with`. Mức T: `ASGITransport(raise_app_exceptions=False)`.
- *Bot chết:* execute xong, không complete; lùi `lease_expires_at`; cho `recover_stale` chạy; **sau đó** lùi mọi cột giờ của lượt 1 giờ.
- *Hai request đồng thời:* R5 bọc `_public` bằng `Barrier(2)` chờ tối đa 2 giây, bỏ qua `BrokenBarrierError`. Fixture dựng và kiểm đúng hai admin trong cả bảng. R6 cho `recognize_png` chờ một `Event`.
- *Khởi động lại:* `OcrJobService` thứ hai trên cùng `runs_path` và store.
- *Windows giữ khoá tệp:* giữ một handle mở trong thư mục job khi xoá; dấu xfail có `condition=sys.platform == "win32"`.
- *Path traversal:* HTTP với `%2e%2e` và `..%5C..%5Cx` (TestClient gộp `/..` trước route), đồng thời gọi thẳng `service.delete(...)`.
- *Tài nguyên:* không cho đường lỗi nổ thật. R8 chỉ dùng PNG với `MOCK_OCR`; C đo đỉnh `tracemalloc`, không đo giờ.

**Dùng lại:** `v2client`, `send`, `queue`, `ledger`, `channel_barrier` (`test_source_memory_discord.py`); `memory`, `reader` (`test_source_memory.py`); `auth_on`, `register`, `bearer` (`test_auth_api.py`); `Discord`, `FakeSource`, `FakeBackend`, `quick`, `run` (`tests/test_discord_progress_message.py`). Chỉ import fixture và helper, không import hàm `test_*`.

**`review2_support.py` thêm:** `KnownBug`, `known_bug`, `snowflake(at=)`, `enqueue(reply_to=)`, `finished_turn`, `seed_history_barrier`, `turn_row`, `orphan_by_dead_bot`, `edit_unledgered` (kiểm luôn tiền đề mốc không đổi), `app_clock(offset)`, `MemoryOcrStore`, `BlockingOcr`, `bot_on_app` (bộ nối mức T).

## 2. Bảng ca

Tệp ở `backend/tests/`: **dt** `test_review2_discord_turns.py`, **bb** `test_review2_bot_backend.py`, **ld** `test_review2_ledger.py`, **ck** `test_review2_clocks.py`, **au** `test_review2_auth.py`, **oj** `test_review2_ocr_jobs.py`, **oa** `test_review2_ocr_access.py`, **or** `test_review2_ocr_reader.py`. Ở `tests/`: **bt** `test_review2_bot_turns.py`.

Cột "Hiện tại": "(chạy)" là đã tái hiện bằng chạy thật (sổ đo 10/11, hoặc Python thuần ở vòng 1); còn lại là dự đoán từ đọc code, người viết phải xác nhận theo nguyên tắc 5.

### Reply, phát lại, thử lại (dt)

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| R1-1 | reply | server có mốc `__history__`; reply vào tin người / đáp án bot / mã không tồn tại, đều cũ hơn mốc (3 tham số) | 200, model được gọi, chữ tin gốc không vào prompt | H | xfail R1 (chạy) | dt |
| R1-2 | reply | server có mốc; reply vào tin người / đáp án bot mới hơn mốc (2 tham số) | 200, chữ tin gốc có trong prompt | H | xfail R1 | dt |
| R1-3 | reply | server chưa có mốc; reply tin có thật / tin ở phiên khác / mã không tồn tại (3 tham số) | 200; tin có thật thì chữ vào prompt; hai loại kia không lỗi | H | đạt | dt |
| R1-4 | reply | tin gốc từng được "nhớ" rồi bị xoá (mốc kênh dời); reply vào nó | 200, chữ đã xoá không vào prompt | H | xfail R1 | dt |
| N2-1 | reply | tin gốc chưa vào sổ bị sửa (vết ở `__deleted__`), mốc kênh không đổi; reply vào nó | chữ cũ của tin gốc không vào prompt | H | xfail N2 | dt |
| N2-2 | reply | như N2-1, nhưng reply vào đáp án bot của tin đó | cả câu hỏi gốc lẫn đáp án cũ không vào prompt | H | xfail N2 | dt |
| R3-1 | phát lại | lượt đã xong; tin hỏi (chưa vào sổ) bị sửa; execute lại | không trả đáp án cũ | H | xfail R3 (chạy) | dt |
| R3-2 | gửi lại | đáp án đã lưu, giao hỏng (`fail` thử lại được); tin hỏi (chưa vào sổ) bị sửa; execute lại | không trả đáp án cũ | H | xfail R3 | dt |
| R3-3 | gửi lại | như R3-2 nhưng mốc kênh đã dời: tin đã "nhớ" bị sửa / tin bị xoá kèm kênh (2 tham số) | không trả đáp án cũ | H | đạt | dt |
| R3-4 | phát lại | lượt đã xong, execute lại: không ai sửa gì / sau một lần "quên" (2 tham số) | trả đúng đáp án cũ / không trả đáp án cũ | H | đạt | dt |
| N4-1 | thử lại | "Hãy quên…", model hỏng lần đầu, execute lại | model được gọi với biên nhận "đã quên"; không có câu "tin đã bị xoá/sửa" | H | xfail N4 | dt |
| N4-2 | thử lại | "Hãy quên…", đáp án đã lưu, giao hỏng, execute lại | trả đúng đáp án đã lưu | H | xfail N4 | dt |
| N4-3 | thử lại | như N4-1; giữa hai lần, chính người đó "nhớ" một điều mới ở kênh khác | điều mới còn nguyên (quên đúng một lần) | H | đạt (nhờ chính lỗi N4; sửa N4 xong vẫn phải đạt) | dt |
| N4-4 | thử lại | "Hãy nhớ…", model hỏng lần đầu, execute lại | đúng một nguồn được lưu, biên nhận "đã lưu" | H | đạt | dt |
| A-1 | lượt | bước chuẩn bị lượt ném lỗi bất ngờ (chèn lỗi) | không 5xx; sau tối đa `max_attempts` lần gọi lại, lượt kết thúc và lượt sau cùng kênh chạy | H | xfail A | dt |
| A-2 | lượt | kênh một có lượt mồ côi: xét kênh hai / gọi `cancel-open` rồi gửi tin ở kênh một (2 tham số) | chạy bình thường | H | đạt | dt |
| A-3 | lượt | lease hết, bot gọi lại execute chính lượt đó | gửi lại đáp án đã lưu, model không bị gọi lần hai | H | đạt | dt |

### Lượt mồ côi, bot nối backend (bb, bt)

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| A-4 | nối | tin thường qua bộ nối, không có sự cố | người hỏi nhận đáp án; lượt `completed` | T | đạt (chứng minh bộ nối) | bb |
| A-5 | mồ côi | tin 1: Discord từ chối nhận đáp án (lỗi 500); gửi tin 2 cùng kênh | tin 2 được trả lời trong hạn chờ | T | xfail A | bb |
| A-6 | mồ côi | tin 1: backend trả 5xx một lần lúc execute; gửi tin 2 cùng kênh | tin 2 được trả lời trong hạn chờ | T | xfail A | bb |
| A-7 | mồ côi | tin 1: model hỏng lần đầu, bot hết hạn chờ khi lượt còn `queued`; gửi tin 2 | tin 2 được trả lời trong hạn chờ | T | xfail A | bb |
| A-8 | mồ côi | bot chết giữa lượt (xem "Giả lập"), đã 1 giờ; gửi tin 2 qua bot | tin 2 được trả lời trong hạn chờ | T | xfail A; **xem băn khoăn 1** | bb |
| A-9 | bot | execute trả `completed` / `failed` / tin gốc bị xoá trước khi giao (3 tham số) | không gửi lại / báo lỗi cho người hỏi / lượt đóng không thử lại | B | đạt | bt |

### Sổ lịch sử (ld)

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| B-1 | sổ | bot sửa tin "⏳" của mình trong lúc một lượt khác đang xếp hàng | lượt đó được trả lời bình thường, lịch sử trước đó còn trong prompt | H | đạt (nhờ sửa B) | ld |
| B-2 | sổ | người sửa nội dung / xoá một tin đã nằm trong lịch sử (2 tham số) | chữ cũ của tin đó không vào prompt của lượt sau | H | đạt | ld |

Bot sửa hoặc xoá tin của mình, và sửa không đổi chữ, đã có trong `test_source_memory_discord.py`; không viết lại.

### Đồng hồ (ck)

`reason` của F-1, F-3, F-4 ghi đánh đổi: nếu so theo giờ nhận, tin gửi trước nhưng tới muộn sẽ lọt.

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| F-0 | đồng hồ | không lệch; kịch bản của F-1 và F-2 | mã đã quên không vào prompt; tin mới được trả lời thường | H | đạt | ck |
| F-1 | đồng hồ | ứng dụng nhanh 30 giây; nói mã, quên, hỏi lại (Discord) | mã không vào prompt | H | xfail F | ck |
| F-2 | đồng hồ | ứng dụng chậm 30 giây; quên rồi gửi tin mới (Discord) | tin mới được trả lời thường, không ra câu "tin đã bị xoá/sửa" | H | xfail F | ck |
| F-3 | đồng hồ | snowflake nhanh 30 giây, tin ghi trước khi quên / snowflake chậm 30 giây, tin ghi sau khi quên (2 tham số) | `search_history` bỏ tin trước / trả tin sau | D | xfail F | ck |
| F-4 | đồng hồ | Web, ứng dụng nhanh 30 giây; nói mã, quên, hỏi lại | mã không vào lịch sử gửi model | D | xfail F | ck |
| F-5 | đồng hồ | Web, ứng dụng chậm 30 giây; quên, nói câu A, hỏi lại | câu A có trong lịch sử gửi model | D | xfail F | ck |

### Quyền (au)

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| R2-1 | quyền | admin B bị hạ quyền, token cũ còn hạn: xem danh sách hội thoại / mở hội thoại của A / xem danh sách dự án (3 tham số) | 401, 403 hoặc 404, hoặc 200 nhưng không có nội dung của A | H | xfail R2 | au |
| R2-2 | quyền | như trên, gọi `/auth/users` | 403 | H | đạt | au |
| R5-1 | quyền | đúng hai admin; hai luồng hạ quyền lẫn nhau, cả hai đã qua bước đếm | đúng một lệnh thành công, lệnh kia bị từ chối, còn ít nhất một admin | D | xfail R5 | au |

### Job OCR (oj)

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| R6-1 | OCR | xoá job đang chạy, có / không huỷ trước (2 tham số); rồi cho worker chạy tiếp tới khi dừng | hoặc (a) không còn dòng lịch sử, không còn thư mục, mở job báo không có; hoặc (b) lệnh xoá trả 409 và job còn nguyên. Không bao giờ 204 rồi job hiện lại | M | xfail R6 | oj |
| R6-2 | OCR | xoá job đã xong | mất khỏi lịch sử và đĩa | M | đạt | oj |
| R7-1 | OCR | job xong; khởi động lại; xoá ngay | thư mục job không còn | M | xfail R7 | oj |
| R7-2 | OCR | job xong; khởi động lại; mở job; xoá | thư mục job không còn | M | đạt | oj |
| R7-3 | OCR | xoá với mã `%2e%2e`, `..%5C..%5Cx` qua HTTP; gọi thẳng `delete` với `..`, `..\..\x`, đường dẫn tuyệt đối, tên thư mục anh em, `ocr_` + 32 ký tự không phải hex (7 tham số) | tệp canh ngoài `runs_path` và thư mục anh em còn nguyên | M + P | đạt (chặn bản sửa ẩu) | oj |
| R7-4 | OCR | `root` lưu trong database trỏ ra ngoài `runs_path`; khởi động lại; mở job; xoá | không có gì ngoài `runs_path` bị xoá | P | xfail R7 | oj |
| R7-5 | OCR | Windows: một tệp của job đang mở khi xoá; đóng tệp; xoá lại, hoặc khởi động lại rồi xoá | không còn tệp nào của job | P | xfail R7 (chỉ win32) | oj |
| R8-1 | OCR | `dpi` = 50000, 401, 71, 0, −1; `output_format=evil`; `page_range` dài hơn 100 ký tự (7 tham số) | 422, không job nào được tạo | M | xfail R8 (chạy với 50000) | oj |
| R8-2 | OCR | `dpi` = 72, 200, 400 | 201 | M | đạt | oj |
| C-1 | OCR | `1-1000000` trên tài liệu 3 trang | `ValueError`, đỉnh bộ nhớ dưới 8 MiB | P | xfail C (chạy: 67 MiB) | oj |
| C-2 | OCR | `1-3`, ` 1 - 2 `, `1,1,2` / `5-1`, `0`, `-1`, `1-2-3`, `a-b`, `1,`, `4` | đúng tập trang / `ValueError` | P | đạt (chạy) | oj |

### Chủ job OCR (oa)

Mọi ca chạy trên `client` + `auth_on`, `MOCK_OCR`, tệp PNG.

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| E-1 | OCR | thành viên B với job do thành viên A tạo: xem lịch sử, mở job, sự kiện, tệp, export, huỷ, promote (7 tham số) | lịch sử không có job đó; các lệnh còn lại 403 hoặc 404, job của A không đổi | H | xfail E | oa |
| E-2 | OCR | chủ job / admin / khoá dịch vụ mở job của A; người chưa đăng nhập (4 tham số) | 200 / 200 / 200 / 401 | H | đạt | oa |

### Bộ lọc trường OCR (or)

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| R9-1 | lọc | hỏi "điện thoại và email", cả hai thứ tự (2 tham số) | cả khối điện thoại lẫn khối email tới model | P | xfail R9 (chạy) | or |
| R9-2 | lọc | hỏi điện thoại; khối là `Phone: +1 415…`, `ĐT: 028…`, `Di động: 09…`, `Hotline: 1900 1234`, `Điện thoại: (84-28)…` (5 tham số) | khối tới model | P | xfail R9 (chạy 4/5; `(84-28)` chưa chạy) | or |
| R9-3 | lọc | "What phone model is shown?" với khối không có số / hỏi "e-mail" khi chỉ có khối tên (2 tham số) | model được hỏi / báo thiếu trường, model không bị gọi | P | xfail R9 (chạy) | or |
| R9-4 | lọc | hỏi điện thoại; chỉ có khối tên / `STK: 0123 456 789` / ngày tháng (3 tham số) | báo thiếu trường, model không bị gọi | P | đạt (chạy; chặn nới regex quá tay) | or |
| R9-5 | lọc | số Việt Nam viết ba kiểu; hỏi riêng email; hỏi riêng số tài khoản (5 tham số) | đúng khối tới model, không lẫn khối trường khác | P | đạt (chạy) | or |

**Phủ mã:** R1, R2, R3, R5, R6, R7, R8, R9, A, B, C, E, F, N2, N4 có ca. **R4 và D không có ca nào trong bộ** (xem mục 3).

## 3. Để ngoài bộ test

**Chờ chủ dự án chọn thiết kế**

| Mục | Lý do |
|---|---|
| R4-1: "quên" chen giữa giờ gửi và lúc chụp trạng thái | Điểm chèn lệnh quên chỉ đúng nghĩa với cách 4a; với 4b cùng điểm chèn đó là "quên đến trước" và việc lưu là đúng. Viết sau khi chọn 4a hay 4b |
| D-1: tệp tải lên quá lớn | Chưa có trần cỡ tệp |
| D-2: render từng trang | Thứ tự render là cơ chế; bản sửa bằng trần số trang nhân DPI không làm nó xanh. Kiểm tay một PDF 300 trang |
| R2-3: dự án do admin tạo không có chủ | Hạ quyền theo hướng 2a làm người đó mất dự án của mình; kỳ vọng đúng chưa được chọn |
| E-3: job OCR cũ không có chủ | Ai được xem là lựa chọn thiết kế |
| B-4: người xoá đáp án của bot | Đáp án vẫn nằm trong lịch sử; giữ hay bỏ chưa được chọn |
| B-5: người khác sửa tin khi một lượt đang chờ | Lượt đó nhận câu "tin này đã bị xoá/sửa", nói sai với người hỏi; hành vi đúng chưa được chọn |
| "Người sửa tin làm Ún quên cả kênh" | Là thiết kế hiện tại; ghim hay không do chủ dự án quyết. B-2 chỉ kiểm phần đúng với mọi thiết kế |
| Member được nâng quyền dùng token cũ | Hướng 2c (thu hồi token) trả 401, hướng 2a cho thấy ngay: không có kỳ vọng chung |
| Tài khoản bị xoá, token còn hạn | Chưa kiểm repo có đường xoá tài khoản hay không |

**Bỏ vì trùng hoặc va test đang có**

| Mục | Lý do |
|---|---|
| Model lỗi 3 lần thì lượt `failed`, lượt sau chạy | `test_max_attempts_fails_head_and_allows_next_turn` |
| Hai execute đồng thời cho một lượt | `test_atomic_claim_has_one_winner_and_enforces_head_of_line` |
| Hạ quyền tuần tự tới admin cuối | `test_the_last_admin_cannot_be_demoted` |
| Bot gặp timeout thì gọi lại | `tests/test_discord_progress_message.py:294` ghim "timeout thì báo lỗi, không thử lại" |
| "Quên" trong lúc model chạy; lượt bị thu hồi khi đang xếp hàng; bot sửa/xoá tin của mình; sửa không đổi chữ | đã có trong `test_source_memory.py`, `test_source_memory_discord.py` |

**Bỏ vì là cơ chế hoặc không xác định được**

| Mục | Lý do |
|---|---|
| "Bot gọi lại execute sau 5xx", "sau `fail(retryable)` bot còn gọi lại hoặc đóng lượt" (mức B) | Chỉ lật với cách sửa ở bot; thay bằng A-5 đến A-8 ở mức T |
| "Lượt mồ côi chuyển `failed`", "lần 3 thành `failed`" | Là cơ chế; thay bằng "lượt sau chạy" |
| Lệnh xoá tin bot tới trước khi tin vào sổ (mức backend) | Backend không biết lệnh xoá đó của ai. Ở mức bot, "bot không chuyển lệnh xoá tin của mình" lại là một cách sửa |
| R7 trên Windows: "không trả 204 khi còn sót tệp" | Dọn sau cũng hợp lệ; R7-5 kiểm trạng thái cuối |
| `1900 1234` không nhãn | Xung đột R9-4; dùng `Hotline: 1900 1234` |

**Không tự động hoá được, kiểm tay**

| Việc | Cách kiểm |
|---|---|
| Discord thật có gửi sự kiện sửa khi chỉ bung xem trước link không | server thử: dán link, xem mốc kênh có dời |
| Hai server thật đã có mốc từ migration | sau khi sửa R1, reply một tin ở mỗi server |
| Bot bị giết thật giữa lượt | tắt bot khi đang "⏳", bật lại, gọi Ún cùng kênh |
| Lệch đồng hồ Windows và Docker sau khi máy ngủ | chạy `clock.py` trước và sau một lần ngủ, ghi sổ đo |
| DPI cao, PDF lớn, RAM thật | đo tay; R8-1 chỉ chặn ở cửa |

## 4. Thứ tự viết và ước lượng

| Bước | Việc | Số test (kể tham số) | Thời gian chạy |
|---|---|---:|---:|
| 0 | **Chứng minh bộ nối `httpx.ASGITransport`** (A-4): `LocalAgentClient` dùng `httpx.AsyncClient(transport=ASGITransport(app=client.app))`, app đã qua lifespan nhờ `v2client`, một tin thường đi trọn vòng. Ghi kết quả vào nhật ký **trước khi** viết A-5 đến A-8 | 1 | ~3 giây |
| 1 | `review2_support.py` | — | — |
| 2 | dt | 25 | ~25 giây |
| 3 | bb | 5 | ~15 giây |
| 4 | ld, ck | 3 + 8 | ~15 giây |
| 5 | oj | 35 | ~8 giây |
| 6 | or | 17 | < 1 giây |
| 7 | au | 5 | ~10 giây (bcrypt; R5-1 chờ tối đa 2 giây) |
| 8 | oa | 11 | ~10 giây |
| 9 | bt | 3 | ~2 giây |

Tổng: 52 ca trong bảng, khoảng 112 test, 9 tệp test và 1 tệp helper, ước dưới 1,5 phút. Phần không cần container (oj, or, bt) là 55 test, dưới 15 giây.

**Nếu bước 0 không nối được:** A-4 đến A-8 chuyển sang mục "để ngoài". Thêm một ca backend "lượt mồ côi đã 1 giờ, lượt sau cùng kênh chạy" vào dt, `reason` ghi rõ nó chỉ lật khi sửa ở backend.

## 5. Băn khoăn của người gộp, cần Opus xem khi ký

1. **A-8 (bot chết)** chỉ lật nếu backend tự gỡ lượt mồ côi. Một bản sửa thuần phía bot không cứu được ca này, vì bot đã chết; đường thoát hiện có là `cancel-open` khi bot được bật lại qua bảng điều khiển (A-2 đã canh). Nếu coi "sửa thuần phía bot + `cancel-open` lúc khởi động" là cách sửa hợp lệ, A-8 phải thêm bước khởi động lại (khi đó nó đạt ngay hôm nay) hoặc để ngoài.
2. **A-1** theo kỳ vọng đã chốt ("không 5xx") cũng không lật với bản sửa thuần phía bot. Giữ theo `DECISIONS.md`.
3. **A-6** dùng cùng lỗi chèn như A-1, nhưng chỉ chèn một lần và quan sát qua bot; hai ca có thể lật cùng lúc. Giữ cả hai vì mức quan sát khác nhau.
4. **R8-1** phần `output_format` và `page_range` dài: giả định bản sửa dùng lại `OcrJobOptions`. Nếu chỉ kẹp DPI, hai tham số này xfail mãi. Tách dấu theo từng tham số để nhìn thấy.
5. **R7-4** giả định `root` đọc lại từ database là không đáng tin. Muốn sửa dữ liệu này phải ghi được vào database, nên mức nghiêm trọng thấp; ca vẫn là kết quả đúng với mọi cách sửa.
6. Mã **R4** và **D** không có ca tự động nào; brief yêu cầu phủ mọi mã. Cần chủ dự án biết khi nhận bộ test.
