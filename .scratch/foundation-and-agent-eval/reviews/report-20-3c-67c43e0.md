ĐÚNG SỐ (báo cáo khớp dữ liệu thô ở mọi con số tôi tính lại; kết luận "trượt điều 3, không gộp" đúng luật đã đăng ký; mọi dòng tách riêng có mặt)

# Duyệt báo cáo #3-C — `kept/agent-eval-v0.6-paste-slip-c/REPORT.md`, commit 67c43e0 — fable 5.1, 28/10/2026

Tính lại từ `task_results.jsonl` + `events.jsonl` + `manifest.json` của bốn lần chạy bằng script riêng (không dùng
`analyze.py` hay `analysis.json`); đối chiếu với `PREREGISTRATION.md` 9f2a23a và hai ghi chú ở `prereg-20-3c-9f2a23a.md`.

## Từng con số của báo cáo so với tệp thô

| Mục báo cáo | Tính lại | Khớp |
|---|---|---|
| Điều 1: băm đúng số đăng ký, bằng nhau ở 4 manifest; `tasks_run` 9 bài | `153209…a75e500`, `6194cf…`, `385cb4…`, `cd38e4d19a09…306ed` ở cả 4; commit 01daa42 / ed210e4, worktree sạch; `git diff 01daa42 ed210e4` chỉ `pastes.py` + test; `git diff 8b91199 01daa42 -- backend` rỗng | ✓ |
| Điểm 2/9 → 6/9 | trước: 42, 45; sau: 39, 41, 42, 43, 45, 46 — ở cả r1 và r2 | ✓ |
| Điều 2: không bài nào đạt → trượt | `pass_to_fail` rỗng (đạt trước = một lần, đạt sau = cả hai) | ✓ |
| Điều 3 SAI: 1/3 bài mới (doc-46) | doc-44 trượt cả hai phía, doc-47 trượt cả hai phía, doc-46 trượt → đạt | ✓ |
| Điều 4: doc-45 đạt, không đọc | đạt cả hai lần sau, 0 lần `read_document` | ✓ |
| Điều 5: 3/4 (39, 41, 43) | đúng ba bài; doc-40 trượt cả hai phía | ✓ |
| Mở trên 7 bài cần phần giữa: trước 4/7, sau 5/7, phần của phiếu 4/7 | trước mở 40, 41, 46, 47; sau mở 39, 41, 43, 46, 47; ở doc-47 phía sau, bước `answer_check` đứng **trước** lần `read_document` đầu (cả r1 và r2), các bài khác không có bước này → trừ doc-47 còn 4 | ✓ |
| Đọc tiếp đúng: trước 1/6, sau 3/6 | `from_chunk` = `next_from_chunk` lần trước: trước chỉ doc-46; sau 41, 43, 46 | ✓ |
| `n` lần đầu ≤ 3: trước 1/4, sau 5/5 | trước (4,4) (0,15) (1,12) (7,3) → 1; sau 5 bài mở đều (0, 3) | ✓ |
| `n` các lần sau ≤ 3: trước 0/2, sau 5/5 | trước doc-46 xin 8, 5; sau 41 (3, 3), 43 (3), 46 (3, 3) | ✓ |
| doc-42 / doc-45 không đọc lần nào ở cả hai phía | 0 / 0 | ✓ |
| r1 = r2 mỗi phía | băm câu trả lời + chuỗi lần đọc giống hệt 9/9 bài, cả hai phía | ✓ |
| Dự đoán 1: phía trước doc-39..43 trùng từng chữ phía trước #3-B | 5/5 bài trùng, ở cả r1 lẫn r2 | ✓ |
| Dự đoán sai duy nhất: doc-44, 46, 47 mở cả ba | doc-44 không gọi công cụ nào; doc-47 mở sau thử lại | ✓ |
| Bảng từng bài: doc-40 sau gọi `search_history`, nói không dùng được `read_document`, nhờ dán phần giữa | `tools_forbidden` + `must_mention` trượt; câu trả lời đúng như tả | ✓ |
| doc-44 sau: không đọc, nói phần giữa chưa hiện, nhờ dán lại | 1 vòng model, 0 công cụ; câu trả lời đúng như tả | ✓ |
| doc-47 sau: bị bác trước, đọc (0, 3), nói "đã đọc được văn bản hợp đồng đầy đủ", nêu 54.000.000 ở mép cuối, bảo hợp đồng không nêu mức giữ | đúng từng ý; 75 ngày có, 36 triệu không | ✓ |
| doc-46 trước: (1, 12) (4, 8) (7, 5), đủ ý, trượt chỉ vì `n` | trượt duy nhất `args_valid` | ✓ |
| doc-44 trước: lấy 420.000 ở mép cuối | câu trả lời nêu 420.000 và "Thôn Mây Ngàn" | ✓ |
| Bảng token vào / độ trễ (r1) / lý do dừng | 18/18 ô token, 18/18 ô độ trễ, 9/9 lý do dừng khớp | ✓ |
| Lượt model lớn nhất 5 792 token | vòng 3 của doc-46 phía sau | ✓ |
| Hai ghi chú của tôi không xảy ra | doc-39 mở và đạt; 5/5 lần sau xin 3 | ✓ |

## Nhận xét

- **Áp luật đúng, kết luận đúng.** Điều 3 trượt rõ (1/3), không có chỗ vênh nào giữa văn bản luật và cách tính. Dòng "phần
  của phiếu là 4/7" trừ doc-47 là đúng theo bản đăng ký ("mở sau lời nhắc thử lại không tính là của phiếu").
- **Cách giải thích ba kiểu trượt đứng được** vì bám vào câu trả lời thật, không suy diễn thêm. Riêng doc-40, tôi thêm
  một giả thuyết opus chưa nêu, **chưa kiểm**: mô tả công cụ `read_document` vẫn nói "document_id lấy từ kết quả
  search_documents" (ticket cấm đổi để giữ `tools_sha256`), còn phiếu nói "search_documents không tìm thấy nó". Model
  doc-40 nối hai câu đó thành "không dùng được read_document" — đúng lời nó viết. Ở #3-B câu đó không gây lỗi vì
  model chưa đọc kỹ phiếu; #3-C làm model đọc kỹ hơn nên mâu thuẫn chữ nghĩa lộ ra. Tôi đã ghi mâu thuẫn này ở bài duyệt
  563ccfe như "không chặn"; nay nó có một ca thật. Sửa nó là đổi mô tả công cụ, tức đổi `tools_sha256` và phải đo đủ 52
  bài — đó là quyết định của chủ dự án, không phải việc sửa phiếu lần ba.
- Số 2/9 → 6/9 là số thật nhưng 3 trong 4 bài lên là bài đã thấy; bài mới chỉ lên 1 (doc-46, và chỉ nhờ sửa `n`). Báo
  cáo đã nói đúng điều này; nhắc lại để không ai đọc "6/9" thành "phiếu dùng được".

## Nhỏ, không chặn

- `__pycache__/` trong thư mục kept không còn trong `git status`; tốt.
- Lần đo 9 bài không vào bảng điểm; đúng như đăng ký.
