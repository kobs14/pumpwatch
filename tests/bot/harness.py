"""Lightweight stubs for telegram ``Update`` and ``Context`` in unit tests.

Handlers only touch a handful of attributes on ``Update`` / ``Context`` — we
duck-type those rather than pulling in python-telegram-bot's full test harness.
Call sites use ``cast`` to satisfy strict mypy when handing stubs to real
handler signatures.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FakeMessage:
    """Stand-in for ``telegram.Message``. Records reply calls."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.reply_text: AsyncMock = AsyncMock()

    @property
    def replies(self) -> list[str]:
        """All text strings passed to reply_text, in call order."""
        return [call.args[0] for call in self.reply_text.call_args_list if call.args]


class FakeUser:
    def __init__(
        self,
        user_id: int,
        username: str | None = None,
        language_code: str | None = "en",
    ) -> None:
        self.id = user_id
        self.username = username
        self.language_code = language_code


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeCallbackQuery:
    """Stand-in for ``telegram.CallbackQuery``."""

    def __init__(self, data: str, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message
        self.answer: AsyncMock = AsyncMock()
        self.edit_message_text: AsyncMock = AsyncMock()


class FakeUpdate:
    def __init__(
        self,
        user: FakeUser,
        chat: FakeChat,
        message: FakeMessage | None = None,
        callback_query: FakeCallbackQuery | None = None,
    ) -> None:
        self.effective_user: FakeUser | None = user
        self.effective_chat: FakeChat | None = chat
        self.effective_message: FakeMessage | None = message
        self.message: FakeMessage | None = message
        self.callback_query: FakeCallbackQuery | None = callback_query


class FakeApplication:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.bot_data: dict[str, Any] = {"sessionmaker": sessionmaker}


class FakeContext:
    """Stand-in for ``telegram.ext.CallbackContext``."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        args: list[str] | None = None,
        user_data: dict[str, Any] | None = None,
    ) -> None:
        self.application = FakeApplication(sessionmaker)
        self.args: list[str] = args if args is not None else []
        self.user_data: dict[str, Any] = user_data if user_data is not None else {}
        self.error: BaseException | None = None


def make_update_context(
    sessionmaker: async_sessionmaker[AsyncSession],
    telegram_id: int = 1111,
    chat_id: int | None = None,
    text: str | None = None,
    args: list[str] | None = None,
    user_data: dict[str, Any] | None = None,
    callback_data: str | None = None,
) -> tuple[FakeUpdate, FakeContext]:
    """Build a matched pair of ``FakeUpdate`` + ``FakeContext`` for one handler call."""
    user = FakeUser(telegram_id, username=f"user{telegram_id}")
    chat = FakeChat(chat_id if chat_id is not None else telegram_id)
    message = FakeMessage(text=text) if (text is not None or callback_data is None) else None
    callback = (
        FakeCallbackQuery(data=callback_data, message=FakeMessage())
        if callback_data is not None
        else None
    )
    update = FakeUpdate(user, chat, message=message, callback_query=callback)
    ctx = FakeContext(sessionmaker, args=args, user_data=user_data)
    return update, ctx


def make_sessionmaker(engine: Any) -> async_sessionmaker[AsyncSession]:
    """Build an ``async_sessionmaker`` bound to the test engine."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
