# ruff: noqa: E501
"""P102: once a person connected Microsoft 365, their own AI can read their Teams chats and
Outlook mail, and draft a reply or a new message to anyone, in Teams or by email (reply,
reply-all, forward); nothing is sent until that person approves it, and then it really goes
out through Microsoft Graph. A person's AI never reads or sends from someone else's mailbox
or chats, and nobody else (not even a manager) approves a message sent as them.

Starting a new Teams chat needs Chat.Create, which each person allows once ("Allow new Teams
chats"): it is never asked for at everyone's sign-in, and a refresh never asks for it unless
the person granted it, so connections made before keep working.

Microsoft is faked (httpx MockTransport, or the mail features' FakeGraph): nothing real is
called.
"""

import json
from urllib.parse import parse_qs

import httpx
from sqlalchemy import select

from agentic.agents import policy, runtime
from agentic.agents.tools import ToolContext
from agentic.core import crypto
from agentic.core.db import SessionLocal
from agentic.core.valkey import valkey
from agentic.microsoft import app, auth, http
from agentic.models import Agent, AuditLog, EmailDraft, MicrosoftAccount, Workspace

from .conftest import csrf
from .test_agents import llm, office, temporal  # noqa: F401
from .test_mail_features import (  # noqa: F401
    FakeGraph,
    mail_item,
    outlook,
    personal_account,
    run_tool,
    staff_with_twin,
)
from .test_microsoft import (  # noqa: F401
    GRANTED,
    TENANT,
    configure,
    connect,
    make_agent,
    ms,
    my_account,
    user_id,
)

CHAT_CREATE = "https://graph.microsoft.com/Chat.Create"
CHATS = [
    {
        "id": "19:chat-1",
        "topic": None,
        "chatType": "oneOnOne",
        "members": [
            {"displayName": "Boss One", "email": "boss@maju.example.com"},
            {"displayName": "Siti Aminah", "email": "siti@maju.example.com"},
        ],
        "lastMessagePreview": {"createdDateTime": "2026-11-13T08:00:00Z",
                               "from": {"user": {"displayName": "Siti Aminah"}},
                               "body": {"content": "<p>Tender pack today?</p>"}},
    }
]  # fmt: skip
MESSAGES = [
    {"id": "2", "messageType": "message", "createdDateTime": "2026-11-13T08:00:00Z",
     "from": {"user": {"displayName": "Siti Aminah"}}, "body": {"content": "<p>Tender pack today?</p>"}},
    {"id": "1", "messageType": "message", "createdDateTime": "2026-11-13T07:55:00Z",
     "from": {"user": {"displayName": "Boss One"}}, "body": {"content": "Hi Siti"}},
]  # fmt: skip


class FakeTeams:
    """Teams on top of the fake Microsoft sign-in: chats, messages, new chats, who asked."""

    def __init__(self, ms_fake) -> None:
        self.ms = ms_fake
        self.sent: list[tuple[str, str, str]] = []  # chat id, token, text
        self.created: list[dict] = []
        self.token_scopes: list[str] = []
        self.refuse_create = 0  # an HTTP status to answer POST /chats with
        http.transport = httpx.MockTransport(self.handler)

    def handler(self, r: httpx.Request) -> httpx.Response:
        if r.url.host == "login.microsoftonline.com":
            form = {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
            self.token_scopes.append(form.get("scope", ""))
            resp = self.ms.handler(r)
            if "Chat.Create" in form.get("scope", "") and resp.status_code == 200:
                body = json.loads(resp.content)
                body["scope"] = f"{body.get('scope', GRANTED)} {CHAT_CREATE}"
                return httpx.Response(200, json=body)
            return resp
        token = r.headers.get("authorization", "").removeprefix("Bearer ")
        p = r.url.path.removeprefix("/v1.0/")
        other = token == "at-aina"  # Aina's own connection: none of the boss's chats
        if p == "me/chats":
            return httpx.Response(200, json={"value": [] if other else CHATS})
        if p.startswith("me/chats/") and p.endswith("/messages"):
            if other or p != "me/chats/19:chat-1/messages":
                return httpx.Response(403, json={"error": {"code": "Forbidden", "message": "no"}})
            return httpx.Response(200, json={"value": MESSAGES})
        if p == "chats" and r.method == "POST":
            if self.refuse_create:
                return httpx.Response(
                    self.refuse_create, json={"error": {"code": "Forbidden", "message": "no"}}
                )
            self.created.append(json.loads(r.content))
            return httpx.Response(201, json={"id": "19:new-chat"})
        if p.startswith("chats/") and p.endswith("/messages") and r.method == "POST":
            chat = p.removeprefix("chats/").removesuffix("/messages")
            self.sent.append((chat, token, json.loads(r.content)["body"]["content"]))
            return httpx.Response(201, json={"id": "m-9"})
        return self.ms.handler(r)


async def _ctx_run(agent_id: str, person: str | None, name: str, args: dict) -> str:
    async with SessionLocal() as db:
        agent = await db.get(Agent, agent_id)
        ws = await db.get(Workspace, agent.workspace_id)
        ctx = ToolContext(db=db, agent=agent, workspace=ws, task=None, person=person)
        return await runtime.run_tool(ctx, name, args)


async def _drafts() -> list[EmailDraft]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(EmailDraft).order_by(EmailDraft.created_at))).all())


async def _aina_connected(ws_id: str, uid: str) -> MicrosoftAccount:
    """Aina's own Microsoft 365 connection (her token is cached, so no sign-in is faked)."""
    async with SessionLocal() as db:
        a = MicrosoftAccount(workspace_id=ws_id, user_id=uid, email="aina@maju.example.com",
                             display_name="Aina", status="connected", ms_user_id="oid-aina",
                             scopes=f"{GRANTED} {CHAT_CREATE}")  # fmt: skip
        db.add(a)
        await db.flush()
        a.token_enc = crypto.encrypt("rt-aina", a.aad)
        await db.commit()
        await db.refresh(a)
    await valkey().set(f"mstok:{a.id}", "at-aina", ex=600)
    return a


# ---------------------------------------------------------------- Teams


async def test_teams_reply_and_new_chat_wait_for_their_person_then_send(client, llm, temporal, ms):
    o = await office(client)
    await configure(client, tenant=TENANT)
    await connect(client)
    teams = FakeTeams(ms)
    me, ws_id = await user_id("owner@example.com")
    twin = await make_agent(o, ws_id, me, name="Boss Twin", is_twin=True)

    # Drafting is allowed in chat as well as in a task (no tool approval card): the draft
    # itself is what the person approves. A person's "deny" on the agent still wins.
    async with SessionLocal() as db:
        a = await db.get(Agent, twin.id)
        d = await policy.evaluate(a, "teams_send", {"chat_id": "19:chat-1", "text": "x"})
        assert d.effect == "allow", d
        a.tools = {"teams_send": "deny"}
        assert (await policy.evaluate(a, "teams_send", {"text": "x"})).effect == "deny"
        a.tools = {}
        await db.commit()

    # 1. A reply in an existing chat: a draft, nothing posted.
    out = await _ctx_run(
        twin.id, me, "teams_send", {"chat_id": "19:chat-1", "text": "Yes, by 5pm today."}
    )
    assert "NOTHING is sent" in out and teams.sent == []
    rows = (await client.get("/api/email-drafts")).json()
    assert len(rows) == 1
    reply = rows[0]
    assert reply["kind"] == "teams" and reply["provider"] == "teams" and reply["is_reply"]
    assert reply["subject"] == "Siti Aminah" and reply["body"] == "Yes, by 5pm today."
    assert reply["original_from"] == "Siti Aminah" and "Tender pack" in reply["original_snippet"]

    # 2. A first message to someone they already have a one-to-one chat with: that chat.
    out = await _ctx_run(
        twin.id, me, "teams_send", {"to": "Siti@Maju.example.com", "text": "Also the BQ."}
    )
    assert "NOTHING is sent" in out
    d2 = (await _drafts())[-1]
    assert d2.thread_id == "19:chat-1" and d2.provider == "teams"

    # 3. Someone new: starting a chat needs "Allow new Teams chats" first. No draft, a plain
    #    answer the AI passes on.
    out = await _ctx_run(
        twin.id, me, "teams_send", {"to": "ali@maju.example.com", "text": "Hello Ali"}
    )
    assert out.startswith("Error:") and "Allow new Teams chats" in out
    assert len(await _drafts()) == 2
    out = await _ctx_run(twin.id, me, "teams_send", {"to": "not an email", "text": "Hi"})
    assert out.startswith("Error:") and "not an email address" in out

    # The person allows it once (their own reconnect), and then it works.
    r = await client.post(
        "/api/integrations/microsoft/connect", json={"with_new_chats": True}, headers=csrf(client)
    )
    q = parse_qs(r.json()["url"].split("?", 1)[1])
    assert "Chat.Create" in q["scope"][0] and "Mail.ReadWrite" in q["scope"][0]
    r = await client.get(
        "/api/integrations/microsoft/callback", params={"state": q["state"][0], "code": "good-code"}
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/mail?app=teams&ms=connected")
    assert (await client.get("/api/integrations/microsoft/account")).json()["new_chats_ok"] is True
    out = await _ctx_run(
        twin.id, me, "teams_send", {"to": "ali@maju.example.com", "text": "Hello Ali"}
    )
    assert "a new chat with ali@maju.example.com" in out
    new = (await _drafts())[-1]
    assert new.thread_id == "" and new.to == "ali@maju.example.com" and new.in_reply_to == ""
    rows = {r["id"]: r for r in (await client.get("/api/email-drafts")).json()}
    assert rows[new.id]["kind"] == "teams" and not rows[new.id]["is_reply"]
    assert teams.sent == [] and teams.created == []

    # Approved: the reply goes to its chat, edited text and all.
    r = await client.patch(
        f"/api/email-drafts/{reply['id']}", json={"body": "Yes, by 4pm today."},
        headers=csrf(client),
    )  # fmt: skip
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/email-drafts/{reply['id']}/send", json={}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent"
    assert [(c, t) for c, _, t in teams.sent] == [("19:chat-1", "Yes, by 4pm today.")]
    r = await client.post(f"/api/email-drafts/{reply['id']}/send", json={}, headers=csrf(client))
    assert r.status_code == 409 and len(teams.sent) == 1

    # The new chat is started only now, between the person and Ali, then the message posted.
    r = await client.post(f"/api/email-drafts/{new.id}/send", json={}, headers=csrf(client))
    assert r.status_code == 200, r.text
    binds = [m["user@odata.bind"] for m in teams.created[0]["members"]]
    assert teams.created[0]["chatType"] == "oneOnOne"
    assert binds == [
        "https://graph.microsoft.com/v1.0/users('oid-boss')",
        "https://graph.microsoft.com/v1.0/users('ali@maju.example.com')",
    ]
    assert teams.sent[-1][0] == "19:new-chat" and teams.sent[-1][2] == "Hello Ali"
    async with SessionLocal() as db:
        assert (await db.get(EmailDraft, new.id)).thread_id == "19:new-chat"
        audits = (
            await db.scalars(select(AuditLog).where(AuditLog.action == "teams_message.sent"))
        ).all()
        assert {a.target for a in audits} == {reply["id"], new.id}

    # Discarding posts nothing.
    r = await client.post(f"/api/email-drafts/{d2.id}/discard", json={}, headers=csrf(client))
    assert r.json()["status"] == "discarded" and len(teams.sent) == 2


async def test_a_refused_new_chat_fails_plainly(client, llm, temporal, ms):
    o = await office(client)
    await configure(client, tenant=TENANT)
    await connect(client)
    teams = FakeTeams(ms)
    me, ws_id = await user_id("owner@example.com")
    twin = await make_agent(o, ws_id, me, name="Boss Twin", is_twin=True)
    async with SessionLocal() as db:
        a = await db.get(MicrosoftAccount, (await my_account()).id)
        a.scopes = f"{a.scopes} {CHAT_CREATE}"
        await db.commit()
    await _ctx_run(twin.id, me, "teams_send", {"to": "ali@maju.example.com", "text": "Hi"})
    d = (await _drafts())[-1]
    teams.refuse_create = 403  # withdrawn at Microsoft since
    r = await client.post(f"/api/email-drafts/{d.id}/send", json={}, headers=csrf(client))
    assert r.status_code == 502 and r.json()["code"] == "teams_failed"
    assert "Allow new Teams chats" in r.json()["message"]
    async with SessionLocal() as db:
        row = await db.get(EmailDraft, d.id)
        assert row.status == "failed" and teams.sent == []


async def test_new_chats_are_asked_only_by_the_person_and_kept(client, llm, temporal, ms):
    await office(client)
    await configure(client, tenant=TENANT)
    await connect(client)
    teams = FakeTeams(ms)
    a = await my_account()

    # Everyone's sign-in and refresh: no Chat.Create (a connection made before keeps working).
    assert "Chat.Create" not in app.DELEGATED_SCOPES
    r = await client.post("/api/integrations/microsoft/connect", json={}, headers=csrf(client))
    assert "Chat.Create" not in parse_qs(r.json()["url"].split("?", 1)[1])["scope"][0]
    await valkey().delete(f"mstok:{a.id}")
    async with SessionLocal() as db:
        await auth.access_token(db, await db.get(MicrosoftAccount, a.id))
    assert "Chat.Create" not in teams.token_scopes[-1]
    acct = (await client.get("/api/integrations/microsoft/account")).json()
    assert acct["new_chats_ok"] is False

    # Refused (a tenant that lets people allow only low-risk permissions): back to Teams with
    # what to ask the admin; nothing else changed.
    before = await my_account()
    r = await client.post(
        "/api/integrations/microsoft/connect", json={"with_new_chats": True}, headers=csrf(client)
    )
    state = parse_qs(r.json()["url"].split("?", 1)[1])["state"][0]
    r = await client.get(
        "/api/integrations/microsoft/callback",
        params={"state": state, "error": "access_denied", "error_description": "AADSTS90094"},
    )
    loc = r.headers["location"]
    assert (
        loc.startswith("/mail?app=teams&ms=error")
        and "Chat.Create" in parse_qs(loc.split("?", 1)[1])["msg"][0]
    )
    after = await my_account()
    assert after.status == "connected" and after.token_enc == before.token_enc

    # Allowed: kept on later refreshes and on a plain reconnect.
    await connect_with_new_chats(client)
    await valkey().delete(f"mstok:{a.id}")
    async with SessionLocal() as db:
        await auth.access_token(db, await db.get(MicrosoftAccount, a.id))
    assert "Chat.Create" in teams.token_scopes[-1]
    await connect(client)
    assert "Chat.Create" in teams.token_scopes[-1]
    assert (await client.get("/api/integrations/microsoft/account")).json()["new_chats_ok"]

    # Withdrawn at Microsoft: the refresh drops it and mail keeps working.
    real = teams.handler

    def withdrawn(r: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
        if form.get("grant_type") == "refresh_token" and "Chat.Create" in form.get("scope", ""):
            return httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "AADSTS65001: consent"}
            )
        return real(r)

    http.transport = httpx.MockTransport(withdrawn)
    await valkey().delete(f"mstok:{a.id}")
    async with SessionLocal() as db:
        assert await auth.access_token(db, await db.get(MicrosoftAccount, a.id))
    acct = (await client.get("/api/integrations/microsoft/account")).json()
    assert acct["status"] == "connected" and acct["mail_ok"] and acct["new_chats_ok"] is False


async def connect_with_new_chats(client) -> None:
    r = await client.post(
        "/api/integrations/microsoft/connect", json={"with_new_chats": True}, headers=csrf(client)
    )
    state = parse_qs(r.json()["url"].split("?", 1)[1])["state"][0]
    r = await client.get(
        "/api/integrations/microsoft/callback", params={"state": state, "code": "good-code"}
    )
    assert "ms=connected" in r.headers["location"]


# ---------------------------------------------------------------- Outlook

