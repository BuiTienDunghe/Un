GỘP ĐƯỢC

# Duyệt wip/27-tool-call-parse c144999 (ticket 27: lệnh gọi công cụ viết hỏng không còn làm mất cả lượt) — fable 5.1, 29/10/2026

Đã kiểm: diff 5200f1f..c144999 (6 tệp: `ollama_client.py` +35, `agent_service.py` +43, `agent_eval_scorecard.py` 1 dòng,
3 tệp test +310). Bộ giữ im; không gọi Ollama; không chạy model. Đối chiếu với đề bài `issues/27-malformed-tool-call.md`
(chủ dự án chọn B, nguyên văn 28/10 23:58).

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| Client: 5xx có `error` chứa "XML syntax error" → `OllamaToolCallParseError` **ngay lần đầu**, không gửi lại | đúng; lớp con của `OllamaUnavailableError` nên mọi `except` cũ vẫn bắt; chữ lỗi của server đi kèm |
| Client: 5xx khác → thử lại như cũ, lỗi cuối "Ollama answered <mã>: <chữ lỗi>"; chỉ `TransportError` mới "Cannot connect"; `HTTPError` khác nêu tên lớp | đúng thứ tự `except` (lớp con bắt trước `HTTPError`); 4xx có chữ "XML syntax error" không bị coi là lỗi cú pháp (test ghim) |
| Agent: cờ riêng `call_retried`, một vòng riêng (`rounds + 1`), chỉ khi còn ≥ `final_reserve_seconds`; tin system không nêu gì ngoài "gọi lại với tham số hợp lệ hoặc trả lời thẳng, không nhắc tới lời nhắc này" | đúng; không đụng `retried` của #2 (test cả hai thử lại trong một lượt) |
| Hỏng lần hai, hoặc hết giờ → câu trả lời ép **không công cụ** với `stop_reason: tool_call_error`, câu ép riêng "Không gọi được công cụ nữa…" | đúng; đường ép dùng `router.chat` nên không thể tái phát lỗi cú pháp lệnh |
| Vết | bước `kind: "tool_call_error"`, `error_code: "TOOL_CALL_PARSE"`, không chữ; dòng `model_round` của vòng hỏng không có token (Ollama 500 không đếm); nhãn tiến độ riêng |
| Không lỗi thì không đổi gì | test "without a parse error the turn is what it was"; `tools_sha256` `153209652c06…`, `AGENT_GUIDE` `6f80aa8ca420…` không đổi |
| Bảng điểm | `STOP_REASONS` thêm `tool_call_error`; test ghim hai cột `max_steps_matches_budget_exhausted` = False và `rounds_timed_and_counted` = 0 khi có lượt như vậy |
| Test | 242 xanh, 18 bỏ qua (agent*, ollama*, chat*); 17 test mới đúng như đề bài |
| Worktree | sạch, HEAD c144999 |

## Nhận xét

- **Đúng đề bài, đúng chỗ đau.** Lỗi thật là client coi "Ollama trả lời 500" như "không nối được Ollama"; bản sửa tách hai
  chuyện đó và chỉ thử lại khi thử lại có nghĩa (có thêm tin system). Người dùng từ nay luôn nhận được câu trả lời từ những gì
  đã tra, và log nói đúng nguyên nhân.
- **Điểm mù "XML syntax error" là thật nhưng chấp nhận được:** chỉ có một ca bắt được (doc-44, ba lần y hệt). Lỗi cú pháp khác
  của bộ phân tích Ollama sẽ đi đường "thử lại ba lần rồi báo mã + chữ lỗi": vẫn mất lượt, nhưng không còn báo sai; lần đó sẽ
  cho ta chữ lỗi thứ hai để thêm vào `TOOL_CALL_PARSE_MARK`. Nên ghi log cảnh báo mọi 5xx kèm chữ lỗi để không phải chờ ai đọc
  tay.
- **Hai cột bảng điểm đọc lượt `tool_call_error` là thiếu** (NV1 để nguyên, có test ghim). Hệ quả: mọi lần chạy có một lượt
  như vậy sẽ bị bảng điểm đánh dấu "không nhất quán" ở hai cột ấy, dù không có gì sai. Nên sửa hai cột cho nhận `tool_call_error`
  như `turn_budget` trước khi đọc bảng điểm của lần đo ticket 27; không chặn gộp vì luật đo không dựa vào hai cột đó.
- `chat_service.py:173` ghi lượt `tool_call_error` là "ok", không mã: cùng cách với `max_steps` và `turn_budget` (người dùng
  có câu trả lời), chỉ `turn_budget_exhausted` (câu cố định) mới là lỗi. Nhất quán; muốn đếm riêng trên dashboard thì thêm mã
  sau, chủ dự án quyết.
- Tin system thử lại nằm lại trong `working` ở các vòng sau, như lời nhắc của bước đoạn dán; không ảnh hưởng vết.

## Cho bản đăng ký đo (opus đang viết)

- Tái hiện doc-44 trên 2839b52 (cô lập): trước = mất lượt ba lần; sau = có bước `tool_call_error`, có câu trả lời, ghi rõ thử
  lại có viết được lệnh đúng không hay đi đường ép. "Đạt" của doc-44 không phải mục tiêu; mục tiêu là "có câu trả lời và
  `error` rỗng".
- Main đủ 62 bài trước/sau dưới cô lập: mọi bài không có bước `tool_call_error` phải trùng từng chữ — đúng tinh thần "không lỗi
  thì không đổi gì". Ghi mẫu lộ lời nhắc cho tin system mới (cùng regex đã có "không nhắc tới"/"lời nhắc").
