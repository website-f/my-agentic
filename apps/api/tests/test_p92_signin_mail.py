"""P92: emailed sign-in passwords (first sign-in, forgotten password, the owner's bulk send)
and the system sender. Microsoft is faked (microsoft/http.py transport): nothing real is called.
Synthetic people only."""

import json
import re
from urllib.parse import parse_qs, unquote

import httpx
import pytest
from sqlalchemy import select

from agentic.core.config import settings
from agentic.core.db import SessionLocal
from agentic.microsoft import http, sendmail
from agentic.models import AuditLog, User, Workspace
from agentic.services import signin_mail

from .conftest import csrf, setup_owner  # noqa: F401  (re-exported for other tests)

CLIENT_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SENDER = "noreply@example.com"
PW = "a-long-new-password-2026"
BOX = re.compile(r'text-align:center">([A-Za-z0-9]+)</div>')


class FakeGraph:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.answers: list[tuple[int, dict, dict]] = []
        self.tokens = 0

    def handler(self, r: httpx.Request) -> httpx.Response:
        if r.url.host == "login.microsoftonline.com":
            form = {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
            assert form["grant_type"] == "client_credentials"
            assert form["scope"] == "https://graph.microsoft.com/.default"
            self.tokens += 1
            return httpx.Response(
                200, json={"access_token": f"app-{self.tokens}", "expires_in": 3600}
            )
        assert r.url.host == "graph.microsoft.com", r.url
        assert r.url.path.endswith("/sendMail"), r.url.path
        if self.answers:
            status, headers, body = self.answers.pop(0)
            return httpx.Response(status, headers=headers, json=body)
        self.sent.append({"path": unquote(r.url.path), "body": json.loads(r.content)})
        return httpx.Response(202)

    def to(self, email: str) -> list[dict]:
        return [
            s
            for s in self.sent
            if s["body"]["message"]["toRecipients"][0]["emailAddress"]["address"] == email
        ]

    def code_for(self, email: str) -> str:
        html = self.to(email)[-1]["body"]["message"]["body"]["content"]
        m = BOX.search(html)
        assert m, html
        return m.group(1)


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph()
    http.transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(settings, "ms_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "ms_client_secret", "s3cret-value")
    monkeypatch.setattr(settings, "ms_tenant", TENANT)
    waits: list[float] = []

    async def no_wait(s: float) -> None:
        waits.append(s)

    monkeypatch.setattr(signin_mail, "sleep", no_wait)
    fake.waits = waits
    yield fake
    http.transport = None


def anon(client: httpx.AsyncClient) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=client._transport, base_url="http://test")


async def sender_on(owner: httpx.AsyncClient, **over) -> dict:
    body = {
        "enabled": True,
        "address": SENDER,
        "from_name": "No Reply",
        "first_login": True,
        "forgot_password": True,
        **over,
    }
    r = await owner.put("/api/settings/system-mail", json=body, headers=csrf(owner))
    assert r.status_code == 200, r.text
    return r.json()


async def add(owner: httpx.AsyncClient, email: str, role: str = "viewer") -> dict:
    r = await owner.post(
        "/api/members",
        json={"email": email, "name": email.split("@")[0].title(), "role": role},
        headers=csrf(owner),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def login(c: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    r = await c.post("/api/auth/login", json={"email": email, "password": password})
    await signin_mail.drain()
    return r


async def user(email: str) -> User:
    async with SessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        assert u is not None
        return u


async def set_user(who: str, **values) -> None:
    async with SessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == who))
        for k, v in values.items():
            setattr(u, k, v)
        await db.commit()


async def audit_rows() -> list[AuditLog]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuditLog).order_by(AuditLog.id))).all())


async def signed_in_member(client, owner, email: str) -> httpx.AsyncClient:
    temp = (await add(owner, email))["temp_password"]
    c = anon(client)
    assert (await login(c, email, temp)).status_code == 200
    r = await c.post(
        "/api/auth/change-password",
        json={"current_password": temp, "new_password": PW},
        headers=csrf(c),
    )
    assert r.status_code == 200, r.text
    return c


# ---------------------------------------------------------------- first sign-in


# ---------------------------------------------------------------- the owner's settings


async def test_send_maps_token_and_app_problems():
    async with SessionLocal() as db:
        ws = Workspace(name="W", slug="w")
        db.add(ws)
        await db.commit()
        with pytest.raises(sendmail.SendError) as e:
            await sendmail.send(
                db,
                ws.id,
                sender=SENDER,
                from_name="No Reply",
                to="a@example.com",
                to_name="A",
                subject="s",
                html="h",
            )
        assert e.value.kind == "not_configured"


# ---------------------------------------------------------------- the Members page

