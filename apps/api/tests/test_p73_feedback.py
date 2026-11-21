"""P73: feedback from the floating button, read by the developer.

The developer is an owner the operator marked (admin make-developer); only they see the
Feedbacks page, switch the button on and off, write the house rules and answer. Everyone
signed in may send while it is on, and sees only their own pieces.
"""

import base64

import httpx
from sqlalchemy import update

from agentic.core.db import SessionLocal
from agentic.models import User

from .conftest import csrf

# The smallest valid PNG (1x1), and a JPEG head.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
SHOT = "data:image/png;base64," + base64.b64encode(PNG).decode()


async def make_dev(email: str = "owner@example.com") -> None:
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_developer=True))
        await db.commit()


async def switch_on(c: httpx.AsyncClient, on: bool = True) -> None:
    r = await c.put("/api/feedback/config", json={"enabled": on}, headers=csrf(c))
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is on

