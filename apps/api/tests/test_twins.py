"""P18: AI twins, each staff member's one agent (their virtual self at work)."""


from agentic.agents import twin

from .test_agents import llm, new_agent, office, temporal  # noqa: F401
from .test_office_roles import as_role

ANSWERS = {
    "name": "Siti's twin",
    "role": "Accounts executive",
    "job": "I chase overdue invoices and prepare the monthly aging report.",
    "style": "Checks every figure twice and keeps a running list of what is pending.",
    "tone": "brief",
    "languages": ["English", "Malay"],
    "helps_with": ["numbers", "reports", "research"],
    "ask_first": ["web", "wiki"],
    "hours": "Weekdays, 8am to 5pm",
    "heartbeat": True,
    "color": "#2f6db5",
}


async def staff_in(client, o, email="siti@example.com", dept="Finance"):
    return await as_role(
        client, email, "staff", branch_id=o["branch"]["id"], department_id=o["depts"][dept]
    )


def test_persona_and_tools_come_from_the_answers():
    tools = twin.tools_for(["forms", "research"], ["web"])
    # Forms work in the browser; sending a form always asks.
    assert tools["browser_click"] == "allow" and tools["browser_submit"] == "ask"
    assert tools["web_fetch"] == "ask" and tools["browser_open"] == "ask"  # "ask me first: web"
    assert tools["notify_person"] == "allow"  # it reports to its person
    assert tools["run_python"] == "deny" and tools["tool_call"] == "deny"  # not chosen: off

    plain = twin.tools_for(["documents"], [])
    assert plain["browser_open"] == "deny" and plain["web_fetch"] == "deny"
    assert plain["draft_document"] == "allow"
    figures = twin.tools_for(["numbers"], [])
    assert figures["run_python"] == "ask"  # code always asks, even when chosen

    # A manager made a tool stricter: re-saving the wizard keeps it strict.
    kept = twin.keep_stricter(
        {"web_search": "allow"}, {"web_search": "deny"}, {"web_search": "allow"}
    )
    assert kept["web_search"] == "deny"

    soul = twin.soul({**ANSWERS}, "Siti Aminah", "Finance, Maju Sdn Bhd")
    assert soul.startswith("You are Siti's twin, the AI twin of Siti Aminah")
    assert "I chase overdue invoices" in soul and "Checks every figure twice" in soul
    assert "short and direct" in soul and "English and Malay" in soul
    assert "Always ask Siti first (ask_human) before: opening web pages" in soul
    assert "sending forms" in soul and "running code" in soul  # the locked ones, always
    assert "pick up queued work by yourself" in soul and "notify_person" in soul
    assert "never sign as Siti" in soul

    # Department-shaped suggestions.
    assert twin._dept_match("Finance")[1][0] == "numbers"
    assert "research" in twin._dept_match("Research & Strategy")[1]
    assert twin._dept_match("HR")[1] == ("documents", "files", "followups")
    assert twin._dept_match("Something else")[1] == twin._DEFAULT_HELPS

