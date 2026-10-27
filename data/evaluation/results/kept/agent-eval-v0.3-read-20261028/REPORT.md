# Agent Eval v0.3 — #1 đọc theo handle, trước/sau (28/10/2026, 00:20–00:27)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm
công bố. Cách đo và dự đoán được đăng ký trước khi chạy (`PREREGISTRATION.md`, commit `199475a`).

## Thật ra chuyện này là gì

Công cụ đọc tiếp làm đúng việc của nó. Ở 4 trong 5 bài mà đáp án nằm sâu trong một đoạn, agent mở đúng
đoạn đó và trả lời đúng; trước #1 nó trượt cả 5. Nhưng thêm công cụ thì phải viết thêm vào lời dặn mà
model đọc. Model 9B rất nhạy với lời dặn: 37 trong 40 câu trả lời cũ đổi chữ, 7 bài cũ từ đạt thành trượt,
2 bài theo chiều ngược lại. Không bài cũ nào gọi công cụ mới, nên chỗ tụt đến từ chữ trong lời dặn đổi,
không phải từ việc đọc. Cộng lại, tổng điểm giảm 1 bài. Mỗi phía chỉ đo một lần ở nhiệt độ 0, nên phép đo
này không tách được tụt "thật" khỏi xáo trộn do lời dặn đổi.

## Điều kiện đo

| | |
|---|---|
| Trước | baseline v0.3 (`7c9177b`, trên nhánh này là `12d7935`): 35/48, r1 = r2 |
| Sau | `wip/20-agent-reading` `199475a`, cây sạch, `verified: true`; H1, A2, P2, L2 (`read_result_max_chars` 6 000), (b); không có công cụ Discord mới |
| Prompt | khác baseline, có chủ ý: `tools_sha256` `153209…` (baseline `872acc…`), `agent_guide_sha256` `20c4e0…` (baseline `6194cf…`) |
| Quy trình | gỡ `qwen3.5:9b` qua API trước mỗi lần; t0, seed 42, `--probe`; `v0.3-read-r1-cold` 00:20:28, `v0.3-read-r2-cold` 00:24:00 |
| Model nhúng | r1: Ollama **không nạp model nào** lúc bắt đầu. r2: `qwen3-embedding:0.6b` còn nạp từ r1 (`ollama_ps.jsonl`). Câu trả lời của r1 và r2 vẫn trùng 48/48 |
| GPU | điều phối báo trống trong lúc đo, không dùng chung |

## Dự đoán đã đăng ký

| Dự đoán | Kết quả |
|---|---|
| doc-33..37 đạt cả 5 | **4/5**: doc-36 trượt (xem dưới) |
| doc-38 (đối chứng) đạt; rủi ro đọc thừa | đạt, 1 lượt tra, không đọc thừa |
| hist-11 vẫn trượt | trượt |
| doc-39 vẫn trượt `INPUT_TOO_LONG` | trượt |
| 40 bài cũ: không dự đoán số; câu trả lời có thể xáo | 37/40 đổi chữ; 34 → 29 đạt |
| r1 trùng r2 từng chữ | 48/48 |

## Tổng

| | Trước | Sau (r1 = r2) |
|---|---:|---:|
| Cả bộ | 35/48 | 34/48 |
| 40 bài cũ | 34/40 | 29/40 |
| 8 bài mới | 1/8 | 5/8 |

## Bài đổi kết quả

| Bài | Trước → sau | Gọi `read_document`? | Vì sao (đọc tay) |
|---|---|---|---|
| doc-33, 34, 35, 37 | trượt → đạt | có, 1 lần | mở đoạn có đáp án, trả lời đủ ý |
| doc-10 | đạt → trượt | không | thiếu số trang khi trích nguồn |
| doc-20 | đạt → trượt | không | nêu tên tệp nhưng thiếu trang |
| doc-26 | đạt → trượt | không | không nêu tên tệp |
| doc-12 | đạt → trượt | không | viết "không thể tìm thấy", mẫu "không tìm thấy" của bộ chấm không khớp |
| doc-19 | đạt → trượt | không | nói kết quả "không trả về thông tin từ file", không đúng câu mẫu |
| hist-05 | đạt → trượt | không | lấy 25 tin mới nhất thay vì lọc `author_id` của Lan |
| hist-08 | đạt → trượt | không | lại hỏi "server Discord nào", lỗi mà ticket 16 đã sửa |
| doc-31 | trượt → đạt | không | lần này có tên tệp |
| stat-02 | trượt → đạt | không | lần này gọi `system_status` và thấy Qdrant hỏng |

Theo loại kiểm, chỗ tụt rải đều, không dồn vào một loại:

| Kiểm | Trước | Sau |
|---|---:|---:|
| `citation` (21 bài) | 16 | 15 |
| `must_mention` (42) | 32 | 35 |
| `not_found` (4) | 4 | 3 |
| `no_ask_back` (3) | 3 | 2 |
| `args_expected` (2) | 2 | 1 |

## Công cụ đọc

| Đo | Số |
|---|---|
| Bài gọi `read_document` | 5 (doc-33..37), mỗi bài 1 lần; không bài cũ nào |
| `BAD_ARGUMENTS` (chép sai `document_id` 36 ký tự, rủi ro H1) | 0/5 |
| `n` ngoài khoảng 1–3 đã nêu | 2/5 xin `n` = 5 (được chặn xuống 3) |
| `from_chunk` | doc-34, 35, 37 trỏ đúng đoạn có đáp án; doc-33 và doc-36 đọc từ đoạn 0 |
| doc-36 | đáp án ở đoạn 9, đoạn mà search trả về ở hạng 3; model đọc từ 0 (đoạn 0–2) nên trượt |
| `tokens_in` lớn nhất một lượt | 3 846 (23,5% cửa sổ 16 384) |
| `tokens_in` cả lần chạy | 121 178 → 164 547 (+36%) |
| Độ trễ mỗi bài (TB / p50 / max, ms) | 3 791 / 3 722 / 11 113 → 4 158 / 3 908 / 10 895 |

## Giới hạn

- Mỗi phía một lần ở t0, seed 42. Nhiệt độ 0 làm phép đo lặp lại được, nhưng không cho biết dải dao động khi
  lời dặn đổi. Vì vậy chưa nói được phần tụt 7 bài là do #1 làm hại hay do xáo trộn.
- Lời dặn và mô tả công cụ đổi cùng lúc, nên chưa biết phần nào gây xáo trộn.
- Bài L-b, L-c và đọc theo trang (P2) chưa đo được: v0.3 không có bài cho chúng.
- doc-12 và doc-19 trượt vì câu chữ không khớp mẫu của bộ chấm, dù ý vẫn là "không tìm thấy". Nới mẫu là
  sửa tiêu chí sau khi thấy kết quả, nên không làm ở đây.

## Tệp

`v0.3-read-r{1,2}-cold/`: đủ bốn tệp mỗi lần chạy. `ollama_ps.jsonl`: model đang nạp trước và sau khi gỡ,
mỗi lần một dòng. `analyze.py` tính lại `analysis.json` từ hai lần chạy này và
`../agent-eval-v0.3-baseline-20261028/`.
