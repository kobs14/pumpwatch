"""add user bot settings

Adds the columns that back the Telegram bot onboarding and ``/settings``
commands: ``chat_id`` (required for alert dispatch), ``alerts_muted`` (global
mute flag, in addition to ``quiet_hours_*``), and per-user default growth /
stoploss percentages used by the ``/add`` conversation when the user accepts
the suggested value.

``chat_id`` has no sensible default at the schema level, so it is added
nullable, backfilled to match ``telegram_id`` (which is correct for every
private-chat row — the only kind Session 2 could have produced — and a safe
non-crashing default for any group-chat row), then altered to NOT NULL.

Revision ID: 5050d79ff7ea
Revises: f66a7128cab1
Create Date: 2026-04-23 19:36:45.580175
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5050d79ff7ea"
down_revision: str | None = "f66a7128cab1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("chat_id", sa.BigInteger(), nullable=True))
    op.execute("UPDATE users SET chat_id = telegram_id WHERE chat_id IS NULL")
    op.alter_column("users", "chat_id", nullable=False)

    op.add_column(
        "users",
        sa.Column(
            "alerts_muted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "default_growth_pct",
            sa.Numeric(precision=8, scale=2),
            server_default="10.00",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "default_stoploss_pct",
            sa.Numeric(precision=8, scale=2),
            server_default="15.00",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "default_stoploss_pct")
    op.drop_column("users", "default_growth_pct")
    op.drop_column("users", "alerts_muted")
    op.drop_column("users", "chat_id")
