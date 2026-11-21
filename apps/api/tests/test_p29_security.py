"""P29: security fixes. Brain pages and facts follow the caller's scope; skills publish only
through managers; Gmail OAuth is bound to the browser that started it; OpenAI tokens follow
their creator; approvals, bindings, MCP servers, broadcasts, monitor, incidents, password
resets, twin settings, client IPs and logout."""



from agentic.core.db import SessionLocal

from .conftest import csrf
from .test_agents import llm, new_agent, office, temporal  # noqa: F401
from .test_office_roles import as_role

JSON = {"content-type": "application/json"}


def h(c) -> dict[str, str]:
    """Headers for a body-less POST / DELETE (the API takes JSON only)."""
    return {**JSON, **csrf(c)}


async def _assistant(client) -> dict:
    r = await client.post(
        "/api/assistants", json={"preset": "chief_of_staff"}, headers=csrf(client)
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- 1. brain pages


# ---------------------------------------------------------------- 2. facts and recall


# ---------------------------------------------------------------- 3. skills


# ---------------------------------------------------------------- 4. Gmail OAuth


async def test_gmail_state_is_tied_to_the_session():
    """Unit check: the same user from another sign-in session cannot finish the flow."""
    import json as _json

    from agentic.assistants import gmail
    from agentic.core.valkey import valkey

    await valkey().set(
        "gauth:s1",
        _json.dumps({"ws": "w", "user": "u", "sid": gmail._sid("sess-a"), "verifier": "v"}),
    )
    async with SessionLocal() as db:
        try:
            await gmail.finish(db, "s1", "c", workspace_id="w", user_id="u", session_id="sess-b")
        except gmail.GmailError as e:
            assert "another browser" in str(e)
        else:  # pragma: no cover
            raise AssertionError("finished in the wrong session")


async def _staff_twin(client, o, email="siti@example.com"):
    staff = await as_role(
        client, email, "staff", branch_id=o["branch"]["id"], department_id=o["depts"]["Finance"]
    )
    r = await staff.post("/api/me/twin", json={}, headers=csrf(staff))
    assert r.status_code == 201, r.text
    return staff, r.json()["twin"]


async def _member_id(client, email: str) -> str:
    rows = (await client.get("/api/members")).json()
    return next(m["user_id"] for m in rows if m["email"] == email)


# ---------------------------------------------------------------- 5. OpenAI tokens


# ---------------------------------------------------------------- 6. approve page, bindings


# ---------------------------------------------------------------- 7. MCP servers


# ---------------------------------------------------------------- 8. broadcasts


# ---------------------------------------------------------------- 9. monitor


# ---------------------------------------------------------------- 10. incidents


# ---------------------------------------------------------------- 11. password resets


# ---------------------------------------------------------------- 12. twins


# ---------------------------------------------------------------- 13. client IP


def test_client_ip_ignores_what_the_client_wrote_in_x_forwarded_for():
    from starlette.requests import Request

    from agentic.api.deps import client_ip

    def req(headers: dict[str, str], peer: str = "1.1.1.1") -> Request:
        return Request(
            {
                "type": "http",
                "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                "client": (peer, 1234),
            }
        )

    real = {"X-Real-IP": "81.2.69.160", "X-Forwarded-For": "6.6.6.6"}
    assert client_ip(req(real)) == "81.2.69.160"
    # The client wrote 6.6.6.6; our proxy appended the real address on the right.
    assert client_ip(req({"X-Forwarded-For": "6.6.6.6, 81.2.69.160"})) == "81.2.69.160"
    hops = "6.6.6.6, 81.2.69.160, 172.18.0.3"
    assert client_ip(req({"X-Forwarded-For": hops})) == "81.2.69.160"
    assert client_ip(req({"X-Forwarded-For": "junk, 192.168.1.20"})) == "192.168.1.20"
    assert client_ip(req({})) == "1.1.1.1"


# ---------------------------------------------------------------- 14. logout

