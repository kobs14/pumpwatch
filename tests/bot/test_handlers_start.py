"""Tests for the ``/start`` and ``/help`` handlers."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes

from pumpwatch.bot.handlers.start import cmd_help, cmd_start
from pumpwatch.db.models import User
from tests.bot.harness import make_update_context


async def test_start_creates_user(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=777001, chat_id=-100500)
    await cmd_start(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))

    assert update.effective_message is not None
    assert any("Welcome" in r for r in update.effective_message.replies)

    async with bot_sessionmaker() as session:
        row = (await session.execute(select(User).where(User.telegram_id == 777001))).scalar_one()
        assert row.chat_id == -100500


async def test_start_idempotent(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    update, ctx = make_update_context(bot_sessionmaker, telegram_id=777002, chat_id=777002)
    await cmd_start(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    update2, ctx2 = make_update_context(bot_sessionmaker, telegram_id=777002, chat_id=777002)
    await cmd_start(cast(Update, update2), cast(ContextTypes.DEFAULT_TYPE, ctx2))

    async with bot_sessionmaker() as session:
        rows = (
            (await session.execute(select(User).where(User.telegram_id == 777002))).scalars().all()
        )
        assert len(rows) == 1


async def test_help_replies(
    bot_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    update, ctx = make_update_context(bot_sessionmaker)
    await cmd_help(cast(Update, update), cast(ContextTypes.DEFAULT_TYPE, ctx))
    assert update.effective_message is not None
    replies = update.effective_message.replies
    assert len(replies) == 1
    assert "/add" in replies[0]
    assert "/settings" in replies[0]
