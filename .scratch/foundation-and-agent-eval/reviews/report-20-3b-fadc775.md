ĐÚNG SỐ (báo cáo khớp dữ liệu thô ở mọi con số tôi tính lại; kết luận "trượt điều 4, không gộp" đúng luật đã đăng ký; hai dòng tách riêng có mặt)

# Duyệt báo cáo #3-B — `kept/agent-eval-v0.5-paste-slip-b/REPORT.md`, 58b9ef9 + fadc775 — fable 5.1, 28/10/2026

Tính lại từ `task_results.jsonl` + `events.jsonl` của bốn lần chạy bằng script riêng (không dùng `analyze.py` của opus);
đối chiếu với `PREREGISTRATION.md` 073d152 và quyết định chủ dự án (giữ luật, báo hai dòng).

## Từng con số của báo cáo so với tệp thô

| Mục báo cáo | Tính lại | Khớp |
|---|---|---|
| Điều 1: ba băm + dataset sha bằng nhau hai phía | `153209…`, `6194cf…`, `385cb4…`, `eb62c4…` ở cả 4 manifest; commit 8bb58e1 / c54e3eb, worktree sạch | ✓ |
| Mở đoạn dán: trước 2/5 (40, 41), sau 5/5 | `read_document` với id `paste_…`: trước chỉ doc-40 (4, 4) và doc-41 (0, 15); sau đủ 5 bài, đều từ đoạn 0 | ✓ |
| Đọc tiếp đúng ở bài xa: trước 0/3, sau 2/3 (40, 41) | `from_chunk` của lần sau = `next_from_chunk` của lần trước: sau doc-40 3=3, doc-41 3=3 rồi 6=6, doc-43 chỉ một lần đọc; trước mỗi bài một lần đọc | ✓ |
| Mở sau khi bị kiểm con số bác: 0 | `events.jsonl` không có dòng thử lại nào; mọi `final` có `unsupported_figures: 0` | ✓ |
| Điều 4 SAI: doc-42 đạt → trượt | trước: đạt, không đọc, 1 lượt; sau: 3 lần đọc (0,8)(3,5)(6,2), `must_mention` vẫn đạt, trượt **chỉ** `args_valid` | ✓ |
| Điều 5 đúng: doc-39 trượt → đạt | trước: `search_documents`, thiếu cả hai mẫu; sau: một lần đọc (0, 3), đạt | ✓ |
| Điểm 1/5 cả hai phía; r1 = r2 | băm câu trả lời + chuỗi lần đọc giống hệt r1/r2 ở cả hai phía | ✓ |
| "Công cụ cắt `n` về 3, mỗi lần đọc vẫn trả đúng 3 đoạn, `next_from_chunk` 0→3→6→9" | `agent_service.py:545` `_bounded(n, 2, 1, READ_MAX_CHUNKS)`; mọi `tool_result` phía sau trả đúng 3 đoạn (doc-42 lần 3 trả 2 đoạn vì hết, `next` null) | ✓ |
| "`n` xin = số đoạn phiếu nêu ở 4/5 bài" | lần đọc đầu phía sau: 8, 15, 8, 10 = tổng đoạn của doc-40, 41, 42, 43; doc-39 n=3 | ✓ |
| doc-43 sau: thấy người, thiếu ngày | trượt `args_valid` + `must_mention` thiếu đúng mẫu ngày 10/12; một lần đọc đoạn 0–2, ngày ở đoạn 5 | ✓ |
| Dự đoán "trước: doc-39 trùng #3" sai, trùng 525 ký tự đầu | so với `v0.3-paste-r1-cold`: không trùng, tiền tố chung 525; cùng `tokens_in` 3 572, cùng một lệnh `search_documents` | ✓ |
| Bảng token vào / độ trễ / lý do dừng | 10/10 ô token, 10/10 ô độ trễ (r1), 5/5 lý do dừng khớp | ✓ |
| Lượt model lớn nhất 5 760 token | doc-41 sau, vòng 3 (`model_round`) | ✓ |

## Nhận xét

- **Áp luật đúng.** Bản đăng ký vênh ở một chỗ (ghi "số lần đọc thừa ở doc-42 không chặn", nhưng điều 4 chấm bằng bộ
  chấm v0.4 có `args_valid`). Opus áp đúng chữ của điều 4 và nói rõ chỗ vênh; không sửa luật sau khi thấy số. Đúng.
- **Phiếu #3-B làm được việc nó nhắm** (mở 5/5, đủ ý 4/5), hỏng ở một chỗ phiếu tự gây: nêu tổng số đoạn khiến model
  xin `n` bằng số đó. Quan sát này chưa phải nguyên nhân đã kiểm (phiếu cũ không nêu số đoạn mà doc-41 vẫn xin 15), nhưng
  là giả thuyết tốt nhất có sẵn và #3-C thử đúng nó.
- Con số "bỏ mục `n` thì 4/5" tính sau khi thấy kết quả; báo cáo đã ghi đúng là không dùng để quyết.

## Cho bản đăng ký #3-C (để opus viết, tôi duyệt sau)

- Nói rõ **mục chấm nào quyết điều "đạt → trượt"**: bộ chấm v0.4 nguyên vẹn (gồm `args_valid`), không có ngoại lệ. Lần này
  chỗ vênh không đổi kết luận; lần sau có thể đổi.
- doc-42 và bài (f) mới là hai bài "đã thấy đủ": (f) có `max_tool_calls: 0` nên đọc thừa là trượt; doc-42 không có. Hai
  bài cùng ý nhưng chấm khác nhau, bản đăng ký phải nói trước cách đọc hai kết quả đó cạnh nhau.
- Dự đoán cho doc-39..43 phía sau đã có số từ #3-B; bản đăng ký #3-C nên dự đoán riêng cho `n` ở lần đọc đầu (kỳ vọng
  ≤ 3 ở mọi bài) vì đó là thứ phiếu #3-C sửa.
- Thứ tự chạy: doc-39 trước khác #3 từ ký tự 525 dù cùng lệnh và token; lần 9 bài, doc-39 vẫn là bài đầu, nên so được
  với lần này (5 bài, cũng bài đầu), không so với #3 (bài 48/48).
