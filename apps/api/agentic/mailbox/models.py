"""P109 tables (migration 0069). Imported by agentic.models so Alembic and the app see them."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, Timestamps
from ..core.ids import new_id

ACCOUNT_STATUSES = ("untested", "ok", "error")
JOB_STATUSES = ("queued", "running", "done", "failed", "cancelled")
SOURCES = ("imap", "gmail")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class ExternalMailAccount(Timestamps, Base):
    """Another email account a person connected besides Microsoft 365 (Gmail, Yahoo, a cPanel
    mailbox...), read over IMAP with an app password, so their attachments can be backed up
    into their own Files before they stop using it. Only its person ever uses it: no admin,
    no AI and no one else reads it. The password is encrypted at rest (core/crypto, bound to
    this row) and deleted when they disconnect. `backup_done_at`: a full backup finished."""

    __tablename__ = "mail_accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "email", name="uq_mail_accounts_email"),
        CheckConstraint(_in("status", ACCOUNT_STATUSES), name="ck_mail_accounts_status"),
        CheckConstraint("security IN ('ssl', 'starttls')", name="ck_mail_accounts_security"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("xm"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(254))
    provider: Mapped[str] = mapped_column(String(20), default="other")
    host: Mapped[str] = mapped_column(String(253))
    port: Mapped[int] = mapped_column(Integer, default=993)
    security: Mapped[str] = mapped_column(String(10), default="ssl")
    username: Mapped[str] = mapped_column(String(254))
    secret_enc: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="untested")
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # My Agentic (0075): the same account also sends, over SMTP with the same login.
    smtp_host: Mapped[str] = mapped_column(String(253), default="", server_default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=465, server_default="465")
    smtp_security: Mapped[str] = mapped_column(String(10), default="ssl", server_default="ssl")
    label: Mapped[str] = mapped_column(String(40), default="", server_default="")

    @property
    def aad(self) -> str:
        return f"mail_account:{self.id}"


class MailBackupJob(Timestamps, Base):
    """One "back up all attachments" run of a person's other email account (IMAP), or of their
    Gmail connected with Google sign-in (source "gmail"). Runs on the worker in short rounds
    and resumes where it stopped (`progress`: per folder its UIDVALIDITY and the last UID done,
    or Gmail's page token). Files go to the person's own Files, "Email backup/<account>/
    <yyyy-mm>", each kept once (same content: skipped)."""

    __tablename__ = "mail_backup_jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="ck_mail_backup_jobs_status"),
        CheckConstraint(_in("source", SOURCES), name="ck_mail_backup_jobs_source"),
        Index("ix_mail_backup_jobs_owner", "workspace_id", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mbk"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("mail_accounts.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(10), default="imap")
    label: Mapped[str] = mapped_column(String(254))  # the account's address
    status: Mapped[str] = mapped_column(String(12), default="queued")
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    messages_seen: Mapped[int] = mapped_column(Integer, default=0)
    messages_total: Mapped[int] = mapped_column(Integer, default=0)
    saved: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    too_large: Mapped[int] = mapped_column(Integer, default=0)
    inline_skipped: Mapped[int] = mapped_column(Integer, default=0)
    bytes_saved: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


WA_MODES = ("off", "me", "everyone")


class WaChatRule(Timestamps, Base):
    """My Agentic (0075): when the AI answers in one WhatsApp chat of the connected number.

    - off: never (the owner chats there by hand).
    - me: only when the owner asks: in a group, a message from the owner's linked number that
      mentions the connected number (or replies to it); in a direct chat, every message from
      the owner.
    - everyone: anyone in the chat who mentions the number (in a direct chat: every message)
      gets an answer. People other than the owner get a plain answer with no tools and no
      private data (wa_bot._guest_answer); `instructions` tells the AI how to answer there.
    `agent_id`: which agent answers (None: the WhatsApp channel's usual agent)."""

    __tablename__ = "wa_chat_rules"
    __table_args__ = (
        UniqueConstraint("channel_id", "chat_id", name="uq_wa_chat_rules_chat"),
        CheckConstraint(_in("mode", WA_MODES), name="ck_wa_chat_rules_mode"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("war"))
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    chat_id: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    mode: Mapped[str] = mapped_column(String(12), default="me", server_default="me")
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
