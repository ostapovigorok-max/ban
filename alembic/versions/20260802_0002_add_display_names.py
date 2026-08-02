"""Add stored display names to punishments.

Revision ID: 20260802_0002
Revises: 20260801_0001
Create Date: 2026-08-02 00:02:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0002"
down_revision: str | None = "20260801_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "punishments",
        sa.Column(
            "admin_display_name",
            sa.String(length=128),
            nullable=False,
            server_default="Адміністратор",
        ),
    )
    op.add_column(
        "punishments",
        sa.Column(
            "user_display_name",
            sa.String(length=128),
            nullable=False,
            server_default="Користувач",
        ),
    )
    with op.batch_alter_table("punishments") as batch_op:
        batch_op.alter_column("admin_display_name", server_default=None)
        batch_op.alter_column("user_display_name", server_default=None)


def downgrade() -> None:
    op.drop_column("punishments", "user_display_name")
    op.drop_column("punishments", "admin_display_name")
