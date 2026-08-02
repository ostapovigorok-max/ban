"""Add permission warning state to group activations.

Revision ID: 20260802_0006
Revises: 20260802_0005
Create Date: 2026-08-02 00:06:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0006"
down_revision: str | None = "20260802_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group_activations",
        sa.Column(
            "permission_warning_sent_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("group_activations", "permission_warning_sent_at")
