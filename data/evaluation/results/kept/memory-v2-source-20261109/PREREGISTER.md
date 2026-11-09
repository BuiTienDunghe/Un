# Memory v2 experiment — 09/11/2026

Branch: codex/tool-state-continuity. Baseline: 966e6b7. No 9B inference, teacher,
cloud fallback or new model download. General reader: installed qwen3.5:2b.

Implementation boundary: explicit source notes, exact channel/thread scope,
transactional PostgreSQL FTS, optimistic revisions, tombstones, audience epochs.
No automatic inferred facts, dense search, typed semantic replacement or legacy import.

Before execution, acceptance checks:
- Source fidelity: exact text, especially negation/numbers/third-person/temporal qualifications.
- Scope: no cross-owner, guild, channel or thread retrieval.
- Lifecycle: retries idempotent, edit/retract invalidate, replay cannot resurrect,
  stale revision rejected, forgotten history/tool-state excluded, generation race blocked.
- API: actual add/search/update/delete on isolated PostgreSQL, with owner isolation.
- Chat: real persistence with stubbed generation; sync and buffered SSE path.
- Existing tests: continuity, Discord, chat/memory and architecture boundaries.
- Optional actual 2B reader: fixed source-grounded questions and abstentions;
  report raw responses/latency separately from deterministic safety tests.

Services: fresh disposable postgres:16-alpine, random isolated database *_test,
port 55439. Additional disposable Redis/Qdrant only if integration checks need them.
Do not migrate the operating database. Log failures as well as passes.
Claims: no universal best, no parity with previous large-model reader, no live-market
or production-scale performance claim. Faithful quote storage is not semantic understanding.
