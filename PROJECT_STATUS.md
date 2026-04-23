# PROJECT_STATUS.md — PumpWatch

This file is the persistent state of the project across Claude Code sessions.
It is updated at the end of every session.

## Current State

**Phase:** Post-Session 1
**Last Session Completed:** Session 1 — Project Scaffold & Infrastructure
**Next Session:** Session 2 — Data Layer & Pump.fun Client
**Last Updated:** 2026-04-22

## Session Plan

| #  | Title                                           | Status  | Notes |
|----|-------------------------------------------------|---------|-------|
| 0  | Bootstrap docs (CLAUDE.md, this file, etc.)     | ✅ done | Created by user before any code session |
| 1  | Project Scaffold & Infrastructure               | ✅ done | Docker Compose, Postgres, Redis, package skeleton, tooling |
| 2  | Data Layer & Pump.fun Client                    | ⬜ next | SQLAlchemy models, Alembic migration, PriceDataSource interface |
| 3  | Telegram Bot, Commands, User Onboarding         | ⬜      | python-telegram-bot, /add /list /stop /settings /help |
| 4  | Scheduler & Batch Builder                       | ⬜      | Priority tiers, batch construction, Celery Beat |
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
