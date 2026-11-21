"""Files given to work after it started: attached to a task from its sheet, and attached to
a person's answer in a workflow run (later steps' agents get them like a task's files)."""

from datetime import UTC, datetime

from agentic.core.db import SessionLocal
from agentic.models import AgentMessage, DocFile, Task

from .conftest import csrf
from .test_agents import llm, messages, new_agent, new_task, office, temporal  # noqa: F401
from .test_documents import inline_reading, upload  # noqa: F401
from .test_workflow_runs import driver, step, tick  # noqa: F401

GRAPH = {
    "nodes": [
        {"id": "s", "type": "start", "title": "Order in"},
        {"id": "po", "type": "input", "title": "Signed PO", "body": "Attach the signed PO."},
        {"id": "mail", "type": "step", "title": "Confirm the order", "role": "Finance"},
        {"id": "e", "type": "end", "title": "Done"},
    ],
    "edges": [
        {"id": "e1", "from": "s", "to": "po"},
        {"id": "e2", "from": "po", "to": "mail"},
        {"id": "e3", "from": "mail", "to": "e"},
    ],
}


async def attach(c, task_id: str, ids: list[str]):
    return await c.post(f"/api/tasks/{task_id}/files", json={"file_ids": ids}, headers=csrf(c))


# ---------------------------------------------------------------- tasks


async def test_files_attached_to_a_task_reach_its_agent(client, llm, temporal, inline_reading):
    o = await office(client)
    fin = await new_agent(client, o, "Faiz", "Finance")
    t = await new_task(client, fin, "Check the invoice")
    f1 = (await upload(client, "invoice-77.txt", b"Invoice 77: RM 1,250.00")).json()

    r = await attach(client, t["id"], [f1["id"], f1["id"]])
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == [f1["id"]] and r.json()[0]["task_id"] == t["id"]
    listed = (await client.get("/api/files", params={"task_id": t["id"]})).json()
    assert [x["id"] for x in listed] == [f1["id"]]
    detail = (await client.get(f"/api/tasks/{t['id']}")).json()
    ev = [e for e in detail["events"] if e["kind"] == "files"]
    assert ev and "invoice-77.txt" in ev[0]["text"]
    assert await messages(t["id"]) == []  # not started: its first message will list them

    # Finished work: a note at the end of the conversation, for the next run.
    async with SessionLocal() as db:
        task = await db.get(Task, t["id"])
        task.status = "done"
        db.add(
            AgentMessage(
                workspace_id=task.workspace_id,
                agent_id=fin["id"],
                task_id=task.id,
                role="assistant",
                content="Checked: all fine.",
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()
    f2 = (await upload(client, "po-12.txt", b"PO 12")).json()
    assert (await attach(client, t["id"], [f2["id"]])).status_code == 200
    last = (await messages(t["id"]))[-1]
    assert last.role == "user" and "Files added to this task" in last.content
    assert f2["id"] in last.content and f1["id"] not in last.content

    # Mid-run: nothing is pushed into the conversation (the agent can list them).
    async with SessionLocal() as db:
        task = await db.get(Task, t["id"])
        task.status = "running"
        await db.commit()
    f3 = (await upload(client, "extra.txt", b"more")).json()
    n = len(await messages(t["id"]))
    assert (await attach(client, t["id"], [f3["id"]])).status_code == 200
    assert len(await messages(t["id"])) == n

    assert (await attach(client, t["id"], ["fl_nope"])).status_code == 400
    assert (await attach(client, "tk_nope", [f3["id"]])).status_code == 404


# ---------------------------------------------------------------- workflow answers


async def test_a_file_from_other_work_stays_with_it(client, llm, temporal, inline_reading):
    """Giving a new task a file another task made or fetched keeps it with that task (its
    By-task files stay whole); the new task's brief names it so the agent can read it."""
    o = await office(client)
    qs = await new_agent(client, o, "Rashid", "Finance")
    tender = await new_task(client, qs, "Prepare the tender")
    research = await new_task(client, qs, "Recommend a product")
    f = (await upload(client, "Spesifikasi.pdf", b"Spec text")).json()
    assert (await attach(client, tender["id"], [f["id"]])).status_code == 200
    r = await attach(client, research["id"], [f["id"]])
    assert r.status_code == 200, r.text
    async with SessionLocal() as db:
        kept = await db.get(DocFile, f["id"])
        t = await db.get(Task, research["id"])
        assert kept is not None and t is not None
        assert kept.task_id == tender["id"]  # still the tender's
        assert f"[{f['id']}] Spesifikasi.pdf" in t.brief
    await attach(client, research["id"], [f["id"]])  # again: named once
    async with SessionLocal() as db:
        t = await db.get(Task, research["id"])
        assert t is not None and t.brief.count(f["id"]) == 1
