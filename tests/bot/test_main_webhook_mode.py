"""Smoke tests for ``bot/main.py`` BOT_MODE dispatch.

We don't boot a real HTTP server or PTB ``Application`` here; we monkey-patch
``build_application`` to a stub whose ``run_polling``/``run_webhook`` are
``MagicMock`` recorders, then assert the right method got called with the
right kwargs. The Settings ``model_validator`` is also exercised: webhook
mode without ``BOT_WEBHOOK_URL`` must raise.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from pumpwatch.bot import main as bot_main
from pumpwatch.config import get_settings


@pytest.fixture
def fake_application(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Stub everything ``run()`` touches except the BOT_MODE branch."""
    get_settings.cache_clear()

    monkeypatch.setattr(bot_main, "start_metrics_server", lambda port: None)
    monkeypatch.setattr(bot_main, "configure_logging", lambda level, env: None)
    monkeypatch.setattr(bot_main, "get_sessionmaker", lambda: MagicMock())

    app = MagicMock()
    app.run_polling = MagicMock()
    app.run_webhook = MagicMock()
    monkeypatch.setattr(bot_main, "build_application", lambda token, sm: app)

    yield app

    get_settings.cache_clear()


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Settings constructor needs DSNs and a token regardless of mode."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-12345")


def test_run_polls_by_default(monkeypatch: pytest.MonkeyPatch, fake_application: MagicMock) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("BOT_MODE", raising=False)

    bot_main.run()

    fake_application.run_polling.assert_called_once()
    fake_application.run_webhook.assert_not_called()


def test_run_webhook_when_configured(
    monkeypatch: pytest.MonkeyPatch, fake_application: MagicMock
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("BOT_WEBHOOK_URL", "https://bot.example.com")
    monkeypatch.setenv("BOT_WEBHOOK_PORT", "8443")
    monkeypatch.setenv("BOT_WEBHOOK_SECRET_TOKEN", "telegram-shared-secret")

    bot_main.run()

    fake_application.run_webhook.assert_called_once()
    fake_application.run_polling.assert_not_called()
    kwargs = fake_application.run_webhook.call_args.kwargs
    assert kwargs["listen"] == "0.0.0.0"
    assert kwargs["port"] == 8443
    assert kwargs["url_path"] == "test-token-12345"
    assert kwargs["webhook_url"] == "https://bot.example.com/test-token-12345"
    assert kwargs["secret_token"] == "telegram-shared-secret"


def test_run_webhook_url_strips_trailing_slash(
    monkeypatch: pytest.MonkeyPatch, fake_application: MagicMock
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("BOT_WEBHOOK_URL", "https://bot.example.com/")
    monkeypatch.delenv("BOT_WEBHOOK_SECRET_TOKEN", raising=False)

    bot_main.run()

    kwargs = fake_application.run_webhook.call_args.kwargs
    assert kwargs["webhook_url"] == "https://bot.example.com/test-token-12345"
    assert kwargs["secret_token"] is None


def test_settings_rejects_webhook_mode_without_url(
    monkeypatch: pytest.MonkeyPatch, fake_application: MagicMock
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.delenv("BOT_WEBHOOK_URL", raising=False)

    with pytest.raises(ValidationError, match="BOT_WEBHOOK_URL is required"):
        bot_main.run()
