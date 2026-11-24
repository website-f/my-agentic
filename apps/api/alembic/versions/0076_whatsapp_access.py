"""My Agentic: other WhatsApp numbers the owner lets instruct the AI, with limits.

wa_members, per WhatsApp channel: a number (and its privacy id once seen), a name, a level
(chat: answers with no tools; assistant: tools but none of the owner's private ones; full: like
the owner), limits per day (messages, AI tokens; 0 = no limit), the chats it may use (empty =
every chat), an expiry, and an on/off switch.

Revision ID: 0076
Revises: 0075
Create Date: 2026-11-25 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wa_members",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(length=40),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("lid", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("level", sa.String(length=12), nullable=False, server_default="assistant"),
        sa.Column("daily_messages", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("daily_tokens", sa.Integer(), nullable=False, server_default="200000"),
        sa.Column("chats", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("channel_id", "number", name="uq_wa_members_number"),
        sa.CheckConstraint("level IN ('chat', 'assistant', 'full')", name="ck_wa_members_level"),
    )


def downgrade() -> None:
    op.drop_table("wa_members")
