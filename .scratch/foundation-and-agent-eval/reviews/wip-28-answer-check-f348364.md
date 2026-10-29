GỘP ĐƯỢC (bốn mục đúng spec; #3 đúng là luật "chỉ bớt bắt, không bắt thêm", kiểm trên 147 câu trả lời đã giữ: không thay đổi; #2 và #3 đổi hành vi nên mốc 55/62 hết hiệu lực như spec đã nói; một ghi chú về nguồn cấu hình ở #4)

# Duyệt wip/28-answer-check f348364 (ticket 28: đuôi ticket 20 — vết ghi con số, lời thử lại, "54 triệu", ngưỡng theo cấu hình) — fable 5.1, 30/10/2026

Đã kiểm: diff dcdb3e7..f348364 (12 tệp, +222 −42), 4 commit theo đúng thứ tự spec. Không chạy model, không DB.

## Từng mục

| Mục | Kiểm | Kết quả |
|---|---|---|
| #1 ff2f6ca — bước `answer_check` ghi chính các con số vào `arguments` | `agent_service.py:400–406`: `arguments={"unsupported_figures": [...]}`, `arguments_shape` giữ số lượng; `postgres_auxiliary_store.py:140` ghi `arguments` vào `AgentTrace` (đi cùng hội thoại), bảng rút gọn chỉ nhận `arguments_shape` + băm `content` — con số không vào bảng rút gọn, đúng ticket 16; `forget_member` đọc `answer_check` như `tool_call`; `redact_arguments` duyệt từng phần tử của list | đúng; không đổi hành vi |
| #2 0cff26b — lời thử lại | chỉ thêm một câu cuối: "viết lại câu trả lời như khi trả lời lần đầu: không xin lỗi, không nhắc tới việc kiểm tra này"; commit riêng | đúng; đổi hành vi, chưa đo |
| #3 a2e2690 — "54 triệu" ↔ "54.000.000" | chạy bộ cũ và mới trên 11 ca dựng tay và trên **147 câu trả lời đã giữ** (gate 66, C7 19, main-after 62) so với đề bài + kết quả công cụ của chúng: **0 ca bắt thêm, 0 ca bớt bắt** trên dữ liệu thật; trên ca dựng tay: "54 triệu" với nguồn "54.000.000" hết bị bắt (cũ bắt "54"), chiều ngược lại cũng hết, "1,5 tỷ" nguồn vouch cho 1.500.000.000, "10,5%" và "năm 2025 tỷ lệ" không đổi, "18.000.000 × 3 = 54.000.000" với nguồn chỉ có 18.000.000 vẫn bị bắt (đúng, đó là phép tính) | đúng; luật đơn điệu (chỉ bớt), hợp lý |
| #4 f348364 — `inline_ceiling(config)` = `context` − 4 096, thiếu `context` → 12 288 | `pastes.py` không import cấu hình; `AgentService(inline_max_tokens=…)` → `take_pastes(messages, max_tokens)`; `main.py` và `agent_eval.py` truyền vào; manifest ghi `paste_inline.max_tokens` thật; test ghim 12 288 với `model_versions.yaml` hôm nay | đúng; không đổi hành vi |
| Test | worktree `28-answer-check` sạch, HEAD f348364; 6 tệp test nhắm chỗ sửa: 192 xanh, 13 bỏ qua | ✓ |

## Về luật #3 (opus hỏi có hợp lý không)

Hợp lý. Nó chỉ mở thêm cách **được vouch** (số đầy đủ ↔ số kèm từ chỉ đơn vị), không mở thêm cách bị bắt, nên không thể làm
câu trả lời nào đang đạt thành trượt. Điểm mù còn lại (số một chữ số kèm đơn vị như "2 triệu" không được kiểm) là điểm mù cũ,
docstring đã ghi. Cái giá thật của luật là ngược chiều: một con số bịa viết "54 triệu" mà nguồn có "54" ở bất kỳ đâu (54 người,
trang 54) thì không bị bắt — nhưng cũ cũng vậy, vì "54" đã vouch cho "54". Không có gì mới để mất.

## Ghi chú, không chặn

- `main.py:226` gọi `settings.load_models()` lần nữa, trong khi chú thích ở `main.py:106` nói "lần gọi thứ hai đã bỏ". Vô hại vì
  `resolve_models` cache lần đầu (cùng dict, không chạy lại probe), nhưng nếu muốn giữ đúng lời chú thích thì truyền
  `router.models.get("general")`. Một dòng.
- `forget_member` phần đọc `answer_check` mới chỉ có test redaction, chưa chạy với DB; opus chạy bộ DB sau gộp như spec.
- Sau gộp, mốc 55/62 cô lập (v1.5.0) không còn áp cho main vì #2 và #3 đổi lời nhắc và bộ soát; CHANGELOG phải ghi, như spec.
  Lần chấm sau cần một lần chạy đủ bộ để có mốc mới.
