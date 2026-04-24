# Lessons Learned

This file accumulates surprises, gotchas, and design lessons across all
sessions. Append-only. Each entry should help a future session avoid a
mistake or make a better choice.

## Format

```
## Session N — YYYY-MM-DD
- **Lesson:** One-sentence summary of what was learned.
  **Context:** What we were doing when it came up.
  **Action:** What we changed (or should change) as a result.
```

---

## Session 1 — 2026-04-22

- **Lesson:** uv resolves the latest Python (3.14) by default when `requires-python = ">=3.12"` is set.
  **Context:** `uv lock` and `uv sync` picked Python 3.14 instead of 3.12.
  **Action:** Use `--python 3.12` flag for local commands and `UV_PYTHON_PREFERENCE=only-system` in the Dockerfile to use the base image's Python.

- **Lesson:** The hatchling build backend module is `hatchling.build`, not `hatchling.backends`.
  **Context:** `uv sync` failed with `ModuleNotFoundError: No module named 'hatchling.backends'`.
  **Action:** Fixed `build-backend` in pyproject.toml to `"hatchling.build"`.

- **Lesson:** `tool.uv.dev-dependencies` is deprecated in favor of `dependency-groups.dev`.
  **Context:** `uv lock` emitted a deprecation warning.
  **Action:** Switched to `[dependency-groups]` section in pyproject.toml.

- **Lesson:** ruff's top-level `select` is deprecated — use `[tool.ruff.lint]` section.
  **Context:** `ruff check` warned about deprecated config.
  **Action:** Moved `select` under `[tool.ruff.lint]`.

- **Lesson:** Bootstrap files (`todo.md`, `lessons.md`) were created in the project root instead of `tasks/` directory; `.gitignore` was missing.
  **Context:** Session prompt expected them at `tasks/todo.md` etc.
  **Action:** Created `tasks/` directory and moved files. Created `.gitignore`.

## Session 2 — 2026-04-23

- **Lesson:** Pump.fun's frontend API is blocked at Cloudflare (HTTP 530 "Origin Down") for unauthenticated external clients as of 2026-04-23.
  **Context:** The end-of-session live smoke test against two well-known Solana mints (Bonk, RAY) both returned 530 with a Cloudflare interstitial HTML page. Tenacity correctly retried, then the client raised `PumpFunUnavailableError` as designed.
  **Action:** Session 2 ships the client contract, retries, rate limiter, and parser — all proven via `aioresponses` mocks. The `PriceDataSource` abstraction means Session 5 can swap to DexScreener (or add a browser-like User-Agent / bypass) without touching repos. Do **not** invent alternate endpoints in a future session without first checking whether the upstream block has lifted.

- **Lesson:** Alembic autogenerate correctly captured every `CheckConstraint`, `UniqueConstraint`, compound `Index`, and FK `ondelete` on first pass — no hand-editing required beyond adding a planning comment and wrapping one long CHECK constraint line.
  **Context:** Contrary to the session prompt's warning, autogenerate did not miss CHECKs/indexes in SA 2.x + alembic 1.13 against a Postgres 16 target. Server-side defaults on columns were only picked up after I explicitly set `server_default=...` on the `mapped_column(...)` — a Python `default=...` alone is not autogen-visible.
  **Action:** For every future column that needs a non-null default, set **both** `default=` (ORM-side) and `server_default=` (DDL-side). Do not rely on autogenerate to infer server defaults from Python defaults.

- **Lesson:** `asyncio.run()` inside `alembic/env.py` conflicts with a pytest-asyncio event loop if you call `alembic.command.upgrade()` directly from an async fixture.
  **Context:** The `_test_database` fixture failed with `RuntimeError: asyncio.run() cannot be called from a running event loop` when running migrations.
  **Action:** Wrap the alembic call in `await asyncio.to_thread(_run_migrations, url)` so alembic spawns its own loop in a worker thread. Cleaner than refactoring `env.py`, which is shared with the CLI path.

- **Lesson:** `AsyncSession.expire()` and `.expire_all()` are **sync** methods; `.refresh()` is async.
  **Context:** Two repo tests failed with `TypeError: object NoneType can't be used in 'await' expression` after I naively awaited `.expire()`. Pure ORM-state operations never touch the DB, so they don't need to be async. `.refresh()` reloads from the DB, so it does.
  **Action:** Use `await session.refresh(obj)` after an UPDATE statement when you need to see the new values through the ORM. Never `await session.expire(...)`.

- **Lesson:** `ApiCallLogRepository` is implemented in Session 2 but **not wired into `PumpFunClient`**.
  **Context:** The session prompt mentions logging API calls "via the repository (you'll need to pass a session factory in — design for this)". Wiring it in this session would require inventing a session-factory hand-off before the scheduler/worker (Sessions 4–5) owns the session lifecycle.
  **Action:** The repo exists and is covered by tests; Session 4/5 will wire it up when the scheduler owns an `async_sessionmaker` callable and can pass it into the client.

- **Lesson:** Test conftest must set required env vars via `os.environ.setdefault` **before** any pumpwatch import, and defensively call `get_settings.cache_clear()` afterwards.
  **Context:** `pumpwatch.db.session` creates the engine eagerly at import time via `_settings = get_settings()`. If conftest imports pumpwatch before setting `DATABASE_URL`, the module-level engine binds to the wrong DB. This is known-technical-debt in `session.py` (Session 1 carry-over) — Session 2 worked around it rather than refactoring.
  **Action:** Keep `tests/__init__.py` empty. The top of `tests/conftest.py` sets envs, imports pumpwatch second, and constructs its own test engine (`NullPool`) that tests use — the module-level engine is never exercised in tests.

## Session 3 — 2026-04-24

- **Lesson:** `python-telegram-bot` v22 was released and `>=21` resolved to 22.7, not 21.x.
  **Context:** `pyproject.toml` declared `python-telegram-bot[job-queue]>=21`; `uv lock` pulled 22.7. The v22 API surface we use (`Application`, `ApplicationBuilder`, `ConversationHandler`, `CommandHandler`, `CallbackQueryHandler`) is backward-compatible, but v22's `CallbackQuery.message` is typed as `MaybeInaccessibleMessage` (a union of `Message` and `InaccessibleMessage`), so `query.message.reply_text(...)` needs an `isinstance(query.message, Message)` narrowing to satisfy strict mypy.
  **Action:** Pin as `>=21,<23` later if 22→23 breaks anything. For now the narrowing pattern is documented in `src/pumpwatch/bot/handlers/settings.py`.

- **Lesson:** The Session 3 prompt's schema assumptions were partially stale vs what Session 2 actually shipped — caught before any code was written.
  **Context:** The prompt referenced `Subscription.threshold_pct` / `.token_id` / `.active`, but Session 2 built `growth_threshold_pct` + `stoploss_threshold_pct`, `token_address` (string FK), and a `SubscriptionStatus` enum. The prompt also asked for `default_cooldown_minutes` on `User`, which overlaps with Session 6's Redis-based dedup.
  **Action:** Ran the pre-plan AskUserQuestion round (growth+stoploss both required, User gets paired defaults, cooldown deferred to Session 6, `alerts_muted` added alongside existing `quiet_hours_*`). Architectural Decision 8–10 in `PROJECT_STATUS.md` now record those outcomes. When a session prompt conflicts with a prior session's schema, stop and clarify before building — the five-minute round prevents a wrong-direction implementation.

- **Lesson:** Handler unit tests don't need the full python-telegram-bot test harness — a small hand-rolled `FakeUpdate`/`FakeContext` harness (`tests/bot/harness.py`) suffices.
  **Context:** Handlers only read a handful of attributes: `update.effective_user`, `update.effective_chat`, `update.effective_message`, `context.args`, `context.user_data`, and `context.application.bot_data`. Call sites `cast(Update, fake)` / `cast(ContextTypes.DEFAULT_TYPE, fake)` to satisfy strict mypy without forcing tests to instantiate real PTB objects.
  **Action:** Kept the harness lightweight; the fake `Message.reply_text` is an `AsyncMock` so assertions can inspect `.replies` without touching network or Bot API code.

- **Lesson:** Bot-test isolation can't use the Session 2 SAVEPOINT-rollback pattern — handlers open their own sessions and commit.
  **Context:** The Session 2 `db_session` fixture wraps each test in an outer transaction that rolls back on teardown. Bot handlers use a sessionmaker to open fresh sessions, so they bypass the SAVEPOINT.
  **Action:** Added `tests/bot/conftest.py` with a `bot_sessionmaker` fixture that `TRUNCATE users, tokens, price_snapshots RESTART IDENTITY CASCADE` in teardown. Subscriptions + alerts_sent cascade. This is heavier than SAVEPOINT but honest about what the handler code actually does.

- **Lesson:** `_test_database` fixture gives the test suite a fresh DB, but bot tests need an explicit TRUNCATE between them because the DB is session-scoped.
  **Context:** The integration-test file `tests/integration/test_bot_flow.py` re-declared its own `bot_sessionmaker` fixture (rather than importing from `tests/bot/conftest.py`) because the truncation needed to happen *before* yield, not after — the integration test has one combined `test_full_flow` that runs start-to-finish and needs a clean DB at entry.
  **Action:** Two similar fixtures exist (`tests/bot/conftest.py` truncates post-yield, `tests/integration/test_bot_flow.py` truncates pre-yield). Not DRY, but fit-for-purpose. Consolidating is a Session 7 hardening task.

- **Lesson:** The `chat_id` backfill in the Alembic migration must be hand-written — autogenerate produces a `NOT NULL` `add_column` with no default, which would fail on any table with rows.
  **Context:** Adding `chat_id: BigInteger NOT NULL` to `users` triggered autogenerate to emit a single `op.add_column(..., nullable=False)` statement. On an empty dev DB it succeeded; on a populated prod DB it would reject.
  **Action:** Rewrote the migration to (1) add nullable, (2) `UPDATE users SET chat_id = telegram_id`, (3) `ALTER COLUMN chat_id SET NOT NULL`. `telegram_id` is a safe backfill because private-chat rows have `chat_id == telegram_id`. Pattern is worth repeating for any future NOT-NULL-with-no-default column addition.

- **Lesson:** PTB v22's `Application.run_polling()` owns the event loop — use it from a sync entry point, not from inside `asyncio.run()`.
  **Context:** The plan file initially specified `async def run()` + `asyncio.run(run())`, but PTB's `run_polling()` internally calls `asyncio.run`, which conflicts with an already-running loop.
  **Action:** `src/pumpwatch/bot/main.py` has a sync `def run()` that calls `application.run_polling()` directly. Async startup/shutdown hooks (`_post_init`, `_post_shutdown`) handle `dispose_engine()` cleanly on SIGTERM.

- **Lesson:** Strict mypy on `tests/` requires an override for `asyncpg` (no stubs / no `py.typed`).
  **Context:** The pre-existing `tests/conftest.py` imports `asyncpg` for the test-DB create/drop admin connection. `mypy --strict src tests` complained about missing stubs.
  **Action:** Added a `[[tool.mypy.overrides]]` stanza in `pyproject.toml` for `asyncpg` / `asyncpg.*`. Kept `files = ["src"]` default so local `mypy` invocations still work; the verification checklist explicitly passes `src tests`.
