"""P116 (feedback 19 Nov): an admin made a test account and connected her own work Microsoft
account in it; "Sign in with Microsoft" then landed in the test account, never her own. Now the
sign-in email decides first, a Microsoft account several people connected (a shared work
mailbox) never picks who signs in, and Prima's link follows only a person's own account."""

from sqlalchemy import select

from agentic.core.db import SessionLocal
from agentic.models import Membership, MicrosoftAccount

from .test_agents import llm, office, temporal  # noqa: F401
from .test_microsoft import TENANT, user_id
from .test_p63_microsoft_signin import anon, configure, sign_in, sso  # noqa: F401


async def _connected(email: str, oid: str, mailbox: str) -> str:
    """`email`'s account has the Microsoft account `oid` (`mailbox`) connected."""
    uid, _ = await user_id(email)
    async with SessionLocal() as db:
        ws = await db.scalar(select(Membership.workspace_id).where(Membership.user_id == uid))
        db.add(
            MicrosoftAccount(
                workspace_id=ws,
                user_id=uid,
                ms_user_id=oid,
                tenant_id=TENANT,
                email=mailbox,
                status="connected",
            )
        )
        await db.commit()
    return uid

