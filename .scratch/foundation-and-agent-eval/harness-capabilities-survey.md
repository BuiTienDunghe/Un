**Plain-language essence.** Established harnesses don't make the model smarter. They manage its small desk better:
- When a document is long, they hand the model a bookmark so it can read the next page, instead of cutting the text off.
- They clear the desk by throwing away old search results, or by replacing old conversation with a short summary.
- They keep notes in a drawer the model can reopen later.
- They check the answer against simple rules before sending it.

Most of this is plain code around the model. Only a few capabilities need extra rounds of model thinking: helpers working in parallel, self-critique, and summarizing.

Scope: capabilities only. Turn limits, tool errors, tracing and registries are excluded. All pages were read on 2026-10-27. The keys [Sn] point to the source list at the end.

### 1. Long input and long context
| Harness | Mechanism / API | Notes | Src |
|---|---|---|---|
| Claude Code | Read `offset`/`limit`, 25k tokens per call; PDF `pages` (≤20); Bash output over ~30k chars and MCP output over 50k chars saved to a file | Over-limit read gives page 1 plus a "PARTIAL view" notice; file outputs give path plus a 2,000-char preview | S14, S18 |
| Anthropic guidance | Pagination, range selection, filtering, truncation; `response_format` concise/detailed | Truncation notice should steer to narrower searches | S5 |
| Memory tool | `view_range`; views truncated past 16k chars | — | S11 |
| deepagents | `read_file` offset/limit; results over 20k tokens go to a file | Model sees the path plus the first 10 lines | S27, S28 |
| ADK | Artifacts + `LoadArtifactsTool` | Loaded into one request only | S47 |
| Token counting | Anthropic `count_tokens` (estimate); Pydantic AI `ctx.context_window_used` | — | S12, S39 |
| Prompt layout | Documents first, query last; `<document>`/`<source>` tags; quote first | "Up to 30%" gain, measured on Claude | S13 |
| Chunked input | LangGraph `Send` (map-reduce); sectioning, orchestrator-workers | No built-in feature for long input found | S32, S1 |
| Retrieval | Contextual embeddings + BM25 + rerank | Failures −67%; 20 chunks beat 5 or 10 | S8 |

Model demand: paging needs only whole-number arguments, so it is low. Map-reduce costs one model pass per chunk.

### 2. Context management over a session
| Harness | Mechanism / API | Notes | Src |
|---|---|---|---|
| Anthropic API | `clear_tool_uses_20250919` (default trigger 100k, keeps 3); `compact_20260112`; on-demand compaction | Betas; cleared results become placeholders | S9, S10 |
| Anthropic guidance | Clearing tool results ("safest lightest touch") → compaction → notes; just-in-time loading by ID | — | S2 |
| Claude Code | Auto-compaction and `/compact <focus>` | Re-injects CLAUDE.md, memory, plan and ≤5 recent files | S19 |
| deepagents | Summarizes at 85% of the window, keeps the newest 10% | Full history saved to a file; `compact_conversation` tool | S28 |
| LangChain | `SummarizationMiddleware(trigger, keep)`; `@before_model` trim | Each tool call must keep its result | S31 |
| OpenAI Agents | Sessions `limit`; `session_input_callback`; compaction session | Compaction works with OpenAI only | S22, S26 |
| Pydantic AI | `ProcessHistory`; Harness `TieredCompaction` | Cheap steps first; repairs calls left without results | S35, S39 |
| ADK | `EventsCompactionConfig` (interval, overlap, token_threshold) | Python v1.16.0 | S45 |
| smolagents | `step_callbacks` edit `agent.memory.steps` | Manual | S44 |

Model demand: clearing and trimming are plain code. A summary costs a pass, and its quality depends on the model.

### 3. Planning
| Harness | Mechanism | Notes | Src |
|---|---|---|---|
| Claude Code | `Task*` or `TodoWrite`; plan mode | On by default only for Opus 4.7, Sonnet 4.6, Haiku 4.5 and earlier models | S14 |
| deepagents | `write_todos` | Opt-in since v0.7 | S27 |
| smolagents | `planning_interval=N` | A step with no tool call that restates facts and next steps | S41 |
| ADK | `BuiltInPlanner`; `PlanReActPlanner` | The second is for models without built-in thinking | S49 |
| Pydantic AI | Harness `Planning` | — | S38 |
| Anthropic | Feature list (JSON) + progress file | For work spanning several sessions | S4 |

Not found: a planning tool in the OpenAI Agents SDK. Model demand: Claude Code says newer models "keep track… without a written checklist". That suggests checklists mainly help weaker models.

### 4. Sub-agents and multi-agent
| Harness | Mechanism | Notes | Src |
|---|---|---|---|
| Claude Code | `Agent` tool with its own context; only the final result returns | Not for back-and-forth, shared context, or latency-sensitive work | S15 |
| Anthropic research system | Orchestrator-workers; workers send back 1–2k-token summaries | +90.2% over a single agent, at ~15× the tokens; poor fit for shared context | S6, S2 |
| OpenAI Agents | Handoffs vs `Agent.as_tool()` | Code orchestration is more predictable | S20, S21 |
| deepagents | `task` tool (isolated or fork) | — | S27 |
| Pydantic AI | Delegation via a tool, hand-off, Harness `SubAgents` | — | S38 |
| smolagents | `managed_agents` | — | S42 |
| ADK | `transfer_to_agent`, `AgentTool`, Sequential/Parallel/Loop agents | — | S50 |

Model demand: high, because tokens multiply. On one local GPU, parallel workers run one after another (my inference).

### 5. Memory
| Harness | Mechanism | Src |
|---|---|---|
| Claude Code | CLAUDE.md loaded at launch (aim for under 200 lines); auto memory loads its first 200 lines | S16 |
| Anthropic API | Memory tool `memory_20250818` (client-side `/memories`); warns before context is cleared | S11, S9 |
| LangGraph | Checkpointer + `thread_id` (short-term); Store (long-term); writes during the turn or in the background | S30 |
| deepagents | `AGENTS.md`; `/memories/` stored via `StoreBackend` | S28 |
| OpenAI Agents | Sessions (SQLite, Redis, SQLAlchemy…) | S22 |
| Pydantic AI | Serializable `message_history`; Harness `Memory`, `ConversationSearch` | S35 |
| ADK | `MemoryService`; `load_memory` (model decides) vs `preload_memory` (every turn) | S46 |
| smolagents | `run(reset=False)` | S42 |

Model demand: the file operations are plain code. The model decides what to write and when to read back. ADK's `preload_memory` removes that decision; `load_memory` leaves it to the model.

### 6. Tool ecosystem
| Capability | Who provides it | Notes | Src |
|---|---|---|---|
| MCP | All six harnesses (Pydantic AI's MCP page not fetched; LangChain support is beta, ≥1.4.0) | ADK advises always setting `tool_filter` | S18, S26, S34, S43, S51 |
| Tool search | Claude Code `ToolSearch`; Anthropic `defer_loading`; OpenAI `ToolSearchTool` | "Less useful" with fewer than 10 tools | S18, S7, S24 |
| Parallel calls | OpenAI `parallel_tool_calls`; Ollama | — | S26, S53 |
| Structured output | OpenAI `output_type`; Pydantic AI tool/native/prompted output; ADK `output_schema` | Prompted output is "least reliable" but the only option without native tool calling | S26, S36, S49 |
| Code execution | smolagents `CodeAgent`; Anthropic programmatic tool calling; ADK; Pydantic AI `CodeMode` | 37% fewer tokens; not for single calls | S40, S7 |
| Filesystem | Claude Code Read/Grep/Glob; deepagents file tools | Try agentic search before semantic search | S14, S27, S3 |
| Tool design | Consolidate tools; namespace them; `input_examples` | Examples raised accuracy from 72% to 90% | S5, S7 |

Model demand: smolagents warns that too many tools "can overwhelm weaker LLM engines" (S43). Whether Qwen 9B makes reliable parallel calls is unverified.

### 7. Human-in-the-loop
| Harness | Mechanism | Src |
|---|---|---|
| Claude Code | Permission rules; `AskUserQuestion` (multiple choice) | S14 |
| OpenAI Agents | `needs_approval` → `interruptions` → approve/reject → resume | S23 |
| LangGraph / deepagents | `interrupt()` + `Command(resume=)`; `interrupt_on` | S29, S27 |
| Pydantic AI | `requires_approval`, `DeferredToolRequests` | S37 |
| ADK | `require_confirmation` (Python v1.14.0, experimental) | S48 |
| smolagents | `agent.interrupt()` (stop only) | S42 |

Model demand: low, because the pause happens in code.

### 8. Instructions and skills
| Harness | Mechanism | Src |
|---|---|---|
| Claude Code | Skills: only the description loads at start (capped at 1,536 chars), the body on use; CLAUDE.md layering | S17, S16 |
| deepagents | Agent Skills with staged loading | S27 |
| OpenAI Agents | Instructions can be a function, changing per run | S26 |
| ADK | `{var}` templating; `GlobalInstructionPlugin` | S49 |
| smolagents | `instructions` appended; editing the templates is "not advised" | S41 |

Model demand: the model must choose a skill from a short description. My inference is that this is why the description cap exists.

### 9. Streaming and progress
| Harness | Mechanism | Src |
|---|---|---|
| OpenAI Agents | `run_streamed`: deltas, `tool_called`/`tool_output` | S25 |
| LangGraph | Stream modes `updates`/`messages`/`custom` (tools emit via `get_stream_writer`) | S33 |
| Pydantic AI | `stream_output` with partial validation | S36 |
| ADK | `run_async` events: `partial`, function call/response | S52 |
| smolagents | `GradioUI` shows each step | S42 |

Not fetched: Claude Agent SDK streaming. Model demand: none.

### 10. Self-verification
| Source | Mechanism | Src |
|---|---|---|
| Anthropic | Evaluator-optimizer when the criteria are clear; rules-based checks first; LLM-as-judge is "not very robust" | S1, S3 |
| Anthropic | Verify end-to-end before marking something done | S4 |
| OpenAI Agents | Evaluator loop in code | S21 |
| Pydantic AI | `output_validator` + `ModelRetry` (1 retry by default) | S36 |
| smolagents | `final_answer_checks` | S42 |
| ADK | Generator-critic; `LoopAgent` refinement | S50 |

Model demand: rule checks are low. An LLM critic costs an extra pass and depends on model quality.

### What recurs across sources, and why
- **Hand the model a handle, not a cut-off blob** (S5, S14, S27, S11). The reason given: context is "a finite resource with diminishing marginal returns" (S2).
- **Cheapest relief first:** clear old tool results before summarizing (S2, S9, S28, S39).
- **When trimming, keep each tool call with its result** (S31, S35).
- **Notes outside the context window survive compaction** (S2, S4, S11, S19).
- **Sub-agents are for isolation, not the default.** The reasons are token cost and poor fit for shared context (S1, S6, S15).
- **Load on demand:** skills, tool search, rules, memory (S16, S17, S18, S46).
- **Prefer code and rules over model judgment** (S1, S3, S21, S41).
- **Scaffolding shrinks as models get stronger:** Claude Code dropped task tools on newer models, and deepagents made planning opt-in (S14, S27).

### Ranking for Ún (my inference)
Ún is limited more by its 16k context and 90 s budget than by its 9B size. "Plain code" below means no extra model pass.

1. **Paged reading through a handle.** For documents: return IDs plus a preview, and add `read_document(doc_id, from_chunk, n)`. For Discord: `read_messages_around(message_id, before, after)`. This targets the 400- and 2,400-char clips directly, and the model only supplies numbers. Cost: one of the 3 tool rounds. (S2, S5, S14, S28)
2. **Documents first, query last, quote-first.** No extra pass, but the quotes are extra output tokens, so it takes time out of the 90 s. The gain was measured only on Claude. (S13)
3. **Clearing old tool results.** Plain code. It only matters if Ún carries history across turns. Risk: earlier evidence has to be re-read by ID. (S2, S9, S35)
4. **Rule-based answer check:** quoted text must appear in what was retrieved, with one retry. Costs a pass only when the check fails. (S3, S36, S42)
5. **Token counting.** Plain code. Items 3 and 6, and any truncation that adapts to context size, depend on it. How to count Qwen tokens locally is unverified.
6. **Code-driven map-reduce for long pasted input.** It is the only way to read all of a long paste. Cost: one 9B pass per chunk, which may exceed 90 s; this is unmeasured. (S1, S21, S32)
7. **Streaming progress.** Only improves the experience; no model risk. (S25, S33, S52)
8. **Memory per user or server.** Risk: notes go stale, and writing during the turn adds latency. (S11, S30)
9. **Clarifying-question tool.** Risk: a weak model asks too often (my inference).

Low value now:
- **Sub-agents:** ~15× tokens, run one after another on one GPU (S6, S15).
- **Tool search:** fewer than 10 tools (S7).
- **Planning tools:** with only 3 rounds there is little to plan, although Claude Code's defaults suggest they help weaker models. Worth a test (S14).
- **Code execution:** security risk, and smolagents' first debugging step is "use a stronger LLM" (S41).
- **Skills:** Ún has few distinct tasks.

Strong-model note: smolagents says Ollama `num_ctx` 2048 "will fail horribly" and 8192 "works for easy tasks" (S42). Ún's 16384 is above both. This is version-dependent.

---
**Sources** (outside the word budget; all read 2026-10-27)
- S1 anthropic.com/engineering/building-effective-agents — Dec 19 2024. The page says its tooling guidance has since changed.
- S2 anthropic.com/engineering/effective-context-engineering-for-ai-agents — Sep 29 2025
- S3 claude.com/blog/building-agents-with-the-claude-agent-sdk — Sep 29 2025 (the old anthropic.com/engineering URL redirects here)
- S4 anthropic.com/engineering/effective-harnesses-for-long-running-agents — Nov 26 2025
- S5 anthropic.com/engineering/writing-tools-for-agents — Sep 11 2025
- S6 anthropic.com/engineering/multi-agent-research-system — Jun 13 2025
- S7 anthropic.com/engineering/advanced-tool-use — Nov 24 2025
- S8 anthropic.com/engineering/contextual-retrieval — Sep 19 2024
- S9 platform.claude.com/docs/en/build-with-claude/context-editing — beta `context-management-2025-06-27`; the end of the page was not read
- S10 platform.claude.com/docs/en/build-with-claude/compaction — beta `compact-2026-09-04`
- S11 platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool — `memory_20250818`
- S12 platform.claude.com/docs/en/build-with-claude/token-counting — GA
- S13 platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices, "Long context prompting" section
- S14–S19 code.claude.com/docs/en/ {tools-reference, sub-agents, memory, skills, mcp, context-window} — Claude Code v2.1.2xx–v2.1.3xx
- S20–S26 openai.github.io/openai-agents-python/ {handoffs, multi_agent, sessions, human_in_the_loop, tools, streaming, agents + ref/model_settings} — no version stated
- S27 docs.langchain.com/oss/python/deepagents/harness — deepagents ≥0.7
- S28 docs.langchain.com/oss/python/deepagents/context-engineering
- S29 docs.langchain.com/oss/python/langgraph/interrupts — `response_schema` needs langgraph ≥1.2.12
- S30 docs.langchain.com/oss/python/langgraph/memory
- S31 docs.langchain.com/oss/python/langchain/short-term-memory
- S32 docs.langchain.com/oss/python/langgraph/graph-api
- S33 docs.langchain.com/oss/python/langgraph/streaming — v2 needs LangGraph 1.1
- S34 docs.langchain.com/oss/python/langchain/mcp — `langchain[mcp]>=1.4.0`, beta
- S35–S39 pydantic.dev/docs/ai/ {core-concepts/message-history, core-concepts/output, tools-toolsets/deferred-tools, multi-agent-applications, capabilities/compaction} — compaction design still changing (GitHub pydantic/pydantic-ai #11395)
- S40–S44 huggingface.co/docs/smolagents/ {conceptual_guides/intro_agents, tutorials/building_good_agents, guided_tour, tutorials/tools, tutorials/memory} — v1.26.0
- S45–S52 adk.dev/ {context/compaction (Py v1.16.0), sessions/memory, artifacts, tools-custom/confirmation (Py v1.14.0, experimental), agents/llm-agents, workflows/patterns, tools-custom/mcp-tools, events}
- S53 docs.ollama.com/capabilities/tool-calling — no version or date stated

**Unverified or not found:**
- Claude Agent SDK streaming
- The Pydantic AI MCP page
- A planning tool in the OpenAI Agents SDK
- Whether Qwen makes reliable parallel calls
- How to count Qwen tokens locally
- Whether gains measured on Claude carry over to Qwen

Pages S9, S15, S17, S18, S47 and S49 were truncated when fetched, so nothing is claimed from their later sections.
