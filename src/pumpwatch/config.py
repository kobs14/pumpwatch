"""Application configuration via pydantic-settings."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal, Self

from pydantic import PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings. Read from environment variables or .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Core
    ENVIRONMENT: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"

    # Infrastructure
    DATABASE_URL: PostgresDsn
    REDIS_URL: RedisDsn
    TELEGRAM_BOT_TOKEN: str

    # Bot transport. ``polling`` is the default (works without a public
    # URL — fine for dev compose and single-instance prod). ``webhook``
    # is the productionised shape; see docs/deployment.md and ADR #8.
    BOT_MODE: Literal["polling", "webhook"] = "polling"
    BOT_WEBHOOK_URL: str | None = None
    BOT_WEBHOOK_PORT: int = 8443
    BOT_WEBHOOK_SECRET_TOKEN: str | None = None

    # Pump.fun API
    PUMPFUN_BASE_URL: str = "https://frontend-api.pump.fun"
    PUMPFUN_RATE_LIMIT_PER_SEC: int = 8
    PUMPFUN_MAX_BATCH_SIZE: int = 30
    PUMPFUN_TIMEOUT_SECONDS: int = 10
    PUMPFUN_MAX_RETRY_ATTEMPTS: int = 5
    PUMPFUN_USER_AGENT: str = "pumpwatch/0.1 (+https://github.com/kobs14/pumpwatch)"

    # Alerting defaults (percentage-point buffers and spike-detection k)
    WARNING_BUFFER_PCT_DEFAULT: Decimal = Decimal("5.00")
    VOLUME_SPIKE_K_DEFAULT: Decimal = Decimal("3.00")

    # Scheduler priority tiers (seconds between polls)
    PRIORITY_TICK_HIGH_SECONDS: int = 3
    PRIORITY_TICK_MEDIUM_SECONDS: int = 15
    PRIORITY_TICK_LOW_SECONDS: int = 60

    # Scheduler (Celery Beat) cadence: how often the batch is rebuilt and dispatched.
    SCHEDULER_FETCH_INTERVAL_SECONDS: int = 30
    # Kill-switch for the api_call_log write inside PumpFunClient. When the
    # client is constructed without a sessionmaker, logging is silently off
    # regardless of this setting.
    PUMPFUN_LOG_CALLS: bool = True

    # Worker data path: which ``PriceDataSource`` to build at worker startup.
    # ``fake`` returns an empty in-memory source (dev safeguard); real tests
    # monkey-patch the factory directly.
    PRICE_SOURCE: Literal["pumpfun", "dexscreener", "fake"] = "pumpfun"

    # DexScreener (fallback / Pump.fun-CF-block path; ADR #14, ADR #20).
    DEXSCREENER_BASE_URL: str = "https://api.dexscreener.com"
    DEXSCREENER_RATE_LIMIT_PER_SEC: int = 5
    DEXSCREENER_MAX_BATCH_SIZE: int = 30
    DEXSCREENER_TIMEOUT_SECONDS: int = 10
    DEXSCREENER_MAX_RETRY_ATTEMPTS: int = 5
    DEXSCREENER_USER_AGENT: str = "pumpwatch/0.1 (+https://github.com/kobs14/pumpwatch)"
    DEXSCREENER_LOG_CALLS: bool = True

    # Redis hot-cache TTL per subscription tier (seconds). HIGH is short so
    # the cache always expires before the next poll-cadence overwrite would
    # otherwise serve a stale value if the token stopped being polled.
    PRICE_CACHE_TTL_HIGH_SECONDS: int = 60
    PRICE_CACHE_TTL_MEDIUM_SECONDS: int = 300
    PRICE_CACHE_TTL_LOW_SECONDS: int = 900

    # Telegram rate limits
    TELEGRAM_PER_CHAT_MSG_PER_SEC: int = 1
    TELEGRAM_GLOBAL_MSG_PER_SEC: int = 25

    # Alert engine — volume-spike detector window (median + MAD).
    VOLUME_SPIKE_WINDOW_SECONDS: int = 3600
    VOLUME_SPIKE_MIN_SAMPLES: int = 12

    # Alert engine — Redis dedup-TTL cooldowns per alert type. *_HIT is the
    # milestone (rare, long cooldown), *_WARNING is a heads-up (re-arm fast),
    # VOLUME_SPIKE sits between the two.
    ALERT_DEDUP_HIT_SECONDS: int = 3600
    ALERT_DEDUP_WARNING_SECONDS: int = 300
    ALERT_DEDUP_SPIKE_SECONDS: int = 600

    # Alert engine — wait between the first and second Telegram dispatch
    # attempt for the same alert. Two attempts max; on second failure the
    # row is marked failed and the loop moves on. Reconciliation handles
    # the persistent-failure case via the periodic Beat sweep below.
    ALERT_DISPATCH_RETRY_DELAY_SECONDS: float = 1.0

    # Alert reconciliation Beat sweep. Picks up rows where
    # ``delivered = False`` and ``delivery_error NOT LIKE 'suppressed:%'``
    # (ADR #17 — never re-dispatch suppressed) created within the window
    # and re-attempts dispatch up to MAX_ATTEMPTS times. Cap defaults to 1
    # so each row is touched at most twice (once live, once reconciled).
    ALERT_RECONCILE_INTERVAL_SECONDS: int = 300
    ALERT_RECONCILE_WINDOW_SECONDS: int = 3600
    ALERT_RECONCILE_MAX_ATTEMPTS: int = 1

    # Worker DLQ: how many Celery-level retries fetch_token gets before its
    # row lands in ``dlq_entries``. PumpFunClient/DexScreenerClient already
    # retry 5x internally via tenacity; cap Celery retries at 1 so total
    # HTTP attempts stay <=10 per logical poll.
    WORKER_FETCH_MAX_CELERY_RETRIES: int = 1
    WORKER_FETCH_RETRY_BACKOFF_SECONDS: int = 5

    # Prometheus exporter ports. Each long-running service binds its own
    # ``/metrics`` endpoint via prometheus_client.start_http_server. The
    # worker uses multiproc mode (Celery prefork forks pool processes;
    # counters incremented in children must aggregate to the parent).
    METRICS_PORT_BOT: int = 9101
    METRICS_PORT_SCHEDULER: int = 9102
    METRICS_PORT_WORKER: int = 9103
    METRICS_PORT_ALERTS: int = 9104
    METRICS_GAUGE_REFRESH_SECONDS: int = 15
    PROMETHEUS_MULTIPROC_DIR: str = "/tmp/pumpwatch-metrics"

    @model_validator(mode="after")
    def _check_webhook_url_when_webhook_mode(self) -> Self:
        if self.BOT_MODE == "webhook" and not self.BOT_WEBHOOK_URL:
            raise ValueError("BOT_WEBHOOK_URL is required when BOT_MODE=webhook")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings. This is the only way to read config."""
    return Settings()
