"""Helpers other tests import (people and a second company). Not tests themselves."""


import httpx


from .conftest import csrf
from .test_agents import llm, messages, new_agent, new_task, office, temporal  # noqa: F401

PW = "a-long-new-password-2026"


async def member(owner: httpx.AsyncClient, email: str, role: str, **where) -> dict:
    r = await owner.post(
        "/api/members",
        json={"email": email, "name": email.split("@")[0].title(), "role": role, **where},
        headers=csrf(owner),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def signed_in(email: str, temp: str):
    from agentic.api.main import app

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await c.post("/api/auth/login", json={"email": email, "password": temp})
    assert r.status_code == 200, r.text
    r = await c.post(
        "/api/auth/change-password",
        json={"current_password": temp, "new_password": PW},
        headers=csrf(c),
    )
    assert r.status_code == 200, r.text
    return c


async def as_role(owner, email, role, **where):
    m = await member(owner, email, role, **where)
    return await signed_in(email, m["temp_password"])


async def two_branches(client):
    o = await office(client)
    b2 = (
        await client.post("/api/branches", json={"name": "Jaya Bhd"}, headers=csrf(client))
    ).json()
    o["b2"] = b2
    o["b2_depts"] = {d["name"]: d["id"] for d in b2["departments"]}
    fin = await new_agent(client, o, "Faiz", "Finance")
    ops = await new_agent(client, o, "Ops One", "Operations")
    far = (
        await client.post(
            "/api/agents",
            json={
                "branch_id": b2["id"],
                "department_id": o["b2_depts"]["Finance"],
                "name": "Far Away",
                "role": "Finance agent",
            },
            headers=csrf(client),
        )
    ).json()
    return o, fin, ops, far


def names(rows):
    return sorted(a["name"] for a in rows)


# ---------------------------------------------------------------- scopes
