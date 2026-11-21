"""P96: work gets the office skill it needs, by itself (agents/skill_grant.py).

A management or HR user's own new agent gets the skill (and the tools its steps need) the
moment work reaches it; staff cannot change a team agent this way; another person's private
assistant is never changed; a skill learned on one agent's work reaches a colleague in the
same company, never an isolated company's agents. Synthetic people only (example.com).
"""


import pytest
from sqlalchemy import select

from agentic.agents import skill_grant
from agentic.brain import embed
from agentic.core.db import SessionLocal
from agentic.models import Agent, Skill, TaskEvent, User

from .conftest import csrf
from .test_agents import llm, new_agent, office, temporal  # noqa: F401

ONBOARD = (
    "Prepare the staff onboarding file for our new hire: the appointment letter, the "
    "documents to collect and a tidy staff file."
)


async def _skill(name: str) -> Skill:
    async with SessionLocal() as db:
        s = await db.scalar(select(Skill).where(Skill.name == name))
        assert s is not None, name
        return s


async def _limit(owner, name: str, agent_ids: list[str]) -> Skill:
    """The owner limits a skill to some agents (Skills page: who uses it)."""
    await owner.get("/api/skills")  # the built-in skills are in place
    s = await _skill(name)
    r = await owner.patch(f"/api/skills/{s.id}", json={"agent_ids": agent_ids}, headers=csrf(owner))
    assert r.status_code == 200, r.text
    return await _skill(name)


async def _agent(agent_id: str) -> Agent:
    async with SessionLocal() as db:
        a = await db.get(Agent, agent_id)
        assert a is not None
        return a


async def _events(task_id: str) -> list[TaskEvent]:
    async with SessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(TaskEvent)
                    .where(TaskEvent.task_id == task_id, TaskEvent.kind == "skill")
                    .order_by(TaskEvent.id)
                )
            ).all()
        )


async def _uid(email: str) -> str:
    async with SessionLocal() as db:
        return (await db.scalar(select(User.id).where(User.email == email))) or ""


async def _task(c, agent_id: str, title: str, brief: str = "") -> dict:
    r = await c.post(
        "/api/tasks",
        json={"title": title, "brief": brief, "assignee_agent_id": agent_id, "start": True},
        headers=csrf(c),
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- management: ePerolehan


# ---------------------------------------------------------------- HR: an HR skill


# ---------------------------------------------------------------- who may not


# ---------------------------------------------------------------- learned skills


@pytest.mark.parametrize("isolated", [False, True])
async def test_a_learned_skill_reaches_a_colleague_but_never_an_isolated_company(
    client, llm, temporal, isolated
):
    o = await office(client)
    r = await client.post(
        "/api/branches", json={"name": "Jaya Bhd", "isolated": True}, headers=csrf(client)
    )
    b2 = r.json()
    b2_fin = {d["name"]: d["id"] for d in b2["departments"]}["Finance"]
    learner = await new_agent(client, o, "Faiz", "Finance")
    colleague = await new_agent(client, o, "Aina", "Finance")
    far = (
        await client.post(
            "/api/agents",
            json={"branch_id": b2["id"], "department_id": b2_fin, "name": "Far", "role": "Clerk"},
            headers=csrf(client),
        )
    ).json()
    home = far if isolated else learner  # where the skill was learned
    name, desc = (
        "supplier-statement-reconcile",
        "Reconcile a supplier statement against our ledger and list every difference.",
    )
    async with SessionLocal() as db:
        db.add(
            Skill(
                workspace_id=(await db.get(Agent, learner["id"])).workspace_id,
                branch_id=b2["id"] if isolated else None,  # an isolated company's stay there
                name=name,
                description=desc,
                body="## When to use\nA supplier statement.\n\n## Steps\n1. read_file it.\n",
                created_by=f"agent:{home['id']}",
                source_task_id="tk_learned",
                agent_ids=[home["id"]],
                embedding=await embed.embed_one(f"{name}: {desc}"),
            )
        )
        await db.commit()
    t = await _task(
        client, colleague["id"], "Reconcile the supplier statement", "Reconcile the supplier "
        "statement against our ledger for October and list every difference."
    )  # fmt: skip
    got = (await _skill(name)).agent_ids
    if isolated:
        assert colleague["id"] not in got and await _events(t["id"]) == []
    else:
        assert colleague["id"] in got
        assert "Aina was given the office's skill supplier-statement-reconcile" in (
            (await _events(t["id"]))[0].text
        )


async def test_matching_is_cheap_and_ignores_small_talk(client, llm, temporal):
    o = await office(client)
    ag = await new_agent(client, o, "Faiz", "Finance")
    await client.get("/api/skills")
    async with SessionLocal() as db:
        a = await db.get(Agent, ag["id"])
        assert await skill_grant.for_chat(db, a, "nobody", "ok thanks") == ""
        found = await skill_grant.match(db, a, ONBOARD)
        assert [s.name for s in found][:1] == ["staff-onboarding-file"]
        found = await skill_grant.match(db, a, "Prepare quotation QT260123 on ePerolehan")
        assert found[0].name == "eperolehan-tender"
        assert await skill_grant.match(db, a, "   ") == []
