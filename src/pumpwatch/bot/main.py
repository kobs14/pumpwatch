"""Entry point for the Telegram bot service.

Run via ``python -m pumpwatch.bot.main``. Defaults to long-polling; switch to
webhook with ``BOT_MODE=webhook`` and a public ``BOT_WEBHOOK_URL`` (see
docs/deployment.md). The process is single-instance by design either way:
``ConversationHandler`` state lives in-process, and making it multi-instance
would require a Redis-backed persistence layer we deliberately deferred.
"""

from __future__ import annotations

from typing import Any

from telegram.ext import Application

from pumpwatch.bot.app import build_application
from pumpwatch.config import get_settings
from pumpwatch.db.session import dispose_engine, get_sessionmaker
from pumpwatch.logging import configure_logging, get_logger
from pumpwatch.observability.metrics import start_metrics_server

logger = get_logger(__name__)


async def _post_init(application: Application[Any, Any, Any, Any, Any, Any]) -> None:
    logger.info("bot.application.started")


async def _post_shutdown(application: Application[Any, Any, Any, Any, Any, Any]) -> None:
    logger.info("bot.application.shutting_down")
    await dispose_engine()


def run() -> None:
    """Construct the Application and run polling or webhook until SIGTERM/SIGINT.

    ``Application.run_polling`` / ``run_webhook`` own the event loop, so this
    is a regular ``def`` entrypoint — the project's single ``asyncio.run``
    rule still holds because PTB runs its own loop internally.
    """
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)
    start_metrics_server(settings.METRICS_PORT_BOT)

    sessionmaker = get_sessionmaker()
    application = build_application(settings.TELEGRAM_BOT_TOKEN, sessionmaker)
    application.post_init = _post_init
    application.post_shutdown = _post_shutdown

    if settings.BOT_MODE == "webhook":
        # ``BOT_WEBHOOK_URL`` is enforced non-empty by the Settings validator.
        assert settings.BOT_WEBHOOK_URL is not None
        webhook_url = f"{settings.BOT_WEBHOOK_URL.rstrip('/')}/{settings.TELEGRAM_BOT_TOKEN}"
        logger.info(
            "bot.webhook.starting",
            environment=settings.ENVIRONMENT,
            port=settings.BOT_WEBHOOK_PORT,
            url=settings.BOT_WEBHOOK_URL,
        )
        application.run_webhook(
            listen="0.0.0.0",  # noqa: S104 — bound inside container; reverse proxy fronts
            port=settings.BOT_WEBHOOK_PORT,
            url_path=settings.TELEGRAM_BOT_TOKEN,
            webhook_url=webhook_url,
            secret_token=settings.BOT_WEBHOOK_SECRET_TOKEN,
        )
    else:
        logger.info("bot.polling.starting", environment=settings.ENVIRONMENT)
        application.run_polling()


if __name__ == "__main__":
    run()
