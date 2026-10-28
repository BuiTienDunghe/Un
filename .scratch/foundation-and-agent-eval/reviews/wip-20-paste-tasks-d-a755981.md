GỘP ĐƯỢC

# Duyệt wip/20-paste-tasks-d a755981 (ticket 20 #3-D: 6 bài đoạn dán chưa ai xem, bộ bài v0.7) — fable 5.1, 28/10/2026

Đã kiểm: diff 61abb34..a755981, hai commit 749667b + a755981 (4 tệp: `tasks.jsonl` +6 dòng, `dataset.json` version, README
mục v0.7, `test_agent_eval.py` +91/−14; không chạm ticket). Mọi lệnh chạy với `env -u POSTGRES_TEST_URL -u REDIS_TEST_URL` và
bộ giữ im Ollama/GPU; không chạy model. Tệp này không nói gì về hai nhánh code của NV1, NV2.

## Kiểm độc lập (script riêng, không dùng test của nhánh)

| Kiểm | Kết quả |
|---|---|
| 56 bài cũ so với 61abb34, từng dòng JSON chuẩn hoá | 56/56 giống hệt; bài mới đúng 6: doc-48..53 |
| Vị trí đáp án, tính lại bằng `pastes._chunks` + `SLIP_EDGE_CHARS` | trùng bảng NV3 từng số: doc-48 đoạn 5/8; doc-49 đoạn 10/15; doc-50 đoạn 14/25; doc-51 đoạn 0 (ký tự 1 026, ngoài mép 600) và đoạn 6/9; doc-52 đoạn 8/9, cả hai regex trong 600 ký tự cuối (cách mép trong 256 và 395 ký tự); doc-53 đoạn 6/11. Mỗi regex khớp đúng một lần trong cả văn bản |
| Mép phiếu | trừ doc-52, không regex nào khớp 600 ký tự đầu hay cuối; doc-51 mảnh ở đoạn 0 không lộ ra mép (opus hỏi, xác nhận) |
| Brief (i)–(n) | (i) 3–6: ✓ 5; (j) ≥ 10 của ≥ 14 đoạn: ✓ 10/15; (k) 30 000–60 000: ✓ 31 681; (l) 0–2 và ≥ 5: ✓ 0 và 6; (m) mép + `max_tool_calls: 0`: ✓; (n) 4–8, đoạn mồi: ✓ 6, mồi 8 (test tính lại số từ chung: đoạn đáp án 0, đoạn mồi nhiều nhất) |
| Độ dài | 10 446–31 681; trần trong test vị trí nâng lên 60 000 đúng brief; chỉ doc-50 vượt 30 000 |
| "Mọi lần đọc 3 đoạn liền nhau đều vừa trần 6 000" | tôi dựng JSON theo hình `_fit_chunks` cho mọi cửa sổ của 6 bài (doc-50 có 9 cửa sổ): rộng nhất 5 866 (doc-50), trùng README; đoạn dài nhất 1 944 < 2 400 nên không bị cắt |
| Bộ bài nạp | `load_dataset` OK: `agent-eval-v0.7`, sha `d87c4155eb3e…`, 62 bài, bộ chấm v0.4; 6 bài mới không có mục truy xuất (như doc-39..47) |
| "Mỗi cặp thứ–ngày khớp lịch" | 5 cặp có dạng "thứ X dd/mm/yyyy" trong doc-50, doc-52 (năm 2027) đều đúng |
| Gây nhiễu README khai | thấy ở mép: doc-48 "giữ nút Nguồn 3 giây", tổng đài; doc-49 "phòng 105"; doc-50 "phép năm 15 ngày"; doc-51 "15 ngày", "21 ngày"; doc-52 "Hồng Hạc", "22 giờ 15"; doc-53 tổng đài |
| Test | 153 xanh (agent_eval, agent_eval_documents, agent_eval_record, agent_eval_scorecard, agent_pastes). Test runner mới: doc-49 đọc 0, 3, 6 với trần thật → hết lượt, lần cuối `next_from_chunk` 9, không lần đọc nào có đáp án; doc-52 không đọc thì đạt, đọc một lần thì trượt riêng `tool_budget` |
| Độc lập | README chỉ nêu tên hai nhánh code; ghi chú không chứa chữ nào của lời nhắc hay phiếu mới ("chunk_index" trong README có từ v0.5) |
| Worktree | sạch, HEAD a755981 |

## Ba điểm opus hỏi

1. **doc-51 (l):** mảnh thứ nhất ở ký tự 1 026 của đoạn 0, ngoài 600 ký tự phiếu cho thấy; không regex nào khớp mép. Đúng
   ý (l): một lần đọc (0, 3) thấy mảnh này mà không thấy mảnh ở đoạn 6.
2. **doc-49 (j):** đáp án ở đoạn 10; đọc lần lượt 0–8 không tới, nhưng một lần đọc từ 9 với n=3 phủ 9–11. Bài vẫn đo đúng
   trần 9 đoạn; ghi vào bản đăng ký để không ai đọc "đoạn 10" thành "xa hẳn". doc-50 (đoạn 14/25) là bài xa hẳn.
3. **Bộ chia đoạn bỏ dòng đánh số không dấu câu cuối:** tôi kiểm lại ở mức câu: doc-39/40/41/43 mất đúng các dòng tiêu đề
   ("1. Tình hình kinh doanh quý III"…), 8/6/11/5 dòng; không regex đáp án nào nằm trong dòng bị mất, và chín bài cũ đều đã
   có kết quả với đúng bộ chia này. Sáu bài mới: không mất câu nào. **Không làm sai luật đo**: cùng bộ chia ở cả ba nhánh,
   và lỗi này đè đều lên mọi nhánh. Hệ quả cần ghi trong bản đăng ký như giới hạn: ở bốn bài cũ đó model và cả công cụ tìm
   không thấy tiêu đề mục, nên chúng khó hơn một chút so với văn bản thật. Sửa bộ chia là việc riêng (opus sẽ đưa chủ dự án),
   không làm trong #3-D vì đổi đầu vào giữa các nhánh.

## Nhận xét

- Sáu bài đúng sáu kiểu, chủ đề và kiểu hỏi khác hẳn chín bài cũ (robot hút bụi, nuôi thú cưng chung cư, sổ tay nhân sự,
  đặt tiệc, tất niên, bảo hiểm du lịch).
- doc-53 (n) là bài thử "tìm bằng chữ của câu hỏi thì trúng đoạn mồi": theo thiết kế, bài này chỉ đạt khi model không tin
  đoạn mồi, hoặc đọc lần lượt tới đoạn 6 (lượt thứ ba). Bản đăng ký nên dự đoán riêng.
- doc-51 và doc-53 đọc lần lượt cần đủ ba lượt; README đã ghi.
- Mẫu số của doc-50, doc-51 chỉ nhận chữ số ("sáu ngày" trượt); README đã ghi; chấp nhận được vì cùng luật với v0.5/v0.6.

## Việc cho opus

- Gộp được; băm bộ bài đổi (v0.6 → v0.7) nên bảng điểm không `--compare` chéo; lần đo 15 bài (`--tasks` doc-39..53) không
  `--append-history`.
- Bản đăng ký: ghi giới hạn tiêu đề bị mất ở doc-39/40/41/43; ghi doc-49 chỉ vượt trần một đoạn; dự đoán riêng doc-53.
