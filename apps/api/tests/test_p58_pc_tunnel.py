"""P58: one site's traffic through a company computer. The gateway tunnels the egress proxy's
CONNECT through the workspace's chosen computer only when the setting is on, the site is on
the list, the computer's own person allows it and the computer is online; otherwise it says
"not mine" (409, the egress goes direct) or refuses (503, the workspace said wait)."""

import asyncio
import base64

from sqlalchemy import select

from agentic.core.db import SessionLocal
from agentic.core.valkey import valkey
from agentic.devices import tunnel
from agentic.models import Device

from .conftest import csrf
from .test_agents import llm, office, temporal  # noqa: F401
from .test_devices import (
    FakePC,
    FakeWS,
    ids_of,
    link,
    personal_agent,
)


class SitePC(FakePC):
    """A computer that opens the "site" itself: it echoes what the browser sends."""

    async def handle(self, method: str, params: dict) -> dict:
        if method != "net.open":
            return await super().handle(method, params)
        relay = await FakeWS(f"/api/devices/cdp/{params['channel']}").connect()
        await relay.send_json({"type": "hello", "token": self.token})
        self.opened = (params["host"], params["port"])

        async def echo() -> None:
            while (data := await relay.recv(timeout=None)) is not None:
                await relay.send_bytes(b"SITE:" + data)

        self.echo = asyncio.create_task(echo())
        return {"ok": True}


async def _connect(port: int, host: str, ws_id: str | None, password: str | None = None):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    head = f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
    if ws_id is not None:
        cred = base64.b64encode(f"{ws_id}:{password or tunnel.sign(ws_id)}".encode()).decode()
        head += f"Proxy-Authorization: Basic {cred}\r\n"
    w.write((head + "\r\n").encode())
    await w.drain()
    status = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 15)
    return r, w, status


async def test_a_site_goes_through_the_chosen_company_computer(client, llm, temporal):
    o = await office(client)
    owner_id, ws_id = await ids_of("owner@example.com")
    await personal_agent(o, owner_id, ws_id, is_twin=True)
    dev = await link(client)
    pc = await SitePC(dev["token"]).start()
    server = await asyncio.start_server(tunnel.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        # The computer's person lets the site through (what `agentic-pc tunnel on` sends).
        await pc.ws.send_json(
            {"type": "state", "tunnel": {"on": True, "hosts": ["eperolehan.gov.my"]}}
        )
        for _ in range(50):
            async with SessionLocal() as db:
                d = await db.scalar(select(Device).where(Device.id == dev["device_id"]))
                if d.tunnel_hosts == ["eperolehan.gov.my"]:
                    break
            await asyncio.sleep(0.05)
        assert d.tunnel_hosts == ["eperolehan.gov.my"]

        # P69: nothing chosen in the workspace: ePerolehan still goes through a linked computer
        # that allowed it (a residential line), never from the server's own address.
        _, w, status = await _connect(port, "www.eperolehan.gov.my", ws_id)
        assert status.startswith(b"HTTP/1.1 200")
        w.close()
        # Other sites are not the gateway's (the egress proxy goes direct).
        _, w, status = await _connect(port, "example.com", ws_id)
        assert status.startswith(b"HTTP/1.1 409")
        w.close()

        r = await client.put(
            "/api/org/computers/tunnel",
            json={"on": True, "device_id": dev["device_id"], "hosts": ["eperolehan.gov.my"]},
            headers=csrf(client),
        )
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["on"] and got["fallback"] == "wait"
        assert next(c for c in got["computers"] if c["id"] == dev["device_id"])["allows"] == [
            "eperolehan.gov.my"
        ]

        # Through the computer: the bytes reach the "site" it opened, and come back.
        r1, w1, status = await _connect(port, "www.eperolehan.gov.my", ws_id)
        assert status.startswith(b"HTTP/1.1 200"), status
        assert pc.opened == ("www.eperolehan.gov.my", 443)
        w1.write(b"client hello")
        await w1.drain()
        assert await asyncio.wait_for(r1.read(100), 5) == b"SITE:client hello"
        w1.close()

        # A forged password, another site: never tunnelled.
        _, w, status = await _connect(port, "www.eperolehan.gov.my", ws_id, "forged")
        assert status.startswith(b"HTTP/1.1 409")
        w.close()
        _, w, status = await _connect(port, "www.other.gov.my", ws_id)
        assert status.startswith(b"HTTP/1.1 409")
        w.close()

        # The computer goes offline: refused, with why (the workspace said wait).
        await pc.stop()
        _, w, status = await _connect(port, "www.eperolehan.gov.my", ws_id)
        assert status.startswith(b"HTTP/1.1 503")
        w.close()
        log = (await client.get("/api/audit")).json()["items"]
        assert any(e["action"] == "devices.tunnel" for e in log)
    finally:
        server.close()
        await pc.stop()


async def test_the_computer_must_allow_the_site_itself(client, llm, temporal):
    """P62: choosing a computer asks its person there (Allow / Not now); until they allow it
    the site is refused with why, and never goes out from the server instead."""
    o = await office(client)
    owner_id, ws_id = await ids_of("owner@example.com")
    await personal_agent(o, owner_id, ws_id, is_twin=True)
    dev = await link(client)
    pc = await SitePC(dev["token"]).start()
    try:
        r = await client.put(
            "/api/org/web",
            json={"mode": "pc", "sites": ["eperolehan.gov.my"], "device_id": dev["device_id"]},
            headers=csrf(client),
        )
        assert r.status_code == 200, r.text
        assert r.json()["asked"] is True and r.json()["mode"] == "pc"
        for _ in range(50):
            if any(m["type"] == "tunnel_ask" for m in pc.other):
                break
            await asyncio.sleep(0.05)
        ask = next(m for m in pc.other if m["type"] == "tunnel_ask")
        assert ask["hosts"] == ["eperolehan.gov.my"] and ask["by"]
        status, msg, device = await tunnel.decide(ws_id, "eperolehan.gov.my")
        assert status == 503 and "has not allowed it yet" in msg and device is None
        assert "has not allowed" in await tunnel.unavailable(ws_id, "www.eperolehan.gov.my")
        assert await tunnel.unavailable(ws_id, "example.com") == ""  # other sites: the server

        # Allow pressed on the computer's page: the agent reports it, and it goes through.
        await pc.ws.send_json(
            {"type": "state", "tunnel": {"on": True, "hosts": ["eperolehan.gov.my"]}}
        )
        for _ in range(50):
            if (await tunnel.route(ws_id, "www.eperolehan.gov.my")).kind == "computer":
                break
            await asyncio.sleep(0.05)
        assert (await tunnel.route(ws_id, "www.eperolehan.gov.my")).kind == "computer"
        got = (await client.get("/api/org/web")).json()
        me = next(c for c in got["computers"] if c["id"] == dev["device_id"])
        assert me["allows"] == ["eperolehan.gov.my"] and me["online"] and not me["can_ask"]

        # A computer carries only listed sites.
        r = await client.put(
            "/api/org/web",
            json={"mode": "pc", "sites": ["*"], "device_id": dev["device_id"]},
            headers=csrf(client),
        )
        assert r.status_code == 422
    finally:
        await pc.stop()


async def test_work_on_the_site_opens_on_the_computers_screen(client, llm, temporal):
    """P59: with "show" on, a task that works only on the chosen sites opens its browser on
    that computer (a real window its person watches); otherwise on the server."""
    o = await office(client)
    owner_id, ws_id = await ids_of("owner@example.com")
    await personal_agent(o, owner_id, ws_id, is_twin=True)
    dev = await link(client)
    pc = await SitePC(dev["token"]).start()
    try:
        await pc.ws.send_json(
            {"type": "state", "tunnel": {"on": True, "hosts": ["eperolehan.gov.my"]}}
        )
        await client.put(
            "/api/org/computers/tunnel",
            json={"on": True, "device_id": dev["device_id"], "show": True},
            headers=csrf(client),
        )
        for _ in range(50):
            async with SessionLocal() as db:
                got = await tunnel.screen_for(db, ws_id, ["eperolehan.gov.my"])
            if got[0]:
                break
            await asyncio.sleep(0.05)
        assert got == (dev["device_id"], "")
        async with SessionLocal() as db:
            assert await tunnel.screen_for(db, ws_id, None) == ("", "")  # any site: the server
            assert await tunnel.screen_for(db, ws_id, ["example.com"]) == ("", "")
        await pc.stop()
        async with SessionLocal() as db:  # offline, and the workspace said wait: why
            dev_id, why = await tunnel.screen_for(db, ws_id, ["eperolehan.gov.my"])
        assert dev_id == "" and "offline" in why
    finally:
        await pc.stop()


async def test_the_task_rests_when_the_site_needs_a_break(client, llm, temporal, monkeypatch):
    """P59: the site budget's rest becomes the task's rest (the workflow sleeps it), and the
    agent reads a plain note, not an error, so it carries on afterwards."""
    from agentic.agents import runtime
    from agentic.models import AgentMessage

    from .test_agents import new_agent, new_task

    o = await office(client)
    a = await new_agent(client, o, "Rina", tools={"browser_open": "allow"})
    t = await new_task(client, a, "Check tender QT123 on ePerolehan")
    await client.post(f"/api/tasks/{t['id']}/start", json={}, headers=csrf(client))

    async def resting(ctx, name, args, call_id):
        return "Error: SITE_REST 420: a short break after a long sitting, as a person takes"

    monkeypatch.setattr(runtime, "run_tool_once", resting)
    llm.call("browser_open", url="https://www.eperolehan.gov.my/")
    r = await runtime.run_task_step(t["id"])
    assert r.state == "rest" and r.timeout_seconds == 420
    async with SessionLocal() as db:
        note = await db.scalar(
            select(AgentMessage.content).where(
                AgentMessage.task_id == t["id"], AgentMessage.role == "tool"
            )
        )
    assert note.startswith("Paused on the site: a short break") and "SITE_REST" not in note


class FakeProxy:
    """An outbound proxy: checks its password, then echoes what passes through it."""

    def __init__(self, user: str = "u", password: str = "p") -> None:  # noqa: S107 - a test fake
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.connects: list[str] = []

    async def handle(self, r, w) -> None:
        head = await r.readuntil(b"\r\n\r\n")
        if f"Proxy-Authorization: Basic {self.auth}".encode() not in head:
            w.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
            await w.drain()
            w.close()
            return
        self.connects.append(head.split(b" ")[1].decode())
        w.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await w.drain()
        while data := await r.read(4096):
            w.write(b"VIA-PROXY:" + data)
            await w.drain()
        w.close()


def test_p84_a_maintenance_page_is_reached_not_blocked():
    """ePerolehan's weekly maintenance answers 503 with a Malay notice: the connection works."""
    page = "Selamat Datang ke Portal ePerolehan AKTIVITI PENYELENGGARAAN MINGGUAN Dimaklumkan"
    got = tunnel.read_answer(503, page)
    assert got["maintenance"] is True and got["blocked"] is False and got["ok"] is False
    blocked = tunnel.read_answer(403, "Your request was blocked for security reasons")
    assert blocked["blocked"] is True and blocked["maintenance"] is False
    assert tunnel.read_answer(200, "Selamat datang")["maintenance"] is False


def test_a_sites_answer_reads_as_opened_or_blocked():
    """P62: the check reads ePerolehan's block page: refused, and the address it saw."""
    page = (
        "<html><head><style>body{}</style></head><body><h1>ePerolehan Access Is Currently "
        "Unavailable</h1><p>Your request was blocked for security reasons.</p>"
        "<p>Your IP address: 84.46.249.133</p><script>x()</script></body></html>"
    )
    got = tunnel.read_answer(403, page)
    assert got["blocked"] and not got["ok"] and got["seen_ip"] == "84.46.249.133"
    assert "blocked for security reasons" in got["says"]
    fine = tunnel.read_answer(200, "<html><body>Welcome to ePerolehan</body></html>")
    assert fine["ok"] and not fine["blocked"] and fine["seen_ip"] == "" and fine["says"] == ""


def test_saved_before_p62_the_two_switches_become_one_choice():
    from agentic.models import Workspace

    ws = Workspace(id="w1", name="x", settings={"pc_tunnel": {"on": True, "hosts": ["a.gov.my"]}})
    assert tunnel.mode_of(ws) == tunnel.Mode("pc", ["a.gov.my"])
    ws.settings = {"web_proxy": {"on": True}}
    assert tunnel.mode_of(ws) == tunnel.Mode("proxy", ["*"])
    ws.settings = {}
    assert tunnel.mode_of(ws) == tunnel.Mode("pc", ["eperolehan.gov.my"])  # P69: the default
    ws.settings = {"web_route": {"mode": "pc", "sites": ["*"]}}
    assert tunnel.mode_of(ws).sites == ["eperolehan.gov.my"]  # a computer never takes every site


async def test_p84_check_opens_the_site_in_the_computers_own_browser(
    client, llm, temporal, monkeypatch
):
    """P84: Check tries the way on the screen (saved or not). Through a computer whose screen
    shows the AI's work, the site opens in that computer's own browser window and the answer
    is read from that page; never from a proxy or the server. An older app is told to update."""
    await office(client)
    dev = await link(client)
    pc = await SitePC(dev["token"]).start()
    try:
        await pc.ws.send_json(
            {"type": "state", "tunnel": {"on": True, "hosts": ["eperolehan.gov.my"]}}
        )
        for _ in range(50):
            async with SessionLocal() as db:
                d = await db.scalar(select(Device).where(Device.id == dev["device_id"]))
                if d.tunnel_hosts == ["eperolehan.gov.my"]:
                    break
            await asyncio.sleep(0.05)
        async with SessionLocal() as db:  # a current app (it asks with Allow)
            d = await db.get(Device, dev["device_id"])
            d.version = "0.6.0"
            await db.commit()
        opened: list[tuple[str, str, list]] = []
        closed: list[str] = []

        async def open_browser(device_id, start_url=None, **kw):
            opened.append((device_id, start_url, kw.get("sites")))
            return "ch-1", "ws://relay/ch-1"

        async def read_page(ws_url, host, wait=25.0):
            assert ws_url == "ws://relay/ch-1" and host == "eperolehan.gov.my"
            return {
                "ready": "complete",
                "url": "https://www.eperolehan.gov.my/home",
                "title": "ePerolehan",
                "status": 200,
                "text": "Selamat datang",
            }

        async def close_later(device_id, channel):
            closed.append(channel)

        monkeypatch.setattr(tunnel.bridge, "open_browser", open_browser)
        monkeypatch.setattr(tunnel, "read_page", read_page)
        monkeypatch.setattr(tunnel, "_close_later", close_later)

        # Saved: proxies. On the screen: this computer, not saved yet. Check uses the screen.
        choice = {
            "site": "eperolehan.gov.my",
            "mode": "pc",
            "sites": ["eperolehan.gov.my"],
            "device_id": dev["device_id"],
            "show": True,
        }
        r = await client.post("/api/org/web/check", json=choice, headers=csrf(client))
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["way"] == "pc" and got["screen"] is True and got["ok"] is True
        assert got["site"] == "www.eperolehan.gov.my" and not got.get("via")
        assert got["computer"]  # the computer by its own name
        assert opened == [
            (dev["device_id"], "https://www.eperolehan.gov.my/", ["eperolehan.gov.my"])
        ]
        await asyncio.sleep(0)
        assert closed == ["ch-1"]  # the window closes a little later

        # Another office's computer cannot be named.
        _, ws_id = await ids_of("owner@example.com")
        await valkey().delete(f"web:check:{ws_id}")  # one check at a time: the next one now
        bad = await client.post(
            "/api/org/web/check", json={**choice, "device_id": "dev_other"}, headers=csrf(client)
        )
        assert bad.status_code == 422

        # An older app that has not allowed the site: told to update, not "press Allow".
        async with SessionLocal() as db:
            d = await db.get(Device, dev["device_id"])
            d.version, d.tunnel_hosts = "0.4.2", []
            await db.commit()
        await valkey().delete(f"web:check:{ws_id}")
        r = await client.post("/api/org/web/check", json=choice, headers=csrf(client))
        got = r.json()
        assert got["way"] == "refuse" and "older Agentic Office app" in got["why"]
    finally:
        await pc.stop()
