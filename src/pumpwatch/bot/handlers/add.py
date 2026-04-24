"""`/add` command — one-shot or three-step conversation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from pumpwatch.bot.deps import sessionmaker_from_context
from pumpwatch.bot.validators import is_valid_solana_mint
from pumpwatch.db.repos.subscription import SubscriptionRepository
from pumpwatch.db.repos.token import TokenRepository
from pumpwatch.db.repos.user import UserRepository
from pumpwatch.logging import get_logger

logger = get_logger(__name__)

AWAIT_MINT = 1
AWAIT_GROWTH = 2
AWAIT_STOPLOSS = 3

# Acceptable range (exclusive 0, inclusive 1000).
_MIN_PCT = Decimal("0.01")
_MAX_PCT = Decimal("1000")


def _parse_pct(text: str) -> Decimal | None:
    """Parse a percentage string. Returns ``None`` on bad input or out-of-range."""
    try:
        value = Decimal(text.strip().rstrip("%"))
    except (InvalidOperation, AttributeError):
        return None
    if value < _MIN_PCT or value > _MAX_PCT:
        return None
    return value


async def _commit(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    chat_id: int,
    username: str | None,
    language_code: str | None,
    mint: str,
    growth: Decimal,
    stoploss: Decimal,
) -> None:
    """Write Token + Subscription inside one transaction."""
    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session, session.begin():
        users = UserRepository(session)
        tokens = TokenRepository(session)
        subs = SubscriptionRepository(session)

        user = await users.upsert_from_telegram(
            telegram_id=telegram_id,
            username=username,
            language_code=language_code,
            chat_id=chat_id,
        )
        await tokens.upsert(address=mint)
        await subs.create_or_update(
            user_id=user.id,
            token_address=mint,
            growth_pct=growth,
            stoploss_pct=stoploss,
        )

    logger.info(
        "bot.add.committed",
        telegram_id=telegram_id,
        chat_id=chat_id,
        mint=f"{mint[:4]}...{mint[-4:]}",
        growth_pct=str(growth),
        stoploss_pct=str(stoploss),
    )


async def cmd_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for `/add`. One-shot if 3 args, else enter conversation."""
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if user is None or chat is None or message is None:
        return ConversationHandler.END

    args: list[str] = list(context.args or [])

    if len(args) == 0:
        await message.reply_text(
            "What Solana mint address should I watch? (Send /cancel to abort.)"
        )
        return AWAIT_MINT

    if len(args) != 3:
        await message.reply_text(
            "Use `/add <mint> <growth%> <stoploss%>` — all three values required. "
            "Or send /add on its own for a guided flow."
        )
        return ConversationHandler.END

    mint, growth_str, stoploss_str = args
    if not is_valid_solana_mint(mint):
        await message.reply_text("That doesn't look like a Solana mint address.")
        return ConversationHandler.END

    growth = _parse_pct(growth_str)
    stoploss = _parse_pct(stoploss_str)
    if growth is None or stoploss is None:
        await message.reply_text(f"Thresholds must be numbers between {_MIN_PCT} and {_MAX_PCT}.")
        return ConversationHandler.END

    await _commit(
        context,
        telegram_id=user.id,
        chat_id=chat.id,
        username=user.username,
        language_code=user.language_code,
        mint=mint,
        growth=growth,
        stoploss=stoploss,
    )
    await message.reply_text(
        f"✅ Watching `{mint[:4]}…{mint[-4:]}` — growth +{growth}%, stoploss -{stoploss}%."
    )
    return ConversationHandler.END


async def add_await_mint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step 1: receive the mint address."""
    message = update.effective_message
    if message is None or message.text is None:
        return AWAIT_MINT
    candidate = message.text.strip()
    if not is_valid_solana_mint(candidate):
        await message.reply_text(
            "That doesn't look like a Solana mint (base58, 32–44 chars). Try again or /cancel."
        )
        return AWAIT_MINT

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    user_data["pending_mint"] = candidate
    await message.reply_text(
        f"Got it: `{candidate[:4]}…{candidate[-4:]}`. "
        f"What growth % should trigger an alert? (e.g. 25)"
    )
    return AWAIT_GROWTH


async def add_await_growth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step 2: receive the growth threshold."""
    message = update.effective_message
    if message is None or message.text is None:
        return AWAIT_GROWTH
    growth = _parse_pct(message.text)
    if growth is None:
        await message.reply_text(
            f"Enter a number between {_MIN_PCT} and {_MAX_PCT} (e.g. 25), or /cancel."
        )
        return AWAIT_GROWTH

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    user_data["pending_growth"] = growth
    await message.reply_text("And what stoploss % should trigger an alert? (e.g. 15)")
    return AWAIT_STOPLOSS


async def add_await_stoploss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step 3: receive the stoploss threshold and commit."""
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if user is None or chat is None or message is None or message.text is None:
        return AWAIT_STOPLOSS

    stoploss = _parse_pct(message.text)
    if stoploss is None:
        await message.reply_text(
            f"Enter a number between {_MIN_PCT} and {_MAX_PCT} (e.g. 15), or /cancel."
        )
        return AWAIT_STOPLOSS

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    mint = user_data.get("pending_mint")
    growth = user_data.get("pending_growth")
    if not isinstance(mint, str) or not isinstance(growth, Decimal):
        # State lost (restart mid-flow). Fail gracefully.
        await message.reply_text("Lost track of the in-progress /add. Please start over.")
        user_data.clear()
        return ConversationHandler.END

    await _commit(
        context,
        telegram_id=user.id,
        chat_id=chat.id,
        username=user.username,
        language_code=user.language_code,
        mint=mint,
        growth=growth,
        stoploss=stoploss,
    )
    user_data.clear()
    await message.reply_text(
        f"✅ Watching `{mint[:4]}…{mint[-4:]}` — growth +{growth}%, stoploss -{stoploss}%."
    )
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exit any in-flight conversation and clear pending state."""
    if context.user_data is not None:
        context.user_data.clear()
    message = update.effective_message
    if message is not None:
        await message.reply_text("Cancelled.")
    return ConversationHandler.END


def build_add_conversation() -> ConversationHandler[ContextTypes.DEFAULT_TYPE]:
    """Build the `/add` ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add_entry)],
        states={
            AWAIT_MINT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_await_mint)],
            AWAIT_GROWTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_await_growth)],
            AWAIT_STOPLOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_await_stoploss)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        name="add",
        persistent=False,
    )
