"""Add activation ownership and prompt tracking.

Revision ID: 20260802_0005
Revises: 20260802_0004
Create Date: 2026-08-02 00:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0005"
down_revision: str | None = "20260802_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group_activations",
        sa.Column("activation_message_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "group_activations",
        sa.Column("activating_admin_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "group_activations",
        sa.Column("activating_admin_name", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_group_activations_activating_admin_id",
        "group_activations",
        ["activating_admin_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_group_activations_activating_admin_id",
        table_name="group_activations",
    )
    op.drop_column("group_activations", "activating_admin_name")
    op.drop_column("group_activations", "activating_admin_id")
    op.drop_column("group_activations", "activation_message_id")
