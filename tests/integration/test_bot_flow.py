"""End-to-end bot command flow against the real test database.

Walks through a realistic user journey (start → add two tokens → list → stop
one → list again) using the same hand-rolled Update/Context stubs the unit
tests use. Asserts DB state at each step rather than message copy.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import cast

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes

from pumpwatch.bot.handlers.add import cmd_add_entry
from pumpwatch.bot.handlers.list_cmd import cmd_list
from pumpwatch.bot.handlers.start import cmd_start
from pumpwatch.bot.handlers.stop import cmd_stop
from pumpwatch.db.enums import SubscriptionStatus
from pumpwatch.db.models import Subscription, Token, User
from tests._helpers.sessionmaker import BOT_TABLES, truncating_sessionmaker
from tests.bot.harness import make_update_context

MINT_A = "So11111111111111111111111111111111111111112"
MINT_B = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TG_ID = 999001


@pytest_asyncio.fixture
async def bot_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Truncate before yield so the flow test starts with a known-empty DB."""
    async with truncating_sessionmaker(
        test_engine, tables=BOT_TABLES, truncate_on_exit=False
    ) as maker:
        yield maker


async def test_full_flow(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    # /start
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=TG_ID, chat_id=TG_ID)
    await cmd_start(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    async with bot_sessionmaker() as session:
        user = (await session.execute(select(User).where(User.telegram_id == TG_ID))).scalar_one()
        user_pk = user.id
        assert user.chat_id == TG_ID

    # /add MINT_A 10 5
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=TG_ID, args=[MINT_A, "10", "5"])
    await cmd_add_entry(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    # /add MINT_B 20 15
    update, ctx = make_update_context(
        bot_sessionmaker, telegram_id=TG_ID, args=[MINT_B, "20", "15"]
    )
    await cmd_add_entry(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    async with bot_sessionmaker() as session:
        tokens = (await session.execute(select(Token))).scalars().all()
        assert {t.address for t in tokens} == {MINT_A, MINT_B}

        subs = (
            (await session.execute(select(Subscription).where(Subscription.user_id == user_pk)))
            .scalars()
            .all()
        )
        assert {s.token_address for s in subs} == {MINT_A, MINT_B}
        assert all(s.status == SubscriptionStatus.ACTIVE for s in subs)
        pcts = {s.token_address: (s.growth_threshold_pct, s.stoploss_threshold_pct) for s in subs}
        assert pcts[MINT_A] == (Decimal("10"), Decimal("5"))
        assert pcts[MINT_B] == (Decimal("20"), Decimal("15"))

    # /list — two active rows
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=TG_ID)
    await cmd_list(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert update.effective_message is not None
    list_reply = update.effective_message.replies[-1]
    assert MINT_A[:4] in list_reply
    assert MINT_B[:4] in list_reply

    # /stop MINT_A
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=TG_ID, args=[MINT_A])
    await cmd_stop(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    async with bot_sessionmaker() as session:
        stmt = select(Subscription).where(Subscription.user_id == user_pk)
        subs = (await session.execute(stmt)).scalars().all()
        by_mint = {s.token_address: s for s in subs}
        assert by_mint[MINT_A].status == SubscriptionStatus.STOPPED
        assert by_mint[MINT_B].status == SubscriptionStatus.ACTIVE

    # /list again — only MINT_B
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=TG_ID)
    await cmd_list(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert update.effective_message is not None
    final_reply = update.effective_message.replies[-1]
    assert MINT_A[:4] not in final_reply
    assert MINT_B[:4] in final_reply
