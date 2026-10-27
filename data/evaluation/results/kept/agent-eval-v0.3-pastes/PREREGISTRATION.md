# Agent Eval v0.3 — #3 đoạn dán dài thành tài liệu tạm: đăng ký trước (28/10/2026, 01:17, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm
công bố.

**Lần đo HOÃN**, như #2: chủ dự án muốn xây trước, đo gom một đợt sau. Bản này viết lúc code xong
(`6ad1d5e`) và ràng buộc lần đo đó, dù nó chạy lúc nào.

## So cái gì

| | Code |
|---|---|
| #2 | main sau khi gộp ticket 20 #2 (`86c419c`); đo cùng đợt, theo bản đăng ký của #2 |
| #3 | `wip/20-pastes`: tin người dùng dài hơn 10 000 ký tự thành phiếu; read_document đọc đoạn dán của lượt; trần chế độ công cụ 100 000 |

#3 không đổi mô tả công cụ hay lời dặn, nên `tools_sha256` và `agent_guide_sha256` phải bằng lần đo #2.
Nếu khác thì dừng, không so. Trong v0.3 chỉ doc-39 (10 164 ký tự) dài hơn ngưỡng.

## Quy trình

Như #2: cây sạch; gỡ `qwen3.5:9b` trước mỗi lần và ghi `/api/ps`; t0, seed 42, `--probe`; hai lần lạnh;
chạy từng lần một, đọc tin giữa hai lần. Chỉ chạy khi điều phối báo GPU dùng được và luật "Giữ im Ollama"
đã gỡ. Lần đo #2 và #3 chạy cùng một buổi, #2 trước.

## Dự đoán (sai thì báo; không sửa bài, tiêu chí hay bộ chấm sau khi thấy kết quả)

| Dự đoán | Lý do |
|---|---|
| **47/48 câu trả lời trùng lần đo #2 từng chữ**; chỉ doc-39 đổi | phiếu chỉ thay tin dài hơn 10 000; prompt của 47 bài kia không đổi một byte |
| **doc-39 tới được agent**: không còn `INPUT_TOO_LONG`, có ít nhất một lượt model | trần của schema là 100 000, runner đọc trần từ schema |
| **doc-39 gọi `read_document` với `document_id` của đoạn dán** ít nhất một lần | đáp án (14/11, Thu Hà) nằm ở mục 6, đoạn 2–3 trên 7 đoạn, ngoài 600 ký tự đầu và cuối mà phiếu cho thấy |
| r1 trùng r2 từng chữ | t0, seed 42 |

Không dự đoán doc-39 có đạt hay không. Đọc từ đoạn 0 với n = 3 thì tới được đoạn 2 nhưng có thể chưa tới
mục 6; lần thử lại của #2 có thể thêm một lần đọc.

## Ghi lại

- Tổng; doc-39: số lượt model, các lần gọi `read_document` (from_chunk, n), có bước `answer_check` không,
  câu trả lời.
- `tokens_in` lớn nhất của doc-39, so với lần đo #2 (phiếu ~1 500 ký tự thay cho 10 164).
- 47 bài còn lại: số câu khác chữ so với #2 (dự đoán 0).

## Luật quyết định (đặt trước khi thấy kết quả)

Đề xuất ship #3 nếu cả ba điều sau đúng:
- 47 bài còn lại trùng #2 từng chữ;
- doc-39 tới được agent;
- doc-39 gọi `read_document` trên đoạn dán.

Đạt hay trượt của doc-39 ghi lại nhưng không chặn. Nếu một điều sai, báo kèm câu trả lời, không tự sửa tiếp.

## Giới hạn đã biết

- Mỗi lượt đọc được khoảng 18 000 ký tự (3 lần × 6 000), nên đoạn dán dài hơn chỉ đọc được từng phần;
  tóm tắt trọn văn bản dài cần map-reduce, không nằm trong #3.
- Không tìm kiếm được bên trong đoạn dán; agent phải đọc theo thứ tự đoạn.
- Câu hỏi nằm giữa đoạn dán (không ở 600 ký tự đầu hay cuối) thì model không thấy câu hỏi nếu chưa đọc.
