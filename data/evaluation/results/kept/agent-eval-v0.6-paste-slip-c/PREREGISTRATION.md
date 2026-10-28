# Agent Eval v0.6 — ticket 20 #3-C, lời phiếu đoạn dán lần hai: đăng ký trước (opus 5.5, 28/10/2026, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.

Chủ dự án chọn B sau khi #3-B trượt luật (28/10 15:40): sửa phiếu thêm ba chỗ, thêm bài mới chưa ai xem, đăng ký lại
rồi đo lại. Nhân viên 1 viết phiếu (`wip/20-paste-slip-c`, `5d16c7b`, fable GỘP ĐƯỢC) mà không thấy bài mới. Nhân viên 3
viết bài doc-44..47 (`wip/20-paste-tasks-c`, `36f8bd7`, fable GỘP ĐƯỢC, đã gộp main `8b91199`) mà không thấy phiếu mới.
Opus thấy cả hai và viết bản này trước khi chạy; fable duyệt bản này trước lần chạy đầu.

## So cái gì

| Phía | Code | Phiếu |
|---|---|---|
| Trước | M = đầu main lúc tách `int/20-3c`: `8b91199` cộng bản này và bài duyệt của fable (chỉ tệp tài liệu); báo cáo ghi sha thật | phiếu #3, đang ship |
| Sau | M + gộp `--no-ff` `wip/20-paste-slip-c` (`5d16c7b`), trên nhánh tạm `int/20-3c`; không commit nào lên main giữa lúc tách và lúc đo xong; nếu đạt luật, main tiến thẳng tới đúng commit đã đo | phiếu #3-C = #3-B + nói trần `n` 1–3, bỏ tổng số đoạn, "đã đủ thì trả lời luôn" đứng trước lệnh đọc |

Bộ bài `agent-eval-v0.6`, bộ chấm `agent-eval-grader-v0.4` **nguyên vẹn** (gồm `args_valid` và `max_tool_calls`, không
ngoại lệ nào). Chạy **9 bài đoạn dán**: doc-39..47 (`--tasks`). 47 bài kia không chạy lại: phiếu chỉ thay tin dài hơn
10 000 ký tự, và không bài nào khác dài hơn ngưỡng đó.

| Nhóm | Bài | Đáp án ở đoạn (đếm từ 0) / số đoạn | Lần đọc tối thiểu từ đoạn 0, mỗi lần 3 |
|---|---|---|---:|
| Đã thấy, cần phần giữa | doc-39 | 2 / 7 | 1 |
| | doc-40 | 3 / 8 | 2 |
| | doc-41 | 6 / 15 | 3 (lượt công cụ cuối) |
| | doc-43 | 1 và 5 / 10 | 2 |
| Đã thấy, đáp án trong phiếu | doc-42 | 600 ký tự cuối / 8 | 0 (không có `max_tool_calls`) |
| **Mới**, cần phần giữa | doc-44 | 4 / 8 | 2 |
| | doc-46 | 7 / 12 | 3 (lượt công cụ cuối) |
| | doc-47 | 2 và 5 / 9 | 2 |
| **Mới**, đáp án trong phiếu | doc-45 | 350 ký tự đầu / 10 | 0, **`max_tool_calls: 0`** |

## Quy trình

Như #3-B: worktree sạch tách tại đúng commit. Trước mỗi lần chạy: gỡ `qwen3.5:9b`, ghi `/api/ps`. t0, seed 42, `--probe`,
`--gpu-shared` theo thật. Thứ tự: trước r1, trước r2, sau r1, sau r2, cùng buổi, từng lần một, đọc tin giữa các lần.

## Điều kiện phải đúng trước khi so (sai thì dừng)

- `tools_sha256` = `153209…a75e500`; `agent_guide_sha256`, `system_prompt_sha256` bằng nhau ở hai phía.
- `dataset.sha256` = `cd38e4d19a09…306ed` (v0.6, 56 bài, tính trên main `8b91199`; fable ra cùng số) ở cả hai phía;
  `tasks_run` đúng 9 bài trên.
- Băm bộ bài khác #3-B (v0.5 → v0.6), nên phía trước đo lại cả doc-39..43, không lấy lại số #3-B (fable).

## Đo gì

| Đo | Định nghĩa |
|---|---|
| **Mở** | có ít nhất một lần gọi `read_document` với id `paste_…` |
| **Đọc tiếp đúng** | có một lần gọi mà `from_chunk` bằng `next_from_chunk` của lần đọc ngay trước; đo ở 40, 41, 43, 44, 46, 47 |
| **`n` lần đọc đầu** / **`n` các lần sau** | tách riêng: phiếu #3-C chỉ sửa được lần đầu; mỗi kết quả đọc vẫn mang `total_chunks` |
| **Đạt** | bộ chấm v0.4 nguyên vẹn |
| Ghi thêm | `from_chunk`/`n` từng lần; số lần đọc ở doc-42 và doc-45; `stop_reason`; có hỏi lại người dùng không (đọc tay); bước `answer_check` trước lần mở đầu (mở sau lời nhắc thử lại không tính là của phiếu); `tokens_in`; độ trễ |

doc-42 và doc-45 cùng ý "đã thấy đủ" nhưng chấm khác nhau: doc-45 có `max_tool_calls: 0` nên **mọi** lần đọc là trượt;
doc-42 chỉ trượt nếu lần đọc thừa xin `n` > 3. Báo cáo đặt hai bài cạnh nhau theo số lần đọc, không theo điểm.

## Dự đoán (sai thì báo; không sửa bài, phiếu hay bộ chấm sau khi thấy kết quả)

| Dự đoán | Lý do |
|---|---|
| Trước: doc-39..43 trùng từng chữ phía trước của #3-B (`../agent-eval-v0.5-paste-slip-b/v0.5-3b-before-r1-cold`) | cùng đầu vào, cùng phiếu, cùng vị trí: runner chạy `--tasks` theo thứ tự bộ bài (`agent_eval.py:394`), nên năm bài này vẫn là năm bài đầu. Trùng thì ủng hộ giải thích "thứ tự chạy" cho lệch doc-39 ở #3-B; không trùng thì r1 = r2 chỉ đúng trong một buổi, không đúng giữa hai buổi |
| Trước: doc-44, 46, 47 trượt; doc-45 đạt, không đọc | #3-B: phiếu cũ đủ ý 1/5, bài đạt duy nhất là doc-42 (đáp án trong phiếu) |
| Sau: mọi bài có đọc đều có `n` lần đọc đầu ≤ 3 | đó là thứ #3-C sửa |
| Sau: doc-39 mở và đạt | như #3-B; lệnh gợi ý (0, n=3) chạm đoạn 2 |
| Sau: doc-43 mở | #3-B mở; fable lưu ý câu "đã đủ thì trả lời luôn" có thể kéo doc-39 và doc-43 về lại kiểu tưởng mép đủ — dự đoán riêng để thấy điều đó |
| Sau: doc-42 và doc-45 không đọc lần nào, cả hai đạt | câu "đã đủ thì trả lời luôn" |
| Sau: doc-44, 46, 47 mở cả ba | như doc-40, 41, 43 ở #3-B (mở 3/3) |
| Mỗi phía r1 trùng r2 từng chữ | t0, seed 42 |

**Không dự đoán `n` các lần đọc sau.** Ở #3-B, 4/5 lần đọc thứ hai trở đi xin `n` = `total_chunks` − `from_chunk`, con số
kết quả đọc tự mang; phiếu chỉ có câu trần nói tới các lần đó (Nhân viên 1, fable). Nếu lần đầu ≤ 3 mà các lần sau vẫn
> 3, thì nguyên nhân là kết quả công cụ (cách E chủ dự án chưa chọn), không phải phiếu — và **điều đó chặn luật**: bộ
chấm v0.4 trượt `args_valid` ở mọi bài cần đọc tiếp (40, 41, 43, 44, 46, 47). Không dự đoán doc-41, doc-46 có đạt không:
cả hai cần trọn 3 lượt công cụ rồi trả lời ở lượt ép (`max_steps`).

## Luật quyết định (đặt trước khi thấy kết quả)

Đề xuất gộp #3-C nếu **cả năm** điều sau đúng. r1 và r2 khác nhau thì đọc theo hướng bất lợi cho đề xuất: một bài "đạt
trước" nếu một lần trước đạt; "đạt sau" chỉ khi cả hai lần sau đạt.

1. Hai điều kiện so ở trên đúng.
2. Không bài nào trong 9 bài đang đạt ở phía trước thành trượt ở phía sau (bộ chấm v0.4 nguyên vẹn).
3. Ít nhất 2 trong 3 bài **mới** cần phần giữa (doc-44, 46, 47) **từ trượt thành đạt**. Đây là điều chặn việc phiếu chỉ
   khớp năm bài đã thấy; tính trượt → đạt chứ không chỉ "đạt sau", để bài phiếu cũ đã làm được không được tính cho phiếu mới.
4. doc-45 (mới, đáp án trong phiếu, `max_tool_calls: 0`) đạt ở phía sau: đo thẳng ý "đã đủ thì trả lời luôn".
5. Ít nhất 2 trong 4 bài **đã thấy** cần phần giữa (doc-39, 40, 41, 43) **từ trượt thành đạt**. #3-B đủ ý ở 39, 40, 41 nhưng
   chỉ đạt 39; điều này kiểm phiếu #3-C có sửa được đúng lỗi `n` đã thấy không.

Lưu ý khi đọc luật: nếu các lần đọc sau vẫn xin `n` > 3, `args_valid` trượt ở mọi bài cần đọc tiếp, nên điều 3 và 5 sẽ
sai dù lần đọc đầu đã đúng; khi đó báo cáo quy nguyên nhân về kết quả công cụ, không về phiếu.

"Đọc tiếp đúng", số lần đọc ở doc-42 (trong phạm vi điều 2), `n` các lần sau được ghi, không chặn thêm. Một điều sai thì
báo kèm câu trả lời, không tự sửa tiếp; chủ dự án quyết. Báo cáo tách riêng: "phiếu làm model mở đoạn dán: có/không,
từng bài", "đọc tiếp tới đáp án xa: x/6", "`n` lần đầu ≤ 3: x/y", "`n` lần sau ≤ 3: x/y"; không gọi một lần đạt luật là
"đọc được đoạn dán dài".

Bảng điểm: lần đo 9 bài là lần đo một phần, không `--append-history`. `analyze.py` bên cạnh tệp này được commit cùng bản
đăng ký, trước lần chạy đầu: nó là cách tính luật, không viết lại sau khi thấy số.

## Giới hạn đã biết

- 9 bài, mỗi bài một câu hỏi; 4 bài mới là bằng chứng duy nhất không bị nhìn thấy trước. Đủ để thấy phiếu có làm model mở
  và đọc trong trần không, chưa đủ để nói tỉ lệ trên đoạn dán thật.
- Mẫu ngày của doc-45 chỉ nhận dạng số (28/11): câu trả lời chỉ nói "thứ Bảy" sẽ trượt (Nhân viên 3).
- doc-47 hai mảnh cách nhau đúng 3 đoạn: đọc lần lượt hai lần là đủ (Nhân viên 3 cố ý, để khác doc-46).
- Vị trí đáp án giả định đọc lần lượt từ đoạn 0, mỗi lần 3; bộ bài không thử kiểu đọc nhảy cóc.
- 47 bài kia được suy ra là không đổi từ code và test, không chạy lại.
