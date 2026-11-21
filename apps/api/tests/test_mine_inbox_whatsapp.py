# ruff: noqa: E501
"""My Agentic: one Inbox over every email account, and WhatsApp group mentions and chat rules.

The IMAP server, SMTP server, WAHA and the AI are fakes; nothing real is called."""

import json
from datetime import UTC, datetime
from email.message import EmailMessage
from email.parser import BytesParser
from email import policy

import pytest
from sqlalchemy import select

from agentic.channels import deliver, wa_bot, whatsapp
from agentic.core import crypto
from agentic.core.db import SessionLocal
from agentic.mailbox import imap, smtp
from agentic.mailbox.models import WaChatRule
from agentic.models import Channel, ChannelLink, Delivery, Membership

from .conftest import csrf, setup_owner


def _mail(subject: str, sender: str, date: str, body: str = "Hello there", attach: bool = False) -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, "me@example.com", subject, date
    m["Message-ID"] = f"<{subject.replace(' ', '')}@mail.example.com>"
    m.set_content(body)
    if attach:
        m.add_attachment(b"%PDF-1.4 x", maintype="application", subtype="pdf", filename="q.pdf")
    return m.as_bytes()


class Box:
    """An IMAP server with INBOX, Sent, Drafts and Trash."""

    def __init__(self) -> None:
        self.boxes = {
            "INBOX": {
                1: (_mail("Old news", "Ali <ali@example.com>", "Mon, 02 Nov 2026 09:00:00 +0800"), ["\\Seen"]),
                2: (_mail("Quote please", "Siti <siti@client.example.com>", "Fri, 20 Nov 2026 10:00:00 +0800", attach=True), []),
            },
            "Sent": {},
            "Drafts": {},
            "Trash": {},
        }
        self.sel = ""
        self.appended: list[tuple[str, bytes, str]] = []

    def folders(self):
        return [
            imap.Folder("INBOX", frozenset()),
            imap.Folder("Sent", frozenset({"\\Sent"})),
            imap.Folder("Drafts", frozenset({"\\Drafts"})),
            imap.Folder("Trash", frozenset({"\\Trash"})),
        ]

    def select(self, name):
        self.sel = name
        return 7, len(self.boxes[name])

    def open_rw(self, name):
        self.sel = name
        return len(self.boxes[name])

    def search_uids(self, query="", unread=False):
        out = []
        for uid, (raw, flags) in self.boxes[self.sel].items():
            if unread and "\\Seen" in flags:
                continue
            if query and query.lower() not in raw.decode().lower():
                continue
            out.append(uid)
        return sorted(out)

    def headers(self, uids):
        out = []
        for u in uids:
            raw, flags = self.boxes[self.sel][u]
            head = raw.split(b"\n\n", 1)[0]
            out.append({"uid": u, "flags": list(flags), "size": len(raw), "attach": b"q.pdf" in raw, "raw": head})
        return out

    def fetch(self, uid):
        return self.boxes[self.sel][uid][0]

    def set_flag(self, uid, flag, on):
        flags = self.boxes[self.sel][uid][1]
        if on and flag not in flags:
            flags.append(flag)
        if not on and flag in flags:
            flags.remove(flag)

    def append(self, folder, message, flags=""):
        self.appended.append((folder, message, flags))

    def move(self, uid, folder):
        self.boxes[folder][uid] = self.boxes[self.sel].pop(uid)

    def close(self):
        pass


@pytest.fixture
def box(monkeypatch):
    b = Box()

    async def opener(cfg):
        return b

    monkeypatch.setattr(imap, "open_box", opener)
    return b


@pytest.fixture
def sent(monkeypatch):
    got: list[dict] = []

    async def fake_send(host, port, security, user, pw, msg):
        got.append({"host": host, "port": port, "security": security, "user": user, "pw": pw, "msg": msg})

    monkeypatch.setattr(smtp, "send", fake_send)
    return got


async def _imap_account(client) -> str:
    r = await client.post(
        "/api/mail-accounts",
        json={"email": "me@example.com", "provider": "cpanel", "host": "mail.example.com", "password": "app-pass-123", "label": "Work"},
        headers=csrf(client),
    )
    assert r.status_code == 201, r.text
    assert r.json()["smtp_host"] == "smtp.example.com"
    assert r.json()["can_send"] is True
    return f"x:{r.json()['id']}"


async def test_inbox_lists_reads_marks_and_replies_over_imap(client, box, sent):
    await setup_owner(client)
    key = await _imap_account(client)

    r = await client.get("/api/inbox/accounts")
    assert r.status_code == 200
    accts = r.json()["accounts"]
    assert [a["key"] for a in accts] == [key]
    assert accts[0]["primary"] is True and accts[0]["label"] == "Work"

    r = await client.get("/api/inbox/messages", params={"account": key})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [m["subject"] for m in items] == ["Quote please", "Old news"]  # newest first
    first = items[0]
    assert first["is_read"] is False and first["has_attachments"] is True
    assert first["from"] == {"name": "Siti", "address": "siti@client.example.com"}

    r = await client.get("/api/inbox/messages", params={"account": key, "unread": True})
    assert [m["subject"] for m in r.json()["items"]] == ["Quote please"]
    r = await client.get("/api/inbox/messages", params={"account": key, "q": "old"})
    assert [m["subject"] for m in r.json()["items"]] == ["Old news"]

    r = await client.get(f"/api/inbox/messages/{first['id']}", params={"account": key})
    assert r.status_code == 200
    full = r.json()
    assert "Hello there" in full["body_text"]
    assert [a["name"] for a in full["attachments"]] == ["q.pdf"]

    r = await client.get(f"/api/inbox/messages/{first['id']}/attachments/0", params={"account": key})
    assert r.status_code == 200 and r.content == b"%PDF-1.4 x"

    r = await client.post(f"/api/inbox/messages/{first['id']}/read", json={"account": key, "read": True}, headers=csrf(client))
    assert r.status_code == 200
    assert "\\Seen" in box.boxes["INBOX"][2][1]

    r = await client.post(
        "/api/inbox/send",
        json={"account": key, "reply_to_id": first["id"], "body": "Here it is."},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["sent"] is True
    (s,) = sent
    assert (s["host"], s["port"], s["security"], s["pw"]) == ("smtp.example.com", 465, "ssl", "app-pass-123")
    msg = s["msg"]
    assert msg["To"] == "siti@client.example.com"
    assert msg["Subject"] == "Re: Quote please"
    assert msg["In-Reply-To"] == "<Quoteplease@mail.example.com>"
    assert "Here it is." in msg.get_body(preferencelist=("plain",)).get_content()
    assert [a[0] for a in box.appended] == ["Sent"]  # a copy in Sent (not Gmail)

    r = await client.post(
        "/api/inbox/send",
        json={"account": key, "to": ["boss@example.com"], "subject": "Plan", "body": "Draft only", "draft": True},
        headers=csrf(client),
    )
    assert r.json()["sent"] is False
    assert box.appended[-1][0] == "Drafts" and "\\Draft" in box.appended[-1][2]
    assert len(sent) == 1

    r = await client.post(f"/api/inbox/messages/{first['id']}/trash", json={"account": key}, headers=csrf(client))
    assert r.status_code == 200 and 2 in box.boxes["Trash"]

    r = await client.get("/api/inbox/messages", params={"account": "all"})
    assert [m["account"] for m in r.json()["items"]] == [key]


async def test_inbox_keys_are_the_owners_only(client, box):
    await setup_owner(client)
    r = await client.get("/api/inbox/messages", params={"account": "x:xm_nothere"})
    assert r.status_code == 404
    r = await client.get("/api/inbox/messages", params={"account": "zz:1"})
    assert r.status_code == 404


async def test_agent_tools_check_read_and_draft(client, box, sent):
    from agentic.agents.inbox_tools import INBOX_TOOLS
    from agentic.agents.tools import TOOLS, ToolContext
    from agentic.models import Agent, Branch, Workspace

    await setup_owner(client)
    key = await _imap_account(client)
    assert TOOLS["inbox_send"].default_mode == "ask" and TOOLS["inbox_draft"].default_mode == "allow"
    by = {t.name: t for t in INBOX_TOOLS}
    async with SessionLocal() as db:
        ws = await db.scalar(select(Workspace))
        branch = await db.scalar(select(Branch).where(Branch.workspace_id == ws.id))
        assert branch is not None  # setup made the owner's one company
        agent = Agent(workspace_id=ws.id, branch_id=branch.id, name="Aide", role="Assistant", slug="aide")
        db.add(agent)
        await db.commit()
        ctx = ToolContext(db=db, agent=agent, workspace=ws, task=None)
        out = await by["inbox_check"].handler(ctx, {})
        assert "Quote please" in out and "<<<" in out  # fenced as data
        mid = out.split("id=")[1].split()[0]
        out = await by["inbox_read"].handler(ctx, {"id": mid, "account": "me@example.com"})
        assert "Hello there" in out
        out = await by["inbox_draft"].handler(ctx, {"mode": "reply", "reply_to_id": mid, "body": "Will do"})
        assert "Drafts" in out and not sent
        out = await by["inbox_send"].handler(ctx, {"mode": "new", "to": ["a@b.example.com"], "subject": "Hi", "body": "Yo", "account": key})
        assert out.startswith("Sent") and len(sent) == 1


# ---------------------------------------------------------------- WhatsApp


ME = {"id": "60111000111@c.us", "lid": "99887766@lid", "pushName": "My Number"}


def _group_payload(text: str, *, mention: list[str] | None = None, reply_participant: str = "", sender: str = "60122223333@c.us", from_me: bool = False) -> dict:
    ctx = {}
    if mention:
        ctx["mentionedJid"] = mention
    return {
        "event": "message.any",
        "me": ME,
        "payload": {
            "id": "false_120363@g.us_ABC",
            "from": "120363000@g.us",
            "fromMe": from_me,
            "participant": sender,
            "body": text,
            **({"replyTo": {"id": "X", "participant": reply_participant}} if reply_participant else {}),
            "_data": {"pushName": "Boss", "message": {"extendedTextMessage": {"text": text, "contextInfo": ctx}}},
        },
    }


def test_group_messages_count_only_when_they_address_the_number():
    got = whatsapp.parse_waha(_group_payload("@60111000111 summarise my inbox", mention=["60111000111@s.whatsapp.net"]))
    assert len(got) == 1
    m = got[0]
    assert (m.chat, m.sender, m.group, m.addressed) == ("120363000@g.us", "60122223333@c.us", True, True)
    # the privacy id (LID) mention counts too
    assert whatsapp.parse_waha(_group_payload("hey @99887766", mention=["99887766@lid"]))
    # a reply to the number's own message counts
    assert whatsapp.parse_waha(_group_payload("and tomorrow?", reply_participant="60111000111@c.us"))
    # anything else in the group is ignored, and so is the number itself
    assert whatsapp.parse_waha(_group_payload("lunch anyone?")) == []
    assert whatsapp.parse_waha(_group_payload("@60111000111 hi", mention=["60111000111@c.us"], from_me=True)) == []


async def _wa_setup(client) -> tuple[str, str]:
    await setup_owner(client)
    async with SessionLocal() as db:
        owner = await db.scalar(select(Membership).where(Membership.role == "owner"))
        ch = Channel(workspace_id=owner.workspace_id, kind="whatsapp", name="WhatsApp", config_enc="")
        db.add(ch)
        await db.flush()
        ch.config_enc = crypto.encrypt(json.dumps({"provider": "waha", "base_url": "http://waha.fake", "api_key": "k", "session": "default"}), f"channel:{ch.id}")
        db.add(ChannelLink(channel_id=ch.id, user_id=owner.user_id, external_id="60122223333@c.us", chat_id="60122223333@c.us", display="me", created_at=datetime.now(UTC)))
        await db.commit()
        return ch.id, owner.user_id


async def test_a_stranger_mentioning_the_number_gets_silence_unless_the_chat_allows_everyone(client, monkeypatch):
    ch_id, _ = await _wa_setup(client)
    asked: list[list[dict]] = []

    class Reply:
        content = "Fitri will get back to you soon."

    async def fake_chat_first(db, ws, groups, messages, **kw):
        asked.append(messages)
        return Reply()

    monkeypatch.setattr(wa_bot.gateway, "chat_first", fake_chat_first)

    async def no_send(db, did):
        return None

    monkeypatch.setattr(deliver, "deliver", no_send)
    stranger = _group_payload("@60111000111 what is Fitri's salary?", mention=["60111000111@c.us"], sender="60177778888@c.us")
    (msg,) = whatsapp.parse_waha(stranger)
    async with SessionLocal() as db:
        ch = await db.get(Channel, ch_id)
        await wa_bot.handle(db, ch, msg)
    assert asked == []  # default rule "me": strangers get nothing

    async with SessionLocal() as db:
        db.add(WaChatRule(channel_id=ch_id, chat_id="120363000@g.us", mode="everyone", name="Family"))
        await db.commit()
    msg.message_id = "second"
    async with SessionLocal() as db:
        ch = await db.get(Channel, ch_id)
        await wa_bot.handle(db, ch, msg)
    assert len(asked) == 1
    system = asked[0][0]["content"]
    assert "NOT" in system and "no access" in system  # a guest: no tools, no private data
    assert "<<<" in asked[0][1]["content"]  # their words are fenced
    async with SessionLocal() as db:
        d = await db.scalar(select(Delivery).where(Delivery.channel == "whatsapp"))
    assert d.target == f"{ch_id}:120363000@g.us"  # answered in the group
    assert d.payload["reply_to"] == "second"  # quoting the ask
    assert "Fitri will get back" in d.payload["text"]


async def test_off_rule_keeps_the_ai_quiet_and_the_page_saves_rules(client, monkeypatch):
    ch_id, _ = await _wa_setup(client)
    r = await client.put(
        "/api/wa/chats/120363000@g.us/rule",
        json={"mode": "off", "instructions": "", "name": "Family"},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "off"
    r = await client.get("/api/wa/chats/120363000@g.us/rule")
    assert r.json() == {"mode": "off", "agent_id": None, "instructions": "", "saved": True}

    called = []

    async def boom(*a, **k):
        called.append(1)
        raise AssertionError("the AI must not run")

    monkeypatch.setattr(wa_bot.runtime, "chat_turn", boom)
    (msg,) = whatsapp.parse_waha(_group_payload("@60111000111 hi", mention=["60111000111@c.us"]))
    async with SessionLocal() as db:
        ch = await db.get(Channel, ch_id)
        await wa_bot.handle(db, ch, msg)
    assert called == []


_ = (BytesParser, policy)
