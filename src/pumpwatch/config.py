"""Application configuration via pydantic-settings."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, RedisDsn
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

    # Telegram rate limits
    TELEGRAM_PER_CHAT_MSG_PER_SEC: int = 1
    TELEGRAM_GLOBAL_MSG_PER_SEC: int = 25


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings. This is the only way to read config."""
    return Settings()
