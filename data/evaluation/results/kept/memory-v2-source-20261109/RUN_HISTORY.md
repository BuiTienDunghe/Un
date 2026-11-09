# Recorded runs
- Initial compile: passed; first registry resolve failed because vision had an empty version list. Fixed inactive placeholder.
- First setup attempt: Windows default cp1252 could not read YAML. Fixed explicit UTF-8.
- First migration invocation used the wrong config location. Corrected to root alembic.ini; isolated migration succeeded.
- Source integration initial: 24 passed, 1.40s.
- Regression initial: 1684 passed, 20 failed, stopped at maxfail=20 (202.62s). Mostly old model/profile and migration contracts.
- Targeted: 215 passed, 8 failed (29.11s). A new test used the wrong Discord URL; corrected. Profile assertions updated.
- Regression second: 2136 passed, 12 failed, stopped at maxfail=12 (259.44s). Remaining profile contracts, doc schema counts and one leftover open turn from failed HTTP test. Isolated DB will be recreated before the final run.
- Qwen 2B initial: 3/6 fully useful answers by manual case-level review; three over-abstentions despite relevant sources.
- Qwen 2B tuned: 6/6 meet the six semantic expectations by manual review. SAME cases after prompt tuning, not heldout evidence. Raw outputs retained separately.
- Backend complete first pass: 2182 passed, 4 failed (314.31s); four legacy worker tests still expected active 9B roles. Fixed to use explicit small-version pins when exercising legacy mode.
- Final-focused: 58 passed, 6.59s, including v2 lifecycle, real tool-state replay/revocation and model policy.
- Backend verified: 2194 passed (299.34s), 4 existing fixture/deprecation warnings.
- Root bot/launcher: 242 passed, 1 skipped, 25.15s; one audioop deprecation warning.
- Six additional cases fixed before running, with unchanged prompt: 5/6 useful by manual review. Redis/PostgreSQL component-role case still over-abstains even though the source is retrieved. No further prompt tuning on this set.
- Final review additionally restores the pre-existing GLM build recipe and rejects v2 AI requests that borrow another owner's conversation, to keep history and revocation scopes identical. Recheck after these changes is retained separately.
- Backend green: 2196 passed, 284.26s. Final-review subset: 179 passed, 14.78s.
- Post-review raw-ledger contention fix: edit/delete now use the same lock order; record/delete UPSERTs the raw tombstone; history tool rejects canonical tombstones. 85 tests passed, 9.59s, including 12 two-thread race rounds and an event lacking scope metadata.
- A forget-focused invocation initially named a nonexistent test file; no tests ran. Corrected paths and retained the failed log.
- An inspection-only pull-list CLI call initially omitted DATABASE_URL and was refused. The correctly configured CLI is covered by registry tests.
- Final frozen source: 2198 backend cases passed, zero errors/failures. See backend-final-state.xml.
- During the last OCR recipe review, a complete pass had 2193 passed and 2 failed (300.67s): pull-list expectations still included a hub model now represented only by a create recipe. Corrected the two contract assertions; runtime recipe retained.
- The final frozen run supersedes the intermediate runs; all 2198 cases passed (295.36s).

- Archive normalization: removed insignificant trailing spaces in two failure JUnit files so git diff --check passes. Original failure output is retained in the corresponding raw logs.
Raw logs retain pytest whitespace; the local .gitattributes excludes only archived .log files from whitespace lint. Source files remain checked.
