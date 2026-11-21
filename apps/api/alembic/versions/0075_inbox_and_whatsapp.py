"""My Agentic: one Inbox for every email account, and WhatsApp chat rules.

- mail_accounts (IMAP accounts) can also SEND: smtp_host / smtp_port / smtp_security (the same
  user name and app password as IMAP), and a label the owner gives the account.
- google_accounts: more than one Gmail per person (was one row per person); the same address
  once per person.
- wa_chat_rules: per WhatsApp chat (a person or a group), when the AI answers there:
  off, only when the owner asks (mentions the number), or for everyone in the chat.

Revision ID: 0075
Revises: 0074
Create Date: 2026-11-21 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mail_accounts",
        sa.Column("smtp_host", sa.String(length=253), nullable=False, server_default=""),
    )
    op.add_column(
        "mail_accounts",
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="465"),
    )
    op.add_column(
        "mail_accounts",
        sa.Column("smtp_security", sa.String(length=10), nullable=False, server_default="ssl"),
    )
    op.add_column(
        "mail_accounts",
        sa.Column("label", sa.String(length=40), nullable=False, server_default=""),
    )
    op.drop_constraint("uq_google_accounts_user", "google_accounts", type_="unique")
    op.create_unique_constraint(
        "uq_google_accounts_email", "google_accounts", ["workspace_id", "user_id", "email"]
    )
    op.create_table(
        "wa_chat_rules",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(length=40),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("mode", sa.String(length=12), nullable=False, server_default="me"),
        sa.Column(
            "agent_id",
            sa.String(length=40),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("channel_id", "chat_id", name="uq_wa_chat_rules_chat"),
        sa.CheckConstraint("mode IN ('off', 'me', 'everyone')", name="ck_wa_chat_rules_mode"),
    )


def downgrade() -> None:
    op.drop_table("wa_chat_rules")
    op.execute(
        "DELETE FROM google_accounts g USING google_accounts h WHERE g.workspace_id = h.workspace_id"
        " AND g.user_id = h.user_id AND g.created_at > h.created_at"
    )
    op.drop_constraint("uq_google_accounts_email", "google_accounts", type_="unique")
    op.create_unique_constraint(
        "uq_google_accounts_user", "google_accounts", ["workspace_id", "user_id"]
    )
    for col in ("label", "smtp_security", "smtp_port", "smtp_host"):
        op.drop_column("mail_accounts", col)
