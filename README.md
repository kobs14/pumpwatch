# PumpWatch

A production-grade, multi-user Telegram bot for monitoring Solana memecoin
tokens via the Pump.fun API. Delivers real-time price threshold alerts and
statistical volume-spike detection to users on their personal watchlists.

> **Status:** Early development (Session 6 complete — alert engine subscribes to `pw:price.updated`, runs threshold + median+MAD detectors, dedupes, suppresses, persists, and dispatches via Telegram).

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

## Scheduler & Workers

The scheduler is a single-instance Celery Beat process that rebuilds the
poll set every `SCHEDULER_FETCH_INTERVAL_SECONDS` (default 30s). For each
active subscription it computes a priority tier (HIGH/MEDIUM/LOW) from the
distance to either growth/stoploss threshold, recent volatility, and
recent volume. One `fetch_token` task per unique token is dispatched, and
the worker pool runs them.

```bash
docker compose up -d postgres redis scheduler worker
# Smoke check — should return "pong"
docker compose exec worker celery -A pumpwatch.celery_app inspect ping
```

The `scheduler` service is deliberately single-instance; running two Beat
processes would fire `fetch_batch` twice per tick. The `worker` service is
horizontally scalable — queue routing (`default`, `high`, `medium`, `low`)
is in place but replica counts are a Session 7 concern.

### Worker write path (Session 5)

Each `fetch_token` task performs three ordered steps:

1. **Fetch** the token from the configured `PriceDataSource`
   (`PRICE_SOURCE=pumpfun|fake`, via the factory in
   `src/pumpwatch/sources/factory.py`). `PumpFunUnavailableError` is a
   silent skip — the scheduler re-dispatches on the next tick.
2. **Persist** a `PriceSnapshot` row in Postgres. This is the authoritative
   step; everything downstream assumes this row exists.
3. **Hot cache + pub-sub** (best-effort): `SET pw:price:<addr> <json>` with
   a tier-varying TTL (HIGH=60s, MEDIUM=300s, LOW=900s), then `PUBLISH
   pw:price.updated <json>`. A Redis outage warns but does not break the
   snapshot write.

The Redis namespace is `pw:*` throughout. The alert engine subscribes to
`pw:price.updated` and uses a separate `pw:alert:*` prefix for dedup
TTL keys.

## Alert engine (Session 6)

The `alerts` service is a single-instance long-running consumer. It
subscribes to `pw:price.updated` once at startup, then for each event:

1. **Detect** — for every active subscription on the event's token:
   - **Threshold detector** (pure): compares the event's `market_cap_usd`
     against `Subscription.baseline_market_cap` and fires `GROWTH_HIT`,
     `GROWTH_WARNING`, `STOPLOSS_HIT`, or `STOPLOSS_WARNING` per the
     sub's `growth_threshold_pct`, `stoploss_threshold_pct`, and
     `warning_buffer_pct`. Inclusive on the HIT side.
   - **Median + MAD volume-spike detector** (pure): pulls the last
     `VOLUME_SPIKE_WINDOW_SECONDS` of `volume_5m_usd` history (excluding
     the current bar), requires `VOLUME_SPIKE_MIN_SAMPLES`, and fires
     `VOLUME_SPIKE` if `(current - median) / mad >= sub.volume_spike_k`.
2. **Dedupe** — Redis-TTL key `pw:alert:<user>:<token>:<type>`. TTL
   varies per alert type (`*_HIT` = 1h, `*_WARNING` = 5m, spike = 10m).
   On Redis failure, falls back to the DB-side
   `AlertRepository.recent_for_subscription` backstop.
3. **Suppress** — `User.alerts_muted`, `Subscription.priority == PAUSED`,
   or quiet-hours window in the user's timezone (zoneinfo, wrap-around
   and DST handled). Suppressed alerts are still persisted (audit
   trail) with `delivered=False` and `delivery_error="suppressed: ..."`,
   and the dedup key is still set so unmute does not replay a backlog.
4. **Persist** — write the row to `alerts_sent` *before* dispatching.
   CLAUDE.md invariant.
5. **Dispatch** — `telegram.Bot.send_message` via the alerts-service-
   owned Bot client (separate process from the bot service, same
   token, no `getUpdates` conflict). Per-chat + global `aiolimiter`
   rate limits. One inline retry on `TelegramError`; second failure
   marks `delivery_error` on the already-persisted row and the loop
   keeps consuming.

```bash
docker compose up -d postgres redis bot scheduler worker alerts
docker compose logs -f alerts

# Watch dedup keys land
docker compose exec redis redis-cli --scan --pattern 'pw:alert:*'

# See recent alert rows
docker compose exec postgres psql -U pumpwatch -d pumpwatch -c \
  "SELECT id, subscription_id, alert_type, delivered, delivery_error, created_at \
   FROM alerts_sent ORDER BY id DESC LIMIT 10;"
```

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
│       ├── sources/              # PriceDataSource protocol + PumpFunClient + factory
│       ├── cache/                # Redis hot-cache + pub-sub helpers
│       ├── bot/                  # Telegram bot: handlers, validators, app factory
│       ├── celery_app.py         # Celery application + Beat schedule
│       ├── scheduler/            # Celery tasks: batch builder, priority tiers, fetch_token
│       ├── alerts/               # subscriber loop, detectors, dedup, suppression, dispatcher
│       └── services/             # (Session 1 placeholders; real code lives above)
└── tests/
    ├── conftest.py
    └── test_smoke.py
```

## License

Private repository. Not licensed for redistribution.
