# 16 — Kiểm soát harness: ngân sách cả lượt, lỗi công cụ có mã, trace bền (M4, cách B)

Status: thiết kế đã duyệt (27/10, opus 5.5); Nhân viên 1 code sau khi 10 gộp
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

### 27/10 — Nhân viên của Ún 1: thiết kế (đọc trên main 22788c4), chép nguyên văn

Bản chất: hiện nay một câu hỏi có thể khiến agent chờ rất lâu mà không có giới hạn tổng. Khi một công
cụ hỏng, model chỉ nhận một câu lỗi tự do, nên có lúc nó hỏi lại người dùng một cách vô ích. Còn dấu
vết của mỗi câu trả lời thì biến mất cùng hội thoại. Thiết kế làm ba việc: (1) đặt một đồng hồ cho cả
lượt; hết giờ thì dừng gọn và trả lời bằng những gì đã có. (2) Mỗi lỗi công cụ có một mã ngắn để
thống kê, kèm một câu nói rõ cho model biết làm gì tiếp. (3) Giữ một bản "khung xương" của mỗi lượt
(gọi công cụ gì, mất bao lâu, lỗi gì), không có câu chữ, sống lâu hơn hội thoại.

Sự thật đã đo hoặc đọc:

| Điều | Bằng chứng |
|---|---|
| Mỗi lần gọi model chờ được tới 360 s, không phải 120 | OllamaClient tự thử lại khi hết giờ, `retry_count=2` (`settings.py:175`, vòng `for attempt` trong `chat`/`chat_tools`) → 3×120 s; 4 lần gọi mỗi lượt → trần thật ~24 phút |
| Một lượt agent thật mất bao lâu | Agent Eval v0.2 (worktree 10, 9 lượt chạy, GPU, model thật): trung vị 3,2–3,6 s; chậm nhất 9,2 s (model đã nạp), 8,4 s (nguội) |
| Phía gọi chờ tối đa | bot chờ `/turns/execute` 180 s (`discord_bot/main.py:78`) |
| `chat_tools` chỉ có ở OllamaClient; `chat` có ở cả 3 client | `llm_clients/*.py` |
| Token: ContextVar chỉ giữ lần gọi cuối | `usage.py:20-36` → `request_logs` hiện chỉ có token của lần gọi cuối trong lượt |
| Tiền lệ "không FK, sống lâu hơn" | `RequestLog.message_id` (`models.py:1101-1106`, "Telemetry outlives its subject") |
| Discord đi chung đường ghi trace với web | `discord_turn_service.py:594` → `respond_with_context` → `_respond` → `add_agent_traces` (`chat_service.py:155`) |
| Dashboard đọc nội dung bước final | `operational_service.py:276-300` (tiêu đề = 160 ký tự đầu câu trả lời) |

**Câu 1 — ngân sách**

Đơn vị:
- (1a) Thời gian tường cho cả lượt, kiểu Pydantic `run(timeout=)` / Inspect. Ưu: đúng thứ người dùng
  cảm nhận, và bao luôn các lần client tự thử lại. Nhược: phải truyền hạn chót xuống client.
- (1b) Thêm ngân sách token. Nhược: Ollama cục bộ không tốn tiền; token vốn đã bị chặn gián tiếp bởi
  `max_steps` × `tool_result_max_chars`. Chỉ ghi token vào trace.
- (1c) Giữ nguyên `max_steps`. Nhược: không chặn được 360 s của một lần gọi.
- → Ý tôi: (1a), và giữ `max_steps`.

Cách cắt một lần gọi đang chạy:
- (m1) Chỉ kiểm giữa các bước. Rẻ, nhưng một lần gọi vẫn kéo được 360 s.
- (m2) Truyền hạn chót xuống: timeout = min(`chat_timeout`, thời gian còn lại), và client không thử lại
  sau hạn. Đụng `ollama_client` (`chat`, `chat_tools`), `model_router` (truyền tiếp), và `chat` của
  gemini/deepseek (thêm tham số tuỳ chọn). Ưu: trần thật. Nhược: sửa 4 file ngoài `agent_service`.
- (m3) Chạy vòng lặp trong một luồng có timeout. Không khuyên: lần gọi bị bỏ vẫn chiếm Ollama duy nhất
  (invariant #7), và khó giữ phần đã làm.
- → Ý tôi: (m2).

Giá trị và cấu hình: trong `models.yaml`, cạnh `max_steps` (`main.py:265-273` đọc như `max_steps`):
`agent.turn_budget_seconds: 90`, `agent.final_reserve_seconds: 20`. Lý do chọn 90: gấp khoảng 10 lần
lượt chậm nhất đã đo, và bằng nửa thời gian bot chờ, nên backend luôn trả lời trước khi bot bỏ cuộc.
Máy chỉ có CPU sẽ chậm hơn nhiều, nên có hai cách cấu hình: (i) chỉ `models.yaml`; (ii) thêm biến môi
trường `AGENT_TURN_BUDGET_SECONDS` đè lên, theo kiểu `RAG_RERANKER_ENABLED`. → Ý tôi: (i) trước; làm
(ii) khi có một máy CPU thật cần đến.

Khi chạm ngân sách, theo họ "dừng có cấu trúc, giữ phần đã làm":
- Thời gian còn lại < `final_reserve` trước một vòng công cụ: không mở vòng mới; thêm chỉ dẫn "Hết thời
  gian dùng công cụ. Trả lời ngay bằng những gì đã thu thập được." (cùng nhánh "Tool budget exhausted"
  hiện có, `agent_service.py:190-201`), rồi gọi lần cuối với timeout = phần còn lại.
  `stop_reason=turn_budget`.
- Lần gọi cuối cũng hết giờ hoặc hỏng: trả một câu cố định ("Mình chưa trả lời kịp trong 90 giây. Bạn
  hỏi lại, hoặc hỏi hẹp hơn nhé."). `stop_reason=turn_budget_exhausted`. Các bước đã làm vẫn vào trace.
  `request_logs` ghi status `error` + `error_code` `AGENT_TURN_BUDGET` (cột đã có), vì câu cố định
  không phải câu trả lời.
- Hết `max_steps` như hiện nay: `stop_reason=max_steps`. Kết thúc bình thường: `final`.
- `stop_reason` đặt vào bước final, không đổi chữ ký `run()`, vì `chat_service` và `agent_eval` đang
  dùng nó.
- Test tất định: `AgentService` nhận một hàm đồng hồ (mặc định `perf_counter`), test truyền đồng hồ giả,
  không phải sleep.

**Câu 2 — lỗi có mã**

Model nhận `{"error": "<câu>", "code": "<MÃ>"}`: giữ khoá `error` như hiện nay, thêm khoá `code`. Câu
có ích cho model đọc; mã vào trace.

| Mã | Khi nào (chỗ hiện tại) | Câu cho model |
|---|---|---|
| `TOOL_UNAVAILABLE_HERE` | `search_history` không có guild hoặc `history_service` (`:217-220`) | "search_history chỉ đọc được lịch sử của server Discord đang trò chuyện; cuộc trò chuyện này không ở Discord. Đừng hỏi người dùng server nào: nói rõ ở đây không xem được tin nhắn Discord, rồi trả lời phần còn lại." (chữa đúng hist-10) |
| `BAD_ARGUMENTS` | query rỗng (`:265-266`) | "search_documents cần `query` là một câu không rỗng. Gọi lại một lần, viết câu hỏi thành câu độc lập." |
| `UNKNOWN_TOOL` | tên công cụ lạ (`:285`) | "Không có công cụ X. Chỉ có search_documents, search_history, system_status." |
| `TOOL_FAILED` | ngoại lệ (`:286-287`) | "X đang lỗi nên chưa tra được. Đừng gọi lại trong lượt này; nói với người dùng là chưa tra được." Tên lớp ngoại lệ vào trace, không vào câu cho model (hiện nay model đang thấy "TypeError: …") |
| `TOOL_TIMEOUT` | công cụ chạy quá hạn | "X không trả lời kịp; đừng gọi lại, trả lời bằng những gì đã có." |

Kết quả rỗng ("không tìm thấy…") vẫn là kết quả, không phải lỗi.

`TOOL_TIMEOUT`: công cụ chạy đồng bộ, muốn cắt thì phải dùng một luồng (như `_qdrant_ok` của ticket
01). (t1) Chưa làm trong ticket này; ngân sách chung đã bao, và các công cụ đã có timeout riêng (Qdrant
10 s × 3, health 3 s); mã giữ lại để dành. (t2) Làm luồng ngay. → Ý tôi: (t1).

Thử lại: (r1) Harness không tự thử lại; model được gọi lại trong giới hạn `max_steps`, và câu cho model
nói rõ mã nào không nên gọi lại. (r2) Harness tự thử lại `TOOL_FAILED` một lần. Nhược: phụ thuộc đã
chết thì chỉ tốn ngân sách; client bên dưới vốn đã tự thử lại (Ollama 2 lần, Qdrant 3 lần). → Ý tôi:
(r1).

**Câu 3 — trace bền, theo (b)**

Mỗi dòng ghi gì: (g1) Một dòng mỗi bước, giống `agent_traces` nhưng bỏ nội dung. Ưu: khớp đúng danh
sách của chủ dự án (tên công cụ, số bước, độ trễ, mã lỗi, token, hash); ghi trong cùng vòng lặp ghi
trace. (g2) Một dòng mỗi lượt. Nhược: mất thứ tự và độ trễ của từng công cụ. → Ý tôi: (g1).

Bảng mới `agent_trace_summaries`:

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BigInteger | PK |
| `conversation_id` | String(128) NOT NULL | KHÔNG FK |
| `message_id` | BigInteger NULL | KHÔNG FK (như `RequestLog.message_id`) |
| `step_index` | Integer | |
| `kind` | String(32) | `tool_call` \| `tool_result` \| `final` |
| `tool_name` | String(128) NULL | |
| `latency_ms` | Integer NULL | |
| `error_code` | String(64) NULL | |
| `error_type` | String(128) NULL | tên lớp ngoại lệ, chỉ khi `TOOL_FAILED` |
| `stop_reason` | String(32) NULL | chỉ ở bước final |
| `tokens_in`, `tokens_out` | Integer NULL | |
| `arguments_shape` | JSONB NULL | chuỗi thay bằng `"str:<độ dài>"`, số giữ nguyên, vd `{"query":"str:42","top_k":4}` |
| `content_sha256` | String(64) NULL | băm kết quả công cụ và câu trả lời |
| `source` | String(16) | `web` \| `discord` |
| `created_at` | timestamptz | |

Index `(conversation_id, created_at)` và `(message_id)`.

Về hash: sha256 của một câu hỏi ngắn có thể đoán ngược bằng cách thử từ điển, nên KHÔNG băm tham số
(dùng `arguments_shape` thay thế); chỉ băm kết quả và câu trả lời, vì chúng dài và khó đoán. Các cách
khác: HMAC với một khoá của bản cài đặt (không đoán được, so sánh được trong cùng một máy; nhưng cần
một chỗ giữ khoá), hoặc bỏ hash hoàn toàn.

Ghi: `add_agent_traces` (`postgres_auxiliary_store.py:110`) ghi cả hai bảng trong CÙNG một transaction.
Xoá hội thoại thì `agent_traces` vẫn cascade như cũ (nội dung đi theo), còn bảng rút gọn ở lại. Không
cần backfill, vì `agent_traces` có 0 dòng.

Discord: đi chung đường; `source=discord` khi `tool_context` có `guild_id`. Không cần đường riêng.

Migration: `backend/alembic/versions/<ngày>_35_agent_trace_summaries.py`; `down_revision` là head lúc
code (hôm nay là `"20261011_34"`); `create_table` + 2 index; downgrade thì drop. `alembic check` và
schema-drift test giữ khớp với model.

Token từng bước: agent gọi `consume_usage()` sau mỗi lần gọi model. Hệ quả với `request_logs`
(`chat_service.py:150` đang consume sau `run()`): (k1) agent ghi lại tổng token của cả lượt — đúng hơn,
nhưng đổi nghĩa con số trên dashboard; (k2) ghi lại đúng token của lần gọi cuối, giữ nguyên nghĩa cũ.
→ Ý tôi: (k2) trong ticket này; (k1) thành việc riêng.

Phát hiện ngoài phạm vi: `scripts/forget_member.py` không xoá `agent_traces`, trong khi trace của hội
thoại Discord chứa trích đoạn tin nhắn của thành viên (kết quả `search_history`). Bảng rút gọn không có
nội dung, nên không làm khoảng hở này rộng thêm. Nên mở một ticket riêng.

**Câu 4** — registry không làm. Điều kiện mở lại: có công cụ thứ 4, hoặc khi danh sách công cụ phải
khác nhau giữa web và Discord.

**Thứ tự commit** (sau khi 10 gộp):
1. Lỗi có mã: chỉ `agent_service.py`, kèm test. Nhỏ nhất. Đổi câu model đọc, nên chạy Agent Eval ngay
   sau.
2. Truyền hạn chót xuống client: `ollama_client`, `model_router`, `chat` của gemini/deepseek. Test
   không cần Ollama.
3. Ngân sách cả lượt: `agent_service`, `models.yaml`, `main.py`. Test bằng đồng hồ giả.
4. Bảng rút gọn: model, migration, store ghi hai bảng, các bước mang `error_code` / tokens /
   `stop_reason`. Test Postgres: xoá hội thoại thì nội dung mất, bản rút gọn còn.
5. Agent Eval v0.2 so với mốc của ticket 10, bỏ một lần khởi động mỗi phía.

Lý do: bước 1–3 sinh ra `error_code`, `stop_reason` và tokens mà bước 4 ghi, nên bước 4 không phải có
cột tạm. Mỗi commit lùi lại được riêng. Bước 2 tách khỏi 3 để lỗi ở tầng client không lẫn với logic
ngân sách.

File sẽ đụng: `agent_service.py`, `ollama_client.py`, `model_router.py`, `gemini_client.py`,
`deepseek_client.py`, `models.yaml`, `main.py`, `postgres/models.py`, một migration mới,
`postgres_auxiliary_store.py`, `chat_service.py` (truyền `source`), cùng các test.

### 27/10 — opus 5.5: duyệt

Duyệt mọi chỗ "Ý tôi" ở trên, kèm 3 chỉnh:
- Câu 1: câu cố định lấy số giây từ cấu hình (`agent.turn_budget_seconds`), không ghi cứng "90 giây".
- Câu 2: các câu mới đổi lời model đọc ở hist-08..10. Báo cáo eval phải ghi rằng lần đo sau commit 1
  nhắm đúng những bài đó.
- Câu 3: hash là sha256 thường, không HMAC. Thêm một test khẳng định bảng rút gọn KHÔNG chứa chuỗi nào
  của tham số hay kết quả: chèn một chuỗi mồi vào câu hỏi, rồi quét mọi cột text/JSONB của bảng.

`forget_member` không xoá `agent_traces` → ticket 17 riêng, làm sau 16. Code chỉ bắt đầu khi 10 đã gộp.
