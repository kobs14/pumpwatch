"""Inline keyboards used by the bot's conversation handlers."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Callback payloads for the /settings root keyboard. Centralized here so the
# handler code and the keyboard definition can't drift.
CB_SETTINGS_MUTE_TOGGLE = "settings:mute:toggle"
CB_SETTINGS_TIMEZONE = "settings:tz"
CB_SETTINGS_DEFAULT_GROWTH = "settings:growth"
CB_SETTINGS_DEFAULT_STOPLOSS = "settings:stoploss"
CB_SETTINGS_CLOSE = "settings:close"


def settings_root_keyboard(alerts_muted: bool) -> InlineKeyboardMarkup:
    """Render the ``/settings`` root inline keyboard.

    The mute row flips label to reflect the current state so the user sees
    what the tap will do, not what is set.
    """
    mute_label = "🔔 Unmute alerts" if alerts_muted else "🔕 Mute alerts"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(mute_label, callback_data=CB_SETTINGS_MUTE_TOGGLE)],
            [InlineKeyboardButton("🌐 Timezone", callback_data=CB_SETTINGS_TIMEZONE)],
            [InlineKeyboardButton("📈 Default growth %", callback_data=CB_SETTINGS_DEFAULT_GROWTH)],
            [
                InlineKeyboardButton(
                    "📉 Default stoploss %", callback_data=CB_SETTINGS_DEFAULT_STOPLOSS
                )
            ],
            [InlineKeyboardButton("Close", callback_data=CB_SETTINGS_CLOSE)],
        ]
    )
