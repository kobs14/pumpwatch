---
name: pre-session
description: Run the PumpWatch pre-session checklist. Reads CLAUDE.md + PROJECT_STATUS.md + tasks/todo.md + tasks/lessons.md + NEXT_PROMPT.md, identifies the next session, restates the objective, and surfaces lessons that constrain it. Use at the start of any session, or when the user says "start session N".
---

# Pre-session checklist

Encodes CLAUDE.md §Session Workflow steps 1–2. Run this before writing any code.

## Steps

1. **Read the locked conventions** (in this exact order, full files):
   - `CLAUDE.md` — project conventions, stack lockdown, architectural invariants, forbidden patterns
   - `PROJECT_STATUS.md` — current phase, session plan table, locked architectural decisions (#1–#NN)
   - `tasks/todo.md` — current session's scratchpad + carry-over items
   - `tasks/lessons.md` — full file; prior-session constraints are load-bearing

2. **Read the session brief** if present:
   - `NEXT_PROMPT.md` — detailed brief for the next session

3. **Identify the next session.** Find the first row in `PROJECT_STATUS.md` "Session Plan" table whose Status is `⬜`. That row's `#` and `Title` are the active session.

4. **Restate the objective in one sentence.** Use your own words, grounded in the session brief.

5. **Predict file impact.** List files this session will touch, separating:
   - **Create:** new files
   - **Modify:** existing files

6. **Surface constraining lessons.** Scan `tasks/lessons.md` for entries that constrain this session's work. Examples to watch for:
   - Eager-mode Celery does NOT re-run on `self.retry(...)` — set `WORKER_FETCH_MAX_CELERY_RETRIES=0` for retry-path tests
   - `prometheus_client` reads `PROMETHEUS_MULTIPROC_DIR` at Counter-construction time; env vars must be set at process start, not in signal handlers
   - Schema columns typed `Mapped[StrEnum]` backed by `String(N)` load as plain `str` — use `==`, not `is`
   - Defensive try/except for logging must wrap the *outer* call site, not just the inner helper
   - SAVEPOINT-rollback fixture pattern doesn't work for handlers that open their own sessions — use `truncating_sessionmaker`

7. **STOP.** Do not write code. Wait for the user to confirm scope and answer any open questions surfaced from the brief vs. the actual repo state. If the brief conflicts with the schema or with prior ADRs, raise it explicitly and ask — per CLAUDE.md "When in Doubt".

## Output shape

Print a short summary in this exact shape:

```
## Pre-session: Session N — <title>

**Objective:** <one sentence>

**Predicted file impact:**
- Create: <paths>
- Modify: <paths>

**Constraining lessons:**
- <bullet list — only entries that actually apply>

**Open questions before code:**
- <questions for the user, or "none">
```
