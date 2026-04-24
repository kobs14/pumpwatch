# PROJECT_STATUS.md — PumpWatch

This file is the persistent state of the project across Claude Code sessions.
It is updated at the end of every session.

## Current State

**Phase:** Post-Session 4
**Last Session Completed:** Session 4 — Scheduler & Batch Builder
**Next Session:** Session 5 — Worker Pool & Price Ingestion
**Last Updated:** 2026-04-24

## Session Plan

| #  | Title                                           | Status  | Notes |
|----|-------------------------------------------------|---------|-------|
| 0  | Bootstrap docs (CLAUDE.md, this file, etc.)     | ✅ done | Created by user before any code session |
| 1  | Project Scaffold & Infrastructure               | ✅ done | Docker Compose, Postgres, Redis, package skeleton, tooling |
| 2  | Data Layer & Pump.fun Client                    | ✅ done | 6 models, initial migration, 6 repos, PumpFunClient + Fake, full test suite |
| 3  | Telegram Bot, Commands, User Onboarding         | ✅ done | PTB v22 long-polling bot, /start /help /add /list /stop /settings, lazy-init db/session, user-settings migration, 37 new tests |
| 4  | Scheduler & Batch Builder                       | ✅ done | Celery app + Beat, pure priority/batch modules, per-sub tier persistence, ApiCallLog wired into PumpFunClient, scheduler + worker compose services, 37 new tests |
| 5  | Worker Pool & Price Ingestion                   | ⬜      | Celery workers, Redis hot cache, price.updated events |
| 6  | Alert Engine: Thresholds + Volume Spike         | ⬜      | Median+MAD detector, dedup, Telegram dispatch |
| 7  | Hardening: Observability, Error Handling, Scale | ⬜      | Prometheus, Grafana, dead-letter queue, load test |
| 8  | Documentation, README, Deployment Guide         | ⬜      | Architecture diagrams, ADRs, deploy guide |

## Files Created So Far

Bootstrap (pre-Session 1):
- `CLAUDE.md` — project conventions and constraints
- `PROJECT_STATUS.md` — this file
- `tasks/todo.md` — current session scratchpad
- `tasks/lessons.md` — accumulated lessons across sessions
- `.gitignore`
- `README.md` — stub, filled in by Session 1

Session 1:
- `pyproject.toml` — project metadata, dependencies, tool configs
- `uv.lock` — locked dependency versions
- `.pre-commit-config.yaml` — ruff + mypy hooks
- `.env.example` — environment variable template
- `docker-compose.yml` — Postgres, Redis, app services
- `Dockerfile` — multi-stage build with uv
- `alembic.ini` — Alembic configuration
- `alembic/env.py` — async migration environment
- `alembic/script.py.mako` — migration template
- `alembic/versions/.gitkeep` — empty versions directory
- `src/pumpwatch/__init__.py` — package version
- `src/pumpwatch/config.py` — pydantic-settings configuration
- `src/pumpwatch/logging.py` — structlog setup
- `src/pumpwatch/main.py` — async entrypoint
- `src/pumpwatch/db/__init__.py` — database package
- `src/pumpwatch/db/base.py` — SQLAlchemy DeclarativeBase
- `src/pumpwatch/db/session.py` — async engine and session factory
- `src/pumpwatch/services/__init__.py` — services package
- `src/pumpwatch/services/bot/__init__.py` — bot service placeholder
- `src/pumpwatch/services/scheduler/__init__.py` — scheduler service placeholder
- `src/pumpwatch/services/worker/__init__.py` — worker service placeholder
- `src/pumpwatch/services/alerts/__init__.py` — alerts service placeholder
- `tests/__init__.py` — tests package
- `tests/conftest.py` — shared test fixtures
- `tests/test_smoke.py` — smoke test

Session 2:
- `alembic/versions/f66a7128cab1_initial_schema.py` — creates all six tables
- `src/pumpwatch/db/enums.py` — `Priority`, `SubscriptionStatus`, `AlertType` StrEnums
- `src/pumpwatch/db/models/{__init__,user,token,subscription,price_snapshot,alert_sent,api_call_log}.py` — six SA 2.x ORM models
- `src/pumpwatch/db/repos/{__init__,user,token,subscription,price_snapshot,alert,api_call_log}.py` — six repository classes
- `src/pumpwatch/sources/{__init__,base,exceptions,fake,pumpfun}.py` — `PriceDataSource` Protocol, `TokenSnapshot` dataclass, `FakePriceDataSource`, `PumpFunClient`
- `tests/db/__init__.py`, `tests/db/test_{user,token,subscription,price_snapshot,alert,api_call_log}_repo.py` — 29 repo tests against a real `pumpwatch_test` DB
- `tests/sources/__init__.py`, `tests/sources/test_fake.py`, `tests/sources/test_pumpfun_client.py` — 19 source tests (fake + aioresponses-mocked client)
- `tests/integration/__init__.py`, `tests/integration/test_fake_source_to_db.py` — end-to-end contract test

Session 3:
- `alembic/versions/5050d79ff7ea_add_user_bot_settings.py` — adds `chat_id` (with backfill), `alerts_muted`, `default_growth_pct`, `default_stoploss_pct` to `users`
- `src/pumpwatch/bot/__init__.py`, `src/pumpwatch/bot/app.py`, `src/pumpwatch/bot/main.py`, `src/pumpwatch/bot/deps.py` — Application factory, entry point, bot_data sessionmaker helper
- `src/pumpwatch/bot/validators.py` — `is_valid_solana_mint` (base58, length 32–44)
- `src/pumpwatch/bot/formatting.py` — MarkdownV2 escape + subscription-row renderer
- `src/pumpwatch/bot/keyboards.py` — `/settings` inline keyboard + callback constants
- `src/pumpwatch/bot/handlers/{__init__,start,add,list_cmd,stop,settings,errors}.py` — all six command handlers plus the global error handler
- `tests/bot/__init__.py`, `tests/bot/conftest.py`, `tests/bot/harness.py` — fake Update/Context stubs and a sessionmaker fixture that truncates between tests
- `tests/bot/test_{validators,handlers_start,handlers_add,handlers_settings}.py` — 29 handler unit tests
- `tests/integration/test_bot_flow.py` — end-to-end `/start → /add → /list → /stop → /list` flow

Modified:
- `pyproject.toml` (+aiohttp, tenacity, aiolimiter, python-dateutil, aioresponses, types-python-dateutil)
- `uv.lock` regenerated
- `src/pumpwatch/config.py` (+5 Settings fields)
- `.env.example` (+5 new documented settings)
- `alembic/env.py` (imports `pumpwatch.db.models` for metadata registration)
- `tests/conftest.py` (rewritten with real test DB fixtures and SAVEPOINT rollback)

Session 3 modified:
- `pyproject.toml` (+python-telegram-bot[job-queue]>=21; +asyncpg mypy override)
- `uv.lock` regenerated
- `src/pumpwatch/db/session.py` — lazy-init `get_engine`/`get_sessionmaker`/`dispose_engine` (replaces eager module-level engine)
- `src/pumpwatch/db/models/user.py` — adds `chat_id`, `alerts_muted`, `default_growth_pct`, `default_stoploss_pct`
- `src/pumpwatch/db/repos/user.py` — `upsert_from_telegram` accepts optional `chat_id`
- `src/pumpwatch/db/repos/subscription.py` — `create_or_update`, `stop_by_user_and_token`, `get_by_user_and_token`
- `docker-compose.yml` (+ `bot` service)
- `tests/conftest.py` — calls `_reset_for_tests()` to drop any cached session singleton

Session 4:
- `src/pumpwatch/celery_app.py` — Celery app + Beat schedule + queue declarations
- `src/pumpwatch/scheduler/__init__.py`, `priority.py`, `batch.py`, `tasks.py`, `main.py`
- `tests/celery_helpers.py` — `eager_celery` fixture
- `tests/scheduler/__init__.py`, `conftest.py`, `test_priority.py`, `test_batch.py`, `test_tasks.py`
- `tests/integration/test_scheduler_real_redis.py` — gated real-broker smoke test

Session 4 modified:
- `pyproject.toml` (+celery>=5.3,<6; +redis>=5.0; +mypy override for celery/kombu)
- `uv.lock` regenerated
- `src/pumpwatch/config.py` (+`SCHEDULER_FETCH_INTERVAL_SECONDS`, `PUMPFUN_LOG_CALLS`)
- `.env.example` (+2 new settings)
- `src/pumpwatch/sources/pumpfun.py` — `PumpFunClient.__init__` now accepts `sessionmaker` + `log_calls`; new `_log_call` helper writes one `api_call_log` row per logical call
- `src/pumpwatch/sources/fake.py` — `FakePriceDataSource` gained `__aenter__`/`__aexit__` so it's interchangeable with the real client in `async with`
- `src/pumpwatch/db/repos/subscription.py` — new `SubscriptionTokenRow` DTO + `list_active_with_tokens` + bulk `set_priorities`
- `src/pumpwatch/db/repos/price_snapshot.py` — new `recent_per_token(addresses, limit, window)`
- `docker-compose.yml` (+`scheduler`, +`worker` services)
- `tests/sources/test_pumpfun_client.py` (+5 logging-wired tests)

## Risks Realized (Session 2)

- **Pump.fun API is Cloudflare-blocked (HTTP 530) as of 2026-04-23.** Both live smoke-test addresses returned a Cloudflare "Origin Down" interstitial. The client's retry + `PumpFunUnavailableError` path is exercised correctly; mocked unit tests prove the happy path. `PriceDataSource` is the abstraction seam — Session 5 will either bypass the block (browser-like UA, session cookie) or swap to DexScreener. See `tasks/lessons.md` for the full note.

## Architectural Decisions Locked

These were decided during design and should not be revisited without an ADR:

1. **Five-service architecture:** bot, scheduler, workers, alerts, plus
   Postgres + Redis. Not a monolith.
2. **Postgres as source of truth, Redis as cache/broker/pub-sub only.**
3. **Scheduler is single-instance; workers are horizontally scalable.**
4. **All external data sources sit behind a `PriceDataSource` interface.**
   Pump.fun is the first implementation; DexScreener is the documented
   fallback if Pump.fun goes dark.
5. **Volume-spike detection uses median + MAD (not mean + stddev)** because
   crypto volume distributions have fat tails and outliers.
6. **Priority tiers are computed, not assigned:** based on distance to
   threshold, recent volatility, and recent volume.
7. **Telegram has its own outbound rate limiter** (per-chat token bucket)
   independent of the Pump.fun rate limiter.
8. **Bot uses long-polling, not webhook.** Webhook deployment is a Session 8
   concern. `ConversationHandler` state is in-memory per-process, which is why
   the bot is a single-instance service; Redis-backed persistence is deferred.
9. **`/add` validates mint format only.** On-chain existence and metadata
   (`symbol`, `name`) are hydrated by the data-source layer when the
   scheduler polls — the bot never talks to Pump.fun directly.
10. **Alert cooldown is not a user setting.** Dedup/cooldown is owned by the
    Session 6 alert engine via Redis TTLs; no `default_cooldown_minutes`
    column exists on `User` by design.
11. **Beat-driven `fetch_batch` is the single scheduling moving part.** A
    long-running asyncio scheduler loop alongside Beat was rejected as an
    unnecessary second moving part at current scale. Beat fires one task,
    the task rebuilds the batch and dispatches.
12. **Priority lives on `Subscription.priority`, not `Token`.** The schema
    already had a `Priority` enum and a per-subscription priority column.
    Session 4 reuses both: each sub gets a tier computed from its own
    thresholds; the batch builder picks `max(priority)` across subs per
    token to drive dispatch routing. A token-level `priority_tier` column
    was considered and rejected to avoid duplicating state.

## Known Risks / Watch Items

- **Pump.fun API stability:** unofficial, has been rate-limited and blocked
  in the past. Mitigation: `PriceDataSource` interface from day one.
- **Telegram rate limits:** ~30 msg/sec global, 1/sec per chat. Must be
  enforced in alert engine (Session 6).
- **High-priority polling load:** 30 tokens × ~3s cadence = up to 10
  req/sec sustained. Must respect Pump.fun limits (Session 5).
- **Postgres `price_snapshots` table growth:** plan for daily partitioning
  in Session 2 schema.

## Deferred / Out of Scope (For Now)

- Web dashboard (decided: Telegram-only)
- LLM `/explain` command (mentioned as possible Session 9, not committed)
- Public/shared watchlists (multi-user is per-user only)
- Predictive ML models (volume-spike detection only)
- Trade execution (read-only project, by policy)

## Deployment Target

To be decided in Session 8. Candidates: Fly.io (preferred for managed
Postgres + simple Docker deploys) or Railway. Local dev is always Docker
Compose.
