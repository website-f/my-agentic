"""My Agentic: one Inbox over every email account the owner connected.

Three kinds of account, each with its own key so the page and the AI can switch between them:

- ``ms:<id>``  a Microsoft account (work Microsoft 365 or a personal Outlook.com), Graph API,
  connected with Microsoft sign-in (microsoft/*). Several per person since 0073.
- ``g:<id>``   a Gmail account, Gmail API, connected with Google sign-in (assistants/gmail.py).
  Several per person since 0075.
- ``x:<id>``   any other mailbox over IMAP (read) + SMTP (send) with an app password
  (mailbox/imap.py, mailbox/smtp.py). Works for Gmail, Yahoo, iCloud, cPanel, Zoho...

Every message comes back in one shape (microsoft/hub.mail_row / mail_full), plus ``account``
(the key), so one page shows them all. Folders are the logical ones of FOLDERS; each provider
maps them to its own (Outlook folders, Gmail labels, IMAP special-use folders).

Only the owner's own accounts are ever listed (each query is scoped to their user id).
"""

import asyncio
import base64
import contextlib
import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesHeaderParser, BytesParser
from email.utils import formataddr, getaddresses, make_msgid, parsedate_to_datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..assistants import gmail
from ..core import crypto
from ..i18n import Msg
from ..mailbox import imap, smtp
from ..mailbox.models import ExternalMailAccount
from ..microsoft import access, graph, hub
from ..microsoft.errors import MicrosoftError
from ..models import GoogleAccount, MicrosoftAccount

FOLDERS = ("inbox", "sentitems", "drafts", "archive", "deleteditems", "junkemail")
FOLDER_NAMES = {
    "inbox": "Inbox",
    "sentitems": "Sent",
    "drafts": "Drafts",
    "archive": "Archive",
    "deleteditems": "Trash",
    "junkemail": "Spam",
}
PAGE = 25


class InboxError(Exception):
    """A sentence for the person; ``status`` is the HTTP status the router answers with."""

    def __init__(self, message: str | Msg, status: int = 400, code: str = "inbox_error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


@dataclass
class Account:
    key: str
    provider: str  # microsoft | google | imap
    email: str
    label: str
    status: str  # ok | error | needs_reconnect
    primary: bool
    can_send: bool
    error: str | None = None

    def dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- accounts


async def accounts(db: AsyncSession, workspace_id: str, user_id: str) -> list[Account]:
    out: list[Account] = []
    for a in (
        await db.scalars(
            select(MicrosoftAccount)
            .where(
                MicrosoftAccount.workspace_id == workspace_id,
                MicrosoftAccount.user_id == user_id,
            )
            .order_by(MicrosoftAccount.is_primary.desc(), MicrosoftAccount.created_at)
        )
    ).all():
        ok = a.status in access.USABLE_ACCOUNT
        out.append(
            Account(
                key=f"ms:{a.id}",
                provider="microsoft",
                email=a.email or "",
                label=a.label or ("Microsoft" if a.is_primary else ""),
                status="ok" if ok else "needs_reconnect",
                primary=bool(a.is_primary),
                can_send=ok,
                error=None if ok else (a.last_error if hasattr(a, "last_error") else None),
            )
        )
    for g in (
        await db.scalars(
            select(GoogleAccount)
            .where(GoogleAccount.workspace_id == workspace_id, GoogleAccount.user_id == user_id)
            .order_by(GoogleAccount.created_at)
        )
    ).all():
        ok = g.status == "connected"
        out.append(
            Account(
                key=f"g:{g.id}",
                provider="google",
                email=g.email,
                label="Gmail",
                status="ok" if ok else "needs_reconnect",
                primary=False,
                can_send=ok and "gmail.compose" in (g.scopes or ""),
                error=g.last_error,
            )
        )
    for x in (
        await db.scalars(
            select(ExternalMailAccount)
            .where(
                ExternalMailAccount.workspace_id == workspace_id,
                ExternalMailAccount.user_id == user_id,
            )
            .order_by(ExternalMailAccount.created_at)
        )
    ).all():
        out.append(
            Account(
                key=f"x:{x.id}",
                provider="imap",
                email=x.email,
                label=x.label or x.provider.title(),
                status="error" if x.status == "error" else "ok",
                primary=False,
                can_send=bool(x.smtp_host),
                error=x.last_error,
            )
        )
    if out and not any(a.primary for a in out):
        out[0].primary = True
    return out


@dataclass
class Picked:
    kind: str
    row: Any


async def pick(db: AsyncSession, workspace_id: str, user_id: str, key: str) -> Picked:
    """The owner's own account behind a key (anyone else's, or a bad key: not found)."""
    kind, _, rid = (key or "").partition(":")
    model = {"ms": MicrosoftAccount, "g": GoogleAccount, "x": ExternalMailAccount}.get(kind)
    row = await db.get(model, rid) if model and rid else None
    if row is None or row.workspace_id != workspace_id or row.user_id != user_id:
        raise InboxError(Msg("That email account is not connected here."), 404, "account_not_found")
    return Picked(kind, row)


def _ms_fail(e: MicrosoftError) -> InboxError:
    st = getattr(e, "status", 0)
    if st == 404:
        return InboxError(Msg("That was not found in Microsoft 365."), 404, "not_found")
    if st in (401, 403):
        return InboxError(
            Msg("Your Microsoft connection may not do this. Reconnect the account once."),
            409,
            "microsoft_not_allowed",
        )
    return InboxError(Msg("Microsoft said: {why}", why=str(e)[:200]), 502, "microsoft_error")


def _g_fail(e: gmail.GmailError) -> InboxError:
    if e.status == 404:
        return InboxError(Msg("That was not found in Gmail."), 404, "not_found")
    msg = e.args[0] if e.args else "Gmail error"
    return InboxError(
        msg if isinstance(msg, Msg) else Msg("Gmail said: {why}", why=str(msg)[:200]),
        502,
        "google_error",
    )


def _x_fail(e: imap.ImapError) -> InboxError:
    msg = e.args[0] if e.args else Msg("The mail server did not answer.")
    return InboxError(msg, 502, "imap_error")


# ---------------------------------------------------------------- shapes


def _addr(name: str, address: str) -> dict[str, str]:
    return {"name": (name or "").strip().strip('"'), "address": (address or "").strip().lower()}


def _addrs(*values: str) -> list[dict[str, str]]:
    return [_addr(n, a) for n, a in getaddresses([v for v in values if v]) if a]


def _iso_date(value: str) -> str | None:
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _row(
    key: str,
    *,
    mid: str,
    thread: str = "",
    subject: str = "",
    sender: str = "",
    to: str = "",
    cc: str = "",
    at: str | None = None,
    read: bool = True,
    draft: bool = False,
    attach: bool = False,
    flagged: bool = False,
    preview: str = "",
    link: str | None = None,
) -> dict[str, Any]:
    frm = _addrs(sender)
    return {
        "id": mid,
        "account": key,
        "conversation_id": thread or None,
        "subject": subject or "",
        "from": frm[0] if frm else _addr("", ""),
        "to": _addrs(to),
        "cc": _addrs(cc),
        "received_at": at,
        "is_read": read,
        "is_draft": draft,
        "has_attachments": attach,
        "importance": "normal",
        "flagged": flagged,
        "preview": (preview or "")[:300],
        "web_link": link,
    }


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


# ---- Gmail


def _g_headers(msg: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in (msg.get("payload") or {}).get("headers") or []}


def _g_row(key: str, acct: GoogleAccount, msg: dict[str, Any]) -> dict[str, Any]:
    h = _g_headers(msg)
    labels = msg.get("labelIds") or []
    at = None
    with contextlib.suppress(TypeError, ValueError):
        at = datetime.fromtimestamp(int(msg.get("internalDate")) / 1000, UTC).isoformat()
    parts = (msg.get("payload") or {}).get("parts") or []
    return _row(
        key,
        mid=str(msg.get("id") or ""),
        thread=str(msg.get("threadId") or ""),
        subject=h.get("subject", ""),
        sender=h.get("from", ""),
        to=h.get("to", ""),
        cc=h.get("cc", ""),
        at=at or _iso_date(h.get("date", "")),
        read="UNREAD" not in labels,
        draft="DRAFT" in labels,
        attach=any(p.get("filename") for p in parts),
        flagged="STARRED" in labels,
        preview=html.unescape(msg.get("snippet") or ""),
        link=f"https://mail.google.com/mail/u/{acct.email}/#all/{msg.get('id')}",
    )


def _g_walk(part: dict[str, Any], out: dict[str, Any]) -> None:
    mime = part.get("mimeType", "")
    body = part.get("body") or {}
    if part.get("filename") and body.get("attachmentId"):
        out["attachments"].append(
            {
                "id": body["attachmentId"],
                "name": part["filename"],
                "size": int(body.get("size") or 0),
                "content_type": mime,
                "inline": False,
            }
        )
    elif body.get("data") and mime == "text/html":
        out["html"].append(gmail._decode(body["data"]))
    elif body.get("data") and mime == "text/plain":
        out["text"].append(gmail._decode(body["data"]))
    for sub in part.get("parts") or []:
        _g_walk(sub, out)


def _g_full(key: str, acct: GoogleAccount, msg: dict[str, Any]) -> dict[str, Any]:
    got: dict[str, Any] = {"html": [], "text": [], "attachments": []}
    _g_walk(msg.get("payload") or {}, got)
    h = _g_headers(msg)
    row = _g_row(key, acct, msg)
    row["has_attachments"] = bool(got["attachments"])
    return {
        **row,
        "body_html": "\n".join(got["html"]),
        "body_text": "" if got["html"] else "\n".join(got["text"]),
        "reply_to": _addrs(h.get("reply-to", "")),
        "attachments": got["attachments"],
        "message_id": h.get("message-id", ""),
        "references": h.get("references", ""),
    }


# ---- IMAP


def _x_cfg(x: ExternalMailAccount) -> imap.Config:
    return imap.Config(x.host, x.port, x.security, x.username, crypto.decrypt(x.secret_enc, x.aad))


SPECIAL = {
    "sentitems": ("\\sent", ("sent", "sent items", "sent messages", "sent mail")),
    "drafts": ("\\drafts", ("drafts", "draft")),
    "archive": ("\\archive", ("archive", "archives", "all mail")),
    "deleteditems": ("\\trash", ("trash", "deleted items", "deleted messages", "bin")),
    "junkemail": ("\\junk", ("spam", "junk", "junk email", "bulk mail")),
}


def _folder_name(folders: list[imap.Folder], logical: str) -> str | None:
    if logical == "inbox":
        return "INBOX"
    flag, names = SPECIAL[logical]
    for f in folders:
        if flag in {x.lower() for x in f.flags}:
            return f.name
    for f in folders:
        tail = f.name.lower().replace("[gmail]/", "").rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        if tail in names:
            return f.name
    return None


def _x_id(folder: str, uid: int) -> str:
    return base64.urlsafe_b64encode(f"{folder}\n{uid}".encode()).decode().rstrip("=")


def _x_unid(mid: str) -> tuple[str, int]:
    try:
        folder, _, uid = (
            base64.urlsafe_b64decode(mid + "=" * (-len(mid) % 4)).decode().partition("\n")
        )
        return folder, int(uid)
    except (ValueError, UnicodeDecodeError) as e:
        raise InboxError(Msg("That message was not found."), 404, "not_found") from e


def _x_row(key: str, folder: str, h: dict[str, Any]) -> dict[str, Any]:
    hdr = BytesHeaderParser(policy=policy.default).parsebytes(h["raw"])
    flags = {f.lower() for f in h["flags"]}

    def g(name: str) -> str:
        return str(hdr.get(name) or "")

    return _row(
        key,
        mid=_x_id(folder, h["uid"]),
        subject=g("subject"),
        sender=g("from"),
        to=g("to"),
        cc=g("cc"),
        at=_iso_date(g("date")),
        read="\\seen" in flags,
        draft="\\draft" in flags,
        attach=bool(h.get("attach")),
        flagged="\\flagged" in flags,
    )


def _x_full(key: str, folder: str, uid: int, raw: bytes, flags: list[str]) -> dict[str, Any]:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    body_html = body_text = ""
    with contextlib.suppress(Exception):
        part = msg.get_body(preferencelist=("html",))
        if part is not None:
            body_html = part.get_content()
    if not body_html:
        with contextlib.suppress(Exception):
            part = msg.get_body(preferencelist=("plain",))
            if part is not None:
                body_text = part.get_content()
    atts = []
    for i, a in enumerate(msg.iter_attachments()):
        data = a.get_payload(decode=True) or b""
        atts.append(
            {
                "id": str(i),
                "name": a.get_filename() or "attachment",
                "size": len(data),
                "content_type": a.get_content_type(),
                "inline": (a.get_content_disposition() or "") == "inline",
            }
        )
    fl = {f.lower() for f in flags}
    row = _row(
        key,
        mid=_x_id(folder, uid),
        subject=str(msg.get("subject") or ""),
        sender=str(msg.get("from") or ""),
        to=str(msg.get("to") or ""),
        cc=str(msg.get("cc") or ""),
        at=_iso_date(str(msg.get("date") or "")),
        read=True,
        draft="\\draft" in fl,
        attach=bool(atts),
        flagged="\\flagged" in fl,
        preview=(_strip_html(body_html) if body_html else body_text)[:300],
    )
    return {
        **row,
        "body_html": body_html,
        "body_text": body_text,
        "reply_to": _addrs(str(msg.get("reply-to") or "")),
        "attachments": atts,
        "message_id": str(msg.get("message-id") or ""),
        "references": str(msg.get("references") or ""),
    }


async def _x_box(x: ExternalMailAccount) -> Any:
    try:
        return await imap.open_box(_x_cfg(x))
    except imap.ImapError as e:
        x.status, x.last_error = "error", str(e.args[0] if e.args else e)[:500]
        raise _x_fail(e) from e


# ---------------------------------------------------------------- reading


async def list_messages(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
    key: str,
    *,
    folder: str = "inbox",
    query: str = "",
    unread: bool = False,
    top: int = PAGE,
    cursor: str = "",
) -> dict[str, Any]:
    """One page of a folder, newest first: {"items": [...], "next": cursor or None}."""
    if folder not in FOLDERS:
        raise InboxError(Msg("That mail folder is not known."), 400, "bad_folder")
    if key == "all":
        return await _all_inboxes(db, workspace_id, user_id, query=query, unread=unread)
    p = await pick(db, workspace_id, user_id, key)
    top = max(1, min(top, 50))
    if p.kind == "ms":
        skip = int(cursor) if cursor.isdigit() else 0
        try:
            g = await graph.for_account(db, p.row)
            rows = await g.folder_messages(
                folder, top=top, skip=skip, unread_only=unread, query=query.strip()
            )
        except MicrosoftError as e:
            raise _ms_fail(e) from e
        items = [{**hub.mail_row(m), "account": key} for m in rows]
        more = len(rows) >= top and not query.strip()
        return {"items": items, "next": str(skip + len(rows)) if more else None}
    if p.kind == "g":
        try:
            rows, nxt = await gmail.page(
                db, p.row, folder, query=query, unread=unread, top=top, page_token=cursor
            )
        except gmail.GmailError as e:
            raise _g_fail(e) from e
        return {"items": [_g_row(key, p.row, m) for m in rows], "next": nxt}
    x: ExternalMailAccount = p.row
    box = await _x_box(x)
    try:
        folders = await imap.run(box.folders)
        name = _folder_name(folders, folder)
        if name is None:
            return {"items": [], "next": None}
        await imap.run(box.select, name)
        uids = await imap.run(box.search_uids, query.strip(), unread)
        offset = int(cursor) if cursor.isdigit() else 0
        newest = list(reversed(uids))[offset : offset + top]
        heads = await imap.run(box.headers, newest)
    except imap.ImapError as e:
        raise _x_fail(e) from e
    finally:
        await imap.run(box.close)
    if x.status != "ok":
        x.status, x.last_error = "ok", None
        await db.commit()
    by_uid = {h["uid"]: h for h in heads}
    items = [_x_row(key, name, by_uid[u]) for u in newest if u in by_uid]
    more = offset + top < len(uids)
    return {"items": items, "next": str(offset + top) if more else None}


async def _all_inboxes(
    db: AsyncSession, workspace_id: str, user_id: str, *, query: str, unread: bool
) -> dict[str, Any]:
    """Every account's newest inbox mail, merged newest first (one page, no paging)."""
    accts = [a for a in await accounts(db, workspace_id, user_id) if a.status == "ok"]
    items: list[dict[str, Any]] = []
    problems: list[dict[str, str]] = []
    for a in accts:  # one at a time: they share the database session
        try:
            got = await list_messages(
                db, workspace_id, user_id, a.key, folder="inbox", query=query, unread=unread, top=15
            )
            items.extend(got["items"])
        except InboxError as e:
            problems.append({"account": a.key, "error": str(e.message)})
    items.sort(key=lambda m: m.get("received_at") or "", reverse=True)
    return {"items": items[:60], "next": None, "problems": problems}


async def get_message(
    db: AsyncSession, workspace_id: str, user_id: str, key: str, mid: str
) -> dict[str, Any]:
    p = await pick(db, workspace_id, user_id, key)
    if p.kind == "ms":
        try:
            g = await graph.for_account(db, p.row)
            m = await g.get_message(mid, body=True, body_type="html")
        except MicrosoftError as e:
            raise _ms_fail(e) from e
        full = hub.mail_full(m)
        return {
            **full,
            "account": key,
            "message_id": m.get("internetMessageId") or "",
            "references": "",
        }
    if p.kind == "g":
        try:
            return _g_full(key, p.row, await gmail.full(db, p.row, mid))
        except gmail.GmailError as e:
            raise _g_fail(e) from e
    folder, uid = _x_unid(mid)
    box = await _x_box(p.row)
    try:
        await imap.run(box.select, folder)
        heads = await imap.run(box.headers, [uid])
        raw = await imap.run(box.fetch, uid)
    except imap.ImapError as e:
        raise _x_fail(e) from e
    finally:
        await imap.run(box.close)
    if not raw:
        raise InboxError(Msg("That message was not found."), 404, "not_found")
    return _x_full(key, folder, uid, raw, heads[0]["flags"] if heads else [])


async def mark_read(
    db: AsyncSession, workspace_id: str, user_id: str, key: str, mid: str, read: bool
) -> None:
    p = await pick(db, workspace_id, user_id, key)
    if p.kind == "ms":
        try:
            g = await graph.for_account(db, p.row)
            await g.mark_read(mid, read)
        except MicrosoftError as e:
            raise _ms_fail(e) from e
        return
    if p.kind == "g":
        try:
            await gmail.set_labels(
                db, p.row, mid, [] if read else ["UNREAD"], ["UNREAD"] if read else []
            )
        except gmail.GmailError as e:
            raise _g_fail(e) from e
        return
    folder, uid = _x_unid(mid)
    box = await _x_box(p.row)
    try:
        await imap.run(box.open_rw, folder)
        await imap.run(box.set_flag, uid, "\\Seen", read)
    except imap.ImapError as e:
        raise _x_fail(e) from e
    finally:
        await imap.run(box.close)


async def trash(db: AsyncSession, workspace_id: str, user_id: str, key: str, mid: str) -> None:
    """Move to the account's trash (never deleted for good here)."""
    p = await pick(db, workspace_id, user_id, key)
    if p.kind == "ms":
        try:
            g = await graph.for_account(db, p.row)
            await g.request(
                "POST", f"{g.root}/messages/{mid}/move", json={"destinationId": "deleteditems"}
            )
        except MicrosoftError as e:
            raise _ms_fail(e) from e
        return
    if p.kind == "g":
        try:
            await gmail.trash(db, p.row, mid)
        except gmail.GmailError as e:
            raise _g_fail(e) from e
        return
    folder, uid = _x_unid(mid)
    box = await _x_box(p.row)
    try:
        target = _folder_name(await imap.run(box.folders), "deleteditems")
        if not target:
            raise InboxError(Msg("This mailbox has no Trash folder."), 409, "no_trash")
        await imap.run(box.open_rw, folder)
        await imap.run(box.move, uid, target)
    except imap.ImapError as e:
        raise _x_fail(e) from e
    finally:
        await imap.run(box.close)


async def attachment(
    db: AsyncSession, workspace_id: str, user_id: str, key: str, mid: str, aid: str
) -> tuple[str, bytes]:
    p = await pick(db, workspace_id, user_id, key)
    if p.kind == "ms":
        try:
            g = await graph.for_account(db, p.row)
            name, _ctype, data = await g.get_attachment_bytes(mid, aid)
        except MicrosoftError as e:
            raise _ms_fail(e) from e
        return name, data
    if p.kind == "g":
        full = await get_message(db, workspace_id, user_id, key, mid)
        meta = next((a for a in full["attachments"] if a["id"] == aid), None)
        if meta is None:
            raise InboxError(Msg("That attachment was not found."), 404, "not_found")
        try:
            return meta["name"], await gmail.attachment(db, p.row, mid, aid)
        except gmail.GmailError as e:
            raise _g_fail(e) from e
    folder, uid = _x_unid(mid)
    box = await _x_box(p.row)
    try:
        await imap.run(box.select, folder)
        raw = await imap.run(box.fetch, uid)
    except imap.ImapError as e:
        raise _x_fail(e) from e
    finally:
        await imap.run(box.close)
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    for i, a in enumerate(msg.iter_attachments()):
        if str(i) == aid:
            return a.get_filename() or "attachment", a.get_payload(decode=True) or b""
    raise InboxError(Msg("That attachment was not found."), 404, "not_found")


# ---------------------------------------------------------------- writing


@dataclass
class Outgoing:
    to: list[str]
    cc: list[str]
    subject: str
    body: str  # plain text the person (or their AI) wrote
    reply_to_id: str = ""
    reply_all: bool = False
    forward_id: str = ""
    draft: bool = False  # keep it in Drafts instead of sending


def _quote(original: dict[str, Any]) -> str:
    text = original.get("body_text") or _strip_html(original.get("body_html") or "")
    who = original.get("from") or {}
    head = f"On {original.get('received_at') or ''}, {who.get('name') or who.get('address') or ''} wrote:"
    return head + "\n" + "\n".join("> " + ln for ln in text.splitlines()[:200])


def _reply_people(
    original: dict[str, Any], me: str, reply_all: bool
) -> tuple[list[str], list[str]]:
    src = original.get("reply_to") or [original.get("from") or {}]
    to = [a["address"] for a in src if a.get("address")]
    cc: list[str] = []
    if reply_all:
        mine = me.lower()
        seen = {*to, mine}
        for a in [*(original.get("to") or []), *(original.get("cc") or [])]:
            addr = (a.get("address") or "").lower()
            if addr and addr not in seen:
                cc.append(addr)
                seen.add(addr)
    return to, cc


def _subject(prefix: str, subject: str) -> str:
    s = subject or ""
    return s if s.lower().startswith(prefix.lower()) else f"{prefix} {s}".strip()


def build_mime(
    sender: str,
    out: Outgoing,
    *,
    in_reply_to: str = "",
    references: str = "",
    quoted: str = "",
) -> EmailMessage:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = ", ".join(out.to)
    if out.cc:
        m["Cc"] = ", ".join(out.cc)
    m["Subject"] = out.subject
    m["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1] or None)
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = f"{references} {in_reply_to}".strip()
    text = out.body + (f"\n\n{quoted}" if quoted else "")
    m.set_content(text)
    m.add_alternative(
        "<div>"
        + html.escape(out.body).replace("\n", "<br>")
        + "</div>"
        + (
            "<br><blockquote style='margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex'>"
            + html.escape(quoted).replace("\n", "<br>")
            + "</blockquote>"
            if quoted
            else ""
        ),
        subtype="html",
    )
    return m


async def send(
    db: AsyncSession, workspace_id: str, user_id: str, key: str, out: Outgoing
) -> dict[str, Any]:
    """Send (or keep as a draft) a new email, a reply or a forward from one account.
    Returns {"sent": bool, "draft_id": str | None}."""
    p = await pick(db, workspace_id, user_id, key)
    original: dict[str, Any] | None = None
    if out.reply_to_id or out.forward_id:
        original = await get_message(
            db, workspace_id, user_id, key, out.reply_to_id or out.forward_id
        )
    if p.kind == "ms":
        return await _ms_send(db, p.row, out)
    me = p.row.email
    if original is not None and out.reply_to_id:
        to, cc = _reply_people(original, me, out.reply_all)
        out.to = out.to or to
        out.cc = out.cc or cc
        out.subject = out.subject or _subject("Re:", original.get("subject") or "")
    elif original is not None:
        out.subject = out.subject or _subject("Fwd:", original.get("subject") or "")
    if not out.to and not out.draft:
        raise InboxError(Msg("Add at least one recipient."), 400, "no_recipient")
    mime = build_mime(
        me,
        out,
        in_reply_to=(original or {}).get("message_id", "") if out.reply_to_id else "",
        references=(original or {}).get("references", "") if out.reply_to_id else "",
        quoted=_quote(original) if original is not None else "",
    )
    if p.kind == "g":
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        thread = str((original or {}).get("conversation_id") or "") if out.reply_to_id else ""
        try:
            if out.draft:
                d = await gmail.draft_raw(db, p.row, raw, thread)
                return {"sent": False, "draft_id": d.get("id")}
            await gmail.send_raw(db, p.row, raw, thread)
        except gmail.GmailError as e:
            raise _g_fail(e) from e
        return {"sent": True, "draft_id": None}
    x: ExternalMailAccount = p.row
    if out.draft:
        await _x_append(x, "drafts", mime, "\\Draft \\Seen")
        return {"sent": False, "draft_id": None}
    if not x.smtp_host:
        raise InboxError(
            Msg("Sending is not set up for this account. Add its SMTP server first."),
            409,
            "no_smtp",
        )
    try:
        await smtp.send(
            x.smtp_host,
            x.smtp_port,
            x.smtp_security,
            x.username,
            crypto.decrypt(x.secret_enc, x.aad),
            mime,
        )
    except imap.ImapError as e:
        raise _x_fail(e) from e
    if "gmail.com" not in x.host:  # Gmail files what SMTP sends by itself
        with contextlib.suppress(InboxError):
            await _x_append(x, "sentitems", mime, "\\Seen")
    return {"sent": True, "draft_id": None}


async def _x_append(x: ExternalMailAccount, logical: str, mime: EmailMessage, flags: str) -> None:
    box = await _x_box(x)
    try:
        name = _folder_name(await imap.run(box.folders), logical)
        if name is None:
            raise InboxError(
                Msg("This mailbox has no {folder} folder.", folder=FOLDER_NAMES[logical]),
                409,
                "no_folder",
            )
        await imap.run(box.append, name, mime.as_bytes(), flags)
    except imap.ImapError as e:
        raise _x_fail(e) from e
    finally:
        await imap.run(box.close)


async def _ms_send(db: AsyncSession, acct: MicrosoftAccount, out: Outgoing) -> dict[str, Any]:
    try:
        g = await graph.for_account(db, acct)
        body = hub.text_html(out.body)
        if out.reply_to_id:
            d = await g.create_reply_draft(out.reply_to_id, body, reply_all=out.reply_all)
        elif out.forward_id:
            if not out.to:
                raise InboxError(Msg("Add at least one recipient."), 400, "no_recipient")
            d = await g.create_forward_draft(out.forward_id, out.to, body)
        else:
            if not out.to and not out.draft:
                raise InboxError(Msg("Add at least one recipient."), 400, "no_recipient")
            d = await g.create_draft(out.to, out.subject.strip(), body, cc=out.cc)
        if not out.draft:
            await g.send_draft(str(d.get("id") or ""))
    except MicrosoftError as e:
        raise _ms_fail(e) from e
    return {"sent": not out.draft, "draft_id": None if not out.draft else d.get("id")}


# ---------------------------------------------------------------- for the AI


def as_text(m: dict[str, Any], limit: int = 12_000) -> str:
    """One message (a full shape) as plain data for a model."""

    def who(a: dict[str, str]) -> str:
        return formataddr((a.get("name") or "", a.get("address") or ""))

    body = m.get("body_text") or _strip_html(m.get("body_html") or "")
    atts = ", ".join(a.get("name", "") for a in m.get("attachments") or [])
    return (
        f"From: {who(m.get('from') or {})}\n"
        f"To: {', '.join(who(a) for a in m.get('to') or [])}\n"
        + (f"Cc: {', '.join(who(a) for a in m.get('cc') or [])}\n" if m.get("cc") else "")
        + f"Date: {m.get('received_at') or ''}\nSubject: {m.get('subject') or ''}\n"
        + (f"Attachments: {atts}\n" if atts else "")
        + f"\n{body[:limit]}"
    )


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


async def first_account(db: AsyncSession, workspace_id: str, user_id: str) -> Account | None:
    got = await accounts(db, workspace_id, user_id)
    return next((a for a in got if a.primary), got[0] if got else None)


__all__ = [
    "FOLDERS",
    "Account",
    "InboxError",
    "Outgoing",
    "accounts",
    "as_text",
    "attachment",
    "first_account",
    "get_message",
    "list_messages",
    "mark_read",
    "pick",
    "send",
    "trash",
]

_ = asyncio  # kept for callers that gather over accounts
