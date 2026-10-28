# Agent Eval v0.4 — mốc trên main (28/10/2026, 08:22–08:29)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.
Đăng ký trước: `.scratch/foundation-and-agent-eval/issues/20-agent-capabilities.md` (Nhân viên 3, 28/10 02:00).
Chạy trong đợt A+B chủ dự án duyệt lúc 07:58. Không có luật ship: đây là mốc để các thay đổi sau so vào.

## Thật ra chuyện này là gì

Đây là lần chấm đầu tiên toàn bộ code hiện có trên main bằng bộ chấm mới nhất. Bộ chấm mới thêm một mục: bắt câu trả
lời đưa con số mà không tra. Mục này bắt đúng một bài, là bài mà phần tự kiểm của agent cũng không cứu được. Câu trả
lời của agent không đổi chữ nào so với lần đo trước đó, nên phần báo tiến độ gộp sau đó không làm agent làm khác đi.

## Kết quả (r1 = r2 từng chữ)

| | |
|---|---:|
| Tổng | **39/48** |
| 8 bài mới của v0.3 (doc-33..39, hist-11) | 4/8 (doc-34, 35, 37, 38 đạt) |
| `figures_without_lookup` trượt | 1 bài: doc-22 (số 140) |
| `read_document`: tham số hợp lệ | 3/4 lần gọi (doc-33 xin `n` = 5, ngoài khoảng 1–3) |
| doc-39 | tới agent, không mở đoạn dán, trượt (như `../agent-eval-v0.3-pastes/REPORT.md`) |

| Dự đoán đăng ký trước | Kết quả |
|---|---|
| r1 trùng r2 từng chữ | **đúng** |
| doc-39 không còn bị từ chối, đi qua phần xử lý đoạn dán | **đúng**; nhưng như lần đo #3, agent không gọi `read_document` |

## So với lần đo ngay trước (C4, `79065d7`, bộ chấm v0.3)

| | C4 (v0.3) | main (v0.4) |
|---|---:|---:|
| Câu trả lời khác chữ | — | **0/48** |
| Tổng | 39 | 39 |
| Bài đổi kết quả | — | doc-19 trượt → đạt (sửa regex của bài); doc-33 đạt → trượt (luật `n` 1–3 mới) |

Giữa `79065d7` và `7b44b03` có ticket 20 #4 (báo tiến độ, `7a2d71b`) và cột "số liệu không tra" của bảng điểm. 48 câu
trùng từng chữ cho thấy cả hai không đổi những gì model thấy, đúng như fable dự đoán khi miễn đo #4. Thay đổi của bộ
bài v0.4 (hist-03, hist-11) chỉ ở tiêu chí chấm, không ở đề bài.

## 9 bài trượt

| Bài | Trượt mục | Đọc tay |
|---|---|---|
| doc-22 | không tra, thiếu ý, thiếu nguồn, số không tra | lần làm lại của #2 không gọi công cụ |
| doc-25, doc-30 | không tra, thiếu ý, thiếu nguồn | trả lời mà không tra tài liệu |
| doc-26, doc-36 | thiếu nguồn (doc-36 thiếu cả ý) | |
| doc-33 | `n` = 5 | đọc đúng tài liệu, sai khoảng tham số |
| doc-39 | thiếu "14/11", "Thu Hà" | không mở đoạn dán |
| hist-05 | không lọc `author_id` của Lan | |
| hist-11 | thiếu ý, có B203 và 9h (dữ kiện bịa bị cấm từ v0.4) | |

## Điều kiện đo

| | |
|---|---|
| Code | worktree sạch tách tại `7b44b03` (main lúc đo; code giống `8bfaf46`, các commit sau chỉ là ghi chú) |
| Bộ bài / chấm | `agent-eval-v0.4` / `agent-eval-grader-v0.4`; `tools_sha256` 153209…, `agent_guide_sha256` 6194cf… (như các lần v0.3) |
| Quy trình | gỡ `qwen3.5:9b` trước mỗi lần, ghi `/api/ps` (`ollama_ps.jsonl`); t0, seed 42, `--probe`, `--gpu-shared no`; r1 08:22:09, r2 08:26:12 |
| GPU | không dùng chung (phiên Quản lý xác nhận); `qwen3-embedding:0.6b` còn nạp ở cả hai lần |

## Tệp

`v0.4-base-r{1,2}-cold/`: bốn tệp mỗi lần chạy. `analyze.py` tính lại `analysis.json`.
