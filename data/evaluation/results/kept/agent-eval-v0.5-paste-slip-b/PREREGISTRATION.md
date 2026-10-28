# Agent Eval v0.5 — ticket 20 #3-B, lời phiếu đoạn dán mới: đăng ký trước (opus 5.5, 28/10/2026, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.

Chủ dự án chọn "Sửa lời phiếu", làm bằng hai người độc lập (28/10 08:45). Nhân viên 1 viết lời phiếu
(`wip/20-paste-slip-b`, `563ccfe` + `feda731`, fable GỘP ĐƯỢC) mà không thấy bài mới. Nhân viên 3 viết 4 bài đoạn dán
(`wip/20-paste-tasks`, `bf764f6`..`2e35df2`) mà không thấy lời phiếu mới. Opus thấy cả hai và viết bản này trước khi
chạy. Fable duyệt bản này trước lần chạy đầu.

**GPU:** phiên Quản lý giữ GPU từ 10:50 tới khoảng 16:00. Lần đo chạy sau khi bên đó báo xong, không sớm hơn.

## So cái gì

| Phía | Code | Phiếu |
|---|---|---|
| Trước | main sau khi gộp `wip/20-paste-tasks` (gọi là M) | phiếu #3: "Văn bản đã được lưu thành tài liệu tạm…" |
| Sau | M + gộp `--no-ff` `wip/20-paste-slip-b`, trên nhánh tạm `int/20-3b`; nếu đạt luật, main tiến thẳng tới đúng commit đã đo | phiếu #3-B: không gọi là tài liệu, nói `search_documents` không thấy, chỉ lệnh `read_document(…, from_chunk=0, n=3)` và đọc tiếp bằng `next_from_chunk` |

Bộ bài `agent-eval-v0.5`, bộ chấm `agent-eval-grader-v0.4`. Chỉ chạy **5 bài đoạn dán**: doc-39, doc-40, doc-41, doc-42,
doc-43 (`--tasks`). 47 bài kia không chạy lại: phiếu chỉ thay tin dài hơn 10 000 ký tự (test của Nhân viên 1 giữ điều
đó), và trong v0.5 không bài nào khác dài hơn ngưỡng đó.

| Bài | Đáp án ở đoạn (đếm từ 0) | Số đoạn | Lần đọc tối thiểu nếu đọc từ 0, mỗi lần 3 đoạn |
|---|---|---:|---:|
| doc-39 | 2 | 7 | 1 |
| doc-40 (a) | 3 | 8 | 2 |
| doc-41 (b) | 6 | 15 | 3 (lượt công cụ cuối, `max_steps` 3) |
| doc-42 (c) | trong 600 ký tự cuối mà phiếu cho thấy | 8 | 0 |
| doc-43 (d) | 1 và 5 | 10 | 2 |

## Quy trình

Như đợt A+B: worktree sạch tách tại đúng commit. Trước MỖI lần chạy: gỡ `qwen3.5:9b` và ghi `/api/ps`. t0, seed 42,
`--probe`, `--gpu-shared` theo trạng thái thật. Thứ tự: trước r1, trước r2, sau r1, sau r2, cùng một buổi, từng lần
một, đọc tin giữa các lần.

## Điều kiện phải đúng trước khi so (sai thì dừng)

- `tools_sha256` = `153209…a75e500`, `agent_guide_sha256` và `system_prompt_sha256` bằng nhau ở hai phía.
- Cùng `dataset.sha256` ở hai phía.

## Đo gì (tách "mở" khỏi "đúng", theo fable)

| Đo | Định nghĩa |
|---|---|
| **Mở** | bài có ít nhất một lần gọi `read_document` với `document_id` của đoạn dán (`paste_…`) |
| **Đọc tiếp đúng** | có một lần gọi mà `from_chunk` bằng `next_from_chunk` của lần đọc ngay trước. Chỉ đo được ở doc-40, 41, 43, vì ở doc-39 một lần đọc là đủ |
| **Đạt** | bộ chấm v0.4 (`must_mention`, `tools_forbidden`) |
| Ghi thêm | số lần đọc và `from_chunk`/`n` từng lần; `stop_reason`; câu trả lời có hỏi lại người dùng không (đọc tay); `tokens_in` cả bài; độ trễ |

## Dự đoán (sai thì báo; không sửa bài, phiếu hay bộ chấm sau khi thấy kết quả)

| Dự đoán | Lý do |
|---|---|
| Trước: doc-39 trùng từng chữ câu trả lời của lần đo #3 (`../agent-eval-v0.3-pastes/v0.3-paste-r1-cold`) | đầu vào, phiếu, prompt không đổi |
| Trước: doc-40, 41, 43 **không mở** đoạn dán | cùng phiếu đã làm doc-39 không mở |
| Sau: doc-39 **mở và đạt** | lệnh đọc gợi ý (0, n=3) chạm đoạn 2. Trùng hợp này đã khai ở commit của Nhân viên 1 |
| Sau: ít nhất 2 trong 3 bài doc-40, 41, 43 **mở** | phiếu chỉ lệnh cụ thể và nói tìm kiếm không thấy |
| Sau: doc-42 **không mở** và đạt | đáp án đã nằm trong phần phiếu cho thấy |
| Mỗi phía r1 trùng r2 từng chữ | t0, seed 42 |

Không dự đoán doc-40, 41, 43 có đạt không. doc-41 dễ hết lượt hoặc hết giờ hơn là đọc sai (Nhân viên 3): ba lần đọc dồn
khoảng 17 000 ký tự trước câu trả lời cuối.

## Luật quyết định (đặt trước khi thấy kết quả)

Đề xuất gộp #3-B nếu **cả năm** điều sau đúng ở phía sau, so với phía trước (r1 và r2 khác nhau thì lấy lần tệ hơn):

1. Hai điều kiện so ở trên đúng.
2. doc-39 mở đoạn dán. Đây là điều kiện #3 đã trượt.
3. Ít nhất 2 trong 3 bài doc-40, doc-41, doc-43 mở đoạn dán. Phiếu phải có tác dụng ngoài doc-39.
4. Không bài đoạn dán nào đang đạt ở phía trước thành trượt. Gồm doc-42: phiếu mới không được làm hỏng bài không cần đọc.
5. Ít nhất một trong 4 bài cần phần giữa (doc-39, 40, 41, 43) từ trượt thành đạt.

"Đọc tiếp đúng" và số lần đọc thừa ở doc-42 được ghi lại nhưng không chặn. Nếu một điều sai thì báo kèm câu trả lời,
không tự sửa tiếp, chủ dự án quyết.

## Giới hạn đã biết

- 5 bài, mỗi bài một câu hỏi: đủ để thấy phiếu có làm model mở đoạn dán không, chưa đủ để nói tỉ lệ mở trên đoạn dán
  thật.
- Bộ bài v0.5 do dự án viết. Nhân viên 3 đặt vị trí đáp án theo giả định đọc lần lượt từ đoạn 0, mỗi lần 3 đoạn
  (trần của `read_document`). Phiếu mới cũng gợi ý đúng cách đọc đó. Hai người tới cùng một cách mà không thấy bài
  của nhau, vì đó là cách đọc hiển nhiên dưới cùng một trần; nhưng vì vậy bộ bài không thử được kiểu đọc nhảy cóc.
- 47 bài kia được suy ra là không đổi từ code và test, không chạy lại.
