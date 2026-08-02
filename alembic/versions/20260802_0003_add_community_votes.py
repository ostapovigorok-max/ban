"""Add community vote tables.

Revision ID: 20260802_0003
Revises: 20260802_0002
Create Date: 2026-08-02 00:03:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0003"
down_revision: str | None = "20260802_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vote_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("callback_token", sa.String(length=32), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("offender_user_id", sa.BigInteger(), nullable=False),
        sa.Column("offender_display_name", sa.String(length=128), nullable=False),
        sa.Column("offender_message_id", sa.Integer(), nullable=False),
        sa.Column("creator_user_id", sa.BigInteger(), nullable=False),
        sa.Column("creator_username", sa.String(length=32), nullable=True),
        sa.Column("creator_display_name", sa.String(length=128), nullable=False),
        sa.Column("voting_message_id", sa.Integer(), nullable=True),
        sa.Column("votes_required", sa.Integer(), nullable=False),
        sa.Column("votes_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "COMPLETED", "EXPIRED", name="votesessionstatus"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_vote_sessions_active_chat_offender",
        "vote_sessions",
        ["chat_id", "offender_user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_vote_sessions_callback_token",
        "vote_sessions",
        ["callback_token"],
        unique=True,
    )
    op.create_index("ix_vote_sessions_chat_id", "vote_sessions", ["chat_id"])
    op.create_index("ix_vote_sessions_status", "vote_sessions", ["status"])
    op.create_index(
        "ix_vote_sessions_status_expires_at",
        "vote_sessions",
        ["status", "expires_at"],
    )

    op.create_table(
        "votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("voter_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["vote_sessions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "session_id", "voter_user_id", name="uq_votes_session_voter"
        ),
    )
    op.create_index("ix_votes_session_id", "votes", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_votes_session_id", table_name="votes")
    op.drop_table("votes")
    op.drop_index("ix_vote_sessions_status_expires_at", table_name="vote_sessions")
    op.drop_index("ix_vote_sessions_status", table_name="vote_sessions")
    op.drop_index("ix_vote_sessions_chat_id", table_name="vote_sessions")
    op.drop_index("ix_vote_sessions_callback_token", table_name="vote_sessions")
    op.drop_index("ix_vote_sessions_active_chat_offender", table_name="vote_sessions")
    op.drop_table("vote_sessions")
