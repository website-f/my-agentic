"""P97: the desk as each person's virtual desk.

Pin anything (a screen of the app or Prima, a web link, a report) with the server
checking what may be pinned; rename pins, keep them in folders, reorder and move them; the
desk's sections shown, hidden and reordered per person; pins that are no longer the person's
to see show as unavailable without saying what the thing is now; finding tasks, agents,
people and reports by name within what the person may open; today's meetings.
"""




from .conftest import csrf
from .test_agents import llm, office, temporal  # noqa: F401

JSON = {"content-type": "application/json"}


async def _pin(c, kind, ref, title="", **extra):
    return await c.post(
        "/api/desk/items", json={"kind": kind, "ref": ref, "title": title, **extra}, headers=csrf(c)
    )

