# Ticket 16 bước 5 — Agent Eval v0.2 trước và sau kiểm soát harness (27/10/2026, 22:57–23:03)

**Thăm dò: mỗi điều kiện một lần chạy lạnh, 40 bài.** Cách đo và luật được đăng ký trước khi chạy
(ticket 16, Comments 27/10 22:57, commit `9d92727`, tác giả 22:57:36; lần A bắt đầu 22:57:43).

## Thật ra chuyện này là gì

Ticket 16 thêm ba thứ vào khung chạy agent: một đồng hồ cho cả lượt trả lời, lỗi công cụ có mã kèm một
câu dặn model rõ ràng, và một bản ghi "khung xương" của từng bước. Chỉ thứ hai đổi điều model đọc, và
chỉ ở ba bài hỏi lịch sử Discord từ giao diện web, nơi công cụ đọc lịch sử không dùng được.

Kết quả: mọi bài khác giữ nguyên từng chữ, ba bài kia vẫn đạt. Đọc tay thì thấy model thôi hỏi lại người
dùng "server nào", đúng điều ticket nhắm tới. Đồng hồ không lần nào phải ra tay. Mỗi bước đều mang đủ
thông tin để ghi bản khung xương, và không mang theo chữ nào của người dùng.

## Điều kiện đo

| | |
|---|---|
| Điều kiện | A = `49c696f` (main trước code của 16; backend và bộ bài giống hệt `9aaa75d`); B = `2306d07` (main sau 16) |
| Quy trình | mỗi điều kiện: checkout đúng commit, gỡ `qwen3.5:9b`, chạy một lần ở nhiệt độ 0, seed 42, `--probe`; cây sạch, `verified: true` |
| Máy | `qwen3-embedding:0.6b` của 09 còn nạp cùng Ollama, như lần 22:31; tiến trình Ollama chạy liên tục từ 22/10. 09 khởi động lại stack heldout lúc 22:57:10 và API của nó ghi log tới 23:04, tức có chạy song song |
| Bộ bài, bộ chấm | `agent-eval-v0.2` sha256 `99b2e915…`; `agent-eval-grader-v0.2` |
| B thêm | `turn_budget_seconds` 90, `final_reserve_seconds` 20 (đọc từ `models.yaml` như `main.py`) |

## Luật "không suy giảm"

| Điều kiện | A | B | Đạt |
|---|---|---|---|
| Tổng lạnh B ≥ A | 34/40 | 34/40 | có |
| hist-08, hist-09, hist-10 không từ đạt thành trượt | đạt, đạt, đạt | đạt, đạt, đạt | có |

**Không suy giảm.** Không bài nào đổi đạt/trượt.

## Dự đoán đã đăng ký

| Dự đoán | Kết quả |
|---|---|
| Mã băm lời dặn, system prompt, ngữ cảnh Discord, mô tả công cụ của A = B | bằng nhau cả bốn |
| 27 bài trước hist-08 trùng từng chữ | 27/27 |
| A trùng A lạnh 22:31 | 40/40 (lần thứ ba trùng: 19:43, 22:31, 22:57) |

Câu trả lời của A và B chỉ khác ở đúng hist-08..10; 10 bài sau đó trùng từng chữ. Lần này một lượt đổi
không lan sang bài sau, giống B/D của ticket 10, khác E/F.

## hist-08..10 đọc tay

Bộ chấm cho cả A lẫn B đạt cả ba bài, vì nó không bắt việc hỏi lại.

| Bài | A (câu lỗi cũ) | B (mã `TOOL_UNAVAILABLE_HERE` + câu dặn mới) |
|---|---|---|
| hist-08 | nói không đọc được, gợi ý tự xem trên Discord | nói cuộc trò chuyện không ở Discord; lệch nhẹ: gợi ý "cấp quyền truy cập server đó" |
| hist-09 | **hỏi lại tên server** và "để tôi thử lại" | nói rõ không ở Discord, không hỏi lại |
| hist-10 | **hỏi lại "server nào"** | nói rõ không ở Discord, đề nghị tra tài liệu |

Hỏi lại "server nào": A 2/3, B 0/3. Mỗi bài vẫn gọi đúng một lần `search_history`.

## Ngân sách 90 s

| | B |
|---|---|
| `stop_reason` ở 40 bước final | `final` 40; `max_steps`, `turn_budget`, `turn_budget_exhausted` 0 |
| Lượt chậm nhất | 9,4 s (doc-04, bài đầu, gồm thời gian nạp model); A cũng 9,4 s |
| Trung vị | 3,8 s (A 4,0 s) |

Không lần nào chạm; một lần chạy ở GPU không thử được nhánh hết giờ, phần đó do test đồng hồ giả của 16.

## Bảng trace rút gọn

Agent Eval không ghi DB, nên phép kiểm áp đúng phép ánh xạ của `add_agent_traces` lên 102 bước của B.

| Kiểm | Số vi phạm |
|---|---:|
| (1) bước thiếu `latency_ms` | 0 |
| (2) bước final thiếu `stop_reason` | 0 |
| (3) `tool_call` thiếu `tool_declared` hoặc `arguments_shape` | 0 |
| (4) hist-08..10 thiếu mã `TOOL_UNAVAILABLE_HERE` | 0 |
| (5) ô text ngoài bộ từ vựng đóng | 0 |

Mã lỗi duy nhất gặp là `TOOL_UNAVAILABLE_HERE`.

## Giới hạn

- Token từng bước: 0/102 bước có token, đúng như đăng ký. Bộ bọc router của runner đọc và xoá số token
  trước khi agent đọc. Token mỗi vòng vẫn có ở sự kiện `model_round` (71/71).
- Không có lần ghi thật vào Postgres; phần đó do `test_agent_trace_summaries` trên DB test.
- Lúc 22:58, khi A đang chạy, Nhân viên 3 lỡ ghi `decide.py` vào worktree, rồi chuyển ra trước 22:58:19.
  Manifest của A vẫn ghi sạch. Runner không đọc thư mục đó, nên câu trả lời không bị ảnh hưởng.

## Các cách tiếp theo

| Cách | Ưu | Nhược |
|---|---|---|
| (a) Đóng ticket 16 | đủ nghiệm thu: test tất định có từ commit 1–4, eval không suy giảm | cái lợi ở hist-09, hist-10 chưa hiện trong điểm, chỉ thấy khi đọc tay |
| (b) Thêm vào v0.3 tiêu chí "không hỏi lại server nào" cho hist-08..10 | bộ chấm thấy được cái lợi đọc tay ở trên | đổi bộ bài thì số v0.2 và v0.3 không so được |
| (c) Sửa `UsageRecordingRouter` để đọc token mà không xoá | eval thấy được cột token của bảng rút gọn | đụng runner; test 957962c đã khẳng định cột đó |

Ý kiến của Nhân viên 3: (a), gom (b) vào danh sách v0.3; (c) chỉ khi cần đo token qua eval.

## Tệp

`v0.2-16-{A,B}-cold/`: đủ bốn tệp mỗi lần chạy. `decide.py` tính lại `analysis.json` từ hai lần chạy này
và lần A lạnh 22:31 ở thư mục 1a-v2.
