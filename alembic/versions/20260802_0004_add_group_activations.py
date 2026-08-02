"""Add group activation table.

Revision ID: 20260802_0004
Revises: 20260802_0003
Create Date: 2026-08-02 00:04:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0004"
down_revision: str | None = "20260802_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "group_activations",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("activation_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_group_activations_is_active", "group_activations", ["is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_group_activations_is_active", table_name="group_activations")
    op.drop_table("group_activations")
