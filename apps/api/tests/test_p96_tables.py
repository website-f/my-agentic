"""P96: data tables. The AI use and limits list is searched, filtered, sorted and paged on the
server (api/table.py), works out everyone's use in a few queries, and keeps its permissions."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from agentic.core.db import SessionLocal
from agentic.core.security import hash_password
from agentic.models import LLMCall, Membership, User, Workspace


HASH = hash_password("not-used-in-these-tests")


async def _ws() -> Workspace:
    async with SessionLocal() as db:
        return (await db.scalars(select(Workspace).order_by(Workspace.created_at))).first()


async def _people(n: int, branch_id: str | None, role: str = "staff", start: int = 0) -> list[str]:
    ws = await _ws()
    ids = []
    async with SessionLocal() as db:
        for i in range(start, start + n):
            u = User(email=f"person{i:03d}@example.com", name=f"Person {i:03d}", password_hash=HASH)
            db.add(u)
            await db.flush()
            db.add(Membership(workspace_id=ws.id, user_id=u.id, role=role, branch_id=branch_id))
            ids.append(u.id)
        await db.commit()
    return ids


async def _used(user_id: str, tokens: int, cost: float = 0.0, task: str = "chat") -> None:
    ws = await _ws()
    async with SessionLocal() as db:
        db.add(
            LLMCall(
                workspace_id=ws.id,
                ts=datetime.now(UTC),
                task=task,
                provider_name="Good",
                model="m1",
                user_id=user_id,
                prompt_tokens=tokens,
                completion_tokens=0,
                cost_usd=cost,
                status="ok",
            )
        )
        await db.commit()


async def _table(c, **params) -> tuple[dict, int]:
    r = await c.get("/api/allowances", params={"page": 1, "size": 10, **params})
    assert r.status_code == 200, r.text
    return r.json(), int(r.headers["X-Total-Count"])


# ------------------------------------------------- the other lists that became tables


async def test_activity_and_approvals_come_in_numbered_pages(client):
    from datetime import timedelta

    from agentic.models import Approval, AuditLog, Task

    from .test_pagination import add, at, owner

    o = await owner(client)
    # Activity: the setup wrote a few entries; add 30 more, some about a person by name.
    async with SessionLocal() as db:
        from agentic.services import audit

        for i in range(30):
            await audit.record(
                db,
                o["ws"],
                f"user:{o['user']}",
                "task.created" if i % 2 else "file.uploaded",
                target=f"t{i}",
                note=f"Rondaan malam {i}" if i % 5 == 0 else None,
            )
        await db.commit()
        everything = await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.workspace_id == o["ws"])
        )
    r = await client.get("/api/audit", params={"page": 1, "size": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert int(r.headers["X-Total-Count"]) == everything and len(body["items"]) == 10
    assert body["kinds"] and "X-Next-Cursor" not in r.headers
    ids = [x["id"] for x in body["items"]]
    assert ids == sorted(ids, reverse=True)  # newest first
    oldest = (await client.get("/api/audit", params={"page": 1, "size": 10, "sort": "ts"})).json()
    assert [x["id"] for x in oldest["items"]] == sorted(x["id"] for x in oldest["items"])
    assert oldest["items"][0]["id"] < ids[-1]
    r = await client.get("/api/audit", params={"page": 1, "q": "rondaan"})
    assert int(r.headers["X-Total-Count"]) == 6
    r = await client.get("/api/audit", params={"page": 1, "q": "owner task.created"})
    assert int(r.headers["X-Total-Count"]) == 15  # by the owner's name, and the action
    r = await client.get("/api/audit", params={"page": 1, "kind": "work", "q": "file"})
    assert int(r.headers["X-Total-Count"]) == 15
    # The lazy list still pages by cursor, and its count follows the search.
    r = await client.get("/api/audit", params={"limit": 4, "q": "rondaan"})
    assert len(r.json()["items"]) == 4 and int(r.headers["X-Total-Count"]) == 6
    r = await client.get("/api/audit", params={"page": 1, "sort": "actor"})
    assert r.status_code == 422

    # Approvals history: numbered pages, words, outcome, and the decided order.
    task = Task(
        workspace_id=o["ws"], title="Bayar invois pembekal", created_by="user:x", created_at=at(0)
    )
    await add(task)
    await add(
        *[
            Approval(
                workspace_id=o["ws"],
                task_id=task.id,
                agent_id=o["agent"],
                tool_name="send_email" if i % 2 else "browser_submit",
                tool_call_id=f"c{i}",
                reason=f"Reason {i}",
                status=("approved", "denied", "pending")[i % 3],
                created_at=at(i * 3),
                decided_at=at(100 - i * 3),
                expires_at=at(i) + timedelta(days=1),
            )
            for i in range(17)
        ]
    )
    r = await client.get("/api/approvals", params={"state": "history", "page": 1, "size": 5})
    assert int(r.headers["X-Total-Count"]) == 12 and len(r.json()) == 5
    first = r.json()
    assert first[0]["created_at"] >= first[-1]["created_at"]
    r = await client.get("/api/approvals", params={"state": "history", "page": 3, "size": 5})
    assert len(r.json()) == 2
    r = await client.get("/api/approvals", params={"state": "history", "page": 1, "q": "browser"})
    assert int(r.headers["X-Total-Count"]) == 6
    r = await client.get(
        "/api/approvals", params={"state": "history", "page": 1, "q": "invois aina"}
    )
    assert int(r.headers["X-Total-Count"]) == 12  # the task's title and the agent's name
    r = await client.get(
        "/api/approvals", params={"state": "history", "page": 1, "status": "denied"}
    )
    assert int(r.headers["X-Total-Count"]) == 6
    by_decided = (
        await client.get(
            "/api/approvals", params={"state": "history", "page": 1, "size": 50, "sort": "decided"}
        )
    ).json()
    assert [a["decided_at"] for a in by_decided] == sorted(a["decided_at"] for a in by_decided)


async def test_the_run_ledger_comes_in_numbered_pages(client):
    from agentic.models import JobRun, Schedule

    from .test_pagination import add, at, owner

    o = await owner(client)
    # The ledger shows runs of schedules whose agent the person sees.
    sched = Schedule(
        workspace_id=o["ws"],
        name="Semak portal tender",
        agent_id=o["agent"],
        title="Semak",
        cron="0 9 * * *",
        created_by="user:x",
    )
    await add(sched)
    await add(
        *[
            JobRun(
                workspace_id=o["ws"],
                schedule_id=sched.id,
                job="heartbeat" if i % 2 else "schedule",
                status="failed" if i % 5 == 0 else "completed",
                error="Portal tamat masa" if i % 5 == 0 else None,
                started_at=at(i),
            )
            for i in range(23)
        ]
    )
    r = await client.get("/api/runs", params={"page": 1, "size": 10})
    assert r.status_code == 200, r.text
    assert int(r.headers["X-Total-Count"]) == 23 and len(r.json()) == 10
    ids = [x["id"] for x in r.json()]
    assert ids == sorted(ids, reverse=True)
    r = await client.get("/api/runs", params={"page": 3, "size": 10, "sort": "started"})
    assert len(r.json()) == 3
    r = await client.get("/api/runs", params={"page": 1, "q": "tamat"})
    assert int(r.headers["X-Total-Count"]) == 5
    r = await client.get("/api/runs", params={"page": 1, "q": "portal tender"})
    assert int(r.headers["X-Total-Count"]) == 23  # the schedule's name
    r = await client.get("/api/runs", params={"page": 1, "job": "heartbeat", "status": "failed"})
    assert int(r.headers["X-Total-Count"]) == 2  # 5 and 15
    # The old shape (the newest 100) still answers without ?page=.
    assert len((await client.get("/api/runs")).json()) == 23
