# ADR 018 — DLQ is a Postgres table, not a fifth Redis namespace

## Context

`fetch_token` Celery tasks can fail persistently — a token is delisted,
the source returns 404 indefinitely, or it consistently times out.
Without a dead-letter mechanism the scheduler keeps re-dispatching the
token every Beat tick, burning HTTP budget on a known-bad address.

Two natural homes for a DLQ:

1. A new Redis list/sorted-set under a fifth `pw:dlq:*` namespace.
2. A Postgres `dlq_entries` table.

[ADR-013](013-redis-roles.md) caps Redis at four roles. (1) would
require an ADR amendment. (2) keeps Redis at four roles and adds a
table that a human can `psql` into.

## Decision

A Postgres `dlq_entries` table:

```sql
CREATE TABLE dlq_entries (
    token_address TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL DEFAULT 1,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    error TEXT,
    payload_json JSONB
);
```

`UNIQUE(token_address)` + `INSERT ... ON CONFLICT DO UPDATE` so
re-failures bump `attempts` and `last_seen`. **No FK to `tokens`** —
DLQ rows must outlive token deletes (otherwise the audit trail
disappears the moment the failing token is removed).

Celery-level retry is *manual*, not via `autoretry_for=`. The outer
task body is `bind=True`, captures the source exception, and:

- If `self.request.retries < settings.WORKER_FETCH_MAX_CELERY_RETRIES`:
  `raise self.retry(exc=exc, countdown=...)`.
- Else: upsert into `dlq_entries` and return the silent-skip dict
  (preserving the contract scheduler/batch.py expects).

Default `WORKER_FETCH_MAX_CELERY_RETRIES=1` so total HTTP attempts
stay ≤ 10 per logical poll (5 tenacity + 5 on retry).

## Consequences

- The DLQ upsert lives in exactly one branch — `attempts` cannot
  double-bump.
- DLQ rows are queryable: `SELECT token_address, attempts, last_seen,
  error FROM dlq_entries ORDER BY last_seen DESC` is the human
  inspection path.
- Retiring a DLQ entry is a manual `DELETE` (or a future ops command).
  Auto-retry from the DLQ would require a separate Beat task; that's
  open work.
- Eager-mode unit tests can't drive multiple Celery retries (eager
  mode propagates `Retry` instead of re-running the task). Tests of
  the exhausted-retry branch set `WORKER_FETCH_MAX_CELERY_RETRIES=0`
  and assert the DLQ upsert directly. Documented in `tasks/lessons.md`
  Session 7.

## Status

Accepted, 2026-04 (Session 7).
