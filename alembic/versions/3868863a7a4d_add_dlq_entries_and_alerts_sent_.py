"""add dlq entries and alerts_sent dispatch_attempts

Two related Session 7 hardening additions in one revision:

1. ``dlq_entries`` — durable record of tokens whose ``fetch_token`` task
   has exhausted its Celery retry budget. ``UNIQUE(token_address)``
   so re-failures bump ``attempts`` + ``last_seen`` rather than insert
   duplicates. No FK to ``tokens`` — DLQ rows must outlive token deletes
   so operators can still inspect what failed and why.

2. ``alerts_sent.dispatch_attempts`` — counts dispatch attempts per
   alert row (default 1, matching the live-path "first attempt was the
   one that landed the row"). Reconciliation caps re-dispatches at
   ``ALERT_RECONCILE_MAX_ATTEMPTS`` so each row is touched at most twice.

Revision ID: 3868863a7a4d
Revises: 5050d79ff7ea
Create Date: 2026-04-25 15:14:53.407293

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3868863a7a4d"
down_revision: str | None = "5050d79ff7ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dlq_entries",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("token_address", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_address", name="uq_dlq_entries_token_address"),
    )
    op.create_index(
        "ix_dlq_entries_last_seen",
        "dlq_entries",
        ["last_seen"],
    )

    op.add_column(
        "alerts_sent",
        sa.Column(
            "dispatch_attempts",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("alerts_sent", "dispatch_attempts")
    op.drop_index("ix_dlq_entries_last_seen", table_name="dlq_entries")
    op.drop_table("dlq_entries")
