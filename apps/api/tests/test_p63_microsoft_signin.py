"""P63: Sign in with Microsoft. One Microsoft sign-in signs a person in to the office (only
someone an admin already added, matched by the organisation-managed address or an earlier
connection, only from the company's own Microsoft organisation) and connects their Outlook and
Teams in the same step. Two-step sign-in is still asked unless Microsoft did multi-factor.

Microsoft is faked (test_microsoft.FakeMicrosoft); nothing real is called."""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from agentic.core.db import SessionLocal
from agentic.microsoft import app as ms_app
from agentic.microsoft import features, http, sync
from agentic.models import AuditLog, Membership, MicrosoftAccount

from .conftest import csrf
from .test_agents import llm, office, temporal  # noqa: F401
from .test_microsoft import CLIENT_ID, GRANTED, TENANT, FakeMicrosoft, _jwt, user_id

OTHER_TENANT = "99999999-8888-7777-6666-555555555555"


class SignInMicrosoft(FakeMicrosoft):
    """Answers the sign-in's code with the claims and /me the test sets."""

    def __init__(self) -> None:
        super().__init__()
        self.nonce = ""
        self.claims: dict = {}
        self.me = {
            "id": "oid-owner",
            "mail": "Owner@Example.com",
            "userPrincipalName": "owner@example.com",
        }
        self.scope = GRANTED

    def handler(self, r: httpx.Request) -> httpx.Response:
        if r.url.host == "login.microsoftonline.com":
            form = {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
            if form.get("grant_type") == "authorization_code":
                assert form["code"] == "good-code" and form["code_verifier"]
                claims = {
                    "tid": TENANT,
                    "oid": self.me["id"],
                    "aud": CLIENT_ID,
                    "nonce": self.nonce,
                    "preferred_username": self.me["userPrincipalName"],
                    **self.claims,
                }
                return httpx.Response(
                    200,
                    json={
                        "access_token": "at-sso",
                        "refresh_token": "rt-sso",
                        "expires_in": 3600,
                        "scope": self.scope,
                        "id_token": _jwt(claims),
                    },
                )
        if r.url.host == "graph.microsoft.com" and r.url.path == "/v1.0/me":
            self.calls.append((r.method, "me", {}))
            return httpx.Response(200, json={**self.me, "displayName": "Signed In"})
        return super().handler(r)


@pytest.fixture
def sso(monkeypatch):
    fake = SignInMicrosoft()
    http.transport = httpx.MockTransport(fake.handler)

    async def kick():
        return True

    async def nothing(*_a, **_k):
        return "skipped"

    monkeypatch.setattr(sync, "kick", kick)
    monkeypatch.setattr(features, "process", nothing)
    yield fake
    http.transport = None


async def configure(c, tenant: str = TENANT) -> None:
    r = await c.put(
        "/api/integrations/microsoft",
        json={"client_id": CLIENT_ID, "client_secret": "s3cret-value", "tenant": tenant},
        headers=csrf(c),
    )
    assert r.status_code == 200, r.text


def anon(client) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=client._transport, base_url="http://test")


async def sign_in(c: httpx.AsyncClient, fake: SignInMicrosoft, email: str = "") -> dict:
    """start -> Microsoft -> our callback; the redirect's path, query and fragment."""
    r = await c.post("/api/auth/microsoft/start", json={"email": email, "next": "/tasks"})
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["url"]).query)
    fake.nonce = fake.nonce or q["nonce"][0]
    r = await c.get(
        "/api/integrations/microsoft/callback", params={"state": q["state"][0], "code": "good-code"}
    )
    assert r.status_code == 303, r.text
    u = urlparse(r.headers["location"])
    return {
        "path": u.path,
        **{k: v[0] for k, v in parse_qs(u.query).items()},
        **{f"#{k}": v[0] for k, v in parse_qs(u.fragment).items()},
    }


async def test_a_member_signs_in_with_microsoft_and_their_outlook_connects(
    client, llm, temporal, sso
):
    await office(client)
    c = anon(client)
    try:
        assert (await c.get("/api/auth/sso")).json()["microsoft"] is False  # not set up yet
        await configure(client)
        assert (await c.get("/api/auth/sso")).json()["microsoft"] is True

        r = await c.post("/api/auth/microsoft/start", json={})
        url = r.json()["url"]
        q = parse_qs(urlparse(url).query)
        assert url.startswith(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize")
        assert q["client_id"] == [CLIENT_ID] and q["code_challenge_method"] == ["S256"]
        assert q["nonce"][0] and "Mail.ReadWrite" in q["scope"][0] and "Chat.Read" in q["scope"][0]
        assert "ChannelMessage.Read.All" not in q["scope"][0]  # only after an admin turns it on
        assert q["redirect_uri"][0].endswith("/api/integrations/microsoft/callback")

        got = await sign_in(c, sso)
        assert got == {"path": "/login", "sso": "done", "next": "/tasks"}
        me = await c.get("/api/auth/me")
        assert me.status_code == 200 and me.json()["user"]["email"] == "owner@example.com"
        owner_id, _ = await user_id("owner@example.com")
        async with SessionLocal() as db:
            acct = await db.scalar(
                select(MicrosoftAccount).where(MicrosoftAccount.user_id == owner_id)
            )
            assert acct.status == "connected" and acct.tenant_id == TENANT
            assert acct.ms_user_id == "oid-owner" and acct.email == "owner@example.com"
            # P66: the verified account, for Prima (agentic/prima).
            mem = await db.scalar(select(Membership).where(Membership.user_id == owner_id))
            assert (mem.ms_oid, mem.ms_tenant_id) == ("oid-owner", TENANT)
            log = (await db.scalars(select(AuditLog).where(AuditLog.action == "auth.login"))).all()
            assert any("Microsoft" in (e.note or "") for e in log)

        # Next time the earlier connection finds them, even if the address changed at Microsoft.
        sso.nonce = ""
        sso.me = {
            **sso.me,
            "mail": "renamed@example.com",
            "userPrincipalName": "renamed@example.com",
        }
        c2 = anon(client)
        try:
            assert (await sign_in(c2, sso))["sso"] == "done"
            assert (await c2.get("/api/auth/me")).json()["user"]["email"] == "owner@example.com"
        finally:
            await c2.aclose()
    finally:
        await c.aclose()


async def test_no_one_new_gets_in_and_the_answer_is_checked(client, llm, temporal, sso):
    await office(client)
    await configure(client)
    c = anon(client)
    try:
        sso.me = {
            "id": "oid-x",
            "mail": "stranger@example.com",
            "userPrincipalName": "stranger@example.com",
        }
        got = await sign_in(c, sso)
        assert got["path"] == "/login" and "No one with stranger@example.com" in got["sso_error"]
        assert (await c.get("/api/auth/me")).status_code == 401

        # The id token's optional email claim alone is never trusted.
        sso.nonce = ""
        sso.claims = {"email": "owner@example.com"}
        assert "No one with" in (await sign_in(c, sso))["sso_error"]

        # A token for another sign-in (wrong nonce) is refused.
        sso.claims = {}
        sso.me = {
            "id": "oid-owner",
            "mail": "owner@example.com",
            "userPrincipalName": "owner@example.com",
        }
        sso.nonce = "someone-elses"
        assert "could not be checked" in (await sign_in(c, sso))["sso_error"]

        # An unknown or used state.
        r = await c.get(
            "/api/integrations/microsoft/callback", params={"state": "nope", "code": "good-code"}
        )
        assert r.status_code == 303 and "/login" not in r.headers["location"]  # not a sign-in

        # Cancelled at Microsoft.
        r = await c.post("/api/auth/microsoft/start", json={})
        state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
        r = await c.get(
            "/api/integrations/microsoft/callback",
            params={"state": state, "error": "access_denied"},
        )
        assert "sso_error=" in r.headers["location"] and "cancelled" in r.headers["location"]
    finally:
        await c.aclose()


async def test_only_the_companys_own_microsoft_organisation(client, llm, temporal, sso):
    await office(client)
    await configure(client, tenant="organizations")  # a multi-tenant app
    c = anon(client)
    try:
        sso.claims = {"tid": OTHER_TENANT}
        got = await sign_in(c, sso)
        assert "not linked to the office" in got["sso_error"]
        _, ws_id = await user_id("owner@example.com")
        async with SessionLocal() as db:
            await ms_app.update(db, ws_id, "test", admin_tenant=OTHER_TENANT)
            await db.commit()
        sso.nonce = ""
        assert (await sign_in(c, sso))["sso"] == "done"
    finally:
        await c.aclose()


async def test_two_step_is_still_asked_unless_microsoft_did_multi_factor(
    client, llm, temporal, sso, monkeypatch
):
    from agentic.services import two_factor

    await office(client)
    await configure(client)
    monkeypatch.setattr(two_factor, "enabled", lambda user: True)
    c = anon(client)
    try:
        sso.claims = {"amr": ["pwd"]}
        got = await sign_in(c, sso)
        assert got["sso"] == "code" and got["#mfa"] and got["#email"] == "owner@example.com"
        assert (await c.get("/api/auth/me")).status_code == 401  # no session before the code
        ch = await two_factor.read_challenge(got["#mfa"])
        owner_id, _ = await user_id("owner@example.com")
        assert ch["user_id"] == owner_id

        sso.nonce = ""
        sso.claims = {"amr": ["pwd", "mfa"]}
        assert (await sign_in(c, sso))["sso"] == "done"
        assert (await c.get("/api/auth/me")).status_code == 200
    finally:
        await c.aclose()

