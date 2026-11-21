"""My Agentic: the WhatsApp page, chatting as the connected number (WAHA), and where the AI
answers.

GET  /api/wa/status                          the number: connected?, its id, my linked phones
GET  /api/wa/chats?limit=&offset=            newest chats first, each with its AI rule
GET  /api/wa/chats/{chat}/messages?limit=    a chat's newest messages (oldest first)
POST /api/wa/chats/{chat}/messages           send as the number ({text, reply_to})
POST /api/wa/chats/{chat}/seen               mark it read
GET  /api/wa/chats/{chat}/rule               when the AI answers there
PUT  /api/wa/chats/{chat}/rule               {mode: off|me|everyone, agent_id, instructions, name}
POST /api/wa/chats/{chat}/ai                 draft a reply / summarize the chat (nothing is sent)

Only the owner uses this (single user). Messages typed here carry the invisible mark, so the
number's own AI never answers them.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...channels import deliver, whatsapp
from ...core.db import get_db
from ...core.fence import fence
from ...mailbox.models import WaChatRule
from ...models import Agent, Channel, ChannelLink
from ...services import audit
from ..deps import Principal, api_error, ensure_allowance, require

router = APIRouter(prefix="/api/wa", tags=["whatsapp-chats"])


async def _channel(db: AsyncSession, principal: Principal) -> tuple[Channel, whatsapp.Config]:
    rows = (
        await db.scalars(
            select(Channel)
            .where(
                Channel.workspace_id == principal.workspace_id,
                Channel.kind == "whatsapp",
                Channel.enabled.is_(True),
            )
            .order_by(Channel.created_at)
        )
    ).all()
    for ch in rows:
        cfg = whatsapp.Config.load(deliver.channel_token(ch))
        if cfg.provider == "waha":
            return ch, cfg
    raise api_error(
        status.HTTP_409_CONFLICT,
        "no_whatsapp",
        "Connect WhatsApp first (Settings > Channels > WhatsApp, scan the QR code).",
    )


def _wa_fail(e: Exception) -> Exception:
    if isinstance(e, whatsapp.WhatsAppError) and e.status == 404:
        return api_error(status.HTTP_404_NOT_FOUND, "not_found", "That chat was not found.")
    return api_error(
        status.HTTP_502_BAD_GATEWAY,
        "whatsapp_error",
        "WhatsApp did not answer: {why}",
        why=str(e)[:200],
    )


def _rule_out(r: WaChatRule | None) -> dict[str, Any]:
    if r is None:
        return {"mode": "me", "agent_id": None, "instructions": "", "saved": False}
    return {
        "mode": r.mode,
        "agent_id": r.agent_id,
        "instructions": r.instructions,
        "saved": True,
    }


@router.get("/status")
async def wa_status(
    principal: Principal = Depends(require("read")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        ch, cfg = await _channel(db, principal)
    except Exception:  # noqa: BLE001 - not connected is an answer, not an error
        return {
            "connected": False,
            "channel_id": None,
            "status": "MISSING",
            "me": None,
            "links": [],
        }
    try:
        st = await whatsapp.waha_status(cfg)
    except Exception:  # noqa: BLE001
        st = {"status": "UNREACHABLE", "me": None}
    links = (
        await db.scalars(
            select(ChannelLink).where(
                ChannelLink.channel_id == ch.id, ChannelLink.user_id == principal.user.id
            )
        )
    ).all()
    return {
        "connected": st["status"] == "WORKING",
        "channel_id": ch.id,
        "status": st["status"],
        "me": st.get("me"),
        "links": [{"id": x.id, "number": x.external_id.split("@")[0]} for x in links],
    }


@router.get("/chats")
async def chats(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=5000),
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ch, cfg = await _channel(db, principal)
    try:
        rows = await whatsapp.waha_chats(cfg, limit, offset)
    except Exception as e:  # noqa: BLE001
        raise _wa_fail(e) from e
    rules = {
        r.chat_id: r
        for r in (await db.scalars(select(WaChatRule).where(WaChatRule.channel_id == ch.id))).all()
    }
    for c in rows:
        c["ai"] = _rule_out(rules.get(c["id"]))["mode"]
    return {"chats": rows, "next": offset + len(rows) if len(rows) >= limit else None}


@router.get("/chats/{chat_id}/messages")
async def messages(
    chat_id: str,
    limit: int = Query(default=60, ge=1, le=200),
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, cfg = await _channel(db, principal)
    try:
        return {"messages": await whatsapp.waha_messages(cfg, chat_id, limit)}
    except Exception as e:  # noqa: BLE001
        raise _wa_fail(e) from e


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    reply_to: str = Field(default="", max_length=200)


@router.post("/chats/{chat_id}/messages")
async def send(
    chat_id: str,
    body: SendIn,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ch, cfg = await _channel(db, principal)
    try:
        mid = await whatsapp.waha_send(cfg, chat_id, body.text, body.reply_to)
    except Exception as e:  # noqa: BLE001
        raise _wa_fail(e) from e
    await audit.record(
        db, principal.workspace_id, principal.actor, "whatsapp.sent", target=chat_id[:200]
    )
    await db.commit()
    return {"id": mid}


@router.post("/chats/{chat_id}/seen")
async def seen(
    chat_id: str,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    _, cfg = await _channel(db, principal)
    try:
        await whatsapp.waha_seen(cfg, chat_id)
    except Exception:  # noqa: BLE001 - read receipts are best effort
        return {"seen": False}
    return {"seen": True}


@router.get("/chats/{chat_id}/rule")
async def get_rule(
    chat_id: str,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ch, _ = await _channel(db, principal)
    r = await db.scalar(
        select(WaChatRule).where(WaChatRule.channel_id == ch.id, WaChatRule.chat_id == chat_id)
    )
    return _rule_out(r)


class RuleIn(BaseModel):
    mode: Literal["off", "me", "everyone"]
    agent_id: str | None = Field(default=None, max_length=40)
    instructions: str = Field(default="", max_length=2000)
    name: str = Field(default="", max_length=200)


@router.put("/chats/{chat_id}/rule")
async def put_rule(
    chat_id: str,
    body: RuleIn,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ch, _ = await _channel(db, principal)
    if body.agent_id:
        a = await db.get(Agent, body.agent_id)
        if a is None or a.workspace_id != principal.workspace_id:
            raise api_error(status.HTTP_404_NOT_FOUND, "agent_not_found", "That agent is not here.")
    r = await db.scalar(
        select(WaChatRule).where(WaChatRule.channel_id == ch.id, WaChatRule.chat_id == chat_id)
    )
    if r is None:
        r = WaChatRule(channel_id=ch.id, chat_id=chat_id[:120])
        db.add(r)
    r.mode = body.mode
    r.agent_id = body.agent_id or None
    r.instructions = body.instructions.strip()
    r.name = body.name.strip()[:200]
    await audit.record(
        db,
        principal.workspace_id,
        principal.actor,
        "whatsapp.rule_set",
        target=chat_id[:200],
        after={"mode": body.mode, "agent_id": body.agent_id},
    )
    await db.commit()
    return _rule_out(r)


class AiIn(BaseModel):
    action: Literal["draft", "summarize"] = "draft"
    instructions: str = Field(default="", max_length=2000)
    name: str = Field(default="", max_length=200)


@router.post("/chats/{chat_id}/ai")
async def ai(
    chat_id: str,
    body: AiIn,
    principal: Principal = Depends(require("read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """A reply for the composer, or what the chat is about. Nothing is sent."""
    from ...engine import gateway
    from ...microsoft import assist

    await ensure_allowance(db, principal)
    _, cfg = await _channel(db, principal)
    try:
        msgs = await whatsapp.waha_messages(cfg, chat_id, 40)
    except Exception as e:  # noqa: BLE001
        raise _wa_fail(e) from e
    me = principal.user.name or "Me"
    lines = [
        f"[{m.get('at') or ''}] {'Me' if m['from_me'] else (m.get('sender_name') or m.get('sender') or '?')}: "
        f"{m.get('text') or ('[media]' if m.get('media') else '')}"
        for m in msgs
    ]
    convo = fence("\n".join(lines)[-10_000:])
    where = f" with {body.name}" if body.name else ""
    if body.action == "summarize":
        prompt = (
            f"Summarize this WhatsApp chat{where} for {me} in a few short bullet points: what "
            f"is going on, what people want from {me}, and anything {me} must do.\n\n{convo}"
        )
    else:
        ask = body.instructions.strip()
        prompt = (
            f"Write {me}'s next WhatsApp message in this chat{where}: short, natural, in the "
            "language the chat uses. Only the message text."
            + (f"\nWhat {me} wants to say: {ask}" if ask else "")
            + f"\n\n{convo}"
        )
    try:
        text = await assist.ask(
            db, principal.workspace_id, prompt, task=f"whatsapp.{body.action}", max_tokens=700
        )
    except gateway.GatewayUnavailable as e:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ai_unavailable",
            "The AI is not answering right now: {why}",
            why=str(e)[:200],
        ) from e
    return {"text": assist.clean_draft(text) if body.action == "draft" else text}
