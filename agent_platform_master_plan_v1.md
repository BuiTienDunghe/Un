# Master Plan — Phát triển Local AI Core thành Nền tảng Agent (V1)

Ngày lập: 2026-08-14
Phạm vi: kế hoạch tổng thể (không phải kế hoạch code chi tiết) cho hướng phát triển **agent** của Local AI Core.
Phương pháp: đối chiếu **hiện trạng thực tế của codebase** (đọc trực tiếp toàn bộ backend, Discord bot, docs, hạ tầng) với **best practice từ các nguồn uy tín** — tài liệu chính thức của Anthropic/OpenAI/Qwen/Ollama/Qdrant và các project GitHub hàng đầu (danh mục đầy đủ kèm số star ở Phụ lục A).

---

## 0. Tóm tắt điều hành

Local AI Core hiện là một nền tảng RAG self-hosted có **kỷ luật hạ tầng dữ liệu hiếm thấy** (PostgreSQL-only source of truth, transactional outbox, durable jobs với lease/heartbeat/recovery, versioned ingestion, RAG citation-grade, 317 test integration) — nhưng **năng lực agent thực thụ hiện bằng 0**: không có tool calling ở bất kỳ tầng nào, không có agent loop, không có auth, memory là write-only (pipeline trích xuất chất lượng cao nhưng chưa có đường đọc lẫn bước apply), và nền client LLM đồng bộ sẽ nghẽn ngay khi agent hóa.

Kết luận chiến lược của plan này:

1. **Tự xây agent loop tối giản (~300–500 dòng), KHÔNG ôm framework.** Ngành đã hội tụ về một bộ nguyên thủy chung (tool = hàm + JSON Schema, loop = while gọi LLM → thực thi tool, durable state = checkpoint từng bước vào DB, HITL = interrupt/resume). Hạ tầng Postgres + Redis/RQ + outbox của dự án đã có sẵn chính những thứ mà LangGraph/MAF "bán" — trong khi framework churn là rủi ro thật (AutoGen ~60k star vẫn vào maintenance mode; AG2 đổi API 2 lần trong 2 năm).
2. **"Workflow trong code, model chỉ điền chỗ trống."** Model 9B đáng tin ở từng bước hẹp, không đáng tin ở chuỗi dài tự hành (bằng chứng BFCL + chính benchmark nội bộ của dự án: qwen3.5:2b trượt gate schema compliance). Orchestration, điều kiện dừng và thứ tự bước nằm trong Python; model chỉ quyết định cục bộ có schema ràng buộc.
3. **Nhân rộng mẫu governance đã tự chứng minh trong DiscordMemoryExtractor** (grammar-constrained JSON Schema → Pydantic strict → trusted-binding allowlist → rồi mới apply) thành khuôn cho **mọi** tool call của agent. Đây là khác biệt hóa thật sự của dự án so với "prompt + túi tool + loop".
4. **Mỗi phase phải kết thúc bằng giá trị người dùng chạm được + eval gate định lượng**, không kết thúc bằng "schema đã xong". Đây là bài học trực tiếp từ plan memory v5: 17 sprint thiết kế trước, thực tế bị chặn ở Sprint 2B.5B và kho candidates nằm ở `deferred` vĩnh viễn.

Lộ trình 5 phase: **Phase 0** trả nợ nền + dựng eval baseline → **Phase 1** memory read-path + apply (giá trị người dùng đầu tiên) → **Phase 2** auth + tool foundation + routing tier → **Phase 3** single agent loop durable + human-in-the-loop → **Phase 4** mở rộng có điều kiện (consolidation, reranker, web search, MCP, orchestrator-workers).

---

## 1. Hiện trạng: tài sản chiến lược và gap chí mạng

### 1.1. Tài sản chiến lược (đã có, phải tận dụng — không viết lại)

| # | Tài sản | Vì sao quý cho agent |
| --- | --- | --- |
| A1 | **Durable job runtime**: durable jobs trong Postgres + transactional outbox + idempotency nhiều tầng + lease/heartbeat/stale-recovery/cancel checkpoint (`job_queue_service.py`, `workers/tasks.py`, `outbox_dispatcher_service.py`) | Đây chính là "agent task runtime" mà các framework thương mại bán. Chỉ cần thêm job_type mới + bảng agent_runs/agent_steps là có agent bền vững, resume được sau crash. |
| A2 | **DiscordTurnService**: máy trạng thái turn bền vững (enqueue/claim/heartbeat/complete/fail/recover_stale, execution_token chống double-execution) | Là một "agent turn state machine" hoàn chỉnh — generalize thành AgentRunService là con đường ngắn nhất, không viết mới. |
| A3 | **DiscordMemoryExtractor**: structured output chuẩn mực với model nhỏ (Ollama `format` = JSON Schema grammar-constrained + Pydantic strict `extra=forbid` + trusted envelope/allowlist + 3 lớp validate + versioning schema/prompt v1→v5 + chống prompt-injection) | Template chuẩn cho **mọi** tool-call envelope của agent. Mẫu "model đề xuất — backend validate — rồi mới apply" là governance ít dự án OSS nào có sẵn. |
| A4 | **Kho memory versioned có provenance**: canonical identity + partial unique index "một active value/fact" + supersede chain + origin_candidate + evidence_hash + advisory lock | Đi trước nhiều sản phẩm thương mại. Thêm 2 cột `valid_from`/`valid_to` là có bi-temporal kiểu Zep/Graphiti bằng một migration, không cần graph DB. |
| A5 | **RAG citation-grade**: hybrid dense (Qdrant, filter active version) + BM25 tiếng Việt in-process + RRF, citation tới chunk_id/page/heading_path/verifiable, đối chiếu active-version chống stale | "Grounded tool" đầu tiên của agent, miễn phí — chất lượng cao hơn đa số RAG demo của các framework. Tokenizer + rule filter tiếng Việt là lợi thế ngách gần như không có đối thủ OSS. |
| A6 | **models.yaml slot-based + 3 provider** (Ollama/Gemini/DeepSeek), think flag đã wire sẵn | Sẵn sàng cho kiến trúc dị thể (planner/executor/extractor dùng model khác nhau) — chỉ bị chặn bởi router hard-code mode `general`. |
| A7 | **Kỷ luật eval đã có mầm**: benchmark harness + dataset 150 case tiếng Việt versioned + văn hóa "dám kết luận BLOCKED thay vì ship" | Nền để mở rộng thành mini-BFCL cho tool calling và eval kiểu LongMemEval cho memory. |
| A8 | **Discord bot Ún + button + RQ** | Sân chơi human-in-the-loop và trigger tự nhiên (approve/deny, scheduled automations) mà không cần giữ process sống. |
| A9 | **Sleep-time compute miễn phí**: GPU nhà rảnh ban đêm | Chạy consolidation/decay/summary/re-extraction nền (mẫu "sleep-time agents" của Letta) không tốn tiền — lợi thế cấu trúc của self-hosted so với cloud. |

### 1.2. Gap chí mạng (xếp theo mức chặn)

| # | Gap | Hiện trạng cụ thể | Chuẩn ngành đối chiếu |
| --- | --- | --- | --- |
| G1 | **Không có tool-use/function-calling** | Cả 3 LLM client không nhận tham số `tools`; ModelRouter không có API thực thi tool; pattern structured output bị "nhốt" trong DiscordMemoryExtractor (bypass cả OllamaClient lẫn router) | Ollama hỗ trợ tools native từ v0.3.0, structured output từ v0.5; mọi nền tảng dẫn đầu đều có tool registry |
| G2 | **Không có auth/multi-user** | Không JWT, không API key, không user_id trong schema; mọi endpoint (xóa tài liệu, giả mạo Discord turn) mở hoàn toàn | Multi-user + workspace isolation + API keys là baseline "nền tảng" (Open WebUI, AnythingLLM, LibreChat) |
| G3 | **Memory write-only, không apply, extractor blocked** | Read-path không tồn tại (`respond_with_context` hard-code `use_memory=False`); primitives apply đã viết-và-test nhưng chưa service nào gọi; qwen3.5:2b trượt benchmark → 2 feature flag OFF | Chuẩn mem0/Letta/Zep: extract → dedup/conflict → apply → **retrieve vào prompt**; memory không đọc = 0% giá trị |
| G4 | **Không có durable agent state** | Chưa có agent_runs/agent_steps/tool_calls; jobs là single-shot; không có khái niệm task đa bước | Checkpoint-per-step vào DB theo thread_id (LangGraph PostgresSaver, 12-factor #12 "stateless reducer") |
| G5 | **Quản lý context ngây thơ** | Lịch sử 12 message đếm theo message (không theo token); không compaction/rolling summary (Discord chỉ ~6 turn); RAG single-turn, không query rewrite | Context engineering (Anthropic): compaction, structured note-taking, JIT retrieval — blocker cứng cho agent multi-step |
| G6 | **Nền client sync + nợ DRY** | 3 client httpx đồng bộ, không pool; dispatch isinstance; mode chat hard-code `general`; message schema dict[str,str] không chứa được role=tool | Agent loop 6–15 lượt gọi/turn sẽ nghẽn threadpool; refactor sau khi agent code chồng lên sẽ đắt gấp nhiều lần |
| G7 | **Không có eval loop + tracing LLM** | Không request-id xuyên suốt, không bảng trace token/latency, không LLM-as-judge, không golden dataset RAG | Tracing là tính năng hạng nhất ở mọi framework 2025–2026; không có thì không debug nổi multi-step |
| G8 | **Không có HITL primitive** | Chưa có pending_action/waiting_approval | Chuẩn interrupt/resume trên checkpoint; "human approval là một tool" (12-factor #7) |
| G9 | **Vận hành chưa chịu được agent workload** | Compose không restart policy, Qdrant không healthcheck, launcher mặc định không bật worker containers, API không container hóa, backup tay, không CI (test skip âm thầm) | Agent chạy dài trên hạ tầng không supervision = chắc chắn mất run giữa chừng |

---

## 2. Mười nguyên tắc kiến trúc xuyên suốt

Rút từ các nguồn ở Phụ lục A; mọi quyết định thiết kế trong roadmap phải tuân theo:

1. **Mượn pattern, không cưới framework.** AutoGen (~60k star) vào maintenance mode 10/2025; AG2 đổi API lớn 2 lần trong 2 năm; Semantic Kernel bị hợp nhất; promptfoo bị OpenAI mua. Agent loop lõi chỉ ~1.000 dòng (smolagents đã chứng minh). Nếu buộc phải tham khảo sâu: chỉ LangGraph (checkpoint-postgres khớp triết lý) và Pydantic AI (khớp stack FastAPI+Pydantic) đáng nhìn — và cũng chỉ để mượn pattern.
2. **Workflow vs Agent (Anthropic).** Pipeline biết trước các bước (OCR → index → outbox → cleanup, RAG retrieve → generate) giữ nguyên là workflow deterministic trên RQ. Chỉ trao quyền tự trị cho LLM ở khâu thật sự không dự đoán được cấu trúc. "Nếu phân vân, hãy đơn giản hóa."
3. **Workflow trong code, model chỉ điền chỗ trống (NVIDIA SLM + BFCL).** Model 7–9B đạt điểm cao ở single-turn tool call nhưng tụt mạnh ở multi-turn/long-horizon. Orchestration, điều kiện dừng, thứ tự bước nằm trong Python; model chỉ ra quyết định hẹp có schema.
4. **Ba tầng bảo đảm structured output:** (a) grammar/`format` JSON Schema ép cú pháp ở sampler; (b) Pydantic strict validate ngữ nghĩa; (c) retry có phản hồi lỗi cho model tự sửa, tối đa 2–3 lần (pattern Instructor). Bù việc Ollama thiếu `tool_choice` bằng pattern **decide-then-act**: call "quyết định" riêng với `format` = schema `{next_action: enum, tool_name: enum, arguments}`.
5. **Governance "model đề xuất — backend validate — rồi mới apply" cho mọi tool call.** Nhân rộng trusted envelope + allowlist + 3 lớp validate của DiscordMemoryExtractor. Phân hạng rủi ro tool: đọc (tự do) < ghi (log + giới hạn) < không-đảo-ngược (bắt buộc approval).
6. **Postgres là source of truth cho cả business state lẫn execution state (12-factor #5).** Mọi run/step/tool-call/checkpoint ghi Postgres; agent là stateless reducer trên event log — pause/resume/replay/audit tự nhiên.
7. **Context engineering là kỹ năng trung tâm (Anthropic).** Tập token tín hiệu cao nhỏ nhất; JIT retrieval (đưa id/đường dẫn, agent tự mở khi cần); compaction khi gần đầy cửa sổ; structured note-taking ra memory. Đặc biệt sống còn với ctx 16384 của model cục bộ.
8. **Routing tier rẻ trước mọi agent loop.** Multi-agent tốn ~15× token (số liệu Anthropic); trên GPU đơn serialize suy luận, để mọi tin nhắn vào agent loop là tự sát về độ trễ. Một call structured-output phân loại `{chitchat, rag_qa, memory, agent_task}` là guardrail chi phí số 1.
9. **Thiết kế tool theo ACI (Anthropic "Writing effective tools"):** ≤5–8 tool/request, đòn bẩy cao, namespace rõ (`docs_search`, `memory_save`), schema **phẳng** + enum (poka-yoke — tránh bug arguments-thành-string của Ollama #6155), kết quả token-efficient (top-5 + con trỏ phân trang), lỗi trả một câu actionable thay stack trace.
10. **Eval gate + tracing trước khi tăng độ tự chủ.** Mỗi phase có eval định lượng chạy trong CI; tracing theo chuẩn OTel GenAI ngay từ đầu; không tin benchmark vendor (vụ Zep vs Mem0 chênh 10% sau khi sửa setup) — chỉ tin eval chạy trên chính stack của mình.

---

## 3. Kiến trúc agent mục tiêu

### 3.1. Sơ đồ tổng thể

```text
Tin nhắn (Web UI / Discord Ún / API / Cron-Automation)
        │
        ▼
[Routing tier — 1 call structured output, format=JSON Schema]
  {chitchat | rag_qa | memory | agent_task}
        │
        ├─ chitchat  → ChatService hiện có (+ memory context block)
        ├─ rag_qa    → RAG WORKFLOW hiện có (retrieve → generate → citation,
        │              tùy chọn 1 vòng evaluator đối chiếu citation)   ← KHÔNG agent hóa
        ├─ memory    → memory_save / memory_search / /memory commands
        └─ agent_task
                ▼
   [AgentRunService — generalize từ DiscordTurnService]
   vòng while ≤ 6–8 bước, mỗi bước:
     1. gọi LLM (tools hoặc decide-then-act format-constrained)
     2. validate args bằng Pydantic TRƯỚC khi thực thi (envelope + allowlist)
     3. thực thi tool (timeout riêng; side-effect qua RQ + idempotency key)
     4. ghi checkpoint: agent_runs / agent_steps / tool_calls (Postgres)
     5. phát SSE đa kênh: token | tool_call | state_update | interrupt
   ├─ tool rủi ro cao → pending_action + Discord button ✅/❌
   │                    → RQ resume từ checkpoint khi có phản hồi (HITL)
   ├─ phát hiện lặp (tool+args trùng bước trước) → ép trả lời
   └─ hết budget bước → lượt cuối bỏ tools, chỉ sinh câu trả lời

Tool registry (decorator + Pydantic, phân hạng rủi ro, cờ requires_approval):
  docs_search / docs_get / memory_search / memory_save / ask_human
  (Phase 4: web_search qua SearXNG, code_run sandbox, MCP tools)

Nền: ModelRouter async đa slot (router/planner/executor/extractor per models.yaml)
     + chat_structured(schema) + chat_with_tools(tools) dùng chung
     + fallback parser <tool_call> trong content (bug Ollama #11662)
Trace: llm_calls / agent_runs / agent_steps / tool_calls (Postgres, chuẩn OTel GenAI)
```

### 3.2. Kiến trúc memory mục tiêu (4 tầng, hội tụ từ Letta/mem0/Zep/LangMem)

| Tầng | Nội dung | Cơ chế |
| --- | --- | --- |
| **Core (profile)** | Vài trăm token ghim trong system prompt mọi lượt: user_profile per member, guild_profile, bot_persona | Bảng `memory_blocks` kiểu Letta; extractor cập nhật block khi fact thuộc registry; không qua retrieval nên không bao giờ miss |
| **Semantic (facts)** | Kho `discord_memories` versioned hiện có, nâng **bi-temporal** (`valid_from`/`valid_to` — INVALIDATE thay vì DELETE, kiểu Graphiti/Zep) | Vòng update 2 pha kiểu mem0: top-k memory tương tự cùng scope → LLM quyết create/update/delete/no_op; fact-key có sẵn trong registry thì UPSERT tất định bỏ qua LLM |
| **Episodic** | Rolling summary per session (Sprint 3 của plan v5) + hội thoại thô đã có | Summary worker trên job/outbox hiện có; bắt buộc trước agent multi-step (cửa sổ 6 turn quá hẹp) |
| **Procedural** | Quy tắc hành vi của agent (workflow_rule) nạp vào system prompt, cập nhật từ feedback | Kiểu LangMem prompt-optimization; làm sau cùng |

**Inject vào prompt** theo mẫu "context block" của Zep: khối có cấu trúc gồm core blocks ghim + top-k memory truy hồi hybrid (không gọi LLM lúc truy vấn — giữ độ trễ thấp trên Ollama), mỗi dòng kèm loại + cửa sổ hiệu lực `[preference, 2026-05 → nay] ...`, ngân sách cứng ~1.000–1.500 token. Hai đường ghi đổ về cùng kho: **background** (pipeline extraction hiện có) + **hot-path** (tool `memory_save` khi user nói "nhớ nhé").

---

## 4. Roadmap theo phase

> Nguyên tắc chung: phase sau chỉ bắt đầu khi phase trước qua **eval gate**; mỗi phase ship một demo end-to-end người dùng chạm được; nếu một phase kéo quá 6 tuần không ship được demo → cắt scope (tín hiệu lặp lại vết xe plan-17-sprint).

### Phase 0 — Trả nợ nền + eval baseline (ước lượng 2–4 tuần)

Làm **trước** mọi thứ agent. Không có tính năng người dùng mới, nhưng là điều kiện để mọi phase sau không sụp.

| Hạng mục | Chi tiết |
| --- | --- |
| 0a. Hợp nhất LLM client | 1 ABC async duy nhất (httpx.AsyncClient + connection pool), signature có `tools`/`response_format`/message role=`tool`; gộp ~70% retry logic trùng lặp; mở khóa mode hard-code `general` → slot tự do theo models.yaml; error mapping đủ 3 provider; chuyển Gemini API key khỏi query string |
| 0b. Tổng quát hóa structured output | Nâng pattern DiscordMemoryExtractor lên `chat_structured(mode, messages, schema)` và `chat_with_tools(mode, messages, tools)` của client/router dùng chung; kèm fallback parser regex `<tool_call>...</tool_call>` trong content |
| 0c. Phòng thủ serving layer | Pin version Ollama trong compose; mini-BFCL 15–20 case tool-calling tiếng Việt (gọi đúng tool, đúng args, biết KHÔNG gọi khi không cần) chạy trong CI; num_ctx/num_predict đủ lớn tránh JSON cụt (#14570); `think=false` trong bước tool-use (#10976) |
| 0d. CI + tracing tối thiểu | CI thật (bộ 317 test hiện skip âm thầm nếu thiếu POSTGRES_TEST_URL); request-id xuyên suốt; bảng `llm_calls` (model, token in/out, latency, lỗi) |
| 0e. Gỡ BLOCKED extractor | Benchmark qwen3.5:9b (và phương án 9b-trích/2b-verify) trên harness 150-case sẵn có — quyết định model extractor bằng số liệu |
| 0f. Vận hành song song | restart policy + healthcheck mọi service; container hóa API (`docker compose up` dựng full stack); bật profile workers + `INGESTION_EXECUTION_BACKEND=rq` mặc định; backup pg_dump theo lịch |

**DoD / eval gate:** 317 test chạy trong CI; mini-BFCL pass ngưỡng đặt trước (đề xuất: ≥90% valid-first-try trên case đơn); client async chịu 10 stream đồng thời; benchmark extractor có kết luận go/no-go bằng số.

### Phase 1 — Memory read-path + apply (giá trị người dùng đầu tiên)

Đứng **trước** tool-use vì primitives đã nằm sẵn ~90% và bot "biết nhớ" là giá trị cảm nhận được ngay.

| Hạng mục | Chi tiết |
| --- | --- |
| 1a. Read-path | `DiscordMemoryRetrievalService`: exact lookup active memories theo fact_key (scope member_in_guild + guild) — chưa cần Qdrant; chèn block "CURRENT VERIFIED FACTS" vào `respond_with_context` (bỏ hard-code `use_memory=False`) |
| 1b. Apply thủ công trước | Admin endpoint duyệt candidate `approved→applied`, gọi các primitive `create_active_version`/`supersede_active_version` đã test sẵn; auto-apply theo ngưỡng confidence chỉ sau khi có số liệu duyệt tay |
| 1c. Bật extractor | Model theo kết quả Phase 0e; bật 2 feature flag ở guild thử nghiệm |
| 1d. Bi-temporal | Migration thêm `valid_from`/`valid_to`; operation update/delete = đóng hiệu lực + bản ghi mới (giữ lịch sử, suy luận thời gian) |
| 1e. Rolling summary | Summary worker per session (Sprint 3 cũ) trên job/outbox hiện có — blocker của agent multi-step |
| 1f. Nghĩa vụ với user | Lệnh `/memory show` + `/memory forget` tối thiểu (rule filter đã nhận diện intent explicit_forget); memory context block có ngân sách token cứng |

**DoD / eval gate:** bộ eval memory kiểu LongMemEval tự dựng (5 hạng mục: single-hop, multi-hop, temporal, knowledge-update, **abstention**) — bot Ún trả lời đúng fact đã nhớ và dám nói "không biết"; user forget được; p95 latency chat thường không tăng quá ngưỡng.

### Phase 2 — Auth + tool foundation + routing tier

Điều kiện tiên quyết trước khi agent có quyền thực thi hành động.

| Hạng mục | Chi tiết |
| --- | --- |
| 2a. Auth tối thiểu | API key (hash trong Postgres) + `user_id` vào conversation/memory/document; ánh xạ Discord user ID → user nội bộ; RBAC tối thiểu admin/user (chưa cần SCIM/LDAP) |
| 2b. Tool registry | Decorator + Pydantic tự sinh JSON Schema; 5–8 tool đầu: `docs_search`, `docs_get`, `memory_search`, `memory_save`, `ask_human`; schema phẳng + enum; phân hạng rủi ro (read/write/irreversible) + cờ `requires_approval` ngay trong registry; mọi tool call đi qua envelope validate kiểu extractor |
| 2c. Routing tier | 1 call `chat_structured` phân loại `{chitchat, rag_qa, memory, agent_task}` đứng trước mọi đường xử lý — guardrail chi phí số 1 trên GPU đơn |

**DoD / eval gate:** routing accuracy đo trên ≥50 tin nhắn thật; tool call được validate-trước-thực-thi 100%; endpoint mutation không còn truy cập nặc danh.

### Phase 3 — Single agent loop durable + HITL

| Hạng mục | Chi tiết |
| --- | --- |
| 3a. AgentRunService | Generalize DiscordTurnService (không viết mới): vòng while max 6–8 bước; bảng `agent_runs`/`agent_steps`/`tool_calls` event-sourced (stateless reducer); checkpoint sau mỗi bước tool |
| 3b. Độ tin cậy loop | Validate args bằng Pydantic trước thực thi; lỗi validation trả role=`tool` cho model tự sửa (max 2 retry); phát hiện lặp tool+args → chặn và ép trả lời; hết budget → lượt cuối bỏ tools; timeout riêng từng tool; side-effect qua RQ với idempotency key `(run_id, step, tool, args_hash)` |
| 3c. HITL | Tool nhạy cảm → ghi `pending_action` + checkpoint_id, gửi Discord message button ✅/❌; phản hồi → RQ job resume từ checkpoint (mẫu interrupt/resume của LangGraph, không giữ process sống) |
| 3d. Streaming đa kênh | SSE event `token` / `tool_call` / `state_update` / `interrupt` — web UI hiển thị tiến trình agent; Discord edit message mỗi 1–2s kèm dòng trạng thái |
| 3e. Agent console | Tiến hóa dashboard hiện có (read-only) thành console xem run/step/tool-trace, retry/cancel run |

**DoD / eval gate:** agent run sống sót `kill -9` worker giữa chừng và resume đúng bước; tỷ lệ tool-call hợp lệ ngay lần đầu ≥ ngưỡng mini-BFCL; trace đầy đủ từng run trong Postgres; 1 tác vụ đa bước thật chạy end-to-end qua bot Ún (ví dụ: "tìm trong tài liệu X, đối chiếu với memory, rồi tóm tắt và hỏi tôi trước khi lưu").

### Phase 4 — Mở rộng có điều kiện

Chỉ khi eval Phase 3 cho thấy nghẽn ở **năng lực** chứ không phải ở prompt/tool:

- **Consolidation/decay job nền** (sleep-time): merge memory cosine >0.9 cùng scope, tóm tắt episodic cũ, decay theo `last_accessed_at`, archive thay vì xóa.
- **Reranker cục bộ**: bge-reranker-v2-m3 (Apache-2.0, đa ngữ, ~568M — cân bằng nhất) hoặc Qwen3-Reranker-0.6B; chạy service riêng (Ollama không serve cross-encoder); bật mặc định chỉ sau A/B trên eval.
- **Hybrid search Qdrant-native**: named vectors dense + sparse BM25 (modifier IDF) trong cùng collection, một Query API với prefetch + RRF — thay merge tầng ứng dụng; tuyệt đối không cộng điểm alpha giữa cosine và BM25.
- **Web search tool**: SearXNG self-hosted (thêm 1 service compose), kết quả đi qua pipeline RAG để trả lời kèm citation URL.
- **MCP hai chiều**: FastAPI làm MCP host mount server chọn lọc (Filesystem/Fetch/Git/Time — trong container sandbox, allowlist tool, coi third-party là untrusted); expose chính Local AI Core (rag_search kèm citation, memory) thành MCP server Streamable HTTP cho client ngoài (Claude Code, IDE).
- **Orchestrator-workers trên RQ** — CHỈ cho task breadth-first (research đa tài liệu): lead agent phân rã, mỗi subtask một RQ job với mô tả tự-đủ, giới hạn 2–3 worker đồng thời (GPU đơn), nhớ bài học 15× token.
- **Observability đầy đủ**: Langfuse self-hosted + OTel GenAI semantic conventions (span `invoke_agent` → `chat {model}` → `execute_tool {tool}`); KPI: tỷ lệ tool-call hợp lệ lần đầu, số retry, số vòng lặp/task, latency từng tool.
- **Scheduled automations kiểu Khoj**: cron cho agent (báo cáo định kỳ, thông báo sự kiện) trên RQ scheduler sẵn có.
- **Hợp nhất Web UI memory vào kho scoped** — làm CUỐI (hiện 0 rows, ít rủi ro).
- **Nâng serving khi cần**: giữ client theo interface OpenAI-compatible làm bảo hiểm; chuyển vLLM (`--tool-call-parser hermes`, tool_choice required, guided decoding, continuous batching) chỉ khi có nhu cầu đa người dùng thật.

---

## 5. Những gì KHÔNG làm (anti-scope)

1. **KHÔNG** ôm LangGraph/CrewAI/AutoGen/ADK/MAF làm runtime — chỉ mượn pattern.
2. **KHÔNG** agent-hóa pipeline OCR/index/outbox/cleanup — chúng là workflow deterministic đúng nghĩa, giữ nguyên.
3. **KHÔNG** chuyển RAG Q&A thành agent tự trị — giữ workflow retrieve → generate (+ tối đa 1–2 vòng evaluator đối chiếu citation).
4. **KHÔNG** code-agent kiểu smolagents (LLM viết Python) khi chưa có sandbox Docker network=none — chính smolagents cảnh báo LocalPythonExecutor không phải sandbox.
5. **KHÔNG** knowledge graph Neo4j/Graphiti ở giai đoạn này — 9B trích entity+relation không đủ tin cậy, và trái nguyên tắc Postgres-source-of-truth; entity-tag JSONB + chỉ mục GIN là đủ (hướng mem0 v2).
6. **KHÔNG** multi-agent GroupChat tự do — nếu cần multi-agent thì dùng agent-as-tool (agent con trả kết quả về orchestrator).
7. **KHÔNG** xây bảng/worker nào mà không có consumer trong cùng phase — bài học trực tiếp từ kho candidates `deferred` vĩnh viễn.
8. **KHÔNG** để mọi tin nhắn Discord vào agent loop — routing tier là bắt buộc.
9. **KHOAN** vLLM/GraphRAG/RAPTOR/code interpreter — chỉ sau khi eval chứng minh cần.

---

## 6. Rủi ro chính và giảm thiểu

| Rủi ro | Mức | Giảm thiểu |
| --- | --- | --- |
| Model 9B không gánh nổi chuỗi dài tự hành (BFCL; 2b đã trượt benchmark nội bộ) | Cao | Kiến trúc "workflow trong code"; benchmark 9b **trước** khi cam kết (Phase 0e); giới hạn 6–8 bước; decide-then-act format-constrained |
| Tầng template/parser Ollama+Qwen vỡ âm thầm (tool call rơi vào content #11662, JSON cụt #14570, think+tools rỗng #10976, args-thành-string #6155) | Cao | Pin version Ollama; mini-BFCL regression trong CI trước mỗi lần nâng cấp; fallback parser `<tool_call>`; think=false trong bước tool-use |
| Bề mặt tấn công phình khi thêm tool trên API không auth + prompt injection qua tài liệu/tin nhắn | Cao | Auth trước tool có side-effect (Phase 2 trước Phase 3); envelope + allowlist cho mọi tool; phân hạng rủi ro + approval gate; guardrail input rẻ chạy song song |
| GPU đơn serialize — agent loop + reranker + consolidation tranh nhau | Trung | Routing tier; giới hạn concurrent worker 2–3; consolidation chạy đêm (sleep-time); đo p95 đường chat thường làm gate mỗi phase |
| Scope creep kiểu "plan 17 sprint" | Trung | Mỗi phase ≤6 tuần phải ship demo người dùng chạm được; không bảng/worker nào thiếu consumer cùng phase |
| Nợ sync-client phát nổ muộn | Trung | Phase 0a làm trước mọi agent code |
| Eval bằng judge 9B nhiễu; benchmark vendor không tin được | Trung | Judge chấm 2–3 lần lấy trung vị, định kỳ đối chiếu model lớn (Gemini/DeepSeek đã có client); chỉ tin eval chạy trên stack của mình |
| Mất agent run vì hạ tầng không supervision | Trung | Phase 0f: restart policy, healthcheck, container hóa API, backup theo lịch — trước khi chất agent workload |

---

## 7. Tiêu chí chuyển phase thống nhất + KPI

Mỗi phase chỉ được đóng khi đủ 4 điều kiện:

1. **Eval gate định lượng chạy trong CI** (mini-BFCL cho tool calling; LongMemEval-style cho memory; faithfulness/context-precision cho RAG).
2. **Một demo end-to-end** người dùng chạm được qua bot Ún hoặc web UI.
3. **Kill-test / restore-test** cho phần durable (kill worker giữa run → resume đúng; restore backup → đọc được).
4. **p95 latency đường chat thường không tăng quá ngưỡng** đặt trước phase đó.

KPI sức khỏe agent theo dõi liên tục (bảng trace Postgres, sau này Langfuse): tỷ lệ tool-call hợp lệ ngay lần đầu; số retry trung bình/bước; số vòng lặp/task; latency từng tool; token in/out mỗi run; tỷ lệ run cần HITL; tỷ lệ memory được dùng trong câu trả lời (citation "vì sao bot nhớ").

---

## Phụ lục A — Danh mục nguồn tham chiếu

Số star xấp xỉ tại thời điểm khảo sát (08/2026), đã kiểm chứng trên repo/trang chính thức.

### A.1. Framework & SDK agent (để mượn pattern)

| Nguồn | Star / thẩm quyền | Bài học chính rút cho plan |
| --- | --- | --- |
| [LangGraph](https://github.com/langchain-ai/langgraph) | ~40k | Checkpoint-per-step vào Postgres theo thread_id; interrupt()/Command(resume) cho HITL; stream đa kênh values/updates/messages |
| [Microsoft AutoGen](https://github.com/microsoft/autogen) | ~60k, **maintenance mode 10/2025** | Cảnh báo framework churn; hội thoại đa agent tự do khó kiểm soát token |
| [AG2](https://github.com/ag2ai/ag2) | ~5k, đổi API lớn 2 lần | Cùng cảnh báo trên |
| [CrewAI](https://github.com/crewAIInc/crewAI) | ~57k | Phải thêm Flows (deterministic) bên cạnh Crews — thừa nhận production cần workflow, agent tự trị chỉ ở chỗ thật cần |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | ~29k | Triết lý tối giản; handoffs-as-tools; guardrails chạy song song fail-fast; agent-as-tool cho model nhỏ |
| [Google ADK](https://github.com/google/adk-python) | ~21k | Tách WorkflowAgent (deterministic) khỏi LlmAgent; nghiêng Gemini/Vertex — không hợp self-hosted |
| [smolagents](https://github.com/huggingface/smolagents) | ~29k | Agent loop lõi ~1.000 dòng; code-agent bắt buộc sandbox |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | ~13k | Điểm hội tụ ngành: graph + checkpoint + HITL + streaming |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | ~19k | Tool từ type hints, ModelRetry, OTel sẵn — khớp stack FastAPI+Pydantic nếu cần bộ khung |

### A.2. Nguyên tắc thiết kế (vendor chính thức)

| Nguồn | Thẩm quyền | Bài học chính |
| --- | --- | --- |
| [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) | Tài liệu nền tảng được cả ngành trích dẫn | Workflow vs agent; 5 pattern (chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer); đơn giản nhất có thể |
| [Anthropic — Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | Hệ production của Anthropic | Multi-agent tốn ~15× token, chỉ hợp task breadth-first; token budget ≈ 80% phương sai hiệu năng |
| [Anthropic — Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Chính thức | Attention budget; JIT retrieval; compaction; note-taking; sub-agent cô lập context |
| [Anthropic — Writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents) | Chính thức | Ít tool đòn bẩy cao; namespace; kết quả token-efficient; tinh chỉnh mô tả tool theo transcript eval |
| [OpenAI — A Practical Guide to Building Agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/) | Chính thức | Khi nào nên/không nên xây agent; single agent trước; guardrail xếp lớp; phân hạng rủi ro tool |
| [MCP](https://modelcontextprotocol.io) + [servers](https://github.com/modelcontextprotocol/servers) | Chuẩn mở; repo ~90k | Tích hợp M×N → M+N; reference servers là bản giáo dục, phải sandbox |
| [12-factor agents](https://github.com/humanlayer/12-factor-agents) | ~25k | Sở hữu prompt/context/control-flow; agent = stateless reducer trên event log; human approval là một tool; agent nhỏ 3–20 bước |

### A.3. Memory dài hạn

| Nguồn | Star / thẩm quyền | Bài học chính |
| --- | --- | --- |
| [Letta (MemGPT)](https://github.com/letta-ai/letta) + [paper](https://arxiv.org/abs/2310.08560) | ~24k; paper nền tảng | Memory blocks ghim trong context; archival tách riêng; sleep-time agents |
| [mem0](https://github.com/mem0ai/mem0) | ~63k | Pipeline 2 pha extract → LLM quyết ADD/UPDATE/DELETE/NOOP trên top-k tương tự; v2: entity-linking + retrieval đa tín hiệu |
| [Graphiti / Zep](https://github.com/getzep/graphiti) + [paper](https://arxiv.org/abs/2501.13956) | ~30k | Bi-temporal (valid_from/valid_to, INVALIDATE thay vì DELETE); retrieval không gọi LLM; context block |
| [LangMem](https://github.com/langchain-ai/langmem) | ~1.6k, chính thức LangChain | Semantic/episodic/procedural; hot-path vs background; profile vs collection |
| [cognee](https://github.com/topoteretes/cognee) | ~30k | Có chế độ chạy toàn bộ memory layer trên Postgres |
| [Zep blog phê bình LoCoMo](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/) | Vendor chính thức | Không tin benchmark vendor; LongMemEval (knowledge-update + abstention) đáng tin hơn |

### A.4. Nền tảng self-hosted đối chiếu tính năng

| Nguồn | Star | Điểm đáng học |
| --- | --- | --- |
| [Open WebUI](https://github.com/open-webui/open-webui) | ~149k | Chuẩn vàng UI+Ollama: hybrid RAG, web search, RBAC, plugin Pipes/Tools, MCP, Persistent Memory |
| [Dify](https://github.com/langgenius/dify) | ~141k | Plugin-hóa toàn bộ model/tool vào marketplace |
| [RAGFlow](https://github.com/infiniflow/ragflow) | ~83k | Chất lượng parse/chunk là điểm nghẽn số 1 của RAG; grounded citations |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | ~64k | Workspace isolation; automatic + user-managed memories; dynamic model routing |
| [LlamaIndex](https://github.com/run-llama/llama_index) | ~49k | Workflows event-driven, async-first, step resume được |
| [LibreChat](https://github.com/danny-avila/LibreChat) | ~42k | Code Interpreter sandbox; subagents; circuit breaker cho stream dài |
| [Khoj](https://github.com/khoj-ai/khoj) | ~35k | Scheduled automations — cron cho agent; mô hình "trợ lý cá nhân qua chat platform" gần bot Ún nhất |
| [Haystack](https://github.com/deepset-ai/haystack) | ~26k | Typed sockets + explicit connections cho pipeline dễ test |

### A.5. Serving, tool calling với model cục bộ, eval & observability

| Nguồn | Star / thẩm quyền | Bài học chính |
| --- | --- | --- |
| [Ollama API docs](https://github.com/ollama/ollama/blob/main/docs/api.md) | ~178k | tools native (v0.3.0), `format`=JSON Schema (v0.5), streaming tool calls (v0.8); **không có tool_choice** → decide-then-act |
| [Qwen function calling](https://qwen.readthedocs.io/en/latest/framework/function_call.html) + [Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) | Chính thức; ~17k | Định dạng Hermes `<tool_call>`; chính đội Qwen tự parse thay vì tin serving layer |
| [vLLM tool calling](https://docs.vllm.ai/en/stable/features/tool_calling/) | ~89k | tool_choice required/named + guided decoding + continuous batching — đường nâng cấp khi cần |
| [BFCL (Gorilla)](https://github.com/ShishirPatil/gorilla) | ~13k; ICML 2025 | Model 7–9B: tốt single-turn, tụt mạnh multi-turn/long-horizon |
| [NVIDIA — SLM agentic AI](https://arxiv.org/abs/2506.02153) | Paper NVIDIA Research | Kiến trúc dị thể: model nhỏ cho tác vụ hẹp có scaffold, orchestration trong code |
| [Outlines](https://github.com/dottxt-ai/outlines) / [Instructor](https://github.com/567-labs/instructor) | ~16k / ~14k | Constrained decoding (cú pháp) + validate-retry (ngữ nghĩa) |
| [Qdrant hybrid search](https://qdrant.tech/articles/hybrid-search/) | Vendor chính thức | Query API prefetch + RRF; anti-pattern cộng điểm alpha không chuẩn hóa |
| [Qwen3 Embedding/Reranker](https://arxiv.org/html/2506.05176v1) | Paper Qwen team | Reranker cùng họ với embedding đang dùng; bge-reranker-v2-m3 là lựa chọn cân bằng self-host |
| [ragas](https://github.com/explodinggradients/ragas) / [DeepEval](https://github.com/confident-ai/deepeval) / [promptfoo](https://github.com/promptfoo/promptfoo) | ~15k / ~17k / ~22k (promptfoo bị OpenAI mua 3/2026 — pin version) | Eval RAG reference-free; "pytest cho LLM" làm gate CI; red-teaming |
| [Langfuse](https://github.com/langfuse/langfuse) | ~27–33k | Observability self-hosted, OTLP endpoint, LLM-as-judge trên traffic thật |
| [OTel GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai) | Chuẩn OpenTelemetry | Span invoke_agent → chat → execute_tool; instrument một lần, đổi backend không sửa code |

---

## Phụ lục B — Quan hệ với các plan hiện có trong repo

- `discord_memory_workflow_plan_v5_final.md`: **vẫn là spec chi tiết của phân hệ memory** — plan này không thay thế mà sắp xếp lại thứ tự thực thi của nó (read-path và rolling summary được kéo lên trước; validator/conflict-window và slash commands vào Phase 1; reconciliation/rebuild giữ ở Phase 4) và bổ sung bi-temporal + 4 tầng memory.
- `docs/IMPLEMENT_MODULAR_WORKER_ARCHITECTURE.md`: nguyên tắc "cấm chuyển microservices/K8s/Kafka khi chưa cần" được kế thừa nguyên vẹn — mọi hạng mục agent trong plan này chạy trên đúng stack Compose + RQ hiện có.
- `docs/current_architecture.md` + final report migration: ranh giới PostgreSQL-only và chính sách legacy Qdrant giữ nguyên; agent state là phần mở rộng của source of truth hiện có, không phải hệ lưu trữ mới.
