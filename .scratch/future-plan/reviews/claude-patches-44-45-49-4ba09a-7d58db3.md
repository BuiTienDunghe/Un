GỘP ĐƯỢC

Nhánh `claude/patches-44-45-49-4ba09a` (7d58db3), đọc `git diff main...`, chạy test không DB và thử bộ lọc với âm thanh dị dạng, 02/11/2026.

## Bản chất

Ba miếng vá độc lập. Một: trước khi đưa đoạn ghi âm cho model, đo xem trong đó có gì giống tiếng người không; không có thì trả chữ rỗng thay vì để model bịa câu. Hai: khi đọc đoạn dán dài theo từng phần, bọc phần văn bản bằng dấu "đây là dữ liệu" giống như kết quả công cụ, để một câu lệnh giấu trong đoạn dán không bị đọc như lời người dùng. Ba: một bộ bài đo riêng cho hai ticket, dữ liệu bịa, sinh từ hạt giống cố định.

## Đã kiểm, không thấy lỗi

| Mục | Kết quả |
|---|---|
| Bộ lọc với âm thanh xấu | `_speech_seconds`: mảng rỗng, 1 mẫu, nửa khung, 1 khung, toàn NaN, nửa NaN → 0.0, không ném; toàn `inf` → 3.0 (model được hỏi, không hỏng). Cảnh báo numpy đi ra stderr, không vào ống trả lời (`model_process` đã `dup2`). Stereo/int16 ném hoặc sai nhưng không tới được: `_decode` (`voice_server.py:75-91`) luôn trả mono float; ngoài ra `model_process:173-175` bắt mọi lỗi của một bản ghi → cửa trả 500, hàng đợi vẫn chạy |
| `_invented` | Chữ rỗng, một chữ, toàn khoảng trắng → False; "ok"×6 → True; 41 chữ cái trong 0,5 s → True; câu mẫu dưới 3 s → True, đúng 3 s → False (biên đúng) |
| Dấu dữ liệu không tràn cửa sổ | `long_input.py:202,220-221`: phần ≤ 36 415 ký tự + hai mép + 3 cặp dấu (78 ký tự mỗi cặp, 234 tổng) ≈ 11 650 token, dưới cả trần 12 288 của N1; test `..._still_fit_the_window` so với 16 384 là đúng vì lời gọi ghi chú chỉ sinh tối đa 450 token, không giữ 4 096 dự trữ. Tắt phòng thủ thì `wrap_tool_result` trả nguyên văn, đường mặc định (`long_input` tắt) không đổi byte |
| 66 bài v0 | `git diff main... -- data/benchmarks/agent_eval/v0` rỗng; test `..._v0_is_untouched` kiểm id không trùng và sha khác |
| Kích thước, dữ liệu | 5 tệp 1,14 MB (tasks 795 KB, documents 289 KB); tên người, công ty, số tiền, guild `900000000000000001` đều bịa, không có id Discord thật |
| Sinh lại đúng tệp | `python -m scripts.agent_eval_build_long --check` → "khớp"; mọi ngẫu nhiên qua `random.Random(seed)`, không dùng `random` toàn cục, so sánh bỏ CRLF |
| Test không DB | backend `test_long_input` + `test_agent_eval_long`: 89 qua; gốc `tests/test_voice_server.py`: 23 qua |

## Ghi chú, không chặn

- **thấp** — `tools/voice_server.py:47-58`: các ngưỡng (−50 dBFS, 3 dB chênh, 0,3 s) đặt từ âm thanh tổng hợp; test tự ghi giọng tổng hợp nhỏ 26 dB (đỉnh −48 dBFS) bị coi là không có gì. Giọng thật nói nhỏ có thể bị bỏ; nhánh đã ghi rõ trong docstring, chưa có số đo trên giọng thật.
- **thấp** — `long_input.py:220`: hai mép (`head`, `tail`) chứa chính câu hỏi của người dùng nay cũng nằm trong dấu "dữ liệu" của lời gọi ghi chú; model có thể coi câu hỏi là dữ liệu, chất lượng ghi chú sau thay đổi này chưa đo (bộ v0-long chính là để đo, chưa chạy).
- Bộ v0-long chưa có số mốc nào (README tự ghi); bài ctx chỉ chạm trần khi cửa sổ 16 384.
