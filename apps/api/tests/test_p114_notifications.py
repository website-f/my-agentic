"""P114 (Fitri, 18 Nov 2026): every person (staff to owner) sets how the office tells them
(email, the app, Telegram, WhatsApp) and about what; email is a delivery channel like the others;
the person whose AI ran out of allowance or waits for a manager hears of it."""


import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from agentic.channels import deliver
from agentic.core.db import SessionLocal
from agentic.models import Delivery, User, Workspace
from agentic.services import notify_prefs

from .test_agents import llm, office, temporal  # noqa: F401


@pytest.fixture
def sent(monkeypatch):
    out: list[dict] = []

    async def fake(db, workspace_id, **kw):
        out.append(kw)

    monkeypatch.setattr(deliver, "send_mail", fake)
    return out


async def _mail_on(ws_id: str) -> None:
    async with SessionLocal() as db:
        ws = await db.get(Workspace, ws_id)
        ws.settings = {
            **(ws.settings or {}),
            "system_mail": {"enabled": True, "address": "noreply@example.com"},
        }
        flag_modified(ws, "settings")
        await db.commit()


async def _rows(user_id: str, channel: str = "email") -> list[Delivery]:
    async with SessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Delivery)
                    .where(Delivery.target == user_id, Delivery.channel == channel)
                    .order_by(Delivery.created_at)
                )
            ).all()
        )


def test_defaults_and_what_email_carries():
    u = User(id="u1", email="a@example.com", name="A", prefs={})
    assert notify_prefs.wants(u, "my_ai", "email") and notify_prefs.wants(u, "limit", "app")
    assert not notify_prefs.wants(u, "other", "email")  # small notices: email only when asked
    assert notify_prefs.wants(u, "other", "telegram")
    u.prefs = {"notify": {"channels": {"email": False}, "events": {"done": False}}}
    assert not notify_prefs.wants(u, "my_ai", "email")
    assert not notify_prefs.wants(u, "done", "app") and notify_prefs.wants(u, "limit", "app")
    u.prefs = {"notify": {"email_other": True}}
    assert notify_prefs.wants(u, "other", "email")

