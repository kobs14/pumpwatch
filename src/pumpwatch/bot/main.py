"""Entry point for the Telegram bot service.

Run via ``python -m pumpwatch.bot.main``. Uses long-polling (webhook mode is a
Session 8 deployment concern). The process is single-instance by design:
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
    """Construct the Application and run long-polling until SIGTERM/SIGINT.

    ``Application.run_polling`` owns the event loop, so this is a regular
    ``def`` entrypoint — the project's single ``asyncio.run`` rule still
    holds because PTB runs its own loop internally.
    """
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)
    start_metrics_server(settings.METRICS_PORT_BOT)

    sessionmaker = get_sessionmaker()
    application = build_application(settings.TELEGRAM_BOT_TOKEN, sessionmaker)
    application.post_init = _post_init
    application.post_shutdown = _post_shutdown

    logger.info("bot.application.starting", environment=settings.ENVIRONMENT)
    application.run_polling()


if __name__ == "__main__":
    run()
