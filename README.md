# PumpWatch

A production-grade, multi-user Telegram bot for monitoring Solana memecoin
tokens via the Pump.fun API. Delivers real-time price threshold alerts and
statistical volume-spike detection to users on their personal watchlists.

> **Status:** Early development (Session 3 complete — Telegram bot online).

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

## Bot Usage

Once `bot` is running with a real `TELEGRAM_BOT_TOKEN`:

| Command | What it does |
|---|---|
| `/start` | Create-or-fetch your PumpWatch account (stores `chat_id`). |
| `/help` | List commands and usage notes. |
| `/add <mint> <growth%> <stoploss%>` | Watch a Solana mint with thresholds. Send `/add` alone for a guided flow. |
| `/list` | Show your active subscriptions. |
| `/stop <mint>` | Soft-deactivate a subscription (history kept). |
| `/settings` | Inline keyboard for mute, timezone, default growth %, default stoploss %. |
| `/cancel` | Abort an in-progress `/add` or `/settings` conversation. |

PumpWatch is read-only: no private keys, no trade execution, no financial
advice.

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
│       │   ├── session.py        # lazy-init async engine + sessionmaker
│       │   ├── models/           # ORM models (User, Token, Subscription, ...)
│       │   └── repos/            # per-table repository classes
│       ├── sources/              # PriceDataSource protocol + PumpFunClient
│       ├── bot/                  # Telegram bot: handlers, validators, app factory
│       └── services/
│           ├── scheduler/        # fetch scheduling service (Session 4)
│           ├── worker/           # Celery worker service (Session 5)
│           └── alerts/           # alert engine service (Session 6)
└── tests/
    ├── conftest.py
    └── test_smoke.py
```

## License

Private repository. Not licensed for redistribution.
