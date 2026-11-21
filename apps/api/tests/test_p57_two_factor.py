"""P57: two-step sign-in (TOTP authenticator app + recovery codes) and the workspace rule."""

import httpx
import pytest
from sqlalchemy import select

from agentic.core import totp
from agentic.core.config import settings
from agentic.core.db import SessionLocal
from agentic.models import AuditLog, User
from agentic.services import two_factor

from .conftest import csrf, setup_owner

OWNER = "owner@example.com"
PW = "correct-horse-battery"


@pytest.fixture
def clock(monkeypatch):
    """The 30-second step the server sees, moved by hand."""
    now = {"step": 1_000_000}
    monkeypatch.setattr(totp, "step_at", lambda when=None: now["step"])
    return now


async def _login(c: httpx.AsyncClient, email: str = OWNER, password: str = PW) -> httpx.Response:
    c.cookies.clear()
    return await c.post("/api/auth/login", json={"email": email, "password": password})


async def _code_step(c: httpx.AsyncClient, challenge: str, **body) -> httpx.Response:
    return await c.post("/api/auth/login/2fa", json={"challenge": challenge, **body})


async def _turn_on(c: httpx.AsyncClient, clock) -> tuple[str, list[str]]:
    r = await c.post("/api/auth/2fa/setup", json={}, headers=csrf(c))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["uri"].startswith("otpauth://totp/Agentic%20Office:")
    assert f"secret={secret}" in r.json()["uri"]
    ok = await c.post(
        "/api/auth/2fa/confirm",
        json={"code": totp.code_at(secret, clock["step"])},
        headers=csrf(c),
    )
    assert ok.status_code == 200, ok.text
    codes = ok.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    return secret, codes


async def _add_member(c: httpx.AsyncClient, email: str, role: str) -> None:
    """Adds the member and signs them in with their own password (the temp one changed)."""
    r = await c.post(
        "/api/members", json={"email": email, "name": role.title(), "role": role}, headers=csrf(c)
    )
    assert r.status_code == 201, r.text
    temp = r.json()["temp_password"]
    await _login(c, email, temp)
    changed = await c.post(
        "/api/auth/change-password",
        json={"current_password": temp, "new_password": f"{role}-own-password-1"},
        headers=csrf(c),
    )
    assert changed.status_code == 200, changed.text


def test_rfc6238_vectors():
    # RFC 6238 appendix B (SHA-1 key "12345678901234567890"), last 6 digits.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp.code_at(secret, totp.step_at(59)) == "287082"
    assert totp.code_at(secret, totp.step_at(1111111109)) == "081804"
    assert totp.code_at(secret, totp.step_at(2000000000)) == "279037"
    assert totp.match(secret, "287 082", when=59) == 1
    assert totp.match(secret, "287082", when=59 + 30) == 1  # one step late still works
    assert totp.match(secret, "287082", when=59 + 90) is None  # out of the window


async def test_setup_sign_in_reuse_and_limits(client: httpx.AsyncClient, clock):
    await setup_owner(client)
    st = (await client.get("/api/auth/2fa")).json()
    assert st["enabled"] is False and st["policy"] == "off" and st["required"] is False

    r = await client.post("/api/auth/2fa/setup", json={}, headers=csrf(client))
    secret = r.json()["secret"]
    bad = await client.post("/api/auth/2fa/confirm", json={"code": "000000"}, headers=csrf(client))
    if totp.code_at(secret, clock["step"]) != "000000":
        assert bad.status_code == 400 and bad.json()["code"] == "bad_code"
    async with SessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == OWNER))
        assert u.totp_secret_enc and secret not in u.totp_secret_enc  # sealed at rest
        assert u.totp_enabled_at is None

    ok = await client.post(
        "/api/auth/2fa/confirm",
        json={"code": totp.code_at(secret, clock["step"])},
        headers=csrf(client),
    )
    assert ok.status_code == 200 and len(ok.json()["recovery_codes"]) == 10
    st = (await client.get("/api/auth/2fa")).json()
    assert st["enabled"] is True and st["recovery_codes_left"] == 10
    assert (await client.get("/api/auth/me")).json()["user"]["two_factor_enabled"] is True
    async with SessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == OWNER))
        assert all(len(h) == 64 for h in u.recovery_codes)  # only hashes are kept
        assert ok.json()["recovery_codes"][0] not in u.recovery_codes

    # The password alone no longer signs in.
    first = await _login(client)
    assert first.status_code == 200 and first.json()["needs_2fa"] is True
    challenge = first.json()["challenge"]
    assert "agentic_session" not in client.cookies
    assert (await client.get("/api/auth/me")).status_code == 401

    # The code used to confirm the setup does not work twice.
    reused = await _code_step(client, challenge, code=totp.code_at(secret, clock["step"]))
    assert reused.status_code == 401 and reused.json()["code"] == "bad_code"
    clock["step"] += 1
    signed = await _code_step(client, challenge, code=totp.code_at(secret, clock["step"]))
    assert signed.status_code == 200, signed.text
    assert signed.json()["user"]["email"] == OWNER
    assert (await client.get("/api/auth/me")).status_code == 200
    # The challenge is spent.
    again = await _code_step(client, challenge, code=totp.code_at(secret, clock["step"]))
    assert again.status_code == 401 and again.json()["code"] == "challenge_expired"

    # Five wrong codes end the challenge.
    clock["step"] += 10
    challenge = (await _login(client)).json()["challenge"]
    wrong = totp.code_at(secret, clock["step"] + 5)
    for _ in range(4):
        r = await _code_step(client, challenge, code=wrong)
        assert r.status_code == 401 and r.json()["code"] == "bad_code"
    r = await _code_step(client, challenge, code=wrong)
    assert r.status_code == 429 and r.json()["code"] == "too_many_codes"
    r = await _code_step(client, challenge, code=totp.code_at(secret, clock["step"]))
    assert r.status_code == 401 and r.json()["code"] == "challenge_expired"

    # Ten wrong codes for one person within 15 minutes lock even a right code out, on a new
    # challenge too (the last sign-in cleared the count; five above, five more here).
    challenge = (await _login(client)).json()["challenge"]
    for _ in range(4):
        assert (await _code_step(client, challenge, code=wrong)).status_code == 401
    assert (await _code_step(client, challenge, code=wrong)).status_code == 429
    challenge = (await _login(client)).json()["challenge"]
    locked = await _code_step(client, challenge, code=totp.code_at(secret, clock["step"]))
    assert locked.status_code == 429 and locked.json()["code"] == "too_many_codes"
    assert "min" in locked.json()["message"]

    owner_id = (await _owner(OWNER)).id
    await two_factor.clear_failures(owner_id)
    challenge = (await _login(client)).json()["challenge"]
    ok = await _code_step(client, challenge, code=totp.code_at(secret, clock["step"]))
    assert ok.status_code == 200


async def _owner(email: str) -> User:
    async with SessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        assert u is not None
        return u


async def test_recovery_code_works_once(client: httpx.AsyncClient, clock):
    await setup_owner(client)
    _secret, codes = await _turn_on(client, clock)

    challenge = (await _login(client)).json()["challenge"]
    r = await _code_step(client, challenge, recovery_code=codes[3].upper())
    assert r.status_code == 200, r.text
    st = (await client.get("/api/auth/2fa")).json()
    assert st["recovery_codes_left"] == 9

    challenge = (await _login(client)).json()["challenge"]
    r = await _code_step(client, challenge, recovery_code=codes[3])
    assert r.status_code == 401 and r.json()["code"] == "bad_code"
    r = await _code_step(client, challenge, recovery_code=codes[4].replace("-", ""))
    assert r.status_code == 200

    async with SessionLocal() as db:
        actions = (await db.scalars(select(AuditLog.action))).all()
    assert actions.count("auth.2fa_recovery_used") == 2 and "auth.2fa_enabled" in actions

    # New codes need a current code; the old ones stop working.
    clock["step"] += 1
    fresh = await client.post(
        "/api/auth/2fa/recovery-codes",
        json={"code": totp.code_at(_secret, clock["step"])},
        headers=csrf(client),
    )
    assert fresh.status_code == 200 and len(fresh.json()["recovery_codes"]) == 10
    challenge = (await _login(client)).json()["challenge"]
    assert (await _code_step(client, challenge, recovery_code=codes[5])).status_code == 401
    r = await _code_step(client, challenge, recovery_code=fresh.json()["recovery_codes"][0])
    assert r.status_code == 200


async def test_disable_needs_password_and_code(client: httpx.AsyncClient, clock):
    await setup_owner(client)
    secret, codes = await _turn_on(client, clock)
    clock["step"] += 1
    code = totp.code_at(secret, clock["step"])
    bad_pw = await client.post(
        "/api/auth/2fa/disable",
        json={"password": "wrong-password-1", "code": code},
        headers=csrf(client),
    )
    assert bad_pw.status_code == 400 and bad_pw.json()["code"] == "bad_current_password"
    no_code = await client.post(
        "/api/auth/2fa/disable", json={"password": PW}, headers=csrf(client)
    )
    assert no_code.status_code == 400 and no_code.json()["code"] == "bad_code"
    ok = await client.post(
        "/api/auth/2fa/disable", json={"password": PW, "code": code}, headers=csrf(client)
    )
    assert ok.status_code == 204
    st = (await client.get("/api/auth/2fa")).json()
    assert st["enabled"] is False and st["recovery_codes_left"] == 0
    r = await _login(client)
    assert r.status_code == 200 and r.json()["user"]["email"] == OWNER
    async with SessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == OWNER))
        assert u.totp_secret_enc is None and u.recovery_codes == []
    assert codes  # the recovery codes went with it


async def test_new_workspace_asks_owner_for_2fa(client: httpx.AsyncClient, clock, monkeypatch):
    monkeypatch.setattr(settings, "new_workspace_require_2fa", "admins")
    me = await setup_owner(client)
    assert me["user"]["two_factor_setup_required"] is True
    r = await client.get("/api/branches")
    assert r.status_code == 403 and r.json()["code"] == "2fa_required"
    assert (await client.get("/api/auth/2fa/policy")).json() == {"require_2fa": "admins"}
    await _turn_on(client, clock)
    assert (await client.get("/api/branches")).status_code == 200


async def test_2fa_required_message_in_malay(client: httpx.AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "new_workspace_require_2fa", "everyone")
    await setup_owner(client)
    r = await client.get("/api/branches", headers={"x-lang": "ms"})
    assert r.json()["code"] == "2fa_required"
    assert "dua langkah" in r.json()["message"]
