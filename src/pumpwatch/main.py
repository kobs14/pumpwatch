"""PumpWatch application entrypoint."""

import asyncio

from pumpwatch import __version__
from pumpwatch.config import get_settings
from pumpwatch.logging import configure_logging, get_logger


async def main() -> None:
    """Start the PumpWatch application."""
    settings = get_settings()
    configure_logging(log_level=settings.LOG_LEVEL, environment=settings.ENVIRONMENT)
    log = get_logger(__name__)
    log.info("startup", status="ready", version=__version__)
    # Idle until killed — real services come in later sessions
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
