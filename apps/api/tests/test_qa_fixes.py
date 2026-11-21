"""Fixes from the live QA: true totals in the assistant's slipping report, bulk retry of
failed work, chat sessions that move up when continued, a light and paged task list, a light
skill-proposal queue, deleting tasks / conversations / workflows, and an honest done count."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from agentic.api.scope import member_scope
from agentic.assistants import insights
from agentic.core.db import SessionLocal
from agentic.models import (
    Agent,
    SkillProposal,
    Task,
    User,
    Workflow,
    WorkflowRun,
)

from .conftest import csrf as _csrf
from .test_agents import llm, new_agent, new_task, office, temporal  # noqa: F401


def csrf(c: httpx.AsyncClient) -> dict[str, str]:
    """CSRF plus the JSON content type every state-changing call (DELETE too) must carry."""
    return {"content-type": "application/json", **_csrf(c)}


async def _seed(
    agent: dict,
    branch_id: str,
    n: int,
    status: str,
    hours_ago: float,
    prefix: str,
    error: str | None = None,
) -> list[str]:
    """Tasks written straight to the database, `hours_ago` old."""
    now = datetime.now(UTC)
    ids = []
    async with SessionLocal() as db:
        ws = (await db.get(Agent, agent["id"])).workspace_id  # type: ignore[union-attr]
        owner = await db.scalar(select(User))
        assert owner is not None
        for i in range(n):
            t = Task(
                workspace_id=ws,
                branch_id=branch_id,
                title=f"{prefix} {i}",
                brief="",
                assignee_agent_id=agent["id"],
                created_by=f"user:{owner.id}",
                status=status,
                error=error,
                position=float(i),
            )
            db.add(t)
            await db.flush()
            t.created_at = t.updated_at = now - timedelta(hours=hours_ago)
            if status in ("done", "failed", "review", "cancelled"):
                t.finished_at = now - timedelta(hours=hours_ago)
            ids.append(t.id)
        await db.commit()
    return ids


# ---------------------------------------------------------------- 1. insight totals


async def test_slacking_report_states_true_totals(client: httpx.AsyncClient, llm, temporal):
    o = await office(client)
    faiz = await new_agent(client, o, "Faiz", "Finance")
    bid = o["branch"]["id"]
    await _seed(faiz, bid, 12, "failed", 5, "Broken", error="Portal timed out")
    await _seed(faiz, bid, 3, "failed", 24 * 20, "Ancient", error="old")  # outside the window
    await _seed(faiz, bid, 11, "ready", 30, "Waiting")
    async with SessionLocal() as db:
        ws = (await db.get(Agent, faiz["id"])).workspace_id  # type: ignore[union-attr]
        now = datetime.now(UTC)
        for i, age in enumerate((2, 50)):
            db.add(
                SkillProposal(
                    workspace_id=ws,
                    kind="new",
                    name=f"skill-{i}",
                    description="A skill waiting for review.",
                    body="## When to use\nx",
                    proposed_by=f"agent:{faiz['id']}",
                    agent_id=faiz["id"],
                    created_at=now - timedelta(hours=age),
                )
            )
        await db.commit()
        owner = await db.scalar(select(User))
        assert owner is not None
        sc = await member_scope(db, ws, owner.id)
        assert sc is not None
        slack = await insights.slacking_report(db, ws, sc, 7)
        pulse = await insights.company_pulse(db, ws, sc, 7)
    assert "## Failed and not retried: 12 total (showing 10)" in slack
    assert "3 more failed earlier and were never retried" in slack
    assert "## Not started after a day: 11 total (showing 10)" in slack
    assert "## Skill proposals waiting for review: 2, oldest waiting since 2 days ago" in slack
    assert "skill-1 (new), proposed by Faiz" in slack
    assert sum(1 for line in slack.splitlines() if line.startswith("- Broken")) == 10
    assert "## Recent failures: 12 total (showing 5)" in pulse
    assert "Skill proposals waiting for review: 2" in pulse


# ---------------------------------------------------------------- 2. bulk retry


# ---------------------------------------------------------------- 3 + 6. chat sessions


# ---------------------------------------------------------------- 4. task list


async def test_task_list_pages_and_trims(client: httpx.AsyncClient, llm, temporal):
    o = await office(client)
    faiz = await new_agent(client, o, "Faiz", "Finance")
    long = "word " * 300  # 1500 characters
    made = [(await new_task(client, faiz, f"Job {i}", brief=long))["id"] for i in range(5)]

    r = await client.get("/api/tasks?limit=2")
    assert r.status_code == 200
    page1 = r.json()
    assert len(page1) == 2 and r.headers["x-next-before"] == page1[-1]["id"]
    assert all(t["truncated"] and len(t["brief"]) <= 401 for t in page1)
    seen = [t["id"] for t in page1]
    cursor = r.headers["x-next-before"]
    while cursor:
        r = await client.get(f"/api/tasks?limit=2&before={cursor}")
        seen += [t["id"] for t in r.json()]
        cursor = r.headers.get("x-next-before")
    assert sorted(seen) == sorted(made) and len(seen) == 5  # every task once, none twice
    assert [t["id"] for t in (await client.get("/api/tasks")).json()] == seen  # same order

    detail = (await client.get(f"/api/tasks/{made[0]}")).json()["task"]
    assert detail["brief"] == long.strip() or detail["brief"] == long
    assert detail["truncated"] is False
    full = (await client.get("/api/tasks?full=true")).json()
    assert all(not t["truncated"] and len(t["brief"]) >= 1400 for t in full)
    assert (await client.get("/api/tasks?limit=501")).status_code == 422
    assert (await client.get("/api/tasks?before=tk_missing")).status_code == 400


# ---------------------------------------------------------------- 5. proposal queue


async def test_proposal_list_is_light_and_detail_is_full(client: httpx.AsyncClient, llm, temporal):
    o = await office(client)
    faiz = await new_agent(client, o, "Faiz", "Finance")
    body = "## When to use\n" + "Check every line carefully. " * 200
    async with SessionLocal() as db:
        ws = (await db.get(Agent, faiz["id"])).workspace_id  # type: ignore[union-attr]
        sp = SkillProposal(
            workspace_id=ws,
            kind="new",
            name="careful-check",
            description="Check every line of a statement.",
            body=body,
            proposed_by=f"agent:{faiz['id']}",
            agent_id=faiz["id"],
            eval_cases=[{"title": "one", "input": "x" * 3000}],
            eval={
                "new": {
                    "passed": 1,
                    "total": 1,
                    "tokens": 10,
                    "cases": [{"title": "one", "pass": True, "failures": [], "output": "y" * 5000}],
                }
            },
            created_at=datetime.now(UTC),
        )
        db.add(sp)
        await db.commit()
        sp_id = sp.id
    rows = (await client.get("/api/skill-proposals")).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["body_truncated"] and len(row["body"]) == 1000
    assert row["eval"]["new"] == {"passed": 1, "total": 1, "tokens": 10, "cases": []}
    assert row["eval_case_count"] == 1 and "eval_cases" not in row
    assert row["proposed_by_name"] == "Faiz"
    full = (await client.get(f"/api/skill-proposals/{sp_id}")).json()
    assert full["body"] == body and full["eval"]["new"]["cases"][0]["output"] == "y" * 5000
    assert full["eval_cases"][0]["input"] == "x" * 3000


# ---------------------------------------------------------------- 6. delete tasks


async def test_cancel_and_delete_cascade_to_open_sub_tasks(
    client: httpx.AsyncClient, llm, temporal
):
    """A stopped task whose sub-task is still open can be cancelled (cascading to the
    sub-task) and then deleted, or deleted with cascade=true in one step."""
    o = await office(client)
    faiz = await new_agent(client, o, "Faiz")
    parent = await new_task(client, faiz, "Find: how to submit a tender")

    async def with_child(parent_status: str) -> str:
        async with SessionLocal() as db:
            p = await db.get(Task, parent["id"])
            p.status = parent_status
            child = Task(
                workspace_id=p.workspace_id,
                branch_id=p.branch_id,
                title="Sub-step",
                created_by="agent:x",
                status="running",
                parent_task_id=p.id,
                depth=1,
            )
            db.add(child)
            await db.commit()
            return child.id

    # Stopped parent (failed), open child: delete refuses, then cascade cancels the child.
    child_id = await with_child("failed")
    r = await client.delete(f"/api/tasks/{parent['id']}", headers=csrf(client))
    assert r.status_code == 409 and r.json()["code"] == "children_active"
    r = await client.delete(f"/api/tasks/{parent['id']}?cascade=true", headers=csrf(client))
    assert r.status_code == 204, r.text
    async with SessionLocal() as db:
        assert await db.get(Task, parent["id"]) is None
        assert await db.get(Task, child_id) is None  # cancelled, then cascaded away

    # Cancelling a task cancels its open sub-tasks, so nothing is left running.
    parent2 = await new_task(client, faiz, "Another tender")
    async with SessionLocal() as db:
        p = await db.get(Task, parent2["id"])
        p.status = "running"
        grand = Task(
            workspace_id=p.workspace_id,
            branch_id=p.branch_id,
            title="Deep step",
            created_by="agent:x",
            status="ready",
            parent_task_id=p.id,
            depth=1,
        )
        db.add(grand)
        await db.commit()
        grand_id = grand.id
    r = await client.post(f"/api/tasks/{parent2['id']}/cancel", headers=csrf(client))
    assert r.status_code == 200, r.text
    async with SessionLocal() as db:
        assert (await db.get(Task, grand_id)).status == "cancelled"
    r = await client.delete(f"/api/tasks/{parent2['id']}", headers=csrf(client))
    assert r.status_code == 204, r.text  # no open children left: deletes cleanly


# ---------------------------------------------------------------- 7. delete workflows


async def test_delete_workflow_refuses_live_runs_and_takes_finished_ones(
    client: httpx.AsyncClient, llm, temporal
):
    await office(client)
    wf = (
        await client.post("/api/workflows", json={"name": "Month end"}, headers=csrf(client))
    ).json()
    async with SessionLocal() as db:
        w = await db.get(Workflow, wf["id"])
        assert w is not None
        run = WorkflowRun(
            workspace_id=w.workspace_id,
            workflow_id=w.id,
            name="Month end",
            title="September",
            created_by="user:x",
            status="waiting",
        )
        db.add(run)
        await db.commit()
        run_id = run.id
    r = await client.delete(f"/api/workflows/{wf['id']}", headers=csrf(client))
    assert r.status_code == 409 and r.json()["code"] == "runs_active"
    async with SessionLocal() as db:
        row = await db.get(WorkflowRun, run_id)
        assert row is not None
        row.status = "done"
        await db.commit()
    r = await client.delete(f"/api/workflows/{wf['id']}", headers=csrf(client))
    assert r.status_code == 204
    async with SessionLocal() as db:
        assert await db.get(WorkflowRun, run_id) is None  # no orphaned run left behind


# ---------------------------------------------------------------- 8. overview

