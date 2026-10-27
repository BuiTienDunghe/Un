# Agent Eval v0.3 — #1 đọc theo handle: đăng ký trước (28/10/2026, 00:20, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm
công bố. Nó chỉ cho biết agent sau #1 khác agent trước #1 ở bài nào.

## So cái gì

| | |
|---|---|
| Trước #1 | baseline v0.3 của Nhân viên 3 (`7c9177b`, ở nhánh này là `12d7935`): 35/48, r1 = r2 từng chữ |
| Sau #1 | `wip/20-agent-reading`: registry (`3d5927a`), `search_documents` trả handle và `read_document` (`3515226`), docstring (`8348f68`), cộng commit đăng ký này. Theo lựa chọn H1, A2, P2, L2 (`read_result_max_chars` 6 000), (b). Phần Discord (`read_messages_around`) không có |
| Bộ bài | `agent-eval-v0.3`, 48 bài, bộ chấm `agent-eval-grader-v0.3`, không sửa gì |

Prompt đổi so với baseline, và đó là chủ ý: thêm mô tả `read_document`, `search_documents` có thêm trường,
lời dặn nhắc đọc tiếp. Vì vậy `tools_sha256` và `agent_guide_sha256` sẽ khác baseline.

## Quy trình

- Cây sạch (`worktree_dirty: false`), `--probe --env-file <main>/.env --temperature 0 --seed 42`.
- Trước MỖI lần chạy: gỡ `qwen3.5:9b` qua API Ollama (`keep_alive: 0`), rồi ghi danh sách model đang nạp
  (`/api/ps`) trước và sau khi gỡ, kể cả model nhúng có còn nạp hay không. Không đụng model nhúng.
- Hai lần lạnh liên tiếp: `v0.3-read-r1-cold`, `v0.3-read-r2-cold`.

## Dự đoán (sai thì báo; không sửa bài hay tiêu chí sau khi thấy kết quả)

| Bài | Dự đoán | Lý do |
|---|---|---|
| doc-33..37 (L-a) | đạt cả 5 | đáp án nằm trong đoạn top 1, sau ký tự 400; `read_document` mở được đoạn đó. Bài nào đạt mà không gọi `read_document` thì ghi riêng |
| doc-38 (đối chứng, `max_tool_calls` 1) | đạt; **rủi ro**: lời dặn mới làm agent đọc thừa, gọi 2 lần và trượt | đáp án nằm trong 400 ký tự đầu |
| hist-11 | vẫn trượt | công cụ đọc tin Discord không có trong #1 |
| doc-39 | vẫn trượt với `INPUT_TOO_LONG`, 0 lượt gọi model | đoạn dán dài là việc của #3 |
| 40 bài cũ | không dự đoán số đạt; câu trả lời có thể xáo | prompt đổi. Ticket 10 đổi lời dặn đã xáo 38/40 câu |
| r1 so với r2 | trùng từng chữ 48/48 | t0, seed 42, như baseline |

## Ghi lại

- Tổng; từng bài trong 8 bài mới; `by_check`.
- Mỗi bài cũ đổi đạt ↔ trượt so với baseline: liệt kê, đọc câu trả lời bằng tay.
- Số câu trả lời của 40 bài cũ khác chữ so với baseline.
- `read_document`: bài nào gọi, bao nhiêu lần, bao nhiêu lần ra `BAD_ARGUMENTS`. Đây là số đo đầu tiên cho
  rủi ro H1, tức model chép sai `document_id` 36 ký tự.
- Số lượt gọi công cụ ở doc-38.
- `tokens_in` lớn nhất của một lượt gọi model, so với cửa sổ 16 384.

Không có luật ship. Đây là phép so trước/sau để điều phối và chủ dự án quyết bước tiếp.
