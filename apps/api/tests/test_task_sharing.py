"""P26: a manager or owner chooses who else may look at a task they give: only the people who
already see it (private), its department, its company or everyone. Shared tasks are read only:
on the board and opened, without the agent's transcript or approvals, and never changeable."""

from .test_agents import llm, new_agent, office, temporal  # noqa: F401

JSON = {"content-type": "application/json"}

