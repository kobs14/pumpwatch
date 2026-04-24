"""Tests for the ``/add`` command and its conversation states."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from pumpwatch.bot.handlers.add import (
    AWAIT_GROWTH,
    AWAIT_MINT,
    AWAIT_STOPLOSS,
    add_await_growth,
    add_await_mint,
    add_await_stoploss,
    cmd_add_entry,
    cmd_cancel,
)
from pumpwatch.db.enums import SubscriptionStatus
from pumpwatch.db.models import Subscription, Token
from tests.bot.harness import make_update_context

MINT_A = "So11111111111111111111111111111111111111112"
MINT_B = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def _existing_subscription(
    sm: async_sessionmaker[AsyncSession], telegram_id: int, mint: str
) -> Subscription | None:
    async with sm() as session:
        stmt = (
            select(Subscription)
            .options(selectinload(Subscription.user))
            .where(Subscription.token_address == mint)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            if row.user.telegram_id == telegram_id:
                return row
        return None


async def test_one_shot_add_creates_token_and_subscription(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    update, ctx = make_update_context(
        bot_sessionmaker,
        telegram_id=800001,
        args=[MINT_A, "25", "15"],
    )
    state = await cmd_add_entry(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == ConversationHandler.END

    async with bot_sessionmaker() as session:
        token = (await session.execute(select(Token).where(Token.address == MINT_A))).scalar_one()
        assert token.address == MINT_A

    sub = await _existing_subscription(bot_sessionmaker, 800001, MINT_A)
    assert sub is not None
    assert sub.growth_threshold_pct == Decimal("25")
    assert sub.stoploss_threshold_pct == Decimal("15")
    assert sub.status == SubscriptionStatus.ACTIVE


async def test_one_shot_wrong_arity_shows_hint(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    update, ctx = make_update_context(bot_sessionmaker, args=[MINT_A, "25"])
    state = await cmd_add_entry(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == ConversationHandler.END
    assert update.effective_message is not None
    assert any("all three values required" in r for r in update.effective_message.replies)


async def test_one_shot_invalid_mint_rejected(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    update, ctx = make_update_context(bot_sessionmaker, args=["not-a-mint", "25", "15"])
    state = await cmd_add_entry(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == ConversationHandler.END

    async with bot_sessionmaker() as session:
        tokens = (await session.execute(select(Token))).scalars().all()
        assert tokens == []


async def test_one_shot_out_of_range_threshold_rejected(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    update, ctx = make_update_context(bot_sessionmaker, args=[MINT_A, "9999", "15"])
    await cmd_add_entry(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    async with bot_sessionmaker() as session:
        tokens = (await session.execute(select(Token))).scalars().all()
        assert tokens == []


async def test_readding_updates_thresholds_without_duplicate(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    update, ctx = make_update_context(
        bot_sessionmaker, telegram_id=800002, args=[MINT_A, "10", "5"]
    )
    await cmd_add_entry(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    update2, ctx2 = make_update_context(
        bot_sessionmaker, telegram_id=800002, args=[MINT_A, "30", "20"]
    )
    await cmd_add_entry(cast(Update, update2), cast(ContextTypes.DEFAULT_TYPE, ctx2))

    async with bot_sessionmaker() as session:
        stmt = select(Subscription).where(Subscription.token_address == MINT_A)
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].growth_threshold_pct == Decimal("30")
        assert rows[0].stoploss_threshold_pct == Decimal("20")


async def test_conversational_flow_commits(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    user_data: dict[str, object] = {}
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=800003, user_data=user_data)
    state = await cmd_add_entry(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == AWAIT_MINT

    update, ctx = make_update_context(
        bot_sessionmaker, telegram_id=800003, text=MINT_B, user_data=user_data
    )
    state = await add_await_mint(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == AWAIT_GROWTH

    update, ctx = make_update_context(
        bot_sessionmaker, telegram_id=800003, text="40", user_data=user_data
    )
    state = await add_await_growth(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == AWAIT_STOPLOSS

    update, ctx = make_update_context(
        bot_sessionmaker, telegram_id=800003, text="12", user_data=user_data
    )
    state = await add_await_stoploss(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == ConversationHandler.END

    sub = await _existing_subscription(bot_sessionmaker, 800003, MINT_B)
    assert sub is not None
    assert sub.growth_threshold_pct == Decimal("40")
    assert sub.stoploss_threshold_pct == Decimal("12")


async def test_cancel_clears_user_data(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    user_data: dict[str, object] = {"pending_mint": MINT_A, "pending_growth": Decimal("10")}
    update, ctx = make_update_context(bot_sessionmaker, user_data=user_data)
    state = await cmd_cancel(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert state == ConversationHandler.END
    assert user_data == {}
