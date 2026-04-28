---
name: new-migration
description: Generate a new Alembic async migration with the PumpWatch safety patterns applied (NOT-NULL backfill rewrite, server_default check). Invoke as /new-migration <slug>. Does NOT run alembic upgrade — the user reviews first.
---

# Scaffold a safe Alembic migration

Encodes the two highest-cost migration mistakes already burned into `tasks/lessons.md`:

- **Session 2:** Alembic autogenerate does not see Python-only `default=` values; you must set both `default=` AND `server_default=` on the model column.
- **Session 3:** A `NOT NULL` `add_column` without a default fails on any populated table. Rewrite into the three-step add-nullable / backfill / set-not-null pattern.

## Inputs

- `<slug>` — kebab-case description (e.g., `add_user_chat_settings`, `partition_price_snapshots`).

## Steps

### 1. Generate the revision

```bash
uv run alembic revision --autogenerate -m "<slug>"
```

This produces a new file under `alembic/versions/<rev_id>_<slug>.py`.

### 2. Read the generated revision

Read the file end-to-end. Note:
- `revision` and `down_revision` IDs (must form a single chain — see `alembic heads`).
- Every `op.add_column`, `op.alter_column`, `op.create_table`, `op.create_index`.

### 3. Safety scan — NOT-NULL on existing tables

For every `op.add_column(<table>, sa.Column(<name>, <type>, nullable=False))`:

- If `<table>` may have rows in any environment, the migration WILL fail.
- Rewrite into the three-step pattern:

  ```python
  op.add_column("<table>", sa.Column("<name>", <type>, nullable=True))
  op.execute("UPDATE <table> SET <name> = <backfill_expr>")
  op.alter_column("<table>", "<name>", nullable=False)
  ```

- **Prompt the user** for `<backfill_expr>` if it isn't obvious. Examples from the project:
  - Session 3 `users.chat_id` → `chat_id = telegram_id` (private chats have `chat_id == telegram_id`).
  - Session 7 `alerts_sent.dispatch_attempts` → `dispatch_attempts = 1` (defaulted via `server_default`, no UPDATE needed because the column has `server_default='1'`).
- Add a planning comment above the rewritten block explaining why.

### 4. Server-default check

For every column with a non-null default:

- Open the corresponding model under `src/pumpwatch/db/models/`.
- Confirm the `mapped_column(...)` has BOTH:
  - `default=<python_value>` — for ORM-side inserts that don't specify the column.
  - `server_default=<sa.text("...") or func.now() or sa.literal(...)>` — for DDL-level default that autogenerate sees.
- If only `default=` is set, autogenerate will not have emitted a default and the migration will need to backfill or add `server_default` to the column. Surface this to the user and ask whether to add `server_default` to the model (preferred) or backfill in the migration.

### 5. Single head check

```bash
uv run alembic heads
```

Must report exactly one head. If two, the user has parallel revisions that need a merge migration:

```bash
uv run alembic merge -m "merge <reason>" <head_a> <head_b>
```

### 6. Print the path; do NOT upgrade

Print the new revision path and the unified diff. Do NOT run `alembic upgrade head` automatically — the user reviews the diff first and runs the upgrade themselves (or it runs in CI / on container start).

## Output shape

```
## Migration scaffolded: alembic/versions/<rev>_<slug>.py

**Safety rewrites applied:**
- <table>.<column>: NOT-NULL → three-step add/backfill/set-not-null (backfill: <expr>)
- <or "none needed">

**Server-default audit:**
- <model>.<column>: ✅ both default= and server_default=
- <or warnings>

**Heads:** ✅ single head <rev>

Next: review the diff, then `uv run alembic upgrade head` when ready.
```

## Notes

- Async Alembic env: `alembic/env.py` already wraps migrations in `asyncio.to_thread` for pytest compatibility (Session 2 lesson). Do not refactor `env.py` from a migration scaffold task.
- Partitioning: `price_snapshots` is the planned partitioned table (see PROJECT_STATUS.md ADR #21). When that migration lands, declarative `RANGE(ts)` parent + N child tables with a Beat task creating tomorrow's child at midnight is the agreed shape.
