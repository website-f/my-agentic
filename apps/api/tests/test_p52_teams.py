# ruff: noqa: E501
"""P52 Microsoft Teams through a person's own Microsoft 365 connection: their chats on the
Microsoft 365 page, and Teams tools only for their own AI (never a company agent, never for
someone else talking to their twin)."""

import httpx

from agentic.microsoft import http

from .conftest import csrf  # noqa: F401
from .test_agents import llm, office, temporal  # noqa: F401
from .test_microsoft import (  # noqa: F401
    TENANT,
    configure,
    connect,
    make_agent,
    ms,
    my_account,
    user_id,
)

CHATS = {
    "value": [
        {
            "id": "19:chat-1",
            "topic": None,
            "chatType": "oneOnOne",
            "webUrl": "https://teams.microsoft.com/l/chat/19:chat-1",
            "members": [{"displayName": "Boss One"}, {"displayName": "Siti Aminah"}],
            "lastMessagePreview": {
                "createdDateTime": "2026-10-26T08:00:00Z",
                "from": {"user": {"displayName": "Siti Aminah"}},
                "body": {"content": "<p>Can you send the <b>tender</b> pack today?</p>"},
            },
        }
    ]
}
MESSAGES = {
    "value": [
        {"id": "2", "messageType": "message", "createdDateTime": "2026-10-26T08:00:00Z",
         "from": {"user": {"displayName": "Siti Aminah"}}, "body": {"content": "<p>Today please</p>"}},
        {"id": "1", "messageType": "message", "createdDateTime": "2026-10-26T07:55:00Z",
         "from": {"user": {"displayName": "Boss One"}}, "body": {"content": "Which pack?"}},
        {"id": "0", "messageType": "systemEventMessage", "createdDateTime": "2026-10-26T07:00:00Z",
         "body": {"content": ""}},
    ]
}  # fmt: skip


def teams_on(ms_fake, sent: list) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        p = r.url.path.removeprefix("/v1.0/")
        if r.url.host == "graph.microsoft.com":
            if p == "me/chats":
                return httpx.Response(200, json=CHATS)
            if p == "me/chats/19:chat-1/messages":
                return httpx.Response(200, json=MESSAGES)
            if p == "chats/19:chat-1/messages" and r.method == "POST":
                sent.append(r.content)
                return httpx.Response(201, json={"id": "3"})
        return ms_fake.handler(r)

    http.transport = httpx.MockTransport(handler)

