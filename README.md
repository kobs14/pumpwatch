# PumpWatch

A production-grade, multi-user Telegram bot for monitoring Solana memecoin
tokens via the Pump.fun API. Delivers real-time price threshold alerts and
statistical volume-spike detection to users on their personal watchlists.

> **Status:** Early development (Session 1 complete — project scaffold).

## Architecture (Planned)

Five services orchestrated with Docker Compose:

- **Bot** — handles Telegram commands, owns user-facing state
- **Scheduler** — decides what to fetch and when (priority tiers)
- **Workers** — Celery pool that fetches prices and writes snapshots
- **Alerts** — consumes price events, runs detectors, dispatches notifications
- **Postgres + Redis** — source of truth and cache/broker/pub-sub

## Quick Start

1. Copy the environment template and fill in your Telegram bot token:

   ```bash
   cp .env.example .env
   # Edit .env and set TELEGRAM_BOT_TOKEN to your token from @BotFather
   ```

2. Start all services:

   ```bash
   docker compose up -d
   ```

3. Verify the app is running:

   ```bash
   docker compose logs -f app
   ```

   You should see a structured log line with `status=ready`.

## Development

Install dependencies locally (requires [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
```

Run checks:

```bash
uv run pytest              # tests
uv run ruff check .        # linter
uv run ruff format .       # formatter
uv run mypy src            # type checker
uv run alembic current     # migration status (requires running Postgres)
```

## Project Structure

```
pumpwatch/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── src/
│   └── pumpwatch/
│       ├── __init__.py           # package version
│       ├── config.py             # pydantic-settings configuration
│       ├── logging.py            # structlog setup
│       ├── main.py               # application entrypoint
│       ├── db/
│       │   ├── base.py           # SQLAlchemy DeclarativeBase
│       │   └── session.py        # async engine and session factory
│       └── services/
│           ├── bot/              # Telegram bot service
│           ├── scheduler/        # fetch scheduling service
│           ├── worker/           # Celery worker service
│           └── alerts/           # alert engine service
└── tests/
    ├── conftest.py
    └── test_smoke.py
```

## License

Private repository. Not licensed for redistribution.
