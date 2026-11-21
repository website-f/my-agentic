"""P48 "Needs you": what waits on each person, only what they may act on."""


from .test_agents import llm, new_agent, new_task, office, temporal  # noqa: F401


def counts(body: dict) -> dict[str, int]:
    return {i["key"]: i["count"] for i in body["items"]}

