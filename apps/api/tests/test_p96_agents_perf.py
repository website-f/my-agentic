"""P96: the agents page, agent create, task start and the skills list stay fast in a big
workspace: ~250 members, ~100 agents (team agents, staff twins, private assistants), thousands
of tasks and a full skill library. Synthetic data only.

Each call is timed and its SQL statements counted: a list must not cost a query per row.
"""

import random
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, insert, select

from agentic.core.db import SessionLocal, engine
from agentic.models import Agent, Membership, Skill, SkillUse, Task, User

from .test_agents import llm, office, temporal  # noqa: F401

MEMBERS, TEAM_AGENTS, TWINS, ASSISTANTS, TASKS = 250, 30, 60, 10, 6000


@contextmanager
def counted():
    """How many SQL statements ran inside the block."""
    n = {"q": 0, "log": []}

    def on(_c, _cur, stmt, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        n["q"] += 1
        n["t"] = time.perf_counter()
        n["s"] = stmt

    def off(*_a, **_k):  # noqa: ANN002, ANN003
        n["log"].append((round((time.perf_counter() - n["t"]) * 1000), n["s"][:90]))

    event.listen(engine.sync_engine, "before_cursor_execute", on)
    event.listen(engine.sync_engine, "after_cursor_execute", off)
    try:
        yield n
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", on)
        event.remove(engine.sync_engine, "after_cursor_execute", off)


def _id(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:20]}"


async def _big_office(o: dict) -> dict:
    rnd = random.Random(96)  # noqa: S311 - synthetic data
    ws = o["branch"]["workspace_id"] if "workspace_id" in o["branch"] else None
    async with SessionLocal() as db:
        if ws is None:
            ws = (await db.scalar(select(Membership.workspace_id).limit(1))) or ""
        depts = list(o["depts"].values())
        branch = o["branch"]["id"]
        now = datetime.now(UTC)
        users, members = [], []
        roles = ["staff"] * 170 + ["supervisor"] * 30 + ["hod"] * 20 + ["branch_manager"] * 5
        roles += ["management"] * 5 + ["hr"] * 5 + ["viewer"] * 10 + ["operator"] * 5
        for i in range(MEMBERS):
            uid = _id("us")
            users.append(
                {"id": uid, "email": f"p{i}@example.com", "name": f"Person {i:03d}",
                 "password_hash": "x", "created_at": now, "updated_at": now}
            )  # fmt: skip
            members.append(
                {"workspace_id": ws, "user_id": uid, "role": roles[i % len(roles)],
                 "branch_id": branch, "department_id": rnd.choice(depts),
                 "created_at": now, "updated_at": now}
            )  # fmt: skip
        await db.execute(insert(User), users)
        await db.execute(insert(Membership), members)
        agents = []
        staff = [m for m in members if m["role"] == "staff"]
        leaders = [m for m in members if m["role"] in ("hod", "supervisor", "management")]
        for i in range(TEAM_AGENTS + TWINS + ASSISTANTS):
            kind = "team" if i < TEAM_AGENTS else "twin" if i < TEAM_AGENTS + TWINS else "pa"
            owner = (
                staff[i]["user_id"] if kind == "twin" else
                leaders[i % len(leaders)]["user_id"] if kind == "pa" else None
            )  # fmt: skip
            agents.append(
                {"id": _id("ag"), "workspace_id": ws, "branch_id": branch,
                 "department_id": rnd.choice(depts), "slug": f"a-{i}", "name": f"Agent {i:03d}",
                 "role": "Clerk", "owner_user_id": owner, "is_twin": kind == "twin",
                 "private": kind == "pa", "tools": {}, "sop_ids": [], "created_at": now,
                 "updated_at": now}
            )  # fmt: skip
        await db.execute(insert(Agent), agents)
        tasks = []
        statuses = ["done"] * 8 + ["failed", "cancelled", "ready", "running", "blocked", "review"]
        for i in range(TASKS):
            a = rnd.choice(agents)
            tasks.append(
                {"id": _id("tk"), "workspace_id": ws, "branch_id": branch,
                 "title": f"Job {i}", "brief": "", "status": rnd.choice(statuses),
                 "created_by": "user:x", "assignee_agent_id": a["id"],
                 "created_at": now - timedelta(minutes=i), "updated_at": now}
            )  # fmt: skip
        await db.execute(insert(Task), tasks)
        await db.commit()
        return {"ws": ws, "agents": agents, "tasks": tasks}


async def _learned_skills(ws: str, agents: list[dict], tasks: list[dict]) -> None:
    from agentic.brain import embed

    rnd = random.Random(7)  # noqa: S311 - synthetic data
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        rows = []
        for i in range(40):
            name = f"learned-procedure-{i}"
            desc = f"A procedure learned from repeated work number {i}, with its steps."
            rows.append(
                {"id": _id("sk"), "workspace_id": ws, "name": name, "description": desc,
                 "body": "## When to use\nRepeated work.\n\n## Steps\n1. read_file.\n" * 40,
                 "version": 1, "trust": "trusted", "status": "active", "agent_ids": [],
                 "created_by": f"agent:{agents[i]['id']}", "embedding":
                 await embed.embed_one(f"{name}: {desc}"), "created_at": now, "updated_at": now}
            )  # fmt: skip
        await db.execute(insert(Skill), rows)
        uses = [
            {"workspace_id": ws, "skill_id": rnd.choice(rows)["id"], "version": 1,
             "agent_id": rnd.choice(agents)["id"], "task_id": rnd.choice(tasks)["id"],
             "outcome": rnd.choice(["accepted", "sent_back", None]), "tokens": 1000,
             "created_at": now}
            for _ in range(3000)
        ]  # fmt: skip
        await db.execute(insert(SkillUse), uses)
        await db.commit()


async def _timed(label: str, call, results: dict):  # noqa: ANN001
    with counted() as n:
        t0 = time.perf_counter()
        r = await call()
        ms = (time.perf_counter() - t0) * 1000
    results[label] = (round(ms), n["q"])
    slow = sorted(n["log"], reverse=True)[:4]
    sql = sum(x[0] for x in n["log"])
    print(f"\n{label}: {round(ms)} ms, {n['q']} statements, SQL {sql} ms; slowest {slow}")
    return r

