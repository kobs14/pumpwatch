"""`/stop <mint>` command: soft-deactivate a subscription."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from pumpwatch.bot.deps import sessionmaker_from_context
from pumpwatch.bot.validators import is_valid_solana_mint
from pumpwatch.db.repos.subscription import SubscriptionRepository
from pumpwatch.db.repos.user import UserRepository
from pumpwatch.logging import get_logger

logger = get_logger(__name__)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop watching the mint in ``context.args[0]``. Soft-deactivate only."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    args: list[str] = list(context.args or [])
    if len(args) != 1:
        await message.reply_text("Use `/stop <mint>`.")
        return

    mint = args[0]
    if not is_valid_solana_mint(mint):
        await message.reply_text("That doesn't look like a Solana mint address.")
        return

    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session, session.begin():
        users = UserRepository(session)
        db_user = await users.get_by_telegram_id(user.id)
        if db_user is None:
            await message.reply_text("You haven't onboarded yet. Send /start first.")
            return

        subs = SubscriptionRepository(session)
        stopped = await subs.stop_by_user_and_token(db_user.id, mint)

    if stopped:
        logger.info("bot.stop.ok", telegram_id=user.id, mint=f"{mint[:4]}...{mint[-4:]}")
        await message.reply_text(f"🛑 Stopped watching `{mint[:4]}…{mint[-4:]}`.")
    else:
        await message.reply_text("You're not currently watching that mint.")
