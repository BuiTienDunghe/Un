# Agent Eval v0.3 — #2 kiểm câu trả lời: đăng ký trước (28/10/2026, 01:03, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm
công bố.

**Lần đo HOÃN.** Chủ dự án (28/10, qua điều phối): "hôm nay chưa cần chạy GPU nhiều, hãy xây dựng trước
đã". Lần đo sẽ gom vào một đợt đo chung sau. Bản đăng ký này viết lúc code xong (`cbab275`) và ràng buộc
lần đo đó, dù nó chạy lúc nào. Thư mục sẽ mang ngày chạy trong `REPORT.md`, không đổi tên.

## So cái gì

| | Code | Kết quả đã có |
|---|---|---|
| #1-B | main sau khi gộp ticket 20 #1-B (`2d4a830`) | 38/48; 40 bài cũ 33; bài đọc dài 4/5 (`../agent-eval-v0.3-read-B-20261028/`) |
| #2 | `wip/20-answer-check`: kiểm số liệu (K3) làm cổng, thử lại một lần có công cụ (T1); K1 chỉ ghi trace | đo sau |

Mô tả công cụ và lời dặn không đổi so với #1-B, nên `tools_sha256` và `agent_guide_sha256` phải bằng
#1-B. Nếu khác thì dừng, không so.

## Quy trình

Như #1-B: cây sạch; trước MỖI lần chạy gỡ `qwen3.5:9b` và ghi `/api/ps`; t0, seed 42, `--probe`; hai
lần lạnh. Chạy TỪNG lần một, đọc tin giữa hai lần (luật nhường GPU). Chỉ chạy khi điều phối báo GPU dùng
được và luật "Giữ im Ollama" đã gỡ.

## Dự đoán (sai thì báo; không sửa bài, tiêu chí hay bộ chấm sau khi thấy kết quả)

Ở t0, bộ kiểm chỉ đổi được một lượt khi nó bắt một con số. Trên câu trả lời của #1-B r1, nó bắt đúng hai
bài: doc-10 (bịa mức phụ cấp) và doc-22 (cách làm chung chung, có số 140). Vậy:

| Dự đoán | Lý do |
|---|---|
| **46/48 câu trả lời trùng #1-B r1 từng chữ**; chỉ doc-10 và doc-22 đổi | prompt không đổi; bộ kiểm chỉ thêm lượt khi bắt được số |
| **Không bài nào đang đạt ở #1-B thành trượt** | 46 bài không đổi; doc-10 và doc-22 đang trượt |
| **doc-10: câu cuối không còn số không có nguồn** (`unsupported_figures` = 0 ở bước final) | lần thử lại được tra; ở mốc A, doc-10 tra và đạt |
| doc-10 và doc-22 mỗi bài có đúng một bước `answer_check` | một lần thử lại |
| r1 trùng r2 từng chữ | t0, seed 42 |

Không dự đoán doc-10 hay doc-22 có đạt hay không: tra xong vẫn có thể thiếu trích nguồn.

## Ghi lại

- Tổng, 40 bài cũ, 5 bài đọc dài; so #1-B từng bài.
- Bài nào có bước `answer_check`; số con số không có nguồn trước và sau lần thử lại; lần thử lại có gọi
  công cụ không.
- Thời gian thêm của mỗi lần thử lại.
- Phân bố nhãn K1 (`grounding`) trên các bước final có tra. Chỉ ghi lại, không quyết gì.

## Luật quyết định (đặt trước khi thấy kết quả)

Đề xuất ship #2 nếu cả hai điều sau đúng: không bài nào đang đạt ở #1-B thành trượt, VÀ câu cuối của
doc-10 không còn số không có nguồn. Nếu không, báo lại kèm bài lật và câu trả lời, không tự sửa tiếp.

## Điểm mù đã biết của bộ kiểm (ghi trong `app/services/answer_figures.py`)

- Số tự tính (tổng, đổi đơn vị) không có trong nguồn sẽ bị bắt nhầm. Kết quả một chữ số ("2 giờ") thì
  không bao giờ bị kiểm.
- Số viết bằng chữ ("hai trăm nghìn") không được thấy.
- Câu khẳng định bịa mà không có số thì không bị bắt.
