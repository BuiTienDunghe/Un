# CLAUDE.md

Hướng dẫn cho coding agent làm việc trong repo này.

`local-ai-core` — hệ AI cục bộ: backend FastAPI, Discord bot, pipeline ingestion và
retrieval. Xem `README.md` để biết cách chạy, `docs/current_architecture.md` để biết
kiến trúc hiện tại.

## Agent skills

Repo dùng bộ [engineering skills của Matt Pocock](https://github.com/mattpocock/skills),
vendored tại `.claude/skills/` — xem `.claude/skills/README.md` để biết đã cài những gì
và cách cập nhật.

### Issue tracker

Issue và spec là file markdown trong `.scratch/<feature-slug>/`, không dùng GitHub Issues.
Xem `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: một `CONTEXT.md` ở gốc repo, ADR trong `docs/adr/`. Cả hai được tạo lười
bởi `/domain-modeling` khi thực sự cần, nên đừng coi việc chúng chưa tồn tại là thiếu sót.
Xem `docs/agents/domain.md`.
