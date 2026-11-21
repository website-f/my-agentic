"""P26: My workspace — each person's desk.

Pins (and who may pin what), the SOPs and workflows for the person's job, their AI workers,
the work they gave and what came back, what waits for them, their workspace files, asking
their AI worker from the desk (the answer and any document land on their desk), uploading to
their workspace, and whose desk work belongs to (provenance.desk_owner).
"""


from agentic.core.db import SessionLocal
from agentic.models import SOP, Agent, Workflow

from .conftest import csrf
from .test_agents import llm, new_agent, office, temporal  # noqa: F401
from .test_office_roles import as_role
from .test_twins import ANSWERS


async def _staff_with_twin(client, o, email="siti@example.com", dept="Finance"):
    staff = await as_role(
        client, email, "staff", branch_id=o["branch"]["id"], department_id=o["depts"][dept]
    )
    r = await staff.post("/api/me/twin", json=ANSWERS, headers=csrf(staff))
    assert r.status_code == 201, r.text
    return staff, r.json()["twin"]


async def _procedures(o, twin_id):
    """A department SOP, a company SOP, an everyone SOP, a draft, another department's SOP;
    a workflow the twin follows and one it does not."""
    async with SessionLocal() as db:
        twin = await db.get(Agent, twin_id)
        assert twin is not None
        ws = twin.workspace_id
        rows = {
            "dept": SOP(
                workspace_id=ws,
                scope="department",
                scope_id=o["depts"]["Finance"],
                title="Claims checking",
                body="Check every claim against the policy.",
                updated_by="test",
            ),
            "company": SOP(
                workspace_id=ws,
                scope="branch",
                scope_id=o["branch"]["id"],
                title="Office hours",
                body="Open 9 to 6.",
                updated_by="test",
            ),
            "all": SOP(
                workspace_id=ws, scope="workspace", title="Code of conduct", body="Be kind."
            ),
            "draft": SOP(
                workspace_id=ws,
                scope="department",
                scope_id=o["depts"]["Finance"],
                title="Draft procedure",
                body="Not yet.",
                status="draft",
            ),
            "other": SOP(
                workspace_id=ws,
                scope="department",
                scope_id=o["depts"]["Operations"],
                title="Forklift safety",
                body="Wear a helmet.",
            ),
        }
        flows = {
            "mine": Workflow(
                workspace_id=ws,
                name="Monthly claims",
                description="From claim forms to payment.",
                graph={"nodes": [{"id": "s", "type": "start"}], "edges": []},
                status="active",
                agent_ids=[twin_id],
                created_by="test",
            ),
            "other": Workflow(
                workspace_id=ws,
                name="Audit prep",
                graph={"nodes": [], "edges": []},
                status="active",
                agent_ids=[],
                created_by="test",
            ),
        }
        db.add_all([*rows.values(), *flows.values()])
        await db.commit()
        return {k: v.id for k, v in rows.items()}, {k: v.id for k, v in flows.items()}, ws

