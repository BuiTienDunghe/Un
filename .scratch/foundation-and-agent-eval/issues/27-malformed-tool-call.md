# 27 — Lệnh gọi công cụ viết hỏng làm mất cả lượt

Status: xong — gộp main `5f60277` (29/10, chủ dự án duyệt); còn mở: hai cột bảng điểm, mã log riêng, chữ lỗi parser khác
Type: task
Blocked by: —

## Bản chất

Đôi khi model viết lệnh gọi công cụ sai cú pháp, và Ollama từ chối với lỗi 500. Client hiện coi mọi lỗi HTTP là mất kết
nối, nên gửi lại đúng yêu cầu đó ba lần. Ở nhiệt độ 0 cả ba lần ra cùng một đầu ra hỏng, rồi client báo "Cannot connect to
Ollama" và cả lượt mất: người dùng không nhận được gì, còn log nói sai nguyên nhân.

## Bằng chứng

- #3-D, nhánh +1+3' `2839b52`, chạy cô lập: doc-44 mất lượt ở cả ba lần chạy (r1, r2, đủ bộ;
  `kept/agent-eval-v0.7-paste-nudge-search/REPORT.md`). Theo chuỗi, doc-51 ở nhánh nền cũng mất lượt hai lần.
- Thân lỗi Ollama trả về, bắt lại lúc 28/10 23:55 khi chạy doc-44 trên `2839b52` (ba lần y hệt):
  `{"error":"XML syntax error on line 12: element <function> closed by </parameter>"}`. Log server ghi
  `qwen3.5 tool call parsing failed`.
- `backend/app/llm_clients/ollama_client.py:206–208`: `chat_tools` bắt mọi `httpx.HTTPError` (kể cả `HTTPStatusError` của
  `raise_for_status`), chờ rồi thử lại, hết lượt thì ném `OllamaUnavailableError("Cannot connect to Ollama")`.

## Sửa

1. `OllamaClient.chat_tools`: phản hồi 5xx có thân JSON `error` chứa "XML syntax error" thì ném ngay
   `OllamaToolCallParseError(OllamaUnavailableError)`, kèm chữ lỗi của server. Không gửi lại yêu cầu y hệt, vì ở t0 nó cho
   lại cùng đầu ra. Đây là lớp con, để mọi nhánh `except OllamaUnavailableError` của các router vẫn bắt được như cũ.
   5xx khác vẫn thử lại như cũ, nhưng lỗi cuối nêu mã và chữ lỗi của server thay vì "Cannot connect". Chỉ lỗi kết nối
   thật (`httpx.TransportError`) mới báo "Cannot connect".
2. `AgentService.run`, quanh `router.chat_tools`, khi gặp `OllamaToolCallParseError`:
   - Thử lại **một lần riêng** (cờ riêng, không dùng chung với #2 hay bước nhắc đoạn dán), trong một vòng của nó, chỉ khi
     còn ≥ `final_reserve_seconds`. Thêm một tin system ngắn: lệnh gọi công cụ vừa rồi sai định dạng nên không chạy được;
     gọi lại với tham số hợp lệ, hoặc trả lời thẳng nếu đã đủ; không nhắc tới lời nhắc này.
   - Lần thử lại cũng hỏng, hoặc không còn lượt hay giờ: đi đường câu trả lời ép không công cụ đã có (`router.chat`), với
     `stop_reason` mới `tool_call_error`, để người dùng vẫn nhận được câu trả lời từ những gì đã tra.
   - Vết: một bước `kind: "tool_call_error"`, `error_code: "TOOL_CALL_PARSE"`, không giữ chữ; nhãn tiến độ riêng.
3. Không lỗi thì không đổi gì: cùng đầu vào model, cùng các bước, từng byte.

Không đổi `AGENT_GUIDE`, mô tả công cụ (`tools_sha256` còn `153209…a75e500`), bộ bài, bộ chấm.

## Test (Ollama giả, luật giữ im)

- 500 + "XML syntax error" → `OllamaToolCallParseError`, chỉ một lần POST; 500 khác → thử lại, lỗi cuối nêu mã; lỗi kết
  nối → "Cannot connect".
- Router vẫn trả `OLLAMA_UNAVAILABLE` cho lớp con.
- Agent: hỏng một lần → thêm một vòng có tin system, rồi trả lời bình thường; hỏng hai lần → câu trả lời không công cụ,
  `stop_reason` `tool_call_error`; không lỗi → các bước giống hệt trước.
- `agent_eval_scorecard.py` đếm đúng khi có kind mới.

## Đo (opus đăng ký trước, fable duyệt, rồi mới chạy)

Dưới cô lập (`--unload-between-tasks`). Tái hiện: doc-44 trên `2839b52` so với `2839b52` + bản sửa. Không tác dụng phụ:
main đủ 62 bài trước và sau bản sửa, mọi bài không có bước `tool_call_error` phải giống hệt.

## Comments

- 28/10 23:58 (opus) — **Chủ dự án chọn B** (nguyên văn): "Chọn B: sửa lỗi lệnh công cụ hỏng làm mất cả lượt (bắt Ollama 500
  tool call parsing failed, thử lại một lần, báo đúng tên lỗi), đo dưới cô lập."
  - **Nhân viên của Ún 1**, nhánh `wip/27-tool-call-parse` cắt từ main ngay sau commit này, worktree
    `local-ai-core-wt/27-tool-call-parse`. Làm mục "Sửa" và "Test" ở trên. Không chạy `agent_eval` thật; test với luật giữ
    im. Không push. Không sửa tệp ticket này.
  - **fable**: duyệt nhánh theo giao thức tệp, rồi duyệt bản đăng ký.
  - **opus**: đăng ký trước phép đo ở mục "Đo", chạy, báo cáo.
- 29/10 00:40 (opus) — **Đo xong, đạt cả bốn điều.** Báo cáo `kept/agent-eval-v0.7-tool-call-parse/REPORT.md` (`3fdb452`),
  đăng ký `26616b3`, fable GỘP ĐƯỢC nhánh và bản đăng ký, ĐÚNG SỐ báo cáo. doc-44 trên `2839b52`: trước mất lượt 2/2, sau có
  câu trả lời 2/2, lần thử lại viết được lệnh đúng; câu trả lời vẫn trượt vì đọc chưa tới đoạn 4. Main M0 `53b1e80` / M1
  `a2b7bde`: 62/62 giống hệt, 45/62, bước sửa không bật.
- 29/10 00:50 (opus) — **Chủ dự án duyệt gộp** (nguyên văn): "Gộp ticket 27 vào main (merge --no-ff wip/27-tool-call-parse)."
  Gộp `5f60277`; phần backend giống hệt M1 đã đo. Test agent/ollama/chat/eval xanh, trừ 8 bài `test_eval_stack_model_version`
  thiếu `DATABASE_URL`, hỏng y hệt trước khi gộp. Còn mở, chưa làm:
  - hai cột bảng điểm (`max_steps_matches_budget_exhausted`, `rounds_timed_and_counted`) coi lượt `tool_call_error` là thiếu;
  - `chat_service.py:173` ghi lượt `tool_call_error` là "ok", không mã riêng;
  - chỉ bắt chữ "XML syntax error"; parser khác từ chối bằng chữ khác thì vẫn mất lượt, nhưng báo đúng mã.
