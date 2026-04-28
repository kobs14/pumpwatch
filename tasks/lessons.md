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

## Session 4 — 2026-04-24

- **Lesson:** Session 4's prompt named `growth_pct` / `stoploss_pct` / `Token.priority_tier`; the schema that Sessions 2–3 actually shipped uses `growth_threshold_pct` / `stoploss_threshold_pct` and a pre-existing `Subscription.priority` column + `Priority` enum.
  **Context:** The pre-session checklist caught the mismatch before any code was written (same failure mode Session 3 hit). The prompt assumed Token-level tier state; the schema tracks it per-Subscription because each user has their own thresholds.
  **Action:** Reused `Subscription.priority` and the existing repo methods (`list_by_priority`, `update_priority`) plus a new bulk `set_priorities`. Added a `SubscriptionTokenRow` DTO in `db/repos/subscription.py` rather than a new column on `Token`. When a session prompt and the actual schema disagree, the schema wins; flag it via AskUserQuestion rather than guessing. Recorded as Architectural Decision #12.

- **Lesson:** `asyncio.run()` inside a Celery task body cannot be called from pytest-asyncio's active event loop.
  **Context:** The Celery tasks wrap their async helpers with `asyncio.run(...)` because Celery's worker threads have no loop. In eager-mode tests, the task body runs synchronously on the pytest event-loop thread, so `asyncio.run` refuses to start a new loop.
  **Action:** Test helpers `_run_batch` and `_run_fetch_token` wrap `fetch_batch.delay().get()` in `asyncio.to_thread(...)`. Same pattern `tests/conftest.py` uses for Alembic. Production code is unchanged — the `asyncio.run` wrapper is the right shape for real Celery workers.

- **Lesson:** Eager-mode Celery ignores `apply_async(queue=...)`. Routing is a Kombu/broker concern that eager mode bypasses entirely.
  **Context:** Wrote tests hoping to assert which queue a dispatched task would land on by inspecting Celery internals; that information doesn't survive eager mode.
  **Action:** Tests monkey-patch `fetch_token.apply_async` to a recording stub and assert on the `queue` kwarg directly. Documented in `tests/celery_helpers.py`'s docstring so Session 5 doesn't repeat the attempt.

- **Lesson:** SA columns typed `Mapped[StrEnum]` but backed by `String(16)` load as plain `str`, not the enum.
  **Context:** `Subscription.priority: Mapped[Priority]` is stored as a `String(16)` column with a CHECK constraint (not a native Postgres enum). After SELECT the attribute is a `"low"` string, so `sub.priority is Priority.LOW` fails. `==` still works because `StrEnum` instances compare equal to their string value.
  **Action:** Use `sub.priority == Priority.LOW` in assertions, not `is`. Noted in a comment next to the assertion for future readers.

- **Lesson:** Sequential `server_default=func.now()` inserts in the same session can produce identical timestamps, making newest-vs-oldest ordering undefined in tests.
  **Context:** `test_fetch_batch_uses_recent_snapshots_to_drive_priority` seeded two snapshots expecting one to be newer. When both rows got the same `now()`, the order in which `recent_per_token` returned them was arbitrary, and half the time the priority came out wrong.
  **Action:** Tests set `ts=...` explicitly with a `timedelta(minutes=5)` gap. Server-default `func.now()` is fine for production writes where ordering doesn't need to be deterministic at sub-microsecond resolution.

- **Lesson:** Defensive try/except for logging must live in the outer caller, not only inside `_log_call`.
  **Context:** The test that injects a logging failure via `monkeypatch.setattr(client, "_log_call", _boom)` replaces the whole method — including its internal try/except — so the `RuntimeError` escaped and broke the data path.
  **Action:** Wrapped the `await self._log_call(...)` site in `fetch_one`'s `finally` block with its own try/except. The data path now survives *any* implementation of `_log_call`, including monkey-patched ones.

- **Lesson:** The `@celery.task(...)` decorator produces an untyped callable, triggering mypy's `untyped-decorator` rule in strict mode.
  **Context:** The first `# type: ignore[misc]` I tried was the wrong code; mypy reports the *error code* in the message but strict mode will ignore a mismatched suppression and re-flag.
  **Action:** Use `# type: ignore[untyped-decorator]` explicitly. Also added `kombu` to the existing `celery` mypy override since kombu ships no `py.typed` marker either.

## Session 5 — 2026-04-24

- **Lesson:** `redis.asyncio` pub-sub is fire-and-forget with zero replay; a subscriber that connects *after* a `PUBLISH` sees nothing. SUBSCRIBE confirmations also arrive as messages on the stream, so real tests need to drain them before asserting on the payload.
  **Context:** The real-Redis integration test originally published, then subscribed — the message was silently dropped. Same shape will bite Session 6: the alert engine must be SUBSCRIBEd and past its confirmation frame *before* the first `PUBLISH pw:price.updated` the worker emits, or the event is lost.
  **Action:** Integration test now builds the subscriber task first, waits for a SUBSCRIBE confirmation (`ready` event), and only then dispatches the Celery task. For Session 6 this means the alert engine's pub-sub connection must be established at service startup (before Beat fires anything); restarts during an active batch will lose messages for the restart window, which is acceptable because Postgres snapshot rows are the source of truth and can be replayed from there.

- **Lesson:** `redis.asyncio.Redis` pools bind to the event loop they first issue IO on, so sharing a module-level client across `asyncio.run(...)` boundaries (one per Celery task body) is a footgun.
  **Context:** My first cut cached a single async client via `get_redis()` (mirroring Session 3's `get_sessionmaker()`). That pattern is fine for long-running services with one loop, but Celery tasks wrap each invocation in a fresh `asyncio.run` — the pool from loop #1 would misbehave on loop #2.
  **Action:** Split the API. `get_redis()` / `close_redis()` stay in `cache/redis_client.py` for long-running consumers (the Session 6 alert engine). The Celery task uses a per-invocation helper `_build_worker_redis()` that creates and `aclose()`s a fresh client inside its own loop. Tests monkey-patch that factory to inject a `fakeredis.FakeAsyncRedis()` instance.

- **Lesson:** `types-redis` (external stubs) conflicts with `redis-py`'s own `py.typed` marker — the stub package wins in older versions and declares `Redis` as a generic with no `aclose()` attribute. Removing the external stubs is the right fix.
  **Context:** `mypy --strict` on the new Session 5 code reported 29 errors against the stub-supplied `Redis[Any]` generic and missing `aclose` methods that exist at runtime. Modern `redis>=5.0` ships its own `py.typed`.
  **Action:** Dropped `types-redis` from dev deps. One small remaining gap: `PubSub.aclose()` and `Redis.aclose()` are still partially untyped in the shipped stubs, so those callsites carry an inline `# type: ignore[no-untyped-call]`. Noted as a minor upstream follow-up, not a blocker.

- **Lesson:** Defensive-outer-try for best-effort writes must wrap *client construction* too, not just the RPCs.
  **Context:** My first draft of `_best_effort_publish` wrapped `set_price_cache` and `publish_price_updated` in try/excepts but built the Redis client outside the guard. A bad `REDIS_URL` or DNS blip during construction would escape and crash the data path.
  **Action:** The client is now constructed inside its own try/except; `_build_worker_redis` failures log `worker.redis.connect_failed` and return early. Same lesson as Session 4's `ApiCallLog` outer wrap, one layer out. Session 6 should assume this pattern: any Redis touch from the data path gets a two-layer guard (construct + operate).

- **Lesson:** Local `scheduler_sessionmaker` fixture defined in `tests/scheduler/conftest.py` doesn't leak into sibling packages — tests under `tests/integration/` can't see it.
  **Context:** The new real-Redis integration test needed the same truncate-bracketed sessionmaker the scheduler tests use; it failed with "fixture 'scheduler_sessionmaker' not found" until I copied the fixture into the integration test file.
  **Action:** Duplicated the small fixture (same shape as `tests/bot/conftest.py` duplicating for its own integration test in Session 3). Session 7 still owns the consolidation task — lifting these TRUNCATE-based fixtures into a single place.

- **Lesson:** Pre-existing `celerybeat-schedule` file-permission bug in the `scheduler` compose service (Beat can't write its persistent-schedule GDBM file inside `/app`) is unrelated to Session 5 but blocks the full compose smoke.
  **Context:** Bringing up `docker compose up -d scheduler worker` produced a CRITICAL Beat loop on the scheduler; the worker itself booted cleanly and processed a hand-dispatched `fetch_token` (successfully exercising the new silent-skip path against the still-CF-blocked Pump.fun endpoint).
  **Action:** Not in scope for Session 5 — file a separate hardening item for Session 7 ("pin Beat state to a writable path or switch to a DB-backed schedule"). The compose smoke coverage is still meaningful: worker boots, registers tasks, consumes from Redis, routes through the Session 5 code path, returns the new `{"fetched": False, "error": "unavailable"}` shape.

## Session 6 — 2026-04-25

- **Lesson:** Real-Redis integration tests must clean their own dedup keys at start; the `alerts_sessionmaker` TRUNCATE resets the DB but leaves Redis state. Re-run within a cooldown window and the second run dedupes against the first run's key.
  **Context:** `tests/integration/test_alerts_real_redis.py` passed on a fresh Redis but failed on the second invocation — the `pw:alert:1:tokALERT1:growth_hit` key from run #1 was still live (TTL=3600s), so run #2 saw `alerts.dedup.skip` and the dispatcher never fired.
  **Action:** Added a `scan_iter(match=f"pw:alert:*:{_ADDR}:*")` + `delete` sweep at the top of the test, before subscribing. Pattern is reusable for any future test that exercises a stateful Redis path against a non-ephemeral instance.

- **Lesson:** SQLAlchemy strict-mypy expects enum *instances*, not their `.value`, when initialising a `Mapped[StrEnum]` column.
  **Context:** Tests originally constructed `Subscription(...)` without setting `priority` and then assigned `sub.priority = Priority.HIGH.value` (a `str`). Strict mypy flagged this as `Incompatible types in assignment (expression has type "str", variable has type "SQLCoreOperations[Priority] | Priority")`. The Session 4 lesson about *reading* `Mapped[StrEnum]` columns back as plain `str` is still true — but the *write* path types check against the enum.
  **Action:** Pass `priority=Priority.HIGH` (the enum) into the constructor, not via post-construction assignment. `==` comparison against the read-back `str` still works because `StrEnum` is a `str` subclass.

- **Lesson:** `python-telegram-bot` v22's `telegram.Bot` runs alongside an `Application`-based long-poller on the same token without conflict, as long as only one process calls `getUpdates`.
  **Context:** Session 6's design question was whether the alerts service should reuse the bot service's PTB `Application` (via Redis outbox / pub-sub bridge) or build its own `telegram.Bot`. The simpler standalone-Bot path was chosen on the basis that Telegram serializes Update consumption per token — bot service owns that — but outbound HTTP is rate-limited only by the documented per-chat / global limits (we enforce both with `aiolimiter`).
  **Action:** Pattern: `bot = telegram.Bot(token=...); await bot.initialize(); await bot.send_message(...); await bot.shutdown()`. The dispatcher class holds the Bot for the lifetime of the alerts service. Wrap construction (`build_dispatcher`) and per-call RPC separately for the Session 5 two-layer defensive shape.

- **Lesson:** `User.timezone` columns store an IANA name as raw `Text`; `zoneinfo.ZoneInfo(name)` raises `ZoneInfoNotFoundError` on garbage input. Don't blow up the alert engine over a bad string the user typed into `/settings`.
  **Context:** `is_suppressed` does timezone-aware quiet-hours math via `zoneinfo`. A typo'd `"Mars/Olympus"` would otherwise propagate as an exception, and per the no-bare-except rule, propagate up the loop.
  **Action:** Fall back to UTC + log `alerts.suppression.unknown_timezone` on `ZoneInfoNotFoundError`. Same fallback for NULL `timezone`. Tests cover both `"Mars/Olympus"` and `None`. Wrap-around windows (23:00→06:00) and DST forward (Europe/Berlin 2026-03-29 02:00 local → 03:00 local) are explicit test cases — `astimezone(zone).timetz()` handles both correctly because the conversion picks up the right offset for the absolute UTC instant.

- **Lesson:** `PriceSnapshotRepository.history_for_token` returns the freshly-committed current snapshot too — by the time the alert engine receives the pub-sub event, the worker's own snapshot is in the DB. Pass it into the median+MAD detector and you're biasing against yourself.
  **Context:** `_load_volume_history` filters `r.ts < event_ts` after fetching to drop the bar that triggered the event. Cleaner than altering the repo signature for a single caller — `history_for_token(since, limit)` stays general-purpose.
  **Action:** Filter in caller, not in repo. If we ever add a third caller that needs the same exclusion, lift to a repo arg.

- **Lesson:** `record(...)` flushes but does not commit; the alert id is populated only after the surrounding `session.begin()` exits. Three small transactions per dispatch (record → mark dedup-key → mark delivered/failed) are deliberate, not a refactor target.
  **Context:** Plan called for "persist before dispatch." Each persistence step needs its own transaction because (a) we want the row visible *before* we hit the network, and (b) `mark_delivered` runs after the network call returns. Holding one transaction across the network is wrong: the row would be invisible to anyone reading `alerts_sent` while the dispatch was in flight, defeating the audit point.
  **Action:** Three short `async with sm() as s, s.begin():` blocks per dispatched alert — one for `record`, one for `mark_delivered` or `mark_failed`. `_best_effort_mark_fired` to Redis sits between them; its failure is logged but does not block dispatch.

- **Lesson:** Total tests went from 134 (Session 5 baseline) to 173 (Session 6) — a +39 net delta from 47 new alert tests minus an apparent earlier overcount. Worth re-counting at the end of Session 7 rather than trusting the running tally.

## Session 7 — 2026-04-27

- **Lesson:** Celery's eager mode does not silently re-run a task on `self.retry(...)` — the `Retry` exception propagates out of `apply()`/`delay().get()` and `EagerResult.get()` re-raises it. So a test that asserts the post-retry-exhaustion behaviour cannot rely on Celery's retry machinery to drive multiple eager iterations.
  **Context:** Session 7 worker DLQ wired `self.retry(exc=..., countdown=..., max_retries=settings.WORKER_FETCH_MAX_CELERY_RETRIES)` in the outer task body. With the production default `max_retries=1`, eager-mode tests of "fake source raises → DLQ row written" failed because the FIRST eager call raised `Retry` and propagated; the second call never ran.
  **Action:** Tests of the DLQ path `monkeypatch.setattr(get_settings(), "WORKER_FETCH_MAX_CELERY_RETRIES", 0)` so the first failure goes straight to the exhausted branch. The retry path is still exercised in production via Celery's real broker (no eager mode there). Document the constraint: **production retry behaviour is not unit-testable in eager mode.**

- **Lesson:** `prometheus_client` decides whether a Counter/Gauge uses in-process storage or `MultiProcessFileBasedMetric` storage at *Counter-construction time*, by reading `PROMETHEUS_MULTIPROC_DIR` from `os.environ`. Setting the env var inside a Celery `worker_init` signal handler is too late — by then `pumpwatch.observability.metrics` has been imported (transitively, via `pumpwatch.alerts.subscriber` etc.) and every counter handle is already in single-process mode.
  **Context:** Session 7 wired per-service `/metrics` endpoints. The Celery worker uses `--concurrency=4` (prefork pool); without multiproc mode the master process binds the port and serves zeros because all task work runs in forked children whose counter increments stay private.
  **Action:** Set `PROMETHEUS_MULTIPROC_DIR=/tmp/pumpwatch-metrics` at the **container** layer (`docker-compose.yml` worker service env), not in code. The worker container has it; the bot/scheduler/alerts containers don't. `start_metrics_server` reads the same env var on bind to choose between `MultiProcessCollector` and the default `REGISTRY`. ADR #19 captures the choice.

- **Lesson:** `redis.asyncio.Redis.llen(key)` is typed as `Awaitable[int] | int` because the same method object is used across sync and async contexts. `await client.llen(...)` is correct but mypy strict flags the `Awaitable[int] | int` shape; `int(await client.llen(...))` doesn't help.
  **Context:** Session 7's `refresh_gauges` task polls Redis queue depths. Strict mypy refused `await client.llen(queue)`.
  **Action:** `await cast(Awaitable[int], client.llen(queue))`. Don't try to coerce with `int(...)` — the cast is the cleanest fix until redis-py's stubs split sync/async.

- **Lesson:** Celery signals like `worker_init.connect` and `beat_init.connect` need `# type: ignore[untyped-decorator]` on the same line as the decorator, *not* `[no-untyped-call]` or `[misc]`. Despite signal connect being a method call (which usually triggers `no-untyped-call`), strict mypy reports it as an `untyped-decorator` issue against the decorated function.
  **Context:** Session 7 wired `@worker_init.connect` and `@beat_init.connect` to bind Prometheus per-process. Tried `[misc]` first (per Session 6 lesson on plain `@celery.task`) — wrong code. Then tried `[no-untyped-call,untyped-decorator,misc]` together — only `untyped-decorator` was actually used.
  **Action:** Use exactly `# type: ignore[untyped-decorator]` on the decorator line. Same tag celery's `@celery.task(...)` already uses.

- **Lesson:** A Postgres `dlq_entries` table satisfies "durable, queryable, no fifth Redis namespace" cleanly *if* the upsert is `pg_insert(...).on_conflict_do_update(constraint="uq_...", set_={"attempts": Table.c.attempts + 1, ...})`. Combined with a manual `self.retry` (not `autoretry_for`), the DLQ write happens in exactly one branch (`self.request.retries >= max_retries`), so `attempts` cannot accidentally double-bump.
  **Context:** Plan agent flagged the "DLQ double-write" risk where `autoretry_for` plus a manual `try/except` could both write to the DLQ on the same logical failure. Manual retry concentrates the upsert call site; `UNIQUE(token_address)` on-conflict-update absorbs concurrent failures.
  **Action:** Pattern: `bind=True` on the task; in the except branch, `if self.request.retries < max_retries: raise self.retry(...) from exc` else upsert + return the silent-skip dict. Tests verify `attempts == 1` after one logical failure and `attempts == 2` after a second logical failure of the same token.

- **Lesson:** DexScreener's `/latest/dex/tokens/{addresses}` endpoint returns a single `pairs[]` array spanning every chain/DEX where any of the requested addresses trades. To resolve back to addresses you have to filter by `chainId == "solana"` AND `baseToken.address == address` — the response order is not guaranteed and one address can produce multiple pairs (Raydium, Orca, ...). Pick the highest `liquidity.usd` per address.
  **Context:** Session 7 implemented DexScreener as the ADR #14 fallback source. Initial naive parser took the first pair; on a real response with multiple Raydium pools that would have been arbitrary.
  **Action:** `_select_pair(payload_pairs, address)` filters then `max(..., key=liquidity.usd)`. `_parse_pair` maps the chosen pair into `TokenSnapshot`. `holder_count` is `None` because DexScreener doesn't expose it (Pump.fun does, but only when the CF block lifts).

- **Lesson:** Celery's eager mode requires the `eager_celery` fixture be applied via `pytest.mark.usefixtures("eager_celery")` *or* taken as a parameter, but not both. Importing the fixture name and naming a parameter `eager_celery` triggers ruff `F811` redefinition.
  **Context:** Session 7's reconciler test needed eager mode for one test only (the rest call the async helper directly). Tried both `from tests.celery_helpers import eager_celery` AND `eager_celery: None` parameter — ruff caught the shadowing.
  **Action:** Use the decorator `@pytest.mark.usefixtures("eager_celery")` on the single test that needs it; keep the import for fixture discoverability. Same shape as the existing scheduler tests' `pytestmark = pytest.mark.usefixtures("eager_celery")`.

- **Lesson:** Container-level `USER pumpwatch` plus `WORKDIR /app` means anything Celery Beat tries to write under `/app` (notably its default `celerybeat-schedule` GDBM file) gets `[Errno 13] Permission denied`. The fix is `--schedule /tmp/celerybeat-schedule` in the scheduler command — `/tmp` is writable by every user. Beat's persistent schedule rebuilds from `celery_app.py` on every restart, so losing the file across restarts is fine for our shape.
  **Context:** Pre-existing Session 4 bug; Session 5 noted the worker came up clean while Beat crashed on startup. Session 7 picked the smallest fix.
  **Action:** Append `--schedule /tmp/celerybeat-schedule` to the scheduler container's command. No Dockerfile change. Documented in `docker-compose.yml`.

- **Lesson:** `redis-py 7.4` pubsub stubs still don't type `aclose()`. The existing `# type: ignore[no-untyped-call]` on `await pubsub.aclose()` call sites stays. `Redis.aclose()` (different from `PubSub.aclose()`) DID get typed, so a future cleanup can split the two.
  **Context:** Session 7 cleanup item said "drop the ignores once upstream stubs catch up". Removed one and ran mypy strict — still untyped.
  **Action:** Defer to a future session. When upstream catches up, grep `no-untyped-call` and re-test.

- **Lesson:** Total tests went from 173 (Session 6) to 210 (Session 7) — net +37 from 23 DexScreener client + factory tests, 3 DLQ repo tests, 2 scheduler DLQ tests, 7 reconciler tests, and 6 Prometheus / metrics tests. No flakiness in the integration suite once the `dlq_entries` truncate was added to the shared CORE_TABLES list.

## Session 8 — 2026-04-27

- **Lesson:** Fly.io's free tier was removed for new users in October 2024 — the platform is now pure pay-as-you-go. Managed Postgres starts at ~$38/mo, plus compute. PROJECT_STATUS's "Fly.io preferred" line predates the change.
  **Context:** The deploy-target question for Session 8 became "where is the lights-on cost low enough to keep a portfolio piece reachable for years?" Fly + decoupled Postgres (Neon) + Upstash Redis still works on free tiers but Upstash's 10k cmds/day limit is tight given Beat fires every 30s plus pub-sub plus cache writes.
  **Action:** Picked Hetzner CX22 (~€4.51/mo flat) + docker-compose + Caddy. Single VPS hosts everything; the existing compose file works unchanged. Predictable cost beat the free-tier story for a project that wants to stay live for years. Recipe in `docs/deployment.md`.

- **Lesson:** Pydantic's `model_validator(mode="after")` runs at every `Settings()` construction — including from `os.environ` in tests — so cross-field invariants like "`BOT_WEBHOOK_URL` is required when `BOT_MODE=webhook`" land cleanly without a custom `field_validator`.
  **Context:** Session 8 added `BOT_MODE: Literal["polling", "webhook"]` plus three webhook fields. The validator catches misconfiguration at first `get_settings()` call, which for the bot service is inside `run()` — before any HTTP server is bound. Tests verify the rejection by setting `BOT_MODE=webhook` without `BOT_WEBHOOK_URL` and asserting `pydantic.ValidationError`.
  **Action:** `from typing import Self` + `@model_validator(mode="after") def _check(...) -> Self:`. Cleaner than checking inside `bot/main.py:run()` because every Settings consumer (e.g., a test that constructs a `Settings()` without going through `get_settings()`) gets the same guarantee.

- **Lesson:** PTB v22's `Application.run_webhook(...)` accepts `secret_token=None` (the validator inside PTB allows it) — the optional Telegram-side secret is genuinely optional, so production can ship without it if the URL-path-as-secret is enough. We support both.
  **Context:** The webhook smoke test originally always set `BOT_WEBHOOK_SECRET_TOKEN`; the test for "no secret" branch needed `monkeypatch.delenv` plus an assertion that `kwargs["secret_token"] is None`.
  **Action:** Documented in `.env.example` that `BOT_WEBHOOK_SECRET_TOKEN` is optional. The deployment guide recommends generating one anyway (`secrets.token_urlsafe(32)`) — it's free defence-in-depth.

- **Lesson:** `redis-py 7.4`'s `PubSub.aclose()` is *still* untyped in the shipped stubs as of 2026-04. Removed `# type: ignore[no-untyped-call]` at one site, ran `mypy --strict src tests`, got `Call to untyped function "aclose" in typed context`, reverted.
  **Context:** Session 7 lessons.md flagged this as a future-strip candidate. Session 8's plan included an attempt; redis-py hasn't shipped a fix.
  **Action:** Left the ignores in place across all five sites (1 src, 4 tests). Re-listed on `tasks/todo.md` for a future session when stubs catch up. The strip is a one-grep-and-replace — keep it cheap to retry.

- **Lesson:** GitHub renders Mermaid `flowchart` and `sequenceDiagram` blocks natively in `README.md`. No build step needed. Tested by previewing the README on the gh-pages-equivalent (`gh repo view --web`).
  **Context:** Session 8 added three Mermaid diagrams to the README (topology, ingestion flow, alert flow). The portfolio framing depends on these rendering correctly without a workflow. They do, on GitHub at least; some other Markdown renderers (e.g., crates.io) require a plugin.
  **Action:** Diagrams live in the README with no toolchain. If we ever switch to a Markdown renderer that doesn't support Mermaid, fall back to the prerendered SVGs that the GitHub Action `mermaid-cli` can produce.

- **Lesson:** Deleting `src/pumpwatch/services/` (5 docstring-only `__init__.py` files) and `src/pumpwatch/main.py` (the Session-1 idle placeholder) required updating the `Dockerfile`'s `CMD` because it pointed at `pumpwatch.main`. Compose always overrides per-service, so the `CMD` is only the "image launched without an override" fallback. Made it fail fast (`sys.exit(2)` with a friendly message) instead of pointing at a deleted module.
  **Context:** A `CMD ["python", "-m", "pumpwatch.main"]` against a deleted module would crash inside the image, confusing whoever ran a forgotten `docker run pumpwatch:latest`. Better to fail with a sentence explaining why.
  **Action:** Pattern: `CMD ["python", "-c", "import sys; sys.stderr.write('...needs an explicit per-service command\\n'); sys.exit(2)"]`. For multi-service images consumed exclusively via compose's `command:` override, this is the right shape.

- **Lesson:** Test count after Session 8: 214 (210 from Session 7 + 4 webhook smoke tests). The cleanup didn't delete any tests; the `services/` placeholders were never imported, never tested.

## Session 9 — 2026-04-28

- **Lesson:** The session prompt assumed `actions/checkout@v4`, `astral-sh/setup-uv@v3`, and `docker/setup-buildx-action@v3`. As of April 2026 the current major tags are `@v6`, `@v8`, and `@v4` respectively. Always web-check action versions before writing the workflow — major-tag drift accumulates faster than expected.
  **Context:** Pre-session exploration caught the mismatch before any YAML was written.
  **Action:** Used the current versions. No functional difference for our use case, but pinning to stale majors would have missed security patches and cache improvements in `setup-uv`.
