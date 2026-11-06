# Model trần trên BFCL: harness thêm hay bớt bao nhiêu (đăng ký trước, 06/11/2026)

Viết và commit trước lần chạy model trần đầu tiên. Chủ dự án chọn "Đo model trần".

## Hai nhánh

| | Harness (`bfcl_run.py`, runner v2) | Trần (`bfcl_bare.py`) |
|---|---|---|
| Vòng lặp | `AgentService.run()` của Ún | `OpenAICompletionsHandler` của chính BFCL (clone `6ea5797`), vòng FC mà bảng xếp hạng dùng |
| Model | `qwen3.5:9b` qua `/api/chat` | cùng trọng số, qua `/v1` của Ollama, tên `un-bare-qwen9b` (tạo từ `qwen3.5:9b`, chỉ thêm `num_ctx 16384`, `seed 42`) |
| Giống nhau | nhiệt độ 0, seed 42, ngữ cảnh 16 384, tắt suy nghĩ, gỡ model trước mỗi bài, 33 bài `ids_v1.json`, cùng bộ chấm (`bfcl_score.py`) | |
| Khác nhau (chính là thứ cần đo) | tối đa 3 vòng công cụ mỗi lượt; lịch sử giữa các lượt chỉ có chữ; `AGENT_GUIDE`; kiểm câu trả lời và kiểm con số | tối đa 20 vòng; mang cả lệnh gọi và kết quả công cụ sang lượt sau; không lời dặn hệ thống; không kiểm gì |

Đối chứng: lần chạy harness `forced` sáng 06/11 (`5d1d16c`, 25/33), Ollama 0.40.13, và **một lần chạy harness nữa ngay sau nhánh trần** để có đối chứng cùng giờ.

## Dự đoán (từng bài)

Harness hỏng 8 bài: `multi_turn_base_77, 113, 128, 180`, `multi_turn_miss_func_143, 174`, `irrelevance_70`, `multiple_51`.

| Bài | Dự đoán ở nhánh trần | Lý do |
|---|---|---|
| `irrelevance_70` | **đạt** | Harness hỏng vì model gọi `calculate`, tên công cụ của Ún mà `AGENT_GUIDE` nhắc tới; nhánh trần không có lời dặn đó |
| `multi_turn_base_128` | **đạt** | Đo 02/11: mang kết quả công cụ qua lượt (H1) sửa đúng bài này |
| `multi_turn_base_180` | **đạt** | Đo 02/11: thêm vòng (H2) sửa bài này |
| `multi_turn_miss_func_174` | đạt hoặc hỏng, nghiêng hỏng | H1+H2 đi xa hơn nhưng vẫn hỏng ở lượt 1 |
| `multiple_51`, `113`, `143`, `77` | hỏng | Lỗi của model (bỏ tham số, nhầm tên với mã, hỏi lại mã đơn) |
| 25 bài harness đạt | đạt, có thể mất 0–2 bài | Nhánh trần không có kiểm con số (02/11 cứu một lượt ở 180) và không có lời dặn; `irrelevance` có thể gọi công cụ bừa hơn |

Tổng dự đoán: **nhánh trần 26–29/33, tức bằng hoặc hơn harness**. Nếu đúng, kết luận sẽ là: trên BFCL, harness hiện tại *làm mất* điểm, chủ yếu vì trần 3 vòng, lịch sử chỉ-chữ và lời dặn nhắc tên công cụ không có trong bài.

## Cách đọc kết quả

- Hơn kém 1–2 bài trên 33 bài, một lần chạy, coi là chưa phân biệt được; chỉ đọc theo từng bài kèm nguyên nhân.
- Một bài nhánh trần đạt mà harness hỏng thì ghi rõ do phần nào (số vòng, lịch sử, lời dặn) bằng cách đọc vết, không suy từ tổng.
- Không đặt cạnh bảng xếp hạng: 33 bài do dự án chọn, không phải toàn bộ hạng mục.

## Giới hạn biết trước

- Ollama `/v1` không nhận `options`, nên ngữ cảnh và seed đi qua một model đặt tên riêng; đã kiểm `context_length` 16 384 sau một lần gọi thử, ghi vào `manifest.json`.
- Tắt suy nghĩ bằng `reasoning_effort: "none"`; nhánh harness dùng `think: false`. Hai cách gọi khác nhau, cùng ý.
- `presence_penalty 1.5`, `top_k 20`, `top_p 0.95` là mặc định của model, có ở cả hai nhánh.
