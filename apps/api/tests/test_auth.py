import httpx

from agentic.core.security import can, hash_password, temp_password, verify_password

from .conftest import csrf, setup_owner


def test_password_hashing_roundtrip():
    h = hash_password("a-long-password")
    assert verify_password(h, "a-long-password")
    assert not verify_password(h, "wrong-password")
    assert not verify_password(None, "anything")


def test_temp_password_has_no_lookalikes():
    for _ in range(50):
        assert not set(temp_password()) & set("0O1lI")


def test_role_matrix():
    assert can("owner", "members.assign_owner")
    assert not can("admin", "members.assign_owner")
    assert can("operator", "work.write") and not can("operator", "approvals.decide")
    assert can("approver", "approvals.decide") and not can("approver", "work.write")
    assert not can("viewer", "work.write")


async def test_setup_then_locked(client: httpx.AsyncClient):
    assert (await client.get("/api/auth/setup-status")).json() == {"needs_setup": True}
    me = await setup_owner(client)
    assert me["role"] == "owner" and me["workspace"]["name"] == "Acme Group"
    assert (await client.get("/api/auth/setup-status")).json() == {"needs_setup": False}

    again = await client.post(
        "/api/auth/setup",
        json={
            "workspace_name": "Other",
            "name": "X",
            "email": "x@example.com",
            "password": "another-long-one",
        },
    )
    assert again.status_code == 409


async def test_setup_rejects_short_password(client: httpx.AsyncClient):
    r = await client.post(
        "/api/auth/setup",
        json={
            "workspace_name": "Acme",
            "name": "O",
            "email": "o@example.com",
            "password": "short",
        },
    )
    assert r.status_code == 422
    assert "password" in r.json()["fields"]


async def test_login_logout_and_session(client: httpx.AsyncClient):
    await setup_owner(client)
    client.cookies.clear()
    assert (await client.get("/api/auth/me")).status_code == 401

    bad = await client.post(
        "/api/auth/login", json={"email": "owner@example.com", "password": "nope-nope-nope"}
    )
    assert bad.status_code == 401 and bad.json()["code"] == "bad_credentials"

    ok = await client.post(
        "/api/auth/login", json={"email": "OWNER@example.com", "password": "correct-horse-battery"}
    )
    assert ok.status_code == 200
    assert (await client.get("/api/auth/me")).json()["user"]["email"] == "owner@example.com"

    out = await client.post("/api/auth/logout", json={}, headers=csrf(client))
    assert out.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_lockout_after_repeated_failures(client: httpx.AsyncClient):
    await setup_owner(client)
    client.cookies.clear()
    for _ in range(5):
        await client.post(
            "/api/auth/login", json={"email": "owner@example.com", "password": "wrong-password-x"}
        )
    locked = await client.post(
        "/api/auth/login", json={"email": "owner@example.com", "password": "correct-horse-battery"}
    )
    assert locked.status_code == 429 and locked.json()["code"] == "too_many_attempts"


async def test_csrf_and_json_required(client: httpx.AsyncClient):
    await setup_owner(client)
    no_token = await client.post("/api/branches", json={"name": "Alpha"})
    assert no_token.status_code == 403 and no_token.json()["code"] == "csrf_failed"

    form = await client.post(
        "/api/branches",
        content="name=Alpha",
        headers={"content-type": "application/x-www-form-urlencoded", **csrf(client)},
    )
    assert form.status_code == 415

    ok = await client.post("/api/branches", json={"name": "Alpha"}, headers=csrf(client))
    assert ok.status_code == 201

