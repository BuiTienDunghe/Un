GỘP ĐƯỢC (bản đăng ký đủ, `analyze.py` đúng với văn bản luật, chạy được như đã viết; hai ghi chú dưới là để báo cáo nói đúng, không đòi sửa trước lần chạy đầu)

# Duyệt bản đăng ký trước #3-C — `kept/agent-eval-v0.6-paste-slip-c/PREREGISTRATION.md` + `analyze.py`, commit 9f2a23a — fable 5.1, 28/10/2026

Đối chiếu với hai nhánh đã duyệt (`wip-20-paste-slip-c-5d16c7b.md`, `wip-20-paste-tasks-c-36f8bd7.md`), với báo cáo
#3-B đã kiểm (`report-20-3b-fadc775.md`) và với số tôi tính lại trên main 9f2a23a. Không chạy model.

## Từng mục so với thực tế

| Mục | Kiểm | Kết quả |
|---|---|---|
| `tools_sha256` = `153209…a75e500`, `dataset.sha256` = `cd38e4d19a09…306ed`, 56 bài | tính lại trên main 9f2a23a như runner (`core_tools` + `agent_tools.register`; `load_dataset`) | trùng cả hai; phía sau chỉ thêm `slip()` nên không đổi băm nào (đã kiểm ở 5d16c7b) |
| Dự đoán 1: phía trước doc-39..43 trùng từng chữ phía trước #3-B | `git diff 8bb58e1 9f2a23a -- backend/app backend/scripts` | **rỗng**: code model chạy giống hệt; đầu vào 5 bài giống hệt (52 bài cũ nguyên byte); thứ tự giống hệt vì `--tasks` lọc theo thứ tự bộ bài (`agent_eval.py:394`) và 9 bài đoạn dán đứng doc-39 → doc-47 trong `tasks.jsonl`. Khác nhau chỉ còn buổi chạy và model đã nạp sẵn (`/api/ps`), đúng như bản đăng ký nói |
| Bảng vị trí đáp án và số lần đọc tối thiểu | so với số tôi tính ở hai bài duyệt | trùng 9/9 dòng; mọi lần đọc 3 đoạn đều vừa trần 6 000 (rộng nhất 5 759 ở bài mới, 5 745 ở bài cũ) nên cột "lần đọc" đứng được |
| Bước `answer_check` đo được không | `agent_service.py:365` ghi một bước `kind: "answer_check"` vào trace, runner chép sang `events.jsonl` | đo được; ở #3-B không có bước nào nên 0 là thật |
| `analyze.py` — phần rút số từng bài | chạy `load()` + `task()` của nó trên 4 lần chạy #3-B (chỉ 5 bài), so với số tôi tự tính | trùng hết: mở, `from_chunk`/`n` lần đầu, `n` các lần sau, đọc tiếp đúng (40, 41, 42 phía sau), mục chấm trượt, lý do dừng; `pass_to_fail` = doc-42, `fail_to_pass` nhóm đã thấy = doc-39 — đúng kết luận #3-B |
| `analyze.py` — năm điều so với văn bản | đọc từng dòng | 1 = mọi băm bằng nhau ở cả 4 manifest + đúng số đăng ký + version v0.6 + `tasks_run` đúng 9 bài theo thứ tự; 2 = không bài nào `before_pass` (một lần đạt) mà không `after_pass` (cả hai lần đạt); 3 = ≥ 2 trong doc-44/46/47 có "trước không lần nào đạt, sau cả hai lần đạt"; 4 = doc-45 `after_pass`; 5 = ≥ 2 trong doc-39/40/41/43 cùng cách tính. Hướng bất lợi đúng như văn bản: đạt trước nếu một lần, đạt sau phải cả hai, và "trượt → đạt" cần cả hai lần trước trượt |
| `analyze.py` — dự đoán | 9 khoá | khớp 9 dòng dự đoán; "trùng từng chữ" so bằng `answer ==` với `v0.5-3b-before-r1-cold`; "`n` lần đầu ≤ 3" chỉ tính bài có mở; r1 = r2 so câu trả lời từng bài |
| Các ghi chú tôi đặt ở ba bài duyệt trước | đã vào bản đăng ký chưa | đủ: mục chấm nào quyết (bộ chấm v0.4 nguyên vẹn, nêu rõ `args_valid` và `max_tool_calls`); doc-42 cạnh doc-45 theo số lần đọc; dự đoán `n` lần đầu; dự đoán riêng doc-39 và doc-43; phía trước đo lại cả 5 bài cũ; không `--append-history` |

## Ghi chú 1 — điều 5 có thể đạt mà doc-39 lùi

Điều 5 cần 2/4 bài đã thấy từ trượt thành đạt. Ở #3-B, doc-40 và doc-41 đã đủ ý, chỉ trượt `n`; nếu #3-C sửa được `n`
thì hai bài đó đủ cho điều 5 **kể cả khi doc-39 lùi** về kiểu trích mép rồi hỏi lại (rủi ro của câu "đã đủ thì trả lời
luôn" tôi nêu ở bài duyệt phiếu). Luật không chặn ca này vì doc-39 trượt ở phía trước nên không phải "đạt → trượt"; chỉ
dự đoán "doc-39 mở và đạt" bắt được nó. Vậy báo cáo phải nêu doc-39 (và doc-43) thành dòng riêng, đúng như dòng "mở
từng bài" đã đăng ký; một lần đạt luật mà dự đoán doc-39 sai thì phải nói là phiếu đổi lỗi chứ không chỉ sửa lỗi.

## Ghi chú 2 — kết quả dễ gặp nhất: lần đầu đúng, lần sau vẫn xin quá 3

Ở #3-B, 4/5 lần đọc từ lần thứ hai xin `n` = số đoạn còn lại, con số nằm trong kết quả công cụ mà phiếu không chạm được.
Nếu lặp lại, điều 3 và 5 trượt ở mọi bài cần đọc tiếp dù phiếu đã làm đúng việc của nó. Bản đăng ký đã nói trước cách
quy nguyên nhân (kết quả công cụ, không phải phiếu) — đúng và đủ. Hệ quả cho chủ dự án: sau lần đo này có thể phải chọn
tiếp giữa sửa kết quả công cụ (cách E) hay bộ chấm (cách D), không phải sửa phiếu lần ba; nên biết trước để không bất ngờ.

## Nhỏ, không chặn

- Thư mục `kept/agent-eval-v0.6-paste-slip-c/__pycache__/` đang nằm chưa theo dõi trên main (ai đó đã import
  `analyze.py`); xoá trước khi commit báo cáo, hoặc chạy với `PYTHONDONTWRITEBYTECODE=1`. `analysis.json` do script ghi
  là tệp cần giữ.
- Phía "trước" M gồm bản đăng ký và các bài duyệt (chỉ tài liệu) trên 8b91199: không đổi gì model thấy; manifest ghi sha
  thật nên không cần nói thêm.
- doc-41 và doc-46 chỉ đạt khi dùng trọn 3 lượt rồi trả lời ở lượt ép; nếu trượt vì hết lượt thì báo cáo ghi
  `stop_reason` cạnh kết quả (bản đăng ký đã liệt kê `stop_reason` trong "ghi thêm").
