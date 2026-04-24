"""Shared helpers that handlers pull from bot_data.

Kept separate from ``app.py`` so handler modules can import from here without
triggering a cycle through the application factory.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram.ext import ContextTypes

# Key under which the sessionmaker is stored on ``application.bot_data``.
SESSIONMAKER_KEY = "sessionmaker"


def sessionmaker_from_context(
    context: ContextTypes.DEFAULT_TYPE,
) -> async_sessionmaker[AsyncSession]:
    """Pull the sessionmaker off bot_data with the correct type."""
    maker = context.application.bot_data[SESSIONMAKER_KEY]
    return cast(async_sessionmaker[AsyncSession], maker)
