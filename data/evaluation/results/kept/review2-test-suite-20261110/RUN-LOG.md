# Nhật ký chạy: bộ test hồi quy review2 (10/11/2026)

Người viết: `claude-opus-5-5`. Kế hoạch: `meeting/test-plan.md`, `meeting/DECISIONS.md`, `meeting/opus-signoff.md`.

**Bản chất.** Mỗi lỗi của bản nhận xét thứ hai trở thành một tình huống "người dùng làm X thì phải thấy Y". Ca đang hỏng mang dấu "biết là hỏng", và chỉ được tính là hỏng khi đúng triệu chứng của lỗi đó xuất hiện. Để chắc dấu ấy sẽ tự báo khi lỗi được sửa, từng ca đã được chạy lại với một bản sửa tạm, đặt trong bộ nhớ chứ không sửa tệp nào, và ca nào cũng chuyển sang "đã sửa".

## Điều kiện chạy

| Mục | Giá trị |
|---|---|
| Code | main `ed60401` cộng phần sửa lỗi B chưa commit (`history_service.py`, `test_source_memory_discord.py`); không tệp có sẵn nào bị sửa |
| Python / pytest | 3.11.9 / 8.4.2 (httpx 0.28.1, fastapi 0.139.0, starlette 1.3.1, discord.py 2.7.1) |
| Container | `chk-r2t-pg` postgres:16-alpine :55441, `chk-r2t-redis` redis:7-alpine :56381, `chk-r2t-qdrant` qdrant v1.18.2 :56334; migrate tới `20261109_39 (head)`; cả ba được `docker stop` sau khi chạy |
| Biến môi trường | `source .../scratchpad/check-c57/env_fix.sh` (Ollama ở cổng chết, CUDA ẩn) |

## Bước 0: nối bot thật với app thật (18:13)

Bot chạy nguyên bản: `DiscordConversationGateway`, `LocalAgentClient` và `answer_mention`, không sửa. Nó gọi app thật (đã qua lifespan nhờ `v2client`) qua `httpx.ASGITransport(raise_app_exceptions=False)`. Discord giả là `Discord`/`FakeSource`/`quick` của `tests/test_discord_progress_message.py`, nạp theo đường dẫn tệp.

- Lệnh: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_bot_backend.py -q`, lúc đó tệp chỉ có A-4.
- Kết quả: `1 passed in 1.69s`. Người hỏi thấy đúng câu trả lời của model giả, lượt kết thúc `completed`, app không ném lỗi nào.
- **Nối được**, nên không dùng phương án lùi của DECISIONS mục 4.

## Lệnh đã chạy

```
docker run -d --rm --name chk-r2t-pg -p 55441:5432 ... postgres:16-alpine   (+ chk-r2t-redis, chk-r2t-qdrant)
source .../check-c57/env_fix.sh && .venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_<tệp>.py -q            # từng tệp
.venv/Scripts/python.exe -m pytest tests/test_review2_bot_turns.py -q                        # tệp ở gốc
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_*.py --runxfail --tb=line   # dòng lỗi hôm nay
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_tmp_flip.py -rA            # vá tạm (tệp đã xoá)
cd backend && REVIEW2_FLIP_A=bot ../.venv/Scripts/python.exe -m pytest tests/test_review2_tmp_flip.py -k "test_a6 or test_a8"
cd backend && ../.venv/Scripts/python.exe -m pytest -q                                        # backend đủ bộ
.venv/Scripts/python.exe -m pytest tests -q                                                   # bộ gốc
bash flip/repeat3.sh                                                                          # 3 lần lặp
docker stop chk-r2t-pg chk-r2t-redis chk-r2t-qdrant
```

## Kết quả theo tệp

Mỗi tệp chạy riêng một lần. Thời gian là thời gian pytest báo, chưa gồm lúc nạp `app.main`.

| Tệp | Đạt | xfail | xpass | Hỏng | Bỏ qua | Thời gian |
|---|---:|---:|---:|---:|---:|---:|
| `backend/tests/test_review2_discord_turns.py` (dt) | 12 | 12 | 0 | 0 | 0 | 21,5 s |
| `backend/tests/test_review2_bot_backend.py` (bb) | 1 | 5 | 0 | 0 | 0 | 80,4 s |
| `backend/tests/test_review2_ledger.py` (ld) | 3 | 0 | 0 | 0 | 0 | 2,7 s |
| `backend/tests/test_review2_clocks.py` (ck) | 2 | 6 | 0 | 0 | 0 | 6,8 s |
| `backend/tests/test_review2_auth.py` (au) | 1 | 4 | 0 | 0 | 0 | 7,9 s |
| `backend/tests/test_review2_ocr_jobs.py` (oj) | 22 | 11 | 0 | 0 | 0 | 2,7 s |
| `backend/tests/test_review2_ocr_access.py` (oa) | 4 | 8 | 0 | 0 | 0 | 18,7 s |
| `backend/tests/test_review2_ocr_reader.py` (or) | 8 | 9 | 0 | 0 | 0 | 1,0 s |
| `tests/test_review2_bot_turns.py` (bt) | 3 | 0 | 0 | 0 | 0 | 0,4 s |
| **Cộng: 111 test** | **56** | **55** | 0 | 0 | 0 | ~142 s |

Helper dùng chung: `backend/tests/review2_support.py`.

Mỗi ca xfail, khi chạy `--runxfail`, đều hỏng bằng đúng `KnownBug` của nó (55/55). Bản đầy đủ ở `flip/runxfail-today.txt`. Vài dòng tiêu biểu:

| Ca | Dòng lỗi hôm nay |
|---|---|
| R1 | `the reply turn crashed: 'ReplyTargetContext' object has no attribute 'created_at'` (BotReplyTargetContext ở tham số đáp án bot) |
| A-5…A-8 | `message 2 was not answered after …`: tin 2 chờ hết 15 s hạn của bot |
| R5-1 | `both demotions went through and 0 admin(s) remain` |
| C-1 | `refusing it took a 67.2 MiB peak` |
| E-1 | B mở, xem sự kiện, tải tệp, export, huỷ, đánh giá job của A đều được 200; promote được 202 |

## Backend đủ bộ và bộ gốc

| Bộ | Kết quả | Thời gian | So với trước |
|---|---|---:|---|
| `cd backend && ../.venv/Scripts/python.exe -m pytest -q` | 2283 passed, 55 xfailed, 0 hỏng | 7 phút 44 giây | Lần chạy bộ đủ trước đó (`scratchpad/rv2/fixb-backend-suite.txt`) được 2230 passed. 2283 = 2230 + 53 test review2 đạt; 55 xfail đều là ca review2 |
| `.venv/Scripts/python.exe -m pytest tests -q` | 245 passed, 1 skipped, 0 hỏng | 24,5 s | Ca bỏ qua là `test_run_mteb_prefixes.py:69`, vì không có `mteb`; có từ trước |

## Ca xfail → vá tạm → lật được?

Cách làm: `test_review2_tmp_flip.py` import lại mọi ca xfail, kèm các ca canh cùng vùng. Một fixture tự động áp một bản sửa tạm theo tên ca, bằng `monkeypatch`: bọc hàm, hoặc biên dịch lại bản sao mã nguồn trong bộ nhớ. Không tệp ứng dụng nào bị sửa. Chạy xong tệp đã bị xoá khỏi `backend/tests/`. Bản lưu nằm ở `flip/test_review2_tmp_flip.py`, kết quả ở `flip/flip-backend-fixes.txt` và `flip/flip-a-bot-fixes.txt`.

Kết quả gộp: **55/55 ca xfail ra `XPASS(strict)`**, và 46 ca canh chạy dưới cùng bản sửa đều đạt.

| Mã | Ca xfail (số test) | Bản sửa tạm | Lật? | Ca canh vẫn đạt |
|---|---|---|---|---|
| R1 | R1-1 (3), R1-2 (2), R1-4 | ngữ cảnh reply mang giờ tạo của lượt gốc | 6/6 | R1-3 (3) |
| N2 | N2-1, N2-2 | bỏ reply target khi tin gốc, hoặc câu hỏi gốc của đáp án bot, có vết xoá | 2/2 | — |
| R3 | R3-1, R3-2 | execute giữ đáp án lại khi tin hỏi có vết xoá | 2/2 | R3-3 (2), R3-4 (2) |
| N4 | N4-1, N4-2 | lượt quên được thử lại nhận ra lần quên của chính nó; chỉ thay đáp án đã lưu khi lượt thật sự cũ | 2/2 | N4-3, N4-4 |
| A (sửa ở backend) | A-5, A-6 (2), A-7, A-8 | backend bỏ lượt `queued` đứng đầu hàng mà không ai chạm tới trong 10 phút | 5/5 | — |
| A (sửa ở bot) | A-6 (2), A-8 | bot hỏi lại khi gặp 5xx trong hạn chờ; bot gọi `cancel-open` khi khởi động | 3/3; A-6 "một lần" xong trong 3,6 s, "mãi" trong 9,7 s, đều dưới hạn 15 s | — |
| F | F-1, F-2 | lượt Discord đóng dấu bằng giờ Postgres | 2/2 | F-0 (2) |
| F | F-3 (2) | `search_history` so theo giờ nhận (`created_at`) | 2/2 | — |
| F | F-4, F-5 | tin Web đóng dấu bằng giờ Postgres | 2/2 | — |
| R2 | R2-1 (3) | vai trò đọc lại từ database ở mỗi request | 3/3 | R2-2 |
| R5 | R5-1 | khoá advisory trước khi đếm admin | 1/1 | — |
| R6, R7 | R6-1 (2), R7-1, R7-4, R7-5 | chỉ xoá `runs_path/ocr_<32 hex>`; job đã xoá không bao giờ được lưu lại | 5/5 | R6-2, R7-2, R7-3 (7) |
| R8 | R8-1 (5) | từ chối dpi ngoài 72–400 trước khi tạo job | 5/5 | R8-2 (3) |
| C | C-1 | kiểm biên từng đoạn trước khi dựng tập trang | 1/1 | C-2 (10) |
| E | E-1 (8) | một cổng ASGI ghi chủ của job, trả 404 cho thành viên khác và lọc lịch sử | 8/8 | E-2 (4) |
| R9 | R9-1 (2), R9-2 (5), R9-3 (2) | hợp mọi luật khớp; nhãn rộng hơn; nhận số quốc tế, "e-mail" và trường hợp "phone model" | 9/9 | R9-4 (3), R9-5 (5) |

Không có ca nào phải ghi "chưa thấy lật".

## Ba lần chạy lặp

Lệnh: `flip/repeat3.sh` (bản chép của script trong scratchpad). Mỗi lần gồm 8 tệp backend chạy chung một lệnh, rồi tệp ở gốc. Ba lần chạy liền nhau, từ 18:48 tới 18:55, cùng một database, không dọn giữa các lần.

| Lần | Backend (8 tệp) | Gốc (bt) | Thời gian backend |
|---|---|---|---:|
| 1 | 53 passed, 55 xfailed | 3 passed | 135,3 s |
| 2 | 53 passed, 55 xfailed | 3 passed | 135,3 s |
| 3 | 53 passed, 55 xfailed | 3 passed | 134,9 s |

Không ca nào lúc đạt lúc hỏng. Không có XPASS và không có lỗi. Tính cả lần chạy từng tệp và lần chạy trong bộ đủ, bộ review2 đã chạy 5 lần cho cùng một kết quả. Kết quả thô ở `flip/repeat3.txt`.

## Chỗ lệch kế hoạch

| # | Lệch | Lý do |
|---|---|---|
| 1 | C-1 và C-2 đi qua `OcrJobService.create` + chạy job trên một PDF thật 3 trang, không gọi thẳng `_select_pages` | Nếu bản sửa chặn khoảng trang sớm hơn (ở route hoặc ở `create`), C-1 vẫn lật. Vẫn ở mức P, không cần container |
| 2 | A-8: sau khi khởi động lại (`create_bot` → `setup_hook` → `on_ready`, chỉ thay bước đồng bộ lệnh với Discord), tin 2 đi qua `answer_mention` với một gateway dựng y như cách `create_bot` dựng | `on_message` cần một người dùng Discord đã đăng nhập. Bản sửa "dọn lượt khi khởi động" vẫn lật ca này (đã chạy) |
| 3 | A-7: "bot hết hạn chờ" được tạo bằng hạn chờ 0 cho tin 1 (gọi một lần rồi bỏ), không bằng model chậm | Tất định và nhanh hơn; tin 2 vẫn được đủ hạn |
| 4 | Hạn chờ của bot là 15 s (5 lần lease), trên mức tối thiểu 4 lần lease | Bản sửa phía bot cho A-6 "lỗi lặp lại mãi" cần 9,7 s. Với 12 s thì chỉ dư 2 s |
| 5 | bb chạy khoảng 80 s; cả bộ review2 khoảng 140 s (kế hoạch ước dưới 1,5 phút, bản ký ước bb khoảng 60 s) | Mỗi ca A xfail chờ đủ 15 s cho tin 2 |
| 6 | R1-2, R1-3: lịch sử thu về 1 lượt (`history_turn_limit`) kèm 1 lượt chen giữa | Để chữ tin gốc chỉ tới được model qua đường reply. Nếu không, lịch sử đã chứa nó và ca đạt vô nghĩa |
| 7 | R1-3 thêm một kiểm: chữ của phiên khác không vào prompt | Rẻ, đúng với mọi thiết kế |
| 8 | E-1 `promote`: `document_service.promote_ocr_run` được thay bằng hàm ghi lại; `runs_path` của app trỏ vào `tmp_path` | Hôm nay B promote được. Nếu chạy thật, ca này sẽ ghi tài liệu vào thư mục dữ liệu thật và xếp job index |
| 9 | F-3 gọi thẳng công cụ `search_history` đã đăng ký trong app (mức D), không có từ khoá | Tránh phụ thuộc cách tách từ |
| 10 | B-2: tin hỏi cũng được ghi vào sổ với cùng mã, như bot vẫn làm | Để lệnh sửa/xoá chạm đúng tin đã nằm trong lịch sử |
| 11 | Tên helper: `age_open_turns` (≈ `orphan_by_dead_bot`), `BotOnApp` (≈ `bot_on_app`), thêm `ledger_message`, `expire_lease`, `active_notes`, `execute_reply`, `FakeModel`; không có `turn_row` | Không đổi nghĩa |
| 12 | Tổng 111 test, kế hoạch ước khoảng 112 | Bỏ A-1 (−1), bỏ hai tham số R8-1 (−2); thêm `evaluate` cho E-1 (+1) và "lỗi lặp lại mãi" cho A-6 (+1) |

## Ghi chú cho người duyệt và người commit

- **B-1 dựa vào phần sửa lỗi B chưa commit** (`history_service.py`). Bộ test phải được commit cùng hoặc sau phần sửa đó; nếu không, B-1 sẽ đỏ.
- **R1-4 có thể lật khi sửa N2** (dự đoán từ đọc code, chưa chạy). Nếu bản sửa N2 bỏ reply target có vết xoá ngay trong bước tìm target, lượt reply không còn chạm `created_at`, nên R1-4 thành XPASS dù R1 chưa sửa. Khi đó chỉ cần bỏ dấu của R1-4; các ca R1 khác vẫn giữ dấu.
- **A-2 và A-3 là ca A ở mức backend**, vẫn giữ vì kế hoạch liệt kê chúng là ca đang đạt. Không ca A xfail nào ở mức backend.
- **Các tệp không cần container đã được kiểm khi container tắt:** oj + or được 30 passed, 20 xfailed; bt được 3 passed.
- **Tệp sinh ra trong lúc chạy:** bộ backend đủ, tức các test có sẵn, ghi 15 thư mục `data/documents/doc_*` lúc 18:40–18:43, như mọi lần chạy (45 thư mục trước đó trong ngày, 4692 tổng cộng, đều bị gitignore). Ba lần chạy lặp riêng bộ review2 không ghi gì ra ngoài `tmp_path`. Không xoá các thư mục đó, vì chúng có từ trước và không thuộc phạm vi.
- **Chưa làm:** chưa chạy trên Linux/CI, nên R7-5 mới chỉ chạy nhánh xfail của Windows. Mục trong `docs/SO_DO.md` để phiên điều phối ghi, theo brief.

## Để ngoài bộ (danh sách cuối)

**Chờ chủ dự án chọn thiết kế:**

| Mục | Lý do |
|---|---|
| R4-1: "quên" chen giữa giờ gửi và lúc chụp trạng thái (Web) | Điểm chèn chỉ đúng với cách 4a. Với 4b, việc lưu là đúng. Ghi chú: trường hợp "quên sau lúc chụp" đã có test đang đạt trong `test_source_memory.py` |
| D-1: tệp OCR tải lên quá lớn | Chưa có trần cỡ tệp |
| D-2: render từng trang | Thứ tự render là cơ chế; kiểm tay bằng một PDF 300 trang |
| R2-3: dự án do admin tạo không có chủ | Hạ quyền theo hướng 2a làm người đó mất dự án của mình |
| E-3: job OCR cũ không có chủ | Ai được xem là lựa chọn thiết kế |
| B-4: người xoá đáp án của bot | Giữ hay bỏ đáp án trong lịch sử chưa được chọn |
| B-5: người khác sửa tin khi một lượt đang chờ | Lượt đó nhận câu "tin này đã bị xoá/sửa", nói sai với người hỏi; hành vi đúng chưa được chọn |
| "Người sửa tin làm Ún quên cả kênh" | Là thiết kế hiện tại; B-2 chỉ kiểm phần đúng với mọi thiết kế |
| Member được nâng quyền dùng token cũ | Hướng 2c trả 401, hướng 2a cho thấy ngay: không có kỳ vọng chung |
| Tài khoản bị xoá, token còn hạn | Chưa kiểm repo có đường xoá tài khoản hay không |

**Bỏ vì trùng hoặc vì là cơ chế:**

| Mục | Lý do |
|---|---|
| A-1 (lỗi bất ngờ ở bước chuẩn bị, mức backend) | Theo bản ký: "không 5xx" là cơ chế; A-6 với "lỗi lặp lại mãi" là bản kiểm kết quả của nó |
| Model lỗi 3 lần thì lượt `failed` | Trùng `test_max_attempts_fails_head_and_allows_next_turn` |
| Hai execute đồng thời | Trùng `test_atomic_claim_has_one_winner_and_enforces_head_of_line` |
| Hạ quyền tuần tự tới admin cuối | Trùng `test_the_last_admin_cannot_be_demoted` |
| Bot gặp timeout thì gọi lại | `tests/test_discord_progress_message.py:294` đang ghim "timeout thì báo lỗi" |
| "Quên" trong lúc model chạy; lượt bị thu hồi khi đang chờ; bot sửa/xoá tin của mình; sửa không đổi chữ | Đã có trong `test_source_memory.py`, `test_source_memory_discord.py` |
| Bot gọi lại execute sau 5xx (mức B); lượt mồ côi chuyển `failed` | Là cơ chế; đã thay bằng A-5 đến A-8 ở mức T |
| Lệnh xoá tin bot tới trước khi tin vào sổ (mức backend) | Backend không biết lệnh xoá đó của ai |
| R7 trên Windows: "không trả 204 khi còn sót tệp" | Dọn sau cũng hợp lệ; R7-5 kiểm trạng thái cuối |
| `1900 1234` không có nhãn | Xung đột với R9-4; dùng `Hotline: 1900 1234` |
| R8-1 với `output_format=evil` và `page_range` dài | Theo bản ký: không thuộc mã nào |

**Không tự động hoá được, kiểm tay:** Discord thật có gửi sự kiện sửa khi chỉ bung xem trước link hay không; hai server thật đã có mốc từ migration (reply một tin ở mỗi server sau khi sửa R1); bot bị giết thật giữa lượt; lệch đồng hồ Windows với Docker sau khi máy ngủ; DPI cao, PDF lớn, RAM thật.

**Mã không có ca tự động:** R4, D.

## Sửa 4 chỗ Fable nêu (10/11)

Người sửa: `claude-opus-5-5`. Phạm vi: đúng bốn dòng "nên sửa" ở `REVIEW-fable.md` mục 2. Kết quả thô, bản sao tệp tạm, bản trước khi sửa (`before/`) và `changes.diff` nằm ở `fix4/`.

**Bản chất.** Trước đây, ở bốn chỗ, test coi *mọi* thứ đi chệch là "lỗi đã biết" hoặc "đã sửa xong". Vì vậy một sự cố chẳng liên quan có thể bị che thành "vẫn hỏng như cũ", hoặc bị đọc nhầm thành "đã sửa, bỏ dấu đi". Giờ mỗi ca chỉ nhận đúng những kết cục được phép. Mọi thứ khác làm ca đỏ thật và in ra lỗi thật. Mỗi chỗ được thử ba cách: code hôm nay, bản sửa tạm, và một hỏng hóc cố ý nhắm vào đúng chỗ vừa thêm.

### Thay đổi

| Chỗ | Tệp:dòng (sau sửa) | Đổi gì |
|---|---|---|
| 1. A-5…A-8 | `review2_support.py:382-394`; `test_review2_bot_backend.py:53-59`, `:76` | `BotOnApp.ask` chỉ trả về lỗi mà ca liệt kê trong `allowed`, mọi lỗi khác được ném lại. A-5 cho phép `discord.HTTPException` ở tin 1, vì hôm nay bot báo giao hỏng rồi ném lại lỗi đó. Tin 2 ở mọi ca, và tin 1 ở A-6, A-7, không được phép lỗi nào |
| 1b. hệ quả của 1 | `review2_support.py:364-375` | Mỗi Discord giả đánh số tin gửi đi từ một snowflake mới. Lý do ở mục "Lệch đề xuất" |
| 2. R5-1 | `test_review2_auth.py:121-124` | Sau `join`: `assert all(o == "demoted" or isinstance(o, AuthConflictError) …)`. Lớp lỗi thật: `app.services.auth_service.AuthConflictError` (dòng 45, ném ở 141) |
| 3. R3-1, R3-2 | `test_review2_discord_turns.py:150`, `:164` | `assert … status_code < 500` trước `known_bug`; 4xx vẫn qua |
| 4. N4-1 | `test_review2_discord_turns.py:15`, `:219-223` | Thêm `known_bug(STALE_TURN_REPLY not in answer, …)`; hằng số import từ `app.discord.source_memory` |

### Lệch đề xuất của Fable

| # | Fable đề xuất | Đã làm | Lý do |
|---|---|---|---|
| 1 | `escaped = await bot.ask(...)`; `assert escaped is None` ở từng chỗ gọi | `ask` tự ném lại mọi lỗi không nằm trong `allowed` | Mặc định là đỏ, nên chỗ gọi mới không thể quên kiểm. Lỗi hiện kèm traceback thật của bot, không chỉ `repr`. A-5 tin 1 được canh luôn, không tốn thêm gì. Nhược điểm: đổi hợp đồng của helper dùng chung. A-4 vẫn `assert escaped is None`, vẫn đúng |
| 2 | `again.json().get("answer") != STALE_TURN_REPLY` | `STALE_TURN_REPLY not in answer` | Với `!=`, đáp án "câu báo cũ + Ún đã quên…" sẽ ra XPASS. Ca (c) bên dưới phải không XPASS. (Suy ra từ phép so chuỗi, không chạy bản `!=`) |
| 3 | (không nêu) | Số tin Discord giả không trùng nhau giữa hai tin | Kiểm tra mới lộ ra lỗi này ngay ở lần chạy (b) đầu tiên với bản sửa phía bot. Discord giả nào cũng đánh số từ 1001, mà backend chỉ cho một mã tin trả lời thuộc về một lượt. Khi cả tin 1 lẫn tin 2 đều được trả lời (A-6 "một lần", bản sửa phía bot), lúc báo đã giao tin 2 backend trả `DISCORD_TURN_DELIVERY_CONFLICT`. Bản cũ nuốt lỗi này, nên lần lật "3/3" trước đây có một ca mà việc báo giao tin 2 thật ra đã hỏng (`fix4/b-flip-a-bot-fixes-before-id-fix.txt`). Đề xuất của Fable cũng sẽ vấp đúng chỗ này (suy ra từ traceback, không chạy bản của Fable). Ba dòng, gỡ được độc lập |

### Lệnh

```
docker run -d --rm --name chk-r2u-pg -p 55441:5432 ... postgres:16-alpine   (+ chk-r2u-redis, chk-r2u-qdrant); trước đó docker ps trống, ba cổng trống
source .../check-c57/env_fix.sh && .venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head     # 20261109_39 (head)
# (a)
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_discord_turns.py tests/test_review2_auth.py tests/test_review2_bot_backend.py -rA
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_discord_turns.py tests/test_review2_auth.py --runxfail --tb=line -k "test_r3_1 or test_r3_2 or test_n4_1 or test_r5_1"
# (b) flip/test_review2_tmp_flip.py chép vào backend/tests, xoá sau khi chạy
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_tmp_flip.py -rA -k "test_a5_ or test_a6_ or test_a7_ or test_a8_ or test_r5_ or test_r3_ or test_n4_"
cd backend && REVIEW2_FLIP_A=bot ../.venv/Scripts/python.exe -m pytest tests/test_review2_tmp_flip.py -rA -k "test_a6_ or test_a8_"
# (c) fix4/run_c.sh: chép fix4/test_review2_tmp_fix4.py và bản trước sửa (tên *_tmp_old_*) vào backend/tests, chạy, xoá
bash run_c.sh new ; bash run_c.sh old          # REVIEW2_FIX4=<đột biến> REVIEW2_FIX4_SOURCE=new|old
REVIEW2_FIX4=n4_appended|n4_exact pytest tests/test_review2_tmp_fix4.py --runxfail -k test_n4_1   # xem dòng ném KnownBug
# tổng
cd backend && ../.venv/Scripts/python.exe -m pytest <8 tệp test_review2_*.py, liệt kê từng tệp> -q -rfEX
.venv/Scripts/python.exe -m pytest tests/test_review2_bot_turns.py -q -rfEX
docker stop chk-r2u-pg chk-r2u-redis chk-r2u-qdrant
```

### Kết quả (a) (b) (c)

(a) là code hôm nay, chạy với tệp test đã sửa. (b) là bản sửa tạm trong `flip/`. (c) là đột biến bằng `monkeypatch`, chạy trên test **trước** sửa (bản ở `fix4/before/`) và **sau** sửa. Mọi dòng FAILED ở (c) đã được đối chiếu lỗi in ra: đó là dòng kiểm mới, không phải `[XPASS(strict)]` hay một điều kiện tiền đề.

| Chỗ | (a) code hôm nay | (b) bản sửa tạm | (c) đột biến | (c) trước sửa | (c) sau sửa |
|---|---|---|---|---|---|
| 1. A | A-5, A-6 ×2, A-7, A-8: 5 xfail | sửa phía backend: 5/5 XPASS(strict); sửa phía bot, A-6 ×2 và A-8: 3/3 XPASS(strict) | bot ném `RuntimeError` ngay sau khi tin 2 đã xếp lượt | 5 xfail (bị che) | 5 FAILED, `RuntimeError` từ `ask` (`bot_backend.py:59`) |
| | | | bot ném `RuntimeError` ở tin 1, sau khi lệnh execute đã về (lỗi tiêm ở backend đã nổ, model đã được gọi): A-6 ×2, A-7 | 3 xfail (bị che) | 3 FAILED, `RuntimeError` ở tin 1 (`:110`, `:132`) |
| | | | A-5: sau khi báo giao hỏng, bot ném `RuntimeError` thay vì lỗi Discord | xfail (bị che) | FAILED, `RuntimeError` |
| 2. R5-1 | xfail | XPASS(strict) | một luồng `set_role` ném `RuntimeError`, luồng kia hạ quyền được | XPASS(strict): đọc thành "đã sửa" | FAILED, `assert all(...)` ở `auth.py:123`: `{'x': RuntimeError(...), 'y': 'demoted'}` |
| | | | cả hai luồng ném `OperationalError` (lỗi kết nối giả, không cắt kết nối thật) | xfail (đỏ nhờ may) | FAILED, cùng dòng |
| 3. R3 | R3-1, R3-2: 2 xfail | 2/2 XPASS(strict); R3-3 ×2, R3-4 ×2 đạt | phát lại / gửi lại trả 500 | 2 XPASS(strict): đọc thành "đã sửa" | 2 FAILED, `assert 500 < 500` (`discord_turns.py:150`, `:164`) |
| | | | phát lại / gửi lại trả 409 (từ chối) | 2 XPASS(strict) | 2 XPASS(strict): 4xx vẫn được tính là sửa đúng |
| 4. N4-1 | xfail (KnownBug ở dòng kiểm "đã quên", đáp án hôm nay là câu báo cũ) | XPASS(strict); N4-2 XPASS(strict), N4-3, N4-4 đạt | bản sửa N4, nhưng đáp án là câu báo cũ + " Ún đã quên những gì bạn nhờ nhớ." | XPASS(strict) | xfail, `KnownBug` ở dòng 223 (dòng mới) |
| | | | bản sửa N4 (biên nhận "đã quên" có trong prompt), nhưng model trả đúng câu báo cũ | XPASS(strict) | xfail, `KnownBug` ở dòng 223 |

Thời gian: (a) 105,3 s cho ba tệp; (b) 13,4 s cho sửa phía backend, 15,3 s cho sửa phía bot; mỗi lượt (c) mới 1,7 đến 4,7 s. (c) trước sửa mất tới 48 s, vì tin 2 phải chờ hết hạn.

Lần chạy (a) đầu tiên làm **trước** bước 1b. Sau 1b, (b) phía bot, (b) phía backend và toàn bộ (c) đều được chạy lại. Lần chạy tổng dưới đây đóng vai (a) cho code cuối.

### Tổng review2 sau sửa

| Bộ | Kết quả | Thời gian |
|---|---|---:|
| 8 tệp backend `test_review2_*.py`, liệt kê từng tệp, một lệnh | 53 passed, 55 xfailed, 0 hỏng | 132,4 s |
| `tests/test_review2_bot_turns.py` | 3 passed | 0,35 s |
| **Cộng** | **56 đạt + 55 xfail**, không đổi so với trước | |
| 8 tệp backend, không có `POSTGRES_TEST_URL` (kiểm import `app.discord.source_memory` mới ở đầu tệp) | 30 passed, 20 xfailed, 58 skipped, 0 lỗi | 3,1 s |

Kết quả khi không có database khớp với lần chạy của Fable. Sau khi chạy, database thử còn 0 lượt mở, 0 tài khoản, 0 dòng giao tin. Mọi tệp tạm đã xoá khỏi `backend/tests/`, và ba container `chk-r2u-*` đã dừng.

### Chưa làm, giới hạn

- Chưa chạy backend đủ bộ: chỉ các tệp review2 bị đổi, và không tệp nào ngoài chúng import `review2_support`.
- Chưa chạy trên Linux. A-5 và A-7 vẫn chưa có bản sửa phía bot để thử lật (ghi chú cũ của Fable).
- R5-1 giờ chỉ nhận một kiểu từ chối: `AuthConflictError`. Một bản sửa để bên thua nổi lên bằng lỗi khác, ví dụ lỗi tuần tự hoá của Postgres không được đổi thành `AuthConflictError`, sẽ làm ca đỏ chứ không lật. Đó là điều chủ dự án đã duyệt, vì người dùng sẽ thấy 500.
- Các lần chạy này chưa có mục trong `docs/SO_DO.md`; phiên điều phối ghi.

## Theo bản duyệt lại của Fable (10/11, phiên điều phối)

Fable `claude-fable-5-2` duyệt phần sửa fix4: **GỘP ĐƯỢC** (`REVIEW-fable-fix4.md`, kết quả thô ở `fix4-review/`). Phiên điều phối (`claude-opus-5-5`) làm theo ba điểm:

| Tệp | Thay đổi | Lý do |
|---|---|---|
| `test_review2_bot_backend.py` (A-7) | `row.status == "queued"` → `row.status != "completed"` | bản sửa phía bot "thôi chờ thì huỷ lượt" làm ca đỏ oan |
| `review2_support.py` (`BotOnApp.message`) | `assert "_next_id" in vars(side)` trước phép gán; đặt số tin trả lời sau `source.id` | tệp kia đổi tên thuộc tính thì lỗi trùng mã quay lại trong im lặng; tin trả lời mang giờ sau câu hỏi |
| `test_review2_auth.py` (R5-1) | `assert succeeded` trước `known_bug` | cả hai lần hạ quyền bị từ chối không phải lỗi cũ, cũng không phải bản sửa |

Kết quả (container `chk-r2w-*`, `fix5/run.txt`, diff ở `fix5/changes.diff`):

| Lần chạy | Kết quả |
|---|---|
| 8 tệp backend review2 | 53 đạt, 55 xfail, 137,6 giây |
| `tests/test_review2_bot_turns.py` | 3 đạt |
| Bản vá phía bot của Fable: A-7 huỷ lượt | XPASS(strict), trước sửa đỏ oan |
| A-5 gửi lại, A-5 báo hỏng dứt khoát, A-6 ×2 | đều XPASS(strict) |
| R5 cả hai bị từ chối | đỏ ở dòng mới, trước là xfail |

Bản vá phía bot cho A-5, A-6, A-7 nằm ở `fix4-review/test_review2_tmp_fx.py` (chọn bằng `REVIEW2_FX=<mode>`).
