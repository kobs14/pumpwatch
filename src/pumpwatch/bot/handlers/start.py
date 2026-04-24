"""`/start` and `/help` command handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from pumpwatch.bot.deps import sessionmaker_from_context
from pumpwatch.db.repos.user import UserRepository
from pumpwatch.logging import get_logger

logger = get_logger(__name__)


_WELCOME_TEXT = (
    "👋 Welcome to PumpWatch.\n\n"
    "I'll watch Solana memecoins on Pump.fun and ping you when a token you\n"
    "follow hits a growth or stoploss threshold you set.\n\n"
    "Start with /help to see every command."
)


_HELP_TEXT = (
    "🛟 Commands:\n"
    "• /add — add a mint to your watchlist with growth + stoploss thresholds\n"
    "• /list — show your active subscriptions\n"
    "• /stop <mint> — stop watching a token (history is kept)\n"
    "• /settings — mute/unmute, timezone, default thresholds\n"
    "• /cancel — abort an in-progress /add or /settings\n\n"
    "PumpWatch only reads public on-chain data. It never stores private keys,\n"
    "executes trades, or gives financial advice."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create-or-fetch the user row and greet."""
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if user is None or chat is None or message is None:
        return

    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session, session.begin():
        repo = UserRepository(session)
        db_user = await repo.upsert_from_telegram(
            telegram_id=user.id,
            username=user.username,
            language_code=user.language_code,
            chat_id=chat.id,
        )

    logger.info(
        "bot.start",
        telegram_id=user.id,
        chat_id=chat.id,
        user_id=db_user.id,
    )
    await message.reply_text(_WELCOME_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Static help text. No DB work."""
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(_HELP_TEXT)
