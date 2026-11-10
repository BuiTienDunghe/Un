**GỘP ĐƯỢC** — không có lỗi chặn; bốn chỗ nên sửa trước hoặc ngay sau khi gộp.

Người duyệt: Fable (`claude-fable-5-2`), 10/11/2026. Đối tượng: `backend/tests/review2_support.py`, 8 tệp `backend/tests/test_review2_*.py`, `tests/test_review2_bot_turns.py`, trên main `ed60401` cộng phần sửa lỗi B chưa commit.

**Bản chất:** bộ test làm đúng việc được giao. Mỗi ca "biết là hỏng" hỏng vì đúng lỗi của nó, và khi tôi áp lại các bản sửa tạm thì chúng tự báo "đã sửa". Các ca "đang đúng phải giữ" cũng canh thật: tôi cố tình làm hỏng hành vi chúng canh, và chúng đỏ. Điểm yếu còn lại nằm ở hai chỗ bắt lỗi quá rộng, khiến một sự cố không liên quan có thể bị đọc nhầm thành "lỗi đã biết".

## 1. Kết quả tôi tự chạy (không dùng số Opus báo)

Điều kiện: container dùng một lần `chk-r2f-pg` / `chk-r2f-redis` / `chk-r2f-qdrant` (cổng 55441 / 56381 / 56334), migrate tới `20261109_39 (head)`, `env_fix.sh` (Ollama cổng chết, CUDA ẩn), Windows. Chạy lần lượt.

| Lần chạy | Kết quả của tôi | Opus báo | Khớp |
|---|---|---|---|
| 7 tệp backend review2 (trừ bb), một lệnh | 52 đạt, 50 xfail, 56,6 giây | 52 + 50 | có |
| `test_review2_bot_backend.py` | 1 đạt, 5 xfail, 80,9 giây | 1 + 5, 80,4 giây | có |
| Tổng review2 (kể `tests/test_review2_bot_turns.py` trong bộ gốc) | 56 đạt, 55 xfail | 56 + 55 | có |
| Backend đủ bộ | 2283 đạt, 55 xfail, 0 hỏng, 7 phút 51 giây | 2283 + 55 | có |
| Bộ gốc `pytest tests` | 245 đạt, 1 bỏ qua | 245 + 1 | có |
| Thứ tự đảo (or → oa → oj → au → ck → ld → dt), rồi `test_source_memory_discord.py`, `test_source_memory.py`, `test_auth_api.py` | 98 đạt, 50 xfail, 0 hỏng | — | — |
| Không có `POSTGRES_TEST_URL` (8 tệp backend) | 30 đạt, 20 xfail, 58 bỏ qua, 0 lỗi, 3,1 giây | oj + or: 30 + 20 | có |
| Vá tạm (`flip/test_review2_tmp_flip.py`, chép vào rồi xoá), 51 ca xfail thuộc R1, N2, R3, N4, F, R2, R5, R6, R7, R8, C, E, R9, A-7 | 51/51 `XPASS(strict)`; 32 ca canh cùng bản vá đều đạt | 55/55 | có, trên phần tôi chạy |
| Đột biến của tôi (mục 4) | 30 ca đỏ đúng như mong; 9 ca vẫn đạt, đều giải thích được | — | — |

Chưa chạy lại: bản vá cho A-5, A-6, A-8 (khoảng 1 phút mỗi biến thể) và ba lần lặp của Opus. Chưa chạy trên Linux.

Sau cả bộ, database thử còn: 0 lượt Discord mở, 0 tài khoản, 2 dòng `ocr_runs` (chưa xác định test nào để lại; ca E của review2 tự xoá job của nó).

## 2. Bảng phát hiện

| Mức | Tệp:dòng | Vấn đề | Cách sửa |
|---|---|---|---|
| nên sửa | `review2_support.py:377-386`, `test_review2_bot_backend.py:53-59` | `BotOnApp.ask` bắt mọi `Exception` và trả về; `second_message_answered` bỏ giá trị đó. Nếu bot vỡ vì chuyện không liên quan khi xử lý tin 2 (sau khi đã xếp lượt), ca A-5 đến A-8 vẫn ra `KnownBug` và báo xfail. Trong thời gian mang dấu, một hỏng hóc của bộ nối bị che; và sau khi A được sửa, ca sẽ không lật mà không ai biết vì sao | Trong `second_message_answered`: `escaped = await bot.ask(api, second)` rồi `assert escaped is None, repr(escaped)`. Hôm nay tin 2 hết hạn chờ thì `answer_mention` tự báo lỗi và trả về bình thường, nên dòng này không làm ca đỏ. Tương tự cho tin 1 ở A-6 và A-7 |
| nên sửa | `test_review2_auth.py:107-112`, `:121-123` | `except Exception` coi mọi lỗi của `set_role` là "bị từ chối". Hai luồng cùng vỡ vì lỗi kết nối thì ra `KnownBug` (xfail nhờ may); một luồng vỡ vì lỗi lạ, luồng kia thành công thì ca **đạt** dù không có gì được canh | Sau `join`: `assert all(o == "demoted" or isinstance(o, AuthConflictError) for o in outcomes.values()), outcomes` |
| nên sửa | `test_review2_discord_turns.py:137-138`, `:149`, `:162` | `answer_of` trả chuỗi rỗng khi mã khác 200, và R3-1, R3-2 không kiểm mã. Một lần gọi lại trả 4xx sẽ được tính là "không trả đáp án cũ". Với R3-1 thì chấp nhận được (từ chối phát lại là hợp lệ), nhưng 5xx thì không | Thêm `assert replay.status_code < 500, replay.text` (và tương tự cho `again`) trước `known_bug` |
| nên sửa | `test_review2_discord_turns.py:216-217` | N4-1 chỉ tìm chuỗi "đã quên" trong đáp án cộng prompt. `DECISIONS.md` chốt thêm "không có câu tin đã bị xoá/sửa". Hôm nay hai điều trùng nhau, nhưng một bản sửa trả câu báo cũ kèm chữ "đã quên" sẽ lọt | Thêm `known_bug(again.json().get("answer") != STALE_TURN_REPLY, ...)` |
| ghi chú | `test_review2_bot_backend.py:20-21` | Năm ca A xfail mỗi ca chờ đủ 15 giây: 75 trong 81 giây của tệp, làm bộ backend dài thêm khoảng 17%. **Chấp nhận được**: thời gian này chỉ tốn khi lỗi A còn đó; sửa xong thì tin 2 được trả lời ngay. Nếu muốn rút: lease 2 giây, hạn chờ 10 giây, còn khoảng 50 giây; phải chạy lại bản vá phía bot của A-6 "mãi" để chắc còn dư hạn | Không bắt buộc |
| ghi chú | `review2_support.py:215-234` | `age_open_turns` lùi bảy cột giờ đang có. Nếu bản sửa A ở backend dựa vào một cột giờ **mới**, hàm này không lùi cột đó, A-5 đến A-8 sẽ xfail mãi dù lỗi đã sửa | Ghi một dòng chú thích trong hàm: thêm cột giờ thì thêm vào đây |
| ghi chú | `flip/test_review2_tmp_flip.py:461-466` | A-5 và A-7 chỉ được chứng minh lật với bản sửa phía backend. Đọc code thì bản sửa phía bot (gọi lại rồi giao lại; huỷ lượt khi thôi chờ) cũng lật, nhưng chưa ai chạy | Ghi rõ trong `RUN-LOG.md` |
| ghi chú | `test_review2_discord_turns.py:274` | A-2 gọi `cancel-open`, lệnh này huỷ **mọi** lượt mở trong database. Chạy lần lượt thì vô hại (test cũ `test_operator_stop_…` cũng vậy); chạy song song trên chung database thì phá test khác | Không sửa; giữ luật "không chạy song song" |
| ghi chú | `review2_support.py:166`, `test_review2_clocks.py:31,45`, `test_review2_discord_turns.py:88` | Các ca dựa vào khoảng đệm 50 ms giữa giờ Postgres và giờ ứng dụng. Đã đo lệch tối đa 3 ms trên container vừa bật. Sau khi máy ngủ, đồng hồ Docker trên Windows có thể lệch hơn 50 ms (chưa đo); khi đó F-0, R1-2, R1-4 đỏ trên máy chủ dự án. Đó là lỗi F lộ ra thật, không phải test sai, nhưng người đọc cần biết | Ghi trong `RUN-LOG.md` |
| ghi chú | `test_review2_ocr_jobs.py:267`, `:278` | C-1, C-2 coi job `failed` vì bất kỳ lý do gì là "bị từ chối". Ba tham số hợp lệ của C-2 (phải `completed` và đúng trang) giữ cho bộ dựng PDF không hỏng thầm, nên rủi ro thấp | Có thể kiểm thêm chữ "Page range" hoặc "Invalid" trong sự kiện lỗi |
| ghi chú | `test_review2_discord_turns.py:60-76` | R1-3 với `other_session`, `not_found` chỉ kiểm "không vỡ và model được gọi"; chúng vẫn đạt khi reply bị vô hiệu hoàn toàn (đã thử). Đúng như kế hoạch, chỉ là ca yếu | Không cần sửa |
| ghi chú | `test_review2_ocr_reader.py:54-57` | Tham số `Hotline: 1900 1234` đòi cả nhãn mới lẫn dạng số 8 chữ số. Bản sửa chỉ thêm nhãn và số quốc tế sẽ để riêng tham số này xfail. Hợp lý, nhưng brief không nêu số 1900 | Người sửa R9 quyết |
| ghi chú | `test_review2_ledger.py:16` | B-1 đỏ nếu thiếu phần sửa lỗi B (đã thử bằng đột biến) | Commit bộ test cùng hoặc sau phần sửa B, như Opus đã ghi |

## 3. Theo từng điểm được giao

1. **Độ phủ.** 52 ca trong `test-plan.md`, trừ các thay đổi của `opus-signoff.md` (bỏ A-1; bỏ hai tham số `output_format`, `page_range` dài của R8-1; thêm `evaluate` cho E-1; thêm "lỗi lặp lại mãi" cho A-6), đều có test: 111 test. Ca thiếu: không. Ca thừa: không. Lệch không lý do: không; 12 chỗ lệch đều có ghi trong `RUN-LOG.md` và tôi thấy hợp lý, nhất là C đi qua `create` thay vì gọi thẳng `_select_pages`.
2. **Ca xfail.** `KnownBug` chỉ được ném ở hai nơi: `known_bug` (`review2_support.py:42`) và `execute_reply` (`:130`). `execute_reply` chỉ bắt `AttributeError` có chữ `created_at`, đúng tại lời gọi execute. Mọi dấu đều có `strict=True, raises=KnownBug`. Nhóm tham số mang dấu chung đều đang hỏng cả nhóm (không XPASS nào). `except` rộng: hai chỗ ở bảng trên; chỗ thứ ba (`review2_support.py:346`) ghi lại rồi ném tiếp, ổn.
3. **Kết quả, không cơ chế.** Không thấy ca nào gắn với một cách sửa. R6-1 nhận cả hai kết cục, R8-1 nhận cả 422 lẫn kẹp DPI, R2-1 nhận 401/403/404, N4-2 đạt với cả "gửi lại đáp án đã lưu" lẫn "trả lời lại". Rủi ro còn lại là cột giờ mới ở `age_open_turns` (bảng trên).
4. **Đạt nhờ may.** Tệp `fable-review/test_review2_tmp_mut.py` và `…_mut2.py` làm hỏng hành vi đang đúng rồi chạy ca canh:

   | Hành vi bị làm hỏng | Ca canh | Kết quả |
   |---|---|---|
   | Xoá job bằng `rmtree(runs_path/job_id)` không kiểm mã (bản sửa R7 ẩu) | R7-3, 7 tham số | 7/7 đỏ, kể cả hai tham số HTTP `%2e%2e`, `..%5C..%5Cx` |
   | Người sửa/xoá tin không còn thu hồi gì | B-2 | 2/2 đỏ |
   | Bỏ phần sửa lỗi B | B-1 | đỏ |
   | Luật điện thoại nới hết cỡ, bỏ nhãn | R9-4, R9-5 | 5 đỏ; 3 tham số không liên quan vẫn đạt, đúng |
   | Gửi lại và phát lại không kiểm mốc | R3-3, R3-4 "quên" | 3/3 đỏ |
   | Reply target không tới model | R1-3 `same_session` | đỏ; hai tham số kia đạt (xem bảng) |
   | Khoảng trang sai bị cắt thầm | C-2 | 8 đỏ; 2 tham số không bị ảnh hưởng vẫn đạt |
   | Đáp án đã lưu bị bỏ, model trả lời lại | A-3 | đỏ |
   | Lượt "nhớ" thử lại không còn biên nhận | N4-4 | đỏ |
   | `require_admin` tin vai trò trong token | R2-2 | đỏ ở lần hai (lần đầu đột biến của tôi không áp vào được route) |

5. **Ổn định, độc lập.** Thứ tự đảo cho cùng kết quả; không ca nào phụ thuộc ca khác. Mỗi ca Discord dùng một guild ngẫu nhiên; tài khoản tên `p3-…` được `auth_on` dọn; OCR nằm trong `tmp_path`. R5-1 đòi cả bảng `users` có đúng hai admin: nếu test khác để sót admin, ca đỏ bằng `assert` thường (to tiếng, đúng). Thời gian: 137 giây cho review2, trong đó bb 81 giây (xem bảng).
6. **CI.** Không test nào đọc `/health`. Thiếu `POSTGRES_TEST_URL` thì 58 ca bỏ qua sạch, 50 ca không cần container vẫn chạy. Job backend của CI (Ubuntu) có Postgres, cài `requirements.txt` (có `discord.py`, `pymupdf`) và `pip install -e .`, nên bb nạp được `discord_bot` và tệp `tests/test_discord_progress_message.py`. Trên Linux: R7-5 chạy không dấu và theo đọc code sẽ đạt (xoá được tệp đang mở); `..%5C..%5Cx` và `..\..\x` thành tên tệp thường, ca đạt vô hại. **Chưa ai chạy trên Linux**; lần CI đầu tiên là phép kiểm thật.
7. **Bằng chứng lật.** 51/51 ở 14 mã, xem bảng mục 1; kết quả thô ở `fable-review/flip-rerun.txt`.

## 4. Lệnh đã chạy

```
docker run -d --rm --name chk-r2f-pg -p 55441:5432 ... postgres:16-alpine   (+ chk-r2f-redis, chk-r2f-qdrant)
source .../check-c57/env_fix.sh && .venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_{discord_turns,ledger,clocks,auth,ocr_jobs,ocr_access,ocr_reader}.py -q -rfEX --durations=8
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_bot_backend.py -q -rfEX --durations=6
(unset POSTGRES_TEST_URL) cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_*.py -q -rfE
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_tmp_flip.py -rA -k "test_r1_ or test_n2_ or ... or test_a7_"   # chép từ flip/, xoá sau khi chạy
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_tmp_mut.py -rA      # chép từ fable-review/, xoá sau khi chạy
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_review2_tmp_mut2.py -rA     # như trên
cd backend && ../.venv/Scripts/python.exe -m pytest <7 tệp review2 theo thứ tự đảo> tests/test_source_memory_discord.py tests/test_source_memory.py tests/test_auth_api.py -q
cd backend && ../.venv/Scripts/python.exe -m pytest -q -rfEX          # backend đủ bộ
.venv/Scripts/python.exe -m pytest tests -q                          # bộ gốc
docker exec chk-r2f-pg psql ... (đếm lượt mở, tài khoản, ocr_runs)
docker stop chk-r2f-pg chk-r2f-redis chk-r2f-qdrant
```

Tệp tạm đã xoá khỏi `backend/tests`; bản lưu và kết quả thô nằm ở `fable-review/` (`test_review2_tmp_mut.py`, `test_review2_tmp_mut2.py`, `flip-rerun.txt`, `mutation-run.txt`, `bb-run.txt`, `full-tails.txt`). Không sửa tệp test, code, `SO_DO.md` hay CHANGELOG; không commit. Các lần chạy này chưa có mục trong `docs/SO_DO.md`; phiên điều phối ghi.
