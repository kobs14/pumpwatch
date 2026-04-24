"""`/list` command: show the user's active subscriptions."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from pumpwatch.bot.deps import sessionmaker_from_context
from pumpwatch.bot.formatting import format_subscription_row
from pumpwatch.db.enums import SubscriptionStatus
from pumpwatch.db.repos.subscription import SubscriptionRepository
from pumpwatch.db.repos.token import TokenRepository
from pumpwatch.db.repos.user import UserRepository


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the caller's active subscriptions as a MarkdownV2 list."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session:
        users = UserRepository(session)
        db_user = await users.get_by_telegram_id(user.id)
        if db_user is None:
            await message.reply_text("You haven't onboarded yet. Send /start first.")
            return

        subs_repo = SubscriptionRepository(session)
        tokens_repo = TokenRepository(session)
        subs = await subs_repo.list_for_user(db_user.id, status=SubscriptionStatus.ACTIVE)
        if not subs:
            await message.reply_text(
                "Your watchlist is empty. Try /add <mint> <growth%> <stoploss%>."
            )
            return

        rows: list[str] = []
        for sub in subs:
            token = await tokens_repo.get(sub.token_address)
            if token is None:
                continue
            rows.append(format_subscription_row(sub, token))

    await message.reply_text("\n".join(rows), parse_mode=ParseMode.MARKDOWN_V2)
