claude-fable-5-2
**GỘP ĐƯỢC** — không có lỗi chặn; một chỗ nên sửa ở ca A-7 (có từ trước, không do Opus gây ra) và hai dòng gia cố nhỏ.

Ngày 10/11/2026. Đối tượng: phần Opus sửa trong `backend/tests/review2_support.py`, `test_review2_bot_backend.py`, `test_review2_auth.py`, `test_review2_discord_turns.py` (theo `fix4/changes.diff`), chưa commit.

**Bản chất:** bốn chỗ hở lần trước đã được bịt thật. Tôi cố tình gây một sự cố lạ ở từng chỗ, và giờ ca báo đỏ thay vì im lặng coi đó là "lỗi đã biết" hay "đã sửa xong". Chỗ thứ năm Opus tự thêm là cần: thiếu nó thì một bản sửa đúng ở phía bot bị đánh đỏ oan, tôi đã tái hiện được bằng một bản sửa khác với bản của Opus. Điều mới tôi tìm ra nằm ngoài phần Opus sửa: một ca vẫn đỏ oan với một kiểu sửa hợp lệ ở phía bot, và nhận định "đọc code là đủ" của chính tôi ở bản duyệt trước là sai.

## 1. Bảng phát hiện

| Mức | Tệp:dòng | Vấn đề | Cách sửa |
|---|---|---|---|
| nên sửa | `test_review2_bot_backend.py:135` | A-7 kiểm cứng `row.status == "queued"` ngay sau tin 1. Bản sửa phía bot "thôi chờ thì huỷ lượt mình bỏ lại" đổi trạng thái thành `cancelled` trước dòng này, nên ca **đỏ oan** bằng `assert` thường, không lật thành XPASS (đã chạy: `fix4-review/fx-a7_bot_cancel.txt`). Lỗi có từ bản gốc, không do fix4 | Đổi thành `assert row is not None and row.status != "completed", row` (điều cần giữ là "tin 1 chưa được trả lời"; dòng 133 đã chứng minh model có được gọi). **Đã kiểm trên bản sao tạm** (`fix4-review/test_review2_tmp_bb135.py`, chỉ khác đúng dòng này): có bản vá huỷ lượt thì `XPASS(strict)`, tin 2 `completed`; không có bản vá thì vẫn xfail như hôm nay |
| nên sửa | `review2_support.py:370-371` | `side._next_id = …` ghi vào thuộc tính riêng của Discord giả ở `tests/test_discord_progress_message.py:50`. Nếu tệp đó đổi tên thuộc tính, phép gán vẫn chạy nhưng không còn tác dụng, mã tin lại bắt đầu từ 1001, và lỗi trùng mã quay lại trong im lặng cho tới ngày lỗi A được sửa | Thêm một dòng trước phép gán: `assert "_next_id" in vars(side), "the fake Discord no longer numbers from _next_id"` |
| ghi chú | `test_review2_auth.py:125-127` | Nếu **cả hai** lần hạ quyền đều bị từ chối bằng `AuthConflictError` (bản sửa quá tay), ca ra `KnownBug` và báo xfail như lỗi cũ (đã chạy: `fx-r5_both_refused.txt`). Chỉ bị che trong lúc còn dấu; bỏ dấu thì đỏ | Thêm trước `known_bug`: `assert succeeded, outcomes` (hai admin hạ quyền lẫn nhau thì luôn phải có một người thành công) |
| ghi chú | `review2_support.py:370-373` | Mã tin trả lời được đóng dấu giờ **trước** mã tin hỏi, nên tin trả lời có thể "cũ hơn" câu hỏi (quan sát thật: trả lời `…230160238649`, hỏi `…230164906390`). Hôm nay vô hại: backend chỉ so mã tin trả lời bằng phép bằng (`repositories.py`, hàm `find_bot_response_delivery` và đoạn kiểm trùng trong `complete_turn`, dòng 458-470), và chỉ đổi mã thành giờ khi ghi sổ tin nghe được (`history_service.py:96`, `:235`), đường mà các ca A không đi qua | Không bắt buộc. Nếu muốn gọn: chuyển hai dòng `side._next_id` xuống sau `source.id = …` |
| ghi chú | `test_review2_discord_turns.py:150`, `:164` | Mọi mã 4xx đều tính là "đã sửa", kể cả 404 hay 422 do một hỏng hóc không liên quan. Khi đó ca ra `XPASS(strict)`, tức vẫn đỏ và có người phải nhìn, nên chấp nhận được | Không sửa |
| ghi chú | `test_review2_discord_turns.py:15` | Import `STALE_TURN_REPLY` ở đầu tệp: nếu hằng số bị đổi tên, cả tệp hỏng lúc nạp chứ không riêng N4-1. Đỏ to tiếng, dễ lần ra | Không sửa. Muốn hẹp hơn thì import trong thân `test_n4_1` |
| ghi chú | `REVIEW-fable.md`, dòng "A-5 và A-7 chỉ được chứng minh lật với bản sửa phía backend" | Câu "đọc code thì bản sửa phía bot cũng lật" của tôi sai với A-7 (dòng đầu bảng này) | Ghi vào `RUN-LOG.md` |

## 2. Trả lời bốn câu hỏi

**Câu 1 — bốn chỗ đã bịt đúng chưa, có mở lỗ mới không.** Đã bịt cả bốn, không thấy lỗ mới.

| Chỗ | Sự cố lạ tôi chạy lại | Kết quả | Bản sửa đúng có bị đỏ oan không |
|---|---|---|---|
| 1. A (`ask` ném lại) | bot vỡ sau khi tin 2 đã xếp lượt | 5/5 FAILED, đúng `RuntimeError` | Không: sửa phía backend 5/5 XPASS; sửa phía bot A-5 (2 kiểu), A-6 ×2, A-8 đều XPASS |
| 2. R5-1 | một luồng vỡ vì lỗi lạ, luồng kia hạ quyền được | FAILED ở `assert all(...)` | Không: bản sửa tạm XPASS |
| 3. R3-1, R3-2 | trả 500 / trả 409 | 500: 2 FAILED `assert 500 < 500`; 409: 2 XPASS | Không |
| 4. N4-1 | câu báo cũ kèm "đã quên"; model trả đúng câu báo cũ | cả hai vẫn xfail, không XPASS | Không: bản sửa tạm XPASS |

Chỗ đỏ oan duy nhất tôi tìm được là A-7 dòng 135, không thuộc bốn chỗ này.

**Câu 2 — ba chỗ làm khác đề xuất.** Đồng ý cả ba.
- *Kiểm trong `ask`:* đồng ý. Mặc định là đỏ nên ca mới viết sau không quên kiểm được, và lỗi hiện kèm traceback thật. Cái giá là helper đổi hợp đồng, nhưng chỉ một tệp gọi nó. Rủi ro tôi đã kiểm: mọi lỗi "hết hạn chờ", "backend 5xx" đều là lớp con của `BackendClientError` nên `answer_mention` tự nuốt, không thành đỏ chập chờn; tệp bot chạy hai lần đều 1 đạt + 5 xfail.
- *"Không chứa" thay cho "khác":* đồng ý, "không chứa" chặt hơn hẳn và không đánh oan đáp án hợp lệ nào (câu báo cũ không chứa chữ "đã quên", nên hai dòng kiểm không dẫm nhau).
- *R5-1 chỉ nhận `AuthConflictError`:* đồng ý. Router chỉ đổi đúng lớp này thành 409 (`routers/auth.py:131`); lỗi nào khác người dùng thấy 500, nên coi là hỏng thật là đúng. Hệ quả cần biết: bản sửa bằng mức cô lập của database mà không đổi lỗi thành `AuthConflictError` sẽ đỏ chứ không lật, và đó là điều mong muốn.

**Câu 3 — chỗ thứ năm.** Cần thật, và đúng. Ràng buộc "một mã tin trả lời chỉ thuộc một lượt" là duy nhất trên **toàn bảng** (`models.py:736-739`), nên bất kỳ bản sửa nào khiến cả tin 1 lẫn tin 2 cùng được giao đều trùng mã 1001. Tôi tái hiện bằng bản sửa của riêng mình cho A-5 (bot gửi lại Discord một lần): đánh số mới thì XPASS, đánh số cũ thì đỏ oan vì `BackendDiscordDeliveryConflictError`; chạy lại A-6 của Opus cũng vậy.

| Cách | Ưu | Nhược |
|---|---|---|
| Giữ nguyên | Đã chạy: hai bản sửa khiến cả hai tin cùng được giao (A-5 gửi lại, A-6 "một lần") lật đúng, và chỉ lật khi có cách đánh số này; ba dòng | Dựa vào thuộc tính riêng của tệp test khác, hỏng thì im lặng |
| Giữ + dòng `assert` canh thuộc tính (bảng trên) | Như trên, và hỏng thì to tiếng; thêm một dòng | Vẫn phụ thuộc tệp kia về tên thuộc tính |
| Sửa Discord giả cho tự cấp mã không trùng | Hết phụ thuộc | Phải sửa tệp test đang có, trái quy ước "chỉ tạo tệp mới"; đụng bộ test của ticket 20 |
| Gỡ | Không phụ thuộc gì | A-5 (sửa kiểu gửi lại) và A-6 "một lần" đỏ oan khi lỗi A được sửa ở phía bot |

Ý kiến của tôi: cách hai. Về tác dụng phụ: trùng với `source.id` cần cùng mili giây và trùng 20 bit ngẫu nhiên, bỏ qua được; thứ tự thời gian xem dòng ghi chú trong bảng phát hiện (vô hại hôm nay).

**Câu 4 — có đáng thêm bản vá phía bot cho A-5, A-7 không.** Đáng, đọc code là không đủ: chính lần chạy này lộ ra A-7 đỏ oan. A-5 đã lật với cả hai kiểu sửa (gửi lại; báo hỏng dứt khoát). Ba bản vá đã có sẵn trong `fix4-review/test_review2_tmp_fx.py`, chép sang `flip/` là xong, mỗi bản chạy dưới 2 giây. Nếu không thêm: tiết kiệm được vài chục dòng tệp tạm, đổi lại người sửa lỗi A ở phía bot sẽ gặp một ca đỏ không rõ lý do.

## 3. Lệnh đã chạy và kết quả

Điều kiện: container dùng một lần `chk-r2g-pg` / `-redis` / `-qdrant` (55441 / 56381 / 56334), migrate tới `20261109_39 (head)`, `env_fix.sh` (Ollama cổng chết, CUDA ẩn), Windows, chạy lần lượt. Kết quả thô ở `fix4-review/`.

| Lần chạy | Kết quả | Tệp |
|---|---|---|
| 8 tệp backend `test_review2_*.py`, code hôm nay | 53 đạt, 55 xfail, 134,4 giây | `baseline-backend.txt` |
| `tests/test_review2_bot_turns.py` | 3 đạt | `baseline-root.txt` |
| `test_review2_bot_backend.py` lần hai | 1 đạt, 5 xfail, 80,7 giây | `bb-second.txt` |
| Bản sửa tạm phía backend (A-5..A-8, R5, R3, N4) | 10/10 XPASS(strict), 6 ca canh đạt | `flip-backend.txt` |
| Bản sửa tạm phía bot của Opus (A-6 ×2, A-8) | 3/3 XPASS(strict) | `flip-bot.txt` |
| Đột biến của Opus trên test đã sửa: `a_msg2`, `r5_one`, `r3_500`, `r3_409`, `n4_appended`, `n4_exact` | 5 FAILED; 1 FAILED; 2 FAILED; 2 XPASS; xfail; xfail — khớp `RUN-LOG.md` | `c-new-*.txt` |
| Của tôi, A-5 bot gửi lại Discord một lần | XPASS(strict); hai lượt đều `completed` | `fx-a5_bot_retry.txt` |
| Như trên, đánh số kiểu cũ (gỡ chỗ thứ năm) | FAILED, `BackendDiscordDeliveryConflictError`; lượt tin 2 kẹt ở `running` | `fx-a5_bot_retry_oldids.txt` |
| Của tôi, A-5 bot báo giao hỏng là dứt khoát | XPASS(strict) | `fx-a5_bot_terminal.txt` |
| A-6 sửa phía bot, đánh số mới / cũ | mới: 2 XPASS; cũ: "một lần" FAILED vì trùng mã, "mãi" XPASS | `fx-a6_bot.txt`, `fx-a6_bot_oldids.txt` |
| Của tôi, A-7 bot huỷ lượt khi thôi chờ | **FAILED ở dòng 135** (`cancelled` khác `queued`) | `fx-a7_bot_cancel.txt` |
| Dòng 135 đổi thành `!= "completed"` (bản sao tạm) + bản vá A-7 huỷ lượt | XPASS(strict); lượt tin 1 `cancelled`, tin 2 `completed` | `fx135-a7_bot_cancel.txt` |
| Bản sao tạm đó, A-7, không bản vá | xfail, 17,8 giây | `bb135-a7-today.txt` |
| Của tôi, R5 cả hai bị từ chối | xfail (bị che trong lúc còn dấu) | `fx-r5_both_refused.txt` |

Sau khi chạy: database thử còn 0 lượt mở, 0 tài khoản, 0 dòng giao tin; tệp tạm đã xoá khỏi `backend/tests/`; ba container `chk-r2g-*` đã dừng (bật hai lượt, lượt hai chỉ để kiểm dòng 135). Không sửa tệp test, code, `SO_DO.md`, CHANGELOG; không commit.

Chưa chạy: đột biến của Opus trên bản test **trước** sửa (`c-old-*`, tôi dùng số của Opus), `a_msg1`, `a5_msg1`, `r5_both`; backend đủ bộ; bộ không có `POSTGRES_TEST_URL`; Linux. Các lần chạy này chưa có mục trong `docs/SO_DO.md`; phiên điều phối ghi.
