# Agent Eval v0.3 — baseline (28/10/2026, 00:04–00:11)

**Mốc, không có luật ship.** Hai lần chạy lạnh, 48 bài. Cách đo và dự đoán được đăng ký trước khi chạy
(ticket 20, Comments 28/10 00:10, commit `c87cfa1`).

## Thật ra chuyện này là gì

Bộ bài mới có 8 bài đòi đọc nhiều hơn những gì agent hiện thấy. Đúng như dự đoán, agent hôm nay trượt cả
6 bài đọc dài: nó tìm đúng tài liệu nhưng chỉ thấy phần đầu mỗi đoạn. Ở phần lớn các bài, nó nói thật là
không thấy thông tin; có bài nó còn nhận ra bảng số liệu bị cắt. Riêng một bài nó bịa: được hỏi về chuyến
dã ngoại, nó ghép giờ họp và phòng họp của chuyện khác thành câu trả lời. Bài dán văn bản dài bị từ chối,
giống hệt API thật.

40 bài cũ cho ra đúng từng chữ như lần đo hơn một giờ trước, nên con số mốc của chúng đáng tin. Đây là
điểm xuất phát để đo công cụ đọc tiếp (#1) và đoạn dán thành tài liệu tạm (#3).

## Điều kiện đo

| | |
|---|---|
| Code | main `f2af55e` cộng các commit eval của `wip/20-eval-v03` (đầu nhánh `c87cfa1`), không đổi `backend/app`; cây sạch, `verified: true` |
| Bộ bài | `agent-eval-v0.3`, sha256 `6f69ddc3c6db…`, 48 bài; bộ chấm `agent-eval-grader-v0.3` |
| Quy trình | gỡ `qwen3.5:9b` trước mỗi lần, t0, seed 42, `--probe`; `v0.3-base-r1-cold` 00:04:42, `v0.3-base-r2-cold` 00:07:55 |
| Model nhúng | `qwen3-embedding:0.6b` **còn nạp** cùng Ollama lúc bắt đầu cả hai lần (log `loaded_before`), giống lần đo của ticket 16 lúc 22:57 |
| Mã băm prompt | lời dặn, system prompt, ngữ cảnh Discord, mô tả công cụ: bằng lần đo B của ticket 16 |

## Dự đoán đã đăng ký

| Dự đoán | Kết quả |
|---|---|
| 6 bài đọc dài (doc-33..37, hist-11) trượt | trượt cả 6 |
| doc-39 bị từ chối `INPUT_TOO_LONG`, 0 lượt gọi model | đúng (10 164 > 10 000) |
| doc-38 (đối chứng) đạt | đạt, 1 lượt tra |
| r1 trùng r2 từng chữ | 48/48 |

## Tổng

| | Đạt |
|---|---:|
| Cả bộ (r1 = r2) | 35/48 |
| 40 bài cũ | 34/40 |
| 8 bài mới | 1/8 (đối chứng) |

40 bài cũ trùng từng chữ với lần đo B của ticket 16 (v0.2, 22:57) trên cả 40 câu trả lời. Bộ chấm v0.3
không lật bài cũ nào: hist-07 vẫn trượt vì chỉ tra tài liệu, không tra lịch sử; hist-08..10 không hỏi lại
"server nào" (3/3).

## 8 bài mới

| Bài | Kết quả | Lượt tra | Câu trả lời |
|---|---|---:|---|
| doc-33 | trượt | 2 | nói không tìm thấy nhiệt độ phòng máy và công suất UPS |
| doc-34 | trượt | 3 | nhận ra "bảng thời hạn lưu không hiển thị đầy đủ trong các đoạn trích" |
| doc-35 | trượt | 2 | nói các đoạn trích không có khổ và giấy của túi giấy |
| doc-36 | trượt (thiếu cả tên tệp) | 1 | nói không thấy mã báo giá lẫn thời gian đặt giấy |
| doc-37 | trượt | 1 | biết máy có card đồ hoạ, nói thông số "chưa được nêu rõ đầy đủ" |
| doc-38 | **đạt** | 1 | qwen3.5:9b, khoảng 7 GB VRAM, có tên tệp |
| doc-39 | trượt | 0 | API từ chối trước khi agent chạy |
| hist-11 | trượt | 1 | **bịa**: ghép "9h sáng thứ Năm" và "phòng B203" của chuyện họp thành phương án dã ngoại |

Ba bài tra lại 2–3 lần để tìm phần bị khuất. doc-34 là lượt chậm nhất của cả lần chạy (11,1 s).

## Giới hạn

- hist-11 bịa mà bộ chấm chỉ bắt được vì thiếu đáp án, không phải vì có dữ kiện sai. Muốn phạt riêng việc
  bịa thì phải thêm `must_not_mention` (B203, 9h). Việc đó là sửa tiêu chí **sau** khi đã xem câu trả lời,
  nên để v0.4.
- Runner trả mã thoát 1 khi có bài lỗi, mà doc-39 luôn "lỗi" ở mốc này. Script nào tự động chạy eval thì
  không được đọc mã 1 thành "chạy hỏng".
- Chưa kiểm được giả thuyết "model nhúng còn nạp góp vào chênh lạnh/nóng": cả hai lần, và lần 22:57, đều có
  model nhúng nạp sẵn. Muốn tách thì cần một lần lạnh không có model nhúng, mà luật hiện tại không cho gỡ nó
  khi 09 hay lab đang dùng.

## Chờ v0.4

| Mục | Vì sao |
|---|---|
| Bài L-b (đáp án ở đoạn kề mà truy xuất không trả về) | Corpus lab quá ngắn: 5 đoạn trả về đã chứa đoạn có đáp án. Cần tài liệu dài hơn |
| Bài L-c (đọc theo số trang, P2) | Corpus lab không có PDF có trang |
| hist-11 cấm dữ kiện bịa | Như mục Giới hạn |
| hist-03 cho phép tra tài liệu trước | Cùng lý do với hist-07 ở v0.3; điều phối chưa giao |

## Tệp

`v0.3-base-r{1,2}-cold/`: đủ bốn tệp mỗi lần chạy. `analyze.py` tính lại `analysis.json` từ hai lần chạy
này và lần B của ticket 16 (`../agent-eval-v0.2-harness-controls-20261027/`).
