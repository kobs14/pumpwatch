# PROJECT_STATUS.md — PumpWatch

This file is the persistent state of the project across Claude Code sessions.
It is updated at the end of every session.

## Current State

**Phase:** Post-Session 7
**Last Session Completed:** Session 7 — Hardening: Observability, Error Handling, Scale
**Next Session:** Session 8 — Documentation, README, Deployment Guide
**Last Updated:** 2026-04-27

## Session Plan

| #  | Title                                           | Status  | Notes |
|----|-------------------------------------------------|---------|-------|
| 0  | Bootstrap docs (CLAUDE.md, this file, etc.)     | ✅ done | Created by user before any code session |
| 1  | Project Scaffold & Infrastructure               | ✅ done | Docker Compose, Postgres, Redis, package skeleton, tooling |
| 2  | Data Layer & Pump.fun Client                    | ✅ done | 6 models, initial migration, 6 repos, PumpFunClient + Fake, full test suite |
| 3  | Telegram Bot, Commands, User Onboarding         | ✅ done | PTB v22 long-polling bot, /start /help /add /list /stop /settings, lazy-init db/session, user-settings migration, 37 new tests |
| 4  | Scheduler & Batch Builder                       | ✅ done | Celery app + Beat, pure priority/batch modules, per-sub tier persistence, ApiCallLog wired into PumpFunClient, scheduler + worker compose services, 37 new tests |
| 5  | Worker Pool & Price Ingestion                   | ✅ done | fetch_token writes PriceSnapshot + pw:price:<addr> hot cache (tier-varying TTL) + pw:price.updated pub-sub; PRICE_SOURCE setting + factory; silent-skip on PumpFunUnavailableError; best-effort cache/pub-sub; fakeredis unit + real-Redis integration tests (39 new) |
| 6  | Alert Engine: Thresholds + Volume Spike         | ✅ done | `alerts` service: subscribe to `pw:price.updated`, threshold + median+MAD detectors, Redis-TTL dedup under `pw:alert:*`, suppression (mute/PAUSED/quiet-hours w/ tz + DST), persist-then-dispatch via standalone `telegram.Bot`, 47 new tests |
| 7  | Hardening: Observability, Error Handling, Scale | ✅ done | DexScreener client, Postgres `dlq_entries` + Celery retry/backoff, alert reconciliation Beat sweep, per-service Prometheus `/metrics` + Grafana profile, `celerybeat-schedule` permission fix, fixture consolidation. 210 tests. |
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

Session 5:
- `src/pumpwatch/cache/__init__.py`, `src/pumpwatch/cache/redis_client.py` — lazy `get_redis()`/`close_redis()`, `pw:price:<addr>` + `pw:price.updated` constants, `set_price_cache`, `publish_price_updated`, `ttl_for_tier`
- `src/pumpwatch/sources/factory.py` — `build_source(sessionmaker)` keyed on `Settings.PRICE_SOURCE`
- `tests/cache/__init__.py`, `tests/cache/test_redis_client.py` — fakeredis unit tests for cache + pub-sub
- `tests/sources/test_factory.py` — source factory tests
- `tests/integration/test_worker_price_ingestion_real_redis.py` — gated real-Redis end-to-end

Session 6:
- `src/pumpwatch/alerts/__init__.py`, `detectors.py`, `dedup.py`, `suppression.py`, `dispatcher.py`, `subscriber.py`, `main.py` — pure detectors (threshold + median+MAD), Redis-TTL dedup, mute/PAUSED/quiet-hours suppression (zoneinfo, wrap-around, DST), standalone `telegram.Bot` dispatcher with per-chat + global aiolimiters and one inline retry, pub-sub subscriber loop, sync entry point with SIGTERM/SIGINT handling
- `tests/alerts/__init__.py`, `tests/alerts/conftest.py`, `test_detectors.py`, `test_suppression.py`, `test_dedup.py`, `test_dispatcher.py`, `test_subscriber.py` — 47 tests: pure detector edge cases, suppression incl. DST forward + Asia/Tokyo + bogus tz fallback, fakeredis-backed dedup, AsyncMock-backed dispatcher (retry + final raise), full per-event flow with seeded DB rows
- `tests/integration/test_alerts_real_redis.py` — gated end-to-end (subscribe → publish → drain → persist → dispatch) against a real Redis

Session 6 modified:
- `src/pumpwatch/cache/redis_client.py` (+`ALERT_DEDUP_PREFIX`, +`alert_dedup_key(...)`; docstring lists alert namespace under the existing cache role)
- `src/pumpwatch/config.py` (+6 settings: `VOLUME_SPIKE_WINDOW_SECONDS`, `VOLUME_SPIKE_MIN_SAMPLES`, `ALERT_DEDUP_HIT_SECONDS`, `ALERT_DEDUP_WARNING_SECONDS`, `ALERT_DEDUP_SPIKE_SECONDS`, `ALERT_DISPATCH_RETRY_DELAY_SECONDS`)
- `.env.example` (+6 documented settings)
- `docker-compose.yml` (+`alerts` service: single replica, `restart: unless-stopped`, env-overridden `DATABASE_URL`/`REDIS_URL`)

Session 7:
- `alembic/versions/3868863a7a4d_add_dlq_entries_and_alerts_sent_.py` — creates `dlq_entries` (with `UNIQUE(token_address)`); adds `alerts_sent.dispatch_attempts` (default 1) for the reconciler attempt cap
- `src/pumpwatch/sources/dexscreener.py` — `DexScreenerClient` (Protocol-compatible: `fetch_one` / `fetch_batch` against `/latest/dex/tokens/{a,b,c}`, tenacity retry, api_call_log writes, highest-liquidity Solana pair selection)
- `src/pumpwatch/db/models/dlq_entry.py`, `src/pumpwatch/db/repos/dlq.py` — `DlqEntry` model + `DlqRepository.upsert/count` (pg-insert on-conflict bumps `attempts` + `last_seen`)
- `src/pumpwatch/alerts/reconciler.py`, `src/pumpwatch/alerts/tasks.py` — Beat-driven sweep: re-checks suppression, rehydrates `AlertCandidate` from `payload_json`, re-dispatches via the same `TelegramDispatcher`, increments `dispatch_attempts`. Skips suppressed rows (ADR #17).
- `src/pumpwatch/observability/{__init__,metrics,tasks}.py` — centralised Prometheus handles (`pumpwatch_alerts_fired_total{type}`, `*_suppressed_total{reason}`, `*_delivery_failed_total`, `pumpwatch_source_calls_total{source,status}`, `pumpwatch_celery_queue_depth{queue}`, `pumpwatch_dlq_size`); idempotent `start_metrics_server` with multiproc support; Beat-scheduled `refresh_gauges` task polls Postgres + Redis
- `ops/prometheus/prometheus.yml`, `ops/grafana/provisioning/{datasources,dashboards}/*.yml`, `ops/grafana/dashboards/pumpwatch.json` — provisioning files for the optional observability profile
- `tests/_helpers/{__init__,sessionmaker}.py` — shared `truncating_sessionmaker` helper (CORE_TABLES / BOT_TABLES presets); replaces five duplicated truncate-style fixtures
- `tests/sources/test_dexscreener_client.py`, `tests/db/test_dlq_repo.py`, `tests/alerts/test_reconciler.py`, `tests/observability/test_metrics.py` — 37 new tests (210 total, +37 from Session 6 baseline)

Session 7 modified:
- `pyproject.toml` (+prometheus-client>=0.20)
- `uv.lock` regenerated
- `src/pumpwatch/config.py` (+`PRICE_SOURCE` accepts `dexscreener`; +DexScreener block; +DLQ retry caps; +reconciler cadence; +metrics ports + multiproc dir)
- `.env.example` (+13 documented settings)
- `src/pumpwatch/sources/exceptions.py` — adds shared `SourceError` / `SourceUnavailableError` parents; `PumpFunUnavailableError` and new `DexScreenerUnavailableError` both inherit from `SourceUnavailableError` so the worker catches one symbol
- `src/pumpwatch/sources/factory.py` — adds `dexscreener` branch (one elif)
- `src/pumpwatch/sources/pumpfun.py` — `SOURCE_CALLS{source,status}` counter increment in the `finally` next to `api_call_log`
- `src/pumpwatch/scheduler/tasks.py` — outer Celery task body wraps the inner async helper with `self.retry` (capped at `WORKER_FETCH_MAX_CELERY_RETRIES=1`) and writes to `dlq_entries` on retry exhaustion; preserves the silent-skip return contract
- `src/pumpwatch/db/models/{__init__,alert_sent}.py` — registers `DlqEntry`; `AlertSent.dispatch_attempts` column
- `src/pumpwatch/db/repos/alert.py` — adds `list_recently_failed(window_seconds, max_attempts)` and `mark_redispatched(alert_id, *, success, error)`
- `src/pumpwatch/celery_app.py` — adds `worker_init` + `beat_init` signal handlers that call `start_metrics_server`; adds Beat entries for `reconcile-failed-alerts` and `refresh-prometheus-gauges`; extends `autodiscover_tasks` to alerts + observability packages
- `src/pumpwatch/alerts/subscriber.py` — `ALERTS_FIRED.labels(type=...).inc()` after persist; `ALERTS_SUPPRESSED.labels(reason=...).inc()` and `ALERTS_DELIVERY_FAILED.inc()` on the matching branches
- `src/pumpwatch/{bot,alerts}/main.py` — call `start_metrics_server(...)` after settings load
- `docker-compose.yml` — scheduler command now passes `--schedule /tmp/celerybeat-schedule` (writable by the non-root pumpwatch user); worker service env adds `PROMETHEUS_MULTIPROC_DIR=/tmp/pumpwatch-metrics`; new `prometheus` + `grafana` services behind `profiles: [observability]`, host-port-bound (9090, 3000)
- `tests/{bot,scheduler,alerts}/conftest.py` and `tests/integration/{test_bot_flow,test_worker_price_ingestion_real_redis,test_alerts_real_redis}.py` — switched to the shared `truncating_sessionmaker` helper

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
13. **Redis roles.** Single Redis instance, four roles: Celery broker,
    Celery result backend, hot cache (`pw:price:<addr>` flat JSON with
    tier-varying TTL — HIGH=60s, MEDIUM=300s, LOW=900s), pub-sub
    (`pw:price.updated` single global channel; payload includes
    `{address, ts, source, tier, cache_key}` and subscribers filter
    in-process). No further Redis roles without an ADR.
14. **Fallback-source policy.** A `build_source(sessionmaker)` factory
    gates on `Settings.PRICE_SOURCE` (values: `pumpfun`, `fake`). A real
    DexScreener `PriceDataSource` implementation is deferred to Session 7
    hardening; the factory seam is ready for a one-line addition.
    `FakePriceDataSource` is dev-only; tests monkey-patch `_build_source`
    in `scheduler/tasks.py` directly rather than flipping the setting.
15. **Worker is subscription-agnostic.** The `fetch_token` worker writes a
    `PriceSnapshot` row + hot cache + pub-sub event unconditionally when
    the source returns data. It reads `Subscription.priority` only to
    derive the cache TTL and the event `tier` field. User-mute,
    quiet-hours, and `PAUSED` suppression all live at alert-dispatch
    time in Session 6 — not in the worker.
16. **Telegram dispatch shape: standalone `telegram.Bot` in the alerts
    service.** The bot service still owns `getUpdates` (long-polling);
    the alerts service holds its own `telegram.Bot` instance against
    the same token and only sends. Two processes sharing the token is
    safe because Telegram only conflicts on Update consumption — outbound
    HTTP is unconstrained beyond the documented rate limits, which we
    enforce with one global + per-chat `aiolimiter` pair. Alternatives
    considered (Redis outbox + bot drain, or refactoring `bot/` into a
    shared library) were rejected as either adding hops or introducing
    a single-process bottleneck for a horizontally scalable concern.
17. **Suppress-but-still-persist + still-mark-fired.** Muted /
    quiet-hours / `PAUSED` alerts hit `alerts_sent` with `delivered=False`
    and `delivery_error="suppressed: <reason>"`; the Redis dedup TTL key
    is set just like a delivered alert. Reason: unmute should not replay
    a thundering herd of stale warnings. Audit trail wins over "did the
    user receive it" — the latter is reconstructible from `delivered`.
    Dedup TTL cooldowns: `*_HIT` = 1h (milestones, rare), `*_WARNING` =
    5m (heads-up, re-arm fast), `VOLUME_SPIKE` = 10m (between the two).
18. **DLQ shape: Postgres `dlq_entries`, not a fifth Redis namespace.**
    Persistent `fetch_token` failures land in a Postgres table with
    `UNIQUE(token_address)` — re-failures bump `attempts` + `last_seen`
    via on-conflict update. Inspectable with `psql`, durable, no FK to
    `tokens` (DLQ rows must outlive token deletes). Celery-level retry
    is manual (`self.retry` in the outer task body, capped at
    `WORKER_FETCH_MAX_CELERY_RETRIES=1`) so the DLQ upsert lives in
    exactly one branch and `attempts` cannot double-bump. This keeps
    ADR #13 (four Redis roles only) intact.
19. **Prometheus exposure: per-service `/metrics` endpoints.** Bot,
    scheduler, worker, and alerts each bind `prometheus_client.start_http_server`
    on their own port (9101–9104). The worker container sets
    `PROMETHEUS_MULTIPROC_DIR=/tmp/pumpwatch-metrics` *before* Python
    boots, which is what flips `prometheus_client` into multiproc mode
    at Counter-construction time — the master `/metrics` endpoint
    aggregates across the prefork pool via `MultiProcessCollector`.
    Prometheus + Grafana ship behind a `--profile observability` flag
    in compose; default `docker compose up` is unchanged.
20. **DexScreener as ADR-#14 fallback source.** Implements the
    `PriceDataSource` Protocol with full parity (Pump.fun `fetch_one`
    + `fetch_batch`, tenacity retry, `api_call_log` writes). Selectable
    via `PRICE_SOURCE=dexscreener`. Pair selection: highest-liquidity
    Solana pair per requested address, since DexScreener returns pairs
    across all chains/DEXes. `DexScreenerUnavailableError` shares the
    `SourceUnavailableError` parent with `PumpFunUnavailableError`, so
    the scheduler's retry/DLQ branch catches one symbol. Batch-mode
    scheduler refactor (replacing per-token `fetch_token` with a real
    multi-token call against the comma-list endpoint) is deferred to
    Session 8 — at low cutover volume the per-token shape stays inside
    DexScreener's ~5 rps published limit via the client's aiolimiter.
21. **`price_snapshots` partitioning explicitly deferred to Session 8.**
    Model docstring says "once row count exceeds ~10M". Dev/test/prod
    cutover all near zero rows; daily partitioning is a one-revision
    online migration when the time comes, not a destructive recreate
    pre-deploy.

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
