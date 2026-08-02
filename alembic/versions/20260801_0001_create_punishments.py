"""Create punishments table.

Revision ID: 20260801_0001
Revises:
Create Date: 2026-08-01 00:01:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "punishments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("admin_username", sa.String(length=32), nullable=True),
        sa.Column("notification_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "RELEASED", "EXPIRED", name="punishmentstatus"),
            nullable=False,
        ),
    )
    op.create_index("ix_punishments_admin_id", "punishments", ["admin_id"])
    op.create_index("ix_punishments_chat_id", "punishments", ["chat_id"])
    op.create_index(
        "ix_punishments_chat_user_status",
        "punishments",
        ["chat_id", "user_id", "status"],
    )
    op.create_index(
        "ix_punishments_status",
        "punishments",
        ["status"],
    )
    op.create_index(
        "ix_punishments_status_expires_at",
        "punishments",
        ["status", "expires_at"],
    )
    op.create_index("ix_punishments_user_id", "punishments", ["user_id"])
    op.create_index(
        "uq_punishments_active_chat_user",
        "punishments",
        ["chat_id", "user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_punishments_active_chat_user", table_name="punishments")
    op.drop_index("ix_punishments_user_id", table_name="punishments")
    op.drop_index("ix_punishments_status_expires_at", table_name="punishments")
    op.drop_index("ix_punishments_status", table_name="punishments")
    op.drop_index("ix_punishments_chat_user_status", table_name="punishments")
    op.drop_index("ix_punishments_chat_id", table_name="punishments")
    op.drop_index("ix_punishments_admin_id", table_name="punishments")
    op.drop_table("punishments")
