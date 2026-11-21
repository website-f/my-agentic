"""My Agentic: the Inbox, every email account in one page (agentic/inbox/service.py).

GET    /api/inbox/accounts                       my accounts (Microsoft, Gmail, IMAP) + how to add
DELETE /api/inbox/accounts/{key}                 disconnect a Gmail or IMAP account
GET    /api/inbox/messages?account=&folder=&q=   a folder page (account=all: every inbox merged)
GET    /api/inbox/messages/{id}?account=         one message
POST   /api/inbox/messages/{id}/read             mark read / unread
POST   /api/inbox/messages/{id}/trash            move to the account's trash
GET    /api/inbox/messages/{id}/attachments/{a}  download an attachment
POST   /api/inbox/send                           new mail, reply, reply all, forward or a draft
POST   /api/inbox/ai                             summarize, draft a reply, improve, write new

Everything is the signed-in owner's own (service.pick checks each key). The AI only writes text
for the composer: the person presses Send (or their agent sends with its inbox_send tool,
which asks for approval by default).
"""

import urllib.parse
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db import get_db
from ...core.fence import fence
from ...i18n import render
from ...inbox import service
from ...inbox.service import InboxError, Outgoing
from ...microsoft import app as ms_app
from ...services import audit
from ..deps import Principal, api_error, ensure_allowance, require

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _fail(e: InboxError) -> Exception:
    msg = e.message
    return api_error(e.status, e.code, render(msg) if not isinstance(msg, str) else msg)


@router.get("/accounts")
async def list_accounts(
    principal: Principal = Depends(require("read")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from ...assistants import gmail

    ms = await ms_app.load(db, principal.workspace_id)
    return {
        "accounts": [
            a.dict() for a in await service.accounts(db, principal.workspace_id, principal.user.id)
        ],
        "folders": [{"id": f, "name": service.FOLDER_NAMES[f]} for f in service.FOLDERS],
        "connect": {
            "microsoft": bool(ms.configured),
            "google": await gmail.app_credentials(db, principal.workspace_id) is not None,
            "imap": True,
        },
    }


@router.delete("/accounts/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_account(
    key: str,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Gmail (Google access revoked) or IMAP (the stored password deleted). A Microsoft account
    is removed with DELETE /api/integrations/microsoft/accounts/{id}."""
    from ...assistants import gmail

    try:
        p = await service.pick(db, principal.workspace_id, principal.user.id, key)
    except InboxError as e:
        raise _fail(e) from e
    if p.kind == "ms":
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "use_microsoft",
            "Remove a Microsoft account from its own menu.",
        )
    if p.kind == "g":
        await gmail.revoke(db, p.row)
    await db.delete(p.row)
    await audit.record(
        db, principal.workspace_id, principal.actor, "inbox.account_removed", target=key
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/messages")
async def messages(
    account: str = Query(min_length=1, max_length=60),
    folder: str = Query(default="inbox"),
    q: str = Query(default="", max_length=200),
    unread: bool = Query(default=False),
    cursor: str = Query(default="", max_length=500),
    top: int = Query(default=25, ge=1, le=50),
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await service.list_messages(
            db,
            principal.workspace_id,
            principal.user.id,
            account,
            folder=folder,
            query=q,
            unread=unread,
            top=top,
            cursor=cursor,
        )
    except InboxError as e:
        raise _fail(e) from e


@router.get("/messages/{mid}")
async def message(
    mid: str,
    account: str = Query(min_length=1, max_length=60),
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await service.get_message(
            db, principal.workspace_id, principal.user.id, account, mid
        )
    except InboxError as e:
        raise _fail(e) from e


class ReadIn(BaseModel):
    account: str = Field(min_length=1, max_length=60)
    read: bool = True


@router.post("/messages/{mid}/read")
async def mark_read(
    mid: str,
    body: ReadIn,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    try:
        await service.mark_read(
            db, principal.workspace_id, principal.user.id, body.account, mid, body.read
        )
    except InboxError as e:
        raise _fail(e) from e
    return {"read": body.read}


class AccountIn(BaseModel):
    account: str = Field(min_length=1, max_length=60)


@router.post("/messages/{mid}/trash")
async def trash(
    mid: str,
    body: AccountIn,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    try:
        await service.trash(db, principal.workspace_id, principal.user.id, body.account, mid)
    except InboxError as e:
        raise _fail(e) from e
    return {"trashed": True}


@router.get("/messages/{mid}/attachments/{aid}")
async def attachment(
    mid: str,
    aid: str,
    account: str = Query(min_length=1, max_length=60),
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        name, data = await service.attachment(
            db, principal.workspace_id, principal.user.id, account, mid, aid
        )
    except InboxError as e:
        raise _fail(e) from e
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


class SendIn(BaseModel):
    account: str = Field(min_length=1, max_length=60)
    to: list[EmailStr] = Field(default_factory=list, max_length=100)
    cc: list[EmailStr] = Field(default_factory=list, max_length=100)
    subject: str = Field(default="", max_length=400)
    body: str = Field(default="", max_length=50_000)
    reply_to_id: str = Field(default="", max_length=500)
    reply_all: bool = False
    forward_id: str = Field(default="", max_length=500)
    draft: bool = False


@router.post("/send")
async def send(
    body: SendIn,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not body.draft and not body.body.strip() and not body.forward_id:
        raise api_error(status.HTTP_400_BAD_REQUEST, "empty", "Write the message first.")
    out = Outgoing(
        to=[str(a) for a in body.to],
        cc=[str(a) for a in body.cc],
        subject=body.subject.strip(),
        body=body.body,
        reply_to_id=body.reply_to_id,
        reply_all=body.reply_all,
        forward_id=body.forward_id,
        draft=body.draft,
    )
    try:
        got = await service.send(db, principal.workspace_id, principal.user.id, body.account, out)
    except InboxError as e:
        raise _fail(e) from e
    if got.get("sent"):
        kind = "reply" if body.reply_to_id else "forward" if body.forward_id else "new"
        await audit.record(
            db,
            principal.workspace_id,
            principal.actor,
            "inbox.sent",
            target=body.account,
            after={"kind": kind, "to": len(out.to), "cc": len(out.cc)},
        )
        await db.commit()
    return got


class AiIn(BaseModel):
    account: str = Field(default="", max_length=60)
    message_id: str = Field(default="", max_length=500)
    action: Literal["summarize", "reply", "improve", "compose", "ask"] = "summarize"
    instructions: str = Field(default="", max_length=2000)
    draft: str = Field(default="", max_length=20_000)
    tone: str = Field(default="", max_length=20)
    lang: str = Field(default="", max_length=8)


@router.post("/ai")
async def ai(
    body: AiIn,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Summaries and drafts for the page (nothing is sent). The email is fenced as data."""
    from ...engine import gateway
    from ...microsoft import assist

    await ensure_allowance(db, principal)
    mail = ""
    if body.message_id and body.account:
        try:
            m = await service.get_message(
                db, principal.workspace_id, principal.user.id, body.account, body.message_id
            )
        except InboxError as e:
            raise _fail(e) from e
        mail = fence(service.as_text(m))
    me = principal.user.name or principal.user.email
    rule = assist.lang_rule(body.lang)
    tone = assist.tone_of(body.tone)
    ask = body.instructions.strip()
    if body.action == "summarize":
        if not mail:
            raise api_error(status.HTTP_400_BAD_REQUEST, "no_message", "Open an email first.")
        prompt = (
            f"Summarize this email for {me} in 2-5 short bullet points: what it is, what the "
            f"sender wants, any dates, amounts or deadlines, and whether {me} must act.\n\n{mail}"
        )
    elif body.action == "reply":
        if not mail:
            raise api_error(status.HTTP_400_BAD_REQUEST, "no_message", "Open an email first.")
        prompt = (
            f"Write the reply {me} will send to this email. Tone: {tone}. {rule} Only the body "
            f"text (no subject line, no placeholders like [Name] unless the name is unknown), "
            f"signed as {me}." + (f"\nWhat {me} wants to say: {ask}" if ask else "") + f"\n\n{mail}"
        )
    elif body.action == "improve":
        if not body.draft.strip():
            raise api_error(status.HTTP_400_BAD_REQUEST, "no_draft", "Write something first.")
        prompt = (
            f"Improve this email draft by {me}: clear, correct, {tone}. Keep its meaning and "
            f"language. Only the improved body text.\n\nDraft:\n{fence(body.draft)}"
            + (f"\n\nIt answers:\n{mail}" if mail else "")
            + (f"\n\nAlso: {ask}" if ask else "")
        )
    elif body.action == "compose":
        if not ask:
            raise api_error(status.HTTP_400_BAD_REQUEST, "no_ask", "Say what the email is about.")
        prompt = (
            f"Write a new email for {me}. Tone: {tone}. {rule} First line 'Subject: ...', then "
            f"a blank line, then the body, signed as {me}.\nWhat it is about: {ask}"
        )
    else:
        if not ask:
            raise api_error(status.HTTP_400_BAD_REQUEST, "no_ask", "Type a question.")
        prompt = f"{me} asks: {ask}" + (f"\n\nAbout this email:\n{mail}" if mail else "")
    try:
        text = await assist.ask(
            db, principal.workspace_id, prompt, task=f"inbox.{body.action}", max_tokens=1200
        )
    except gateway.GatewayUnavailable as e:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ai_unavailable",
            "The AI is not answering right now: {why}",
            why=str(e)[:200],
        ) from e
    out = assist.clean_draft(text) if body.action in ("reply", "improve", "compose") else text
    subject = ""
    if body.action == "compose" and out.lower().startswith("subject:"):
        first, _, rest = out.partition("\n")
        subject, out = first.split(":", 1)[1].strip(), rest.strip()
    return {"text": out, "subject": subject}
