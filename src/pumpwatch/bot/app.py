"""Application factory: register handlers and stash the sessionmaker."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram.ext import Application, ApplicationBuilder, CommandHandler

from pumpwatch.bot.deps import SESSIONMAKER_KEY
from pumpwatch.bot.handlers.add import build_add_conversation
from pumpwatch.bot.handlers.errors import error_handler
from pumpwatch.bot.handlers.list_cmd import cmd_list
from pumpwatch.bot.handlers.settings import build_settings_conversation
from pumpwatch.bot.handlers.start import cmd_help, cmd_start
from pumpwatch.bot.handlers.stop import cmd_stop


def build_application(
    token: str,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Application[Any, Any, Any, Any, Any, Any]:
    """Construct the ``Application`` with all handlers registered.

    The ``sessionmaker`` is stashed on ``bot_data`` so every handler can pull
    it out via ``pumpwatch.bot.deps.sessionmaker_from_context`` without a
    module-level global.
    """
    application = ApplicationBuilder().token(token).build()
    application.bot_data[SESSIONMAKER_KEY] = sessionmaker

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("list", cmd_list))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(build_add_conversation())
    application.add_handler(build_settings_conversation())
    application.add_error_handler(error_handler)

    return application
