"""Global error handler for the bot's Application."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from pumpwatch.logging import get_logger

logger = get_logger(__name__)

_GENERIC_REPLY = "Something went wrong. Please try again in a moment."


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log uncaught handler errors and reply with a generic message.

    Never leaks exception text to the user — leaked tracebacks are an info-
    disclosure bug. The real error goes to structured logs.
    """
    telegram_id = None
    chat_id = None
    if isinstance(update, Update):
        if update.effective_user is not None:
            telegram_id = update.effective_user.id
        if update.effective_chat is not None:
            chat_id = update.effective_chat.id

    logger.exception(
        "bot.handler.error",
        telegram_id=telegram_id,
        chat_id=chat_id,
        exc_info=context.error,
    )

    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(_GENERIC_REPLY)
        except Exception:  # noqa: BLE001 — swallowed; logged already
            logger.warning("bot.handler.error.reply_failed", telegram_id=telegram_id)
