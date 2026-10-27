# 16 — Kiểm soát harness: ngân sách cả lượt, lỗi công cụ có mã, trace bền (M4, cách B)

Status: đã khảo sát; giao Nhân viên 1 thiết kế; code sau khi 10 gộp
Type: task
Blocked by: 10 (cùng đụng `backend/app/services/agent_service.py`; đổi harness giữa chừng làm bẩn phép đo của 10)

## Vì sao

Chủ dự án chọn cách B (27/10): ba tiêu chí nghiệm thu của họ ở Mốc 4 — quản lý tài nguyên, tracing,
khả năng phục hồi — không bao giờ hiện thành lỗi trong Agent Eval (bài thi không thử treo hay xoá), nên
"chỉ làm khi lỗi đo được chỉ ra" sẽ không bao giờ tới chúng. Registry công cụ **chỉ khi có công cụ thứ 4**.

Bằng chứng đã có (kiểm code 27/10):

| Điều | Bằng chứng |
|---|---|
| Không có ngân sách thời gian cho cả lượt | `agent_service.py` không có timeout; chỉ `max_steps` 3 và mỗi lần gọi model chờ tối đa `ollama_chat_timeout_seconds` 120 s (`settings.py:173`) → một câu trả lời có thể ~8 phút |
| Lỗi công cụ là chuỗi tự do | `_execute_tool` (`agent_service.py:203`) trả `{"error": "..."}`; hist-10 ở t0.4 hỏi lại "server nào?" thay vì nói rõ công cụ không dùng được ở web |
| Trace chết cùng hội thoại | `agent_traces.conversation_id` `ondelete="CASCADE"` (`models.py:1079`); chú thích `models.py:1104` ghi bảng có 0 dòng. Cả web (`chat_service.py:155`) lẫn Discord (qua `respond_with_context`) đều ghi vào bảng này |

## Câu hỏi thiết kế phải trả lời trước khi code

1. **Ngân sách**: thời gian tường cho cả lượt (bao nhiêu? cấu hình ở đâu — `models.yaml` mục `agent`?);
   có cần ngân sách token không; khi chạm thì làm gì (trả lời từ những gì đã có, như nhánh "Tool budget
   exhausted" hiện tại, hay báo lỗi rõ).
2. **Lỗi có mã**: bộ mã nhỏ (vd `TOOL_UNAVAILABLE_HERE`, `TOOL_FAILED`, `TOOL_TIMEOUT`, `BAD_ARGUMENTS`),
   phần nào cho model đọc, phần nào ghi vào trace; có thử lại không.
3. **Trace bền — và quyền riêng tư**: chú thích `models.py:1069-1071` ghi đây là thiết kế có chủ đích
   ("a trace never outlives the answer it explains"). Trace chứa tham số công cụ (câu hỏi của người dùng)
   và kết quả (đoạn tài liệu, tin Discord). Giữ nguyên văn sau khi người dùng xoá hội thoại là giữ dữ liệu
   cá nhân trái ý họ. Phải chọn giữa: (a) giữ trọn; (b) giữ bản rút gọn không có nội dung (tên công cụ,
   số bước, độ trễ, mã lỗi, token, hash) và xoá nội dung theo hội thoại; (c) giữ trọn có thời hạn. Đối
   chiếu với khuyến nghị của các harness và OpenTelemetry GenAI về việc ghi nội dung.
4. **Registry**: không làm (chưa có công cụ thứ 4); ghi điều kiện mở lại.

## Khảo sát harness (nguồn chính thống, 27/10)

Một agent phụ đọc tài liệu chính thức và repo gốc; nguồn đầy đủ ở cuối mục. Số mặc định đọc từ `main`
của repo không gắn với một bản phát hành; các mục đánh dấu ⚠ là chưa kiểm được từ nguồn gốc hoặc phụ
thuộc phiên bản.

| Mối quan tâm | Các harness làm gì | Hệ quả cho Ún |
|---|---|---|
| Ngân sách cả lượt | Hầu hết giới hạn **số lượt / số lần gọi / token**, hiếm khi giới hạn giây: Claude Agent SDK `max_turns`, `max_budget_usd`; OpenAI Agents `max_turns` (mặc định 10 ⚠ đọc từ source), và nói rõ timeout của họ "không giới hạn cả lượt chạy"; LangGraph `recursion_limit` (⚠ mặc định chưa rõ: 25 / 1000 / 10007); Pydantic AI `UsageLimits` (`request_limit` 50) và `run(timeout=)`; smolagents `max_steps` 20; Google ADK `max_llm_calls` 500. Chỉ Pydantic AI và Inspect AI giới hạn **thời gian tường** cho cả lượt | Ún đã có `max_steps`; thêm thời gian tường là theo mẫu Pydantic AI / Inspect |
| Khi chạm giới hạn | Hai họ: **ném lỗi, mất phần đã làm** (OpenAI, LangGraph, ADK, Pydantic `UsageLimitExceeded`) hoặc **dừng có cấu trúc, giữ phần đã làm** (Claude SDK trả subtype `error_max_turns`; smolagents ép một câu trả lời cuối; Inspect "vẫn chấm điểm"; Pydantic `RunTimedOut.all_messages()`) | Ún nên theo họ thứ hai: trả lời từ những gì đã gom (như nhánh "Tool budget exhausted" hiện có), ghi mã lý do dừng vào trace |
| Lỗi công cụ | Mặc định phổ biến: **trả lỗi về model như một kết quả công cụ, vòng lặp chạy tiếp** (Claude SDK `is_error`, OpenAI `failure_error_function`, smolagents, ADK, Inspect `ToolError`). Anthropic ("Writing tools for agents") muốn thông báo lỗi "cụ thể, gợi ý được việc cần làm", không phải mã khó hiểu; OTel muốn `error.type` là định danh ít giá trị | **Mã vào trace, câu giải thích có ích vào model** — không mâu thuẫn với yêu cầu "lỗi có mã". Thử lại có ngân sách riêng (Pydantic `retries=1`) |
| Trace và quyền riêng tư | Trace luôn nằm **ở kho khác** với trạng thái hội thoại (OpenAI sessions vs trace processor; Claude transcript vs OTel; LangGraph checkpointer vs LangSmith). OTel GenAI: tham số/kết quả công cụ và nội dung tin nhắn là **opt-in, "SHOULD NOT capture by default"**; Claude Code tắt mọi cổng nội dung mặc định nhưng luôn phát `error_type`. (OpenAI và Pydantic AI thì mặc định bật nội dung) | Khớp lựa chọn (b) của chủ dự án: bản rút gọn không nội dung, khoá theo `conversation_id` như một thuộc tính chứ không phải khoá ngoại CASCADE (suy luận của agent phụ, không nguồn nào nói thẳng) |
| Registry công cụ | Anthropic: "bắt đầu bằng gọi API LLM trực tiếp", "giảm lớp trừu tượng"; "nhiều công cụ hơn không phải lúc nào cũng tốt hơn". Mọi SDK đăng ký công cụ bằng decorator hoặc danh sách, không cần lớp registry riêng | Khớp "registry chỉ khi có công cụ thứ 4" |

Nguồn chính: anthropic.com/engineering/building-effective-agents (19/12/2024) và
/writing-tools-for-agents (11/09/2025); code.claude.com/docs (agent-sdk/agent-loop, hooks, custom-tools,
monitoring-usage); openai.github.io/openai-agents-python (running_agents, tools, tracing, models) và
`run_config.py`; docs.langchain.com/oss/python/langgraph (graph-api, persistence) và PR #7177;
pydantic.dev/docs/ai (agent, timeouts, tools-advanced, instrumented); huggingface.co/docs/smolagents;
adk.dev (runconfig, plugins, observability/traces); github.com/open-telemetry/semantic-conventions-genai
(`gen-ai-spans.md`, trạng thái Development ⚠); inspect.aisi.org.uk (setting-limits, tools-custom).

## Nghiệm thu

- Test tất định cho từng cơ chế: chạm ngân sách → kết quả kiểm soát được; mỗi mã lỗi; trace còn sau khi
  xoá hội thoại đúng theo phương án đã chọn.
- Agent Eval v0.2: không suy giảm so với mốc của ticket 10 (một lần khởi động bỏ đi mỗi phía).

## Comments

- 27/10 (chủ dự án): câu 3 chốt **(b)** — giữ bản rút gọn không có nội dung (tên công cụ, số bước, độ
  trễ, mã lỗi, token, hash) sống lâu hơn hội thoại; nội dung (tham số công cụ, kết quả, câu trả lời) vẫn
  xoá theo hội thoại.
