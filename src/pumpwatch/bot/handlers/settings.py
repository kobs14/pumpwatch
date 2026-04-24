"""`/settings` command and its inline-keyboard conversation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import available_timezones

from telegram import Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from pumpwatch.bot.deps import sessionmaker_from_context
from pumpwatch.bot.keyboards import (
    CB_SETTINGS_CLOSE,
    CB_SETTINGS_DEFAULT_GROWTH,
    CB_SETTINGS_DEFAULT_STOPLOSS,
    CB_SETTINGS_MUTE_TOGGLE,
    CB_SETTINGS_TIMEZONE,
    settings_root_keyboard,
)
from pumpwatch.db.repos.user import UserRepository
from pumpwatch.logging import get_logger

logger = get_logger(__name__)

AWAIT_TIMEZONE = 10
AWAIT_GROWTH = 11
AWAIT_STOPLOSS = 12

_MIN_PCT = Decimal("0.01")
_MAX_PCT = Decimal("1000")

# Cached once per process. ``available_timezones()`` returns ~600 strings; no need
# to rebuild the set per settings toggle.
_VALID_TIMEZONES = frozenset(available_timezones())


def _parse_pct(text: str) -> Decimal | None:
    try:
        value = Decimal(text.strip().rstrip("%"))
    except (InvalidOperation, AttributeError):
        return None
    if value < _MIN_PCT or value > _MAX_PCT:
        return None
    return value


async def _resolve_user_id(context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> int | None:
    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(telegram_id)
        return user.id if user is not None else None


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the settings root keyboard."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return ConversationHandler.END

    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session:
        repo = UserRepository(session)
        db_user = await repo.get_by_telegram_id(user.id)
        if db_user is None:
            await message.reply_text("You haven't onboarded yet. Send /start first.")
            return ConversationHandler.END
        muted = db_user.alerts_muted

    await message.reply_text("⚙️ Settings", reply_markup=settings_root_keyboard(muted))
    return ConversationHandler.END  # keyboard routes via CallbackQueryHandlers below


async def on_mute_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Flip the user's ``alerts_muted`` flag."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return ConversationHandler.END
    await query.answer()

    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session, session.begin():
        repo = UserRepository(session)
        db_user = await repo.get_by_telegram_id(user.id)
        if db_user is None:
            return ConversationHandler.END
        new_value = not db_user.alerts_muted
        await repo.update_settings(db_user.id, alerts_muted=new_value)

    status = "muted 🔕" if new_value else "unmuted 🔔"
    if query.message is not None:
        await query.edit_message_text(
            f"Alerts are now {status}.",
            reply_markup=settings_root_keyboard(new_value),
        )
    return ConversationHandler.END


async def on_timezone_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.reply_text(
            "Send an IANA timezone name (e.g. `Europe/Berlin`) or /cancel."
        )
    return AWAIT_TIMEZONE


async def on_timezone_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or message.text is None:
        return AWAIT_TIMEZONE
    tz = message.text.strip()
    if tz not in _VALID_TIMEZONES:
        await message.reply_text("Unknown timezone. Send a valid IANA name, or /cancel.")
        return AWAIT_TIMEZONE

    user_db_id = await _resolve_user_id(context, user.id)
    if user_db_id is None:
        await message.reply_text("You haven't onboarded yet. Send /start first.")
        return ConversationHandler.END

    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session, session.begin():
        await UserRepository(session).update_settings(user_db_id, timezone=tz)

    await message.reply_text(f"🌐 Timezone set to {tz}.")
    return ConversationHandler.END


async def on_default_growth_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.reply_text(
            f"Send the new default growth % (between {_MIN_PCT} and {_MAX_PCT}), or /cancel."
        )
    return AWAIT_GROWTH


async def on_default_stoploss_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.reply_text(
            f"Send the new default stoploss % (between {_MIN_PCT} and {_MAX_PCT}), or /cancel."
        )
    return AWAIT_STOPLOSS


async def _apply_default_pct(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    field: str,
    state_on_bad_input: int,
) -> int:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or message.text is None:
        return state_on_bad_input
    value = _parse_pct(message.text)
    if value is None:
        await message.reply_text(f"Enter a number between {_MIN_PCT} and {_MAX_PCT}, or /cancel.")
        return state_on_bad_input

    user_db_id = await _resolve_user_id(context, user.id)
    if user_db_id is None:
        await message.reply_text("You haven't onboarded yet. Send /start first.")
        return ConversationHandler.END

    sessionmaker = sessionmaker_from_context(context)
    async with sessionmaker() as session, session.begin():
        fields: dict[str, Any] = {field: value}
        await UserRepository(session).update_settings(user_db_id, **fields)

    await message.reply_text(f"✅ Updated {field.replace('_', ' ')} to {value}%.")
    return ConversationHandler.END


async def on_default_growth_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _apply_default_pct(update, context, "default_growth_pct", AWAIT_GROWTH)


async def on_default_stoploss_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _apply_default_pct(update, context, "default_stoploss_pct", AWAIT_STOPLOSS)


async def on_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    if query.message is not None:
        await query.edit_message_text("Settings closed.")
    return ConversationHandler.END


async def cmd_settings_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if message is not None:
        await message.reply_text("Cancelled.")
    return ConversationHandler.END


def build_settings_conversation() -> ConversationHandler[ContextTypes.DEFAULT_TYPE]:
    """Build the `/settings` ConversationHandler.

    The root keyboard is posted by ``cmd_settings`` outside the conversation.
    Each option's callback-query handler acts as its own entry point so the
    inline buttons remain responsive even after the conversation has ended.
    """
    return ConversationHandler(
        entry_points=[
            CommandHandler("settings", cmd_settings),
            CallbackQueryHandler(on_mute_toggle, pattern=f"^{CB_SETTINGS_MUTE_TOGGLE}$"),
            CallbackQueryHandler(on_timezone_prompt, pattern=f"^{CB_SETTINGS_TIMEZONE}$"),
            CallbackQueryHandler(
                on_default_growth_prompt, pattern=f"^{CB_SETTINGS_DEFAULT_GROWTH}$"
            ),
            CallbackQueryHandler(
                on_default_stoploss_prompt, pattern=f"^{CB_SETTINGS_DEFAULT_STOPLOSS}$"
            ),
            CallbackQueryHandler(on_close, pattern=f"^{CB_SETTINGS_CLOSE}$"),
        ],
        states={
            AWAIT_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_timezone_value)],
            AWAIT_GROWTH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_default_growth_value)
            ],
            AWAIT_STOPLOSS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_default_stoploss_value)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_settings_cancel)],
        name="settings",
        persistent=False,
        per_message=False,
    )
