"""Entrypoint for the alerts service.

Run via ``python -m pumpwatch.alerts.main``. Wires structlog, the lazy
DB sessionmaker, the long-running Redis client, and the Telegram
dispatcher; then drives the subscriber loop until SIGTERM/SIGINT.

The Redis pubsub connection must be established before any worker
``PUBLISH`` to avoid lost events (pub-sub has zero replay). Operationally
this means: bring the alerts service up before the scheduler/worker
pair when starting fresh; on a restart, any in-flight events for the
restart window are lost. Snapshot rows in Postgres remain authoritative.
"""

from __future__ import annotations

import asyncio
import signal

from pumpwatch.alerts.dispatcher import build_dispatcher, shutdown_dispatcher
from pumpwatch.alerts.subscriber import run as run_subscriber
from pumpwatch.cache.redis_client import close_redis, get_redis
from pumpwatch.config import get_settings
from pumpwatch.db.session import dispose_engine, get_sessionmaker
from pumpwatch.logging import configure_logging, get_logger
from pumpwatch.observability.metrics import start_metrics_server

_log = get_logger(__name__)


async def _run_async() -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)
    start_metrics_server(settings.METRICS_PORT_ALERTS)
    _log.info("alerts.service.starting", environment=settings.ENVIRONMENT)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover — non-POSIX, e.g. Windows
            signal.signal(sig, lambda *_: stop_event.set())

    sessionmaker = get_sessionmaker()
    redis_client = get_redis()
    dispatcher = await build_dispatcher(settings.TELEGRAM_BOT_TOKEN, settings)
    try:
        await run_subscriber(sessionmaker, redis_client, dispatcher, stop_event)
    finally:
        _log.info("alerts.service.stopping")
        await shutdown_dispatcher(dispatcher)
        await close_redis()
        await dispose_engine()
        _log.info("alerts.service.stopped")


def run() -> None:
    """Sync entrypoint used by ``python -m pumpwatch.alerts.main``."""
    asyncio.run(_run_async())


if __name__ == "__main__":
    run()
