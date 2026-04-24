"""Tests for ``/settings`` conversation state transitions."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from pumpwatch.bot.handlers.settings import (
    AWAIT_GROWTH,
    AWAIT_STOPLOSS,
    AWAIT_TIMEZONE,
    on_default_growth_value,
    on_default_stoploss_value,
    on_mute_toggle,
    on_timezone_value,
)
from pumpwatch.bot.handlers.start import cmd_start
from pumpwatch.db.models import User
from tests.bot.harness import make_update_context


async def _onboard(sm: async_sessionmaker[AsyncSession], telegram_id: int) -> None:
    update, ctx = make_update_context(sm, telegram_id=telegram_id, chat_id=telegram_id)
    await cmd_start(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))


async def _get_user(sm: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sm() as session:
        return (
            await session.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one()


async def test_mute_toggle_flips_flag(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _onboard(bot_sessionmaker, 900001)
    update, ctx = make_update_context(
        bot_sessionmaker, telegram_id=900001, callback_data="settings:mute:toggle"
    )

    state = await on_mute_toggle(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == ConversationHandler.END
    assert (await _get_user(bot_sessionmaker, 900001)).alerts_muted is True

    update2, ctx2 = make_update_context(
        bot_sessionmaker, telegram_id=900001, callback_data="settings:mute:toggle"
    )
    await on_mute_toggle(cast(Update, update2), cast(ContextTypes.DEFAULT_TYPE, ctx2))
    assert (await _get_user(bot_sessionmaker, 900001)).alerts_muted is False


async def test_timezone_value_rejects_unknown(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _onboard(bot_sessionmaker, 900002)
    before = (await _get_user(bot_sessionmaker, 900002)).timezone

    update, ctx = make_update_context(bot_sessionmaker, telegram_id=900002, text="Not/A_Real_Zone")
    state = await on_timezone_value(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == AWAIT_TIMEZONE
    assert (await _get_user(bot_sessionmaker, 900002)).timezone == before


async def test_timezone_value_accepts_iana(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _onboard(bot_sessionmaker, 900003)
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=900003, text="Europe/Berlin")
    state = await on_timezone_value(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == ConversationHandler.END
    assert (await _get_user(bot_sessionmaker, 900003)).timezone == "Europe/Berlin"


async def test_default_growth_value_rejects_out_of_range(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _onboard(bot_sessionmaker, 900004)
    before = (await _get_user(bot_sessionmaker, 900004)).default_growth_pct

    update, ctx = make_update_context(bot_sessionmaker, telegram_id=900004, text="-5")
    state = await on_default_growth_value(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )
    assert state == AWAIT_GROWTH
    assert (await _get_user(bot_sessionmaker, 900004)).default_growth_pct == before


async def test_default_stoploss_value_writes_new_decimal(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _onboard(bot_sessionmaker, 900005)
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=900005, text="22.5")
    state = await on_default_stoploss_value(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )
    assert state == ConversationHandler.END
    user = await _get_user(bot_sessionmaker, 900005)
    assert user.default_stoploss_pct == Decimal("22.5")


async def test_default_growth_rejects_zero(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _onboard(bot_sessionmaker, 900006)
    before = (await _get_user(bot_sessionmaker, 900006)).default_growth_pct
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=900006, text="0")
    state = await on_default_growth_value(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )
    assert state == AWAIT_GROWTH
    assert (await _get_user(bot_sessionmaker, 900006)).default_growth_pct == before


async def test_settings_without_onboarding_refuses(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    # Reuse the stoploss value handler: user was never /start'd.
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=900099, text="20")
    state = await on_default_stoploss_value(
        cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx)
    )
    assert state == ConversationHandler.END
    assert update.effective_message is not None
    assert any("/start" in r for r in update.effective_message.replies)


# Suppress unused-import warning on AWAIT_STOPLOSS (used via handlers).
_ = AWAIT_STOPLOSS
