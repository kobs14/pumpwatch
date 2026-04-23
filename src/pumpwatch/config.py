"""Application configuration via pydantic-settings."""

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

    # Scheduler priority tiers (seconds between polls)
    PRIORITY_TICK_HIGH_SECONDS: int = 3
    PRIORITY_TICK_MEDIUM_SECONDS: int = 15
    PRIORITY_TICK_LOW_SECONDS: int = 60

    # Telegram rate limits
    TELEGRAM_PER_CHAT_MSG_PER_SEC: int = 1
    TELEGRAM_GLOBAL_MSG_PER_SEC: int = 25


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings. This is the only way to read config."""
    return Settings()
