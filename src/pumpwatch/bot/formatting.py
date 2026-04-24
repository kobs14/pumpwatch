"""Message formatting helpers for the Telegram bot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.helpers import escape_markdown

if TYPE_CHECKING:
    from pumpwatch.db.models.subscription import Subscription
    from pumpwatch.db.models.token import Token


def escape_md_v2(text: str) -> str:
    """Escape ``text`` for MarkdownV2. Thin wrapper over python-telegram-bot."""
    return escape_markdown(text, version=2)


def truncate_mint(address: str) -> str:
    """Render a mint as ``Abcd…wxyz`` for readable listings."""
    if len(address) <= 10:
        return address
    return f"{address[:4]}…{address[-4:]}"


def format_subscription_row(sub: Subscription, token: Token) -> str:
    """Render one ``/list`` row as a MarkdownV2-escaped single line."""
    label = token.symbol or truncate_mint(token.address)
    return (
        f"• *{escape_md_v2(label)}* — "
        f"growth \\+{escape_md_v2(str(sub.growth_threshold_pct))}%, "
        f"stoploss \\-{escape_md_v2(str(sub.stoploss_threshold_pct))}% "
        f"\\(`{escape_md_v2(truncate_mint(token.address))}`\\)"
    )
