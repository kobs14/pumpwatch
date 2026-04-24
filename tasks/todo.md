# Current Session TODO

This file is session-scoped. It is reset at the end of every session with
the next session's name and any carry-over items.

## Active: Session 4 — Scheduler & Batch Builder

See the Session 4 prompt (provided by the user at session start) for full
scoped steps.

### Carry-over notes from Session 3

- `ApiCallLogRepository` is still not wired into `PumpFunClient`. Session 4
  must pass an `async_sessionmaker` into the client (or a session factory
  callback) so the scheduler/worker can record every external call.
- The bot uses a **lazy-init** `get_engine()` / `get_sessionmaker()` in
  `src/pumpwatch/db/session.py`. Scheduler/worker/alerts services should use
  the same helpers — do not reintroduce an eager module-level engine.
- `User` now carries `chat_id`, `alerts_muted`, `default_growth_pct`,
  `default_stoploss_pct`. Alert dispatch (Session 6) reads `chat_id` for
  delivery and must skip users with `alerts_muted=True`.
- `Subscription.status` is a `StrEnum` (`ACTIVE` / `STOPPED` / `ARCHIVED`) —
  the scheduler must filter to `ACTIVE` when computing the poll set.
- The bot uses **long-polling**; the scheduler is independent of the bot
  process. Both can run concurrently without coordination because Postgres
  is the shared source of truth.
- `/settings` does not yet support per-subscription editing (only global
  defaults). Deferred to a future session; left here so it isn't forgotten.
- `ConversationHandler` state is in-process. If/when the bot goes
  multi-instance, add Redis-backed `PicklePersistence` (or equivalent) —
  `user_data` contents must be picklable if we do.
- Compose `bot` service overrides `DATABASE_URL` / `REDIS_URL` via
  `environment:` because the root `.env` uses `localhost` for local dev.
  Session 4's scheduler/worker services should do the same, or Session 7
  should unify the env story.
- PTB v22.7 resolved against our `>=21` spec. If v23 ever breaks handlers,
  pin `>=21,<23` in `pyproject.toml`.

### Future (not Session 4 scope)

- Per-subscription editing in `/settings` (inline keyboards per token).
- Redis-backed `ConversationHandler` persistence when multi-instance.
- Remove the stale `src/pumpwatch/services/bot/` placeholder (Session 1
  left an empty `__init__.py` that is now superseded by `src/pumpwatch/bot/`).
- Unify the `tests/bot/conftest.py` and `tests/integration/test_bot_flow.py`
  truncate fixtures.
