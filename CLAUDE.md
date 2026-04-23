# CLAUDE.md — PumpWatch Project Conventions

This file is the single source of truth for how code is written in this project.
Every Claude Code session MUST read this file as the first step of its
pre-session checklist. Deviations from these rules require explicit approval
from the user and must be recorded in `tasks/lessons.md`.

## Project Summary

**PumpWatch** is a production-grade, multi-user Telegram bot that monitors
Solana memecoin tokens via the Pump.fun API. It delivers real-time price
threshold alerts and statistical volume-spike alerts to users on their
personal watchlists. The system is designed as a distributed service —
Telegram bot + scheduler + Celery workers + alert engine — backed by
Postgres and Redis, orchestrated with Docker Compose.

This is a portfolio project. Code quality, architectural clarity, and
documentation matter as much as functionality.

## Session Workflow

Every Claude Code session follows this exact lifecycle:

1. **Pre-session:** Read `CLAUDE.md` (this file), then `PROJECT_STATUS.md`,
   then `tasks/todo.md`. Confirm which session number you are working on.
2. **Plan:** Before writing code, restate the session objective in your own
   words and list the files you intend to create or modify.
3. **Execute:** Implement only the scoped steps for the current session.
   Do not invent scope. Do not pre-create files for "future" sessions.
4. **Verify:** Run every check in the session's verification checklist.
   Fix anything that fails before declaring the session complete.
5. **Document:** Update `PROJECT_STATUS.md` (mark session complete, list
   created files, note deviations). Append to `tasks/lessons.md` anything
   surprising or worth remembering. Reset `tasks/todo.md` with the next
   session's name.
6. **Commit:** One commit per session, message format:
   `<type>: <description> (Session N)`
   Example: `feat: add Pump.fun client and data layer (Session 2)`

If you finish early, do NOT start the next session. Stop and wait.

## Stack Lockdown

These are not negotiable. If a session prompt seems to require something
outside this list, stop and ask the user.

- **Language:** Python 3.12
- **Package manager:** uv (never pip, never poetry)
- **Async runtime:** asyncio. All I/O is async.
- **DB:** Postgres 16, accessed via SQLAlchemy 2.x async + asyncpg driver
- **Migrations:** Alembic (async template)
- **Cache / broker / pub-sub:** Redis 7
- **Task queue:** Celery 5.x with Redis broker and Redis result backend
- **HTTP client:** aiohttp (never `requests`, never `httpx` unless we
  explicitly switch the whole project)
- **Telegram:** python-telegram-bot v21+ (async API)
- **Config:** pydantic-settings, loaded once via `@lru_cache`
- **Logging:** structlog (JSON in prod, console renderer in dev)
- **Retry:** tenacity
- **Rate limiting:** aiolimiter for outbound HTTP, custom token bucket
  for Telegram per-chat limits
- **Testing:** pytest, pytest-asyncio (`asyncio_mode = "auto"`)
- **Linting / formatting:** ruff (format + check)
- **Type checking:** mypy strict mode on `src/`
- **Containers:** Docker + Docker Compose

## Architectural Invariants

These describe the shape of the system. Violating them is a refactor, not a
feature. If a session would require violating one, stop and ask.

1. **Postgres is the source of truth.** Redis is *only* a cache, broker, and
   pub-sub bus. Anything in Redis must be reconstructible from Postgres.
2. **The scheduler service is single-instance.** It decides what to fetch
   and when. Running two of them would cause duplicate work. It is the only
   component that is not horizontally scalable.
3. **Workers are stateless and horizontally scalable.** A worker must be
   killable at any time without data loss; jobs go back to the queue.
4. **All external APIs sit behind an interface.** Pump.fun is accessed
   through a `PriceDataSource` protocol, never directly. This lets us swap
   to DexScreener or a fake in one line.
5. **No business logic in the bot service.** The bot service only translates
   Telegram commands into database writes and reads. All monitoring,
   alerting, and decision logic lives in scheduler / worker / alert services.
6. **Alerts are deduplicated.** The alert engine uses Redis with TTL keys to
   prevent the same alert from firing twice within a cooldown window.
7. **No alert is sent without being persisted first.** Write to
   `alerts_sent` table, then dispatch to Telegram. This prevents lost-alert
   debugging from being impossible.

## Code Conventions

### Async discipline

- Every function that does I/O is `async def`.
- Never use `time.sleep` in async code. Use `asyncio.sleep`.
- Never use sync DB calls. Every session is `AsyncSession`.
- Never use `requests`. Use the project's aiohttp client wrapper.
- Long-running CPU work goes in a Celery task, not in the event loop.

### Logging

- Always use `structlog`, never `print`, never stdlib `logging` directly.
- Bind context at module load: `logger = structlog.get_logger(__name__)`.
- Bind per-request context with `logger.bind(...)` when entering a unit of
  work (a batch, a user command, an alert dispatch).
- Log levels: `debug` for normal flow, `info` for state changes worth seeing
  in prod, `warning` for recoverable problems, `error` for failures that
  affect users, `exception` (with `exc_info`) for unhandled errors.
- Never log secrets, full Telegram tokens, or full wallet addresses.
  Truncate addresses to `Abc...xyz` format in logs.

### Database access

- All DB access goes through repository classes in `src/pumpwatch/db/repos/`.
- Services receive an `AsyncSession` via dependency injection, never create
  their own engine.
- Transactions are explicit. Use `async with session.begin():` for write
  units of work.
- Use `select()` from SQLAlchemy 2.x style. Never legacy Query API.
- All foreign keys have explicit `ondelete` behavior. No silent cascades
  unless intended and documented in the migration.

### Configuration

- All settings live in `src/pumpwatch/config.py` as a pydantic `Settings`
  class. No literal magic numbers in business code.
- `get_settings()` is the only way to read config. Cache it with `@lru_cache`.
- New settings are added with a sensible default and documented in
  `.env.example` in the same commit.

### Errors

- External API calls are wrapped in tenacity retry with exponential backoff
  and jitter. Cap retry attempts (default 5) so we don't retry forever.
- After max retries, raise a domain-specific exception
  (`PumpFunUnavailableError`, etc.), not the underlying aiohttp error.
- The worker catches domain exceptions and pushes the job to a dead-letter
  queue rather than crashing.

### Testing

- Every external API has a fake implementation in `tests/fakes/`. Tests
  never hit the real Pump.fun.
- Every repository has a test using a real Postgres (test container or
  the project's compose-managed test DB).
- Telegram dispatch is faked in unit tests; only the alert-engine
  integration test exercises the real bot client (with a test bot token).

## Forbidden Patterns

These will be reverted on review. Do not write them.

- `print(...)` anywhere outside of one-off scripts in `scripts/`
- `requests.get(...)` or any sync HTTP call
- `time.sleep(...)` inside `async def`
- `import logging; logging.basicConfig(...)` — use structlog setup instead
- Bare `except:` or `except Exception:` without re-raising or logging
- Global mutable state (use dependency injection or explicit singletons via
  `@lru_cache`)
- Hardcoded secrets, even in tests (use `.env.test`)
- SQLAlchemy 1.x patterns: `query.filter_by(...).first()`, `Session()`
  context managers without async, etc.
- `asyncio.run()` inside library code (only in entrypoints)
- Empty `__init__.py` directory pre-creation for "future" features

## Naming

- Package name: `pumpwatch` (lowercase, no underscore, no hyphen)
- Repo name: `pumpwatch`
- Docker service names: `bot`, `scheduler`, `worker`, `alerts`, `postgres`,
  `redis`
- Module names: snake_case
- Class names: PascalCase
- Constants: UPPER_SNAKE_CASE
- Telegram command handlers: `cmd_<name>` (e.g., `cmd_add`, `cmd_list`)
- Celery tasks: `<verb>_<noun>` (e.g., `fetch_batch`, `recompute_priorities`)

## Privacy & Safety in Code

- No real wallet addresses, real Telegram user IDs, or real bot tokens in
  committed code, tests, or fixtures. Use generated fakes.
- The README and architecture docs may screenshot the bot UI but must
  redact any real user information.
- This project monitors public on-chain data. We do not store private
  keys, do not execute trades, and do not advise on financial decisions.
  The bot's `/help` text must say so.

## Documentation Discipline

- Every architectural decision worth more than two sentences gets an ADR
  in `docs/adr/NNN-title.md`. Format: context, decision, consequences.
- The README is updated incrementally each session, not all at the end.
- Every public function/class has a one-line docstring minimum. Complex
  logic gets a block comment explaining *why*, not *what*.
- Mermaid diagrams in the README for architecture and key sequence flows.

## When in Doubt

If a session's prompt seems ambiguous, contradicts this file, or seems to
require crossing a forbidden pattern: STOP. Do not guess. Write a question
to the user in chat and wait. Recovering from a wrong-direction session is
more expensive than a five-minute clarification.
