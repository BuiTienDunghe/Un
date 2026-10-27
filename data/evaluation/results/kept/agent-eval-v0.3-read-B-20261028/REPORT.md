# Agent Eval v0.3 — #1-B: công cụ đọc, lời dặn như cũ (28/10/2026, 00:32–00:39)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm
công bố. Cách đo, thước đo và luật quyết định được đăng ký trước khi chạy (`PREREGISTRATION.md`, commit
`cc354e1` lúc 00:32:24, sửa giờ ở `aff4a64`; lần chạy đầu 00:32:47).

## Thật ra chuyện này là gì

Bỏ câu nhắc "đọc tiếp" khỏi lời dặn, chỉ để mô tả công cụ tự nói. Kết quả: agent vẫn mở đúng đoạn ở 4 trong
5 bài đọc dài, và các bài cũ gần như về lại mức trước #1. Vậy câu nhắc trong lời dặn là phần lớn lý do làm
bài cũ tụt ở lần #1, không phải bản thân công cụ. Theo luật đặt trước, #1-B đủ điều kiện để đề xuất ship.
Nhưng bài cũ vẫn bị xáo: gần như mọi câu trả lời đổi chữ, năm bài tụt và bốn bài lên. Một trong các bài tụt
là câu trả lời bịa con số mà không tra tài liệu.

## Ba phía (r1; r2 trùng r1 từng chữ ở cả #1 và #1-B)

| | Tổng /48 | 40 bài cũ | 5 bài đọc dài |
|---|---:|---:|---:|
| A — mốc v0.3 | 35 | 34 | 0 |
| #1 — công cụ + câu nhắc trong lời dặn | 34 | 29 | 4 |
| **#1-B — công cụ, lời dặn như main** | **38** | **33** | **4** |

**Luật đặt trước:** ≥ 4/5 bài đọc dài VÀ 40 bài cũ ≥ 33 → đề xuất ship #1-B; nếu không thì làm (C).
**Kết quả: đạt (4/5, 33/40) → đề xuất ship #1-B.** 40 bài cũ đúng bằng ngưỡng, không hơn.

## Điều kiện đo

| | |
|---|---|
| Code | `wip/20-agent-reading` `aff4a64`, cây sạch, `verified: true`. Khác #1 đúng một chỗ: `AGENT_GUIDE` về đúng bản main (`1f9a4d4`, sha bằng main) |
| Quy trình | gỡ `qwen3.5:9b` qua API trước mỗi lần; t0, seed 42, `--probe`; r1 00:32:47, r2 00:36:09 |
| Model nhúng | r1: Ollama không nạp model nào lúc bắt đầu; r2: `qwen3-embedding:0.6b` còn nạp (`ollama_ps.jsonl`). r1 = r2 48/48 |
| GPU | r1 chạy trên GPU trống. Tin "nhường GPU" của điều phối đến lúc r1 sắp xong, nhưng vòng lặp đã nối sang r2 trước khi tin được đọc, nên r2 (00:36–00:39) chạy khi dự án decision model đang chờ. Độ trễ của r2 không dùng ở đây. Xong thì gỡ cả hai model; 00:40 `ollama ps` trống, VRAM 130 MiB |

## Bài đổi kết quả so với A

| Bài | A → #1-B | Đọc tay |
|---|---|---|
| doc-33, 34, 35, 37 | trượt → đạt | gọi `read_document`, mở đoạn có đáp án |
| doc-29, doc-31 | trượt → đạt | có đủ ý và trích nguồn |
| hist-07 | trượt → đạt | lần này tra lịch sử |
| stat-02 | trượt → đạt | gọi `system_status`, thấy Qdrant hỏng |
| doc-10 | đạt → trượt | **không tra gì, bịa** mức phụ cấp "theo quy định hiện hành của Việt Nam" với các con số tự nghĩ ra. A tra và trả lời đúng |
| doc-25 | đạt → trượt | không tra; hỏi người dùng có cho phép tra tài liệu không |
| doc-26 | đạt → trượt | không nêu tên tệp |
| doc-19 | đạt → trượt | trượt regex `must_mention` riêng của bài (câu "không trả về thông tin từ file …pdf") |
| hist-05 | đạt → trượt | lấy tin mới nhất, không lọc `author_id` của Lan |

doc-36 vẫn trượt; lần này nó chỉ tra, không gọi `read_document`. 39/40 câu trả lời cũ khác chữ so với A
(#1: 37/40).

| Kiểm | A | #1 | #1-B |
|---|---:|---:|---:|
| `citation` (21) | 16 | 15 | 15 |
| `must_mention` (42) | 32 | 35 | 35 |
| `not_found` (4) | 4 | 3 | 4 |
| `no_ask_back` (3) | 3 | 2 | 3 |
| `tools_required` (36) | 32 | 33 | 32 |

`tools_required` bằng A (32/36): việc trả lời mà không tra có cả ở A, chỉ rơi vào bài khác. Nhưng ở #1-B,
một bài như vậy (doc-10) bịa số liệu, và bộ chấm chỉ bắt được vì thiếu trích nguồn.

## Công cụ đọc

| Đo | #1 | #1-B |
|---|---|---|
| Bài gọi `read_document` | 5 | 4 (doc-36 không gọi) |
| `BAD_ARGUMENTS` | 0/5 | 0/4 |
| `n` ngoài khoảng 1–3 | 2/5 | 1/4 (doc-33, `n` = 5) |
| `from_chunk` đúng đoạn có đáp án | 3/5 | 3/4 (doc-33 đọc từ 0 vẫn đạt) |
| `tokens_in` lớn nhất một lượt | 3 846 | 3 811 (23,3% cửa sổ) |
| `tokens_in` cả lần chạy (A = 121 178) | 164 547 | 149 244 |

## Giới hạn

- Mỗi phía một lần ở t0, seed 42. Đổi mô tả công cụ vẫn xáo 39/40 câu trả lời cũ, với 5 bài tụt và 4 bài
  lên. Vì vậy mức 33 so với 34 nằm trong vùng xáo trộn mà phép đo này không đo được độ rộng. Luật đặt trước
  vẫn được áp đúng như đã ghi.
- Bộ chấm v0.3 có hai nghi lỗi, để v0.4 xét, không sửa giữa chừng:
  - `NOT_FOUND_PATTERN` không nhận "không thể tìm thấy" (doc-12 ở lần #1);
  - regex `must_mention` riêng của doc-19 không nhận "không trả về thông tin từ file" (fable chỉ ra đúng
    chỗ ở lần duyệt `cd99811`).
- Bài L-b, L-c và đọc theo trang (P2) chưa đo được, vì v0.3 không có bài cho chúng.
- `must_not_mention` không chặn được câu bịa ở doc-10. Muốn bắt riêng việc bịa thì cần tiêu chí mới ở v0.4.

## Tệp

`v0.3-read-B-r{1,2}-cold/`: đủ bốn tệp mỗi lần chạy. `ollama_ps.jsonl`: model đang nạp trước và sau khi gỡ.
`analyze.py` tính lại `analysis.json` (A, #1, #1-B và luật quyết định) từ các thư mục kept/.
