# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

**Layout: single-context.** One `CONTEXT.md` at the repo root, ADRs in `docs/adr/`.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached directly, or via `/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-<slug>.md
│   └── 0002-<slug>.md
├── app/
├── backend/
├── discord_bot/
└── tools/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_

---

## Ghi chú cho repo này

Sinh ra bởi `/setup-matt-pocock-skills`, từ template `domain.md`.

- Chọn **single-context** vì repo không có tín hiệu monorepo nào (không `pnpm-workspace.yaml`,
  không `package.json`, không `packages/*/`). `pyproject.toml` khai báo một package duy nhất
  `local-ai-core`.
- Bỏ nhánh multi-context và mục `src/<context>/docs/adr/` khỏi tài liệu cho gọn. Nếu sau này
  repo tách thành nhiều context, lấy lại từ `.claude/skills/setup-matt-pocock-skills/domain.md`.
- Bỏ tham chiếu `/improve-codebase-architecture` — skill đó chưa được cài.
- `CONTEXT.md` và `docs/adr/` **chưa tồn tại**, và đó là điều bình thường: `/domain-modeling`
  sẽ tạo chúng khi thực sự có thuật ngữ hoặc quyết định cần ghi lại.
