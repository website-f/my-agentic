# ruff: noqa: E501
"""My Agentic: copy a file with changes (same format), saved formats, background jobs, the chat
promise nudge, and WhatsApp access for other numbers (levels, limits, chats)."""

import io
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from agentic.agents import runtime
from agentic.agents.tools import TOOLS, ToolContext
from agentic.channels import deliver, wa_bot, whatsapp
from agentic.core.db import SessionLocal
from agentic.documents import render_pdf
from agentic.documents import service as doc_service
from agentic.mailbox.models import WaMember
from agentic.models import Agent, AgentMessage, Channel, ChatSession, Delivery, DocFile, Membership, Task, Workspace

from .conftest import csrf
from .test_agents import llm, new_agent, office, temporal  # noqa: F401
from .test_mine_inbox_whatsapp import ME, _group_payload, _wa_setup


async def _ctx(db, agent_id: str, **kw) -> ToolContext:
    ws = await db.scalar(select(Workspace))
    agent = await db.get(Agent, agent_id)
    return ToolContext(db=db, agent=agent, workspace=ws, task=None, **kw)


async def _upload(db, ws_id: str, name: str, data: bytes, mime: str) -> str:
    f = await doc_service.create_file(db, workspace_id=ws_id, name=name, data=data, mime=mime, created_by="system", status="ready")
    await db.commit()
    return f.id


async def test_copy_a_pdf_and_a_word_file_with_changes_and_save_the_format(client, llm, temporal):
    from docx import Document

    o = await office(client)
    a = await new_agent(client, o, "Chief", "Management")
    pdf = render_pdf.render("**JADUAL HARGA - MERDEKA**\n\n| Item | Harga (RM) |\n|---|---|\n| Sistem | 21,239,660.97 |\n", "J", None)
    d = Document()
    d.add_paragraph("Syarikat: Merdeka Sdn Bhd, potongan 5.00%")
    buf = io.BytesIO()
    d.save(buf)
    async with SessionLocal() as db:
        ws = await db.scalar(select(Workspace))
        pdf_id = await _upload(db, ws.id, "Jadual Merdeka.pdf", pdf, "application/pdf")
        docx_id = await _upload(db, ws.id, "Analisis Merdeka.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        ctx = await _ctx(db, a["id"])
        out = await TOOLS["copy_file_with_changes"].handler(ctx, {
            "file_id": pdf_id,
            "changes": [{"find": "MERDEKA", "replace": "SUTERA"}, {"find": "21,239,660.97", "replace": "20,123,456.10"}, {"find": "99,999", "replace": "1"}],
            "new_name": "Jadual Sutera",
        })
        assert "Made Jadual Sutera.pdf" in out and "x1" in out and "NOT found" in out and "'99,999'" in out
        new_id = out.split("(file ")[1].split(")")[0]
        f = await db.get(DocFile, new_id)
        assert f.mime == "application/pdf" and f.agent_id == a["id"] and f.folder == "AI documents/Edited"
        from agentic.documents import storage
        from agentic.agents.tools import pdf_text

        text = pdf_text(await storage.read(db, f))
        assert "20,123,456.10" in text and "21,239,660.97" not in text  # the cell's old value is gone

        out = await TOOLS["copy_file_with_changes"].handler(ctx, {"file_id": docx_id, "changes": [{"find": "Merdeka", "replace": "Arena"}, {"find": "5.00%", "replace": "6.10%"}]})
        new_doc = await db.get(DocFile, out.split("(file ")[1].split(")")[0])
        para = Document(io.BytesIO(await storage.read(db, new_doc))).paragraphs[0].text
        assert para == "Syarikat: Arena Sdn Bhd, potongan 6.10%"

        saved = await TOOLS["save_format"].handler(ctx, {"file_id": pdf_id, "name": "Jadual Harga Tawaran", "kind": "price schedule"})
        assert "Saved Jadual Merdeka.pdf as the format 'Jadual Harga Tawaran'" in saved
        listing = await TOOLS["list_templates"].handler(ctx, {})
        assert "Saved formats" in listing and "Jadual Harga Tawaran" in listing and "ask them which kind" in listing
        refused = await TOOLS["draft_document"].handler(ctx, {"template": "Jadual Harga Tawaran", "title": "x"})
        assert "saved format" in refused and "copy_file_with_changes" in refused
        again = await TOOLS["copy_file_with_changes"].handler(ctx, {"format": "Jadual Harga Tawaran", "changes": [{"find": "MERDEKA", "replace": "MATRIX"}]})
        assert again.startswith("Made Jadual Merdeka (edited).pdf")


async def test_a_promise_in_chat_is_sent_back_to_be_done(client, llm, temporal):
    o = await office(client)
    a = await new_agent(client, o, "Chief", "Management")
    async with SessionLocal() as db:
        owner = await db.scalar(select(Membership).where(Membership.role == "owner"))
        agent = await db.get(Agent, a["id"])
        s = ChatSession(workspace_id=agent.workspace_id, agent_id=agent.id, user_id=owner.user_id, title="Kerja")
        db.add(s)
        await db.commit()
        llm.say("Baik, aku akan buat keenam-enam file tu. Tunggu sekejap.").say("Siap: 6 file dah dibuat.")
        reply = await runtime.chat_turn(db, agent, s, "buat 6 PDF")
        saved = (await db.scalars(select(AgentMessage).where(AgentMessage.session_id == s.id, AgentMessage.role == "assistant"))).all()
    assert reply.content == "Siap: 6 file dah dibuat."
    assert [m.content for m in saved] == ["Siap: 6 file dah dibuat."]  # the promise was not kept
    last = llm.requests[-1]["messages"]
    assert last[-1]["content"] == runtime.CHAT_WORK_NUDGE and "Tunggu sekejap" in last[-2]["content"]
    assert runtime.promises_more_work("I'll prepare the files now") and not runtime.promises_more_work("Here are the files.")


async def test_a_background_job_posts_its_result_and_files_back_to_the_chat(client, monkeypatch):
    ch_id, owner_id = await _wa_setup(client)
    sent: list[dict] = []

    async def fake_file(cfg, chat_id, data, mime, filename, caption="", reply_to=""):
        sent.append({"chat": chat_id, "name": filename})
        return "f"

    async def no_send(db, did):
        return None

    monkeypatch.setattr(whatsapp, "waha_send_file", fake_file)
    monkeypatch.setattr(deliver, "deliver", no_send)
    async with SessionLocal() as db:
        ws_id = (await db.get(Channel, ch_id)).workspace_id
        from agentic.models import Branch

        branch = await db.scalar(select(Branch).where(Branch.workspace_id == ws_id))
        agent = Agent(workspace_id=ws_id, branch_id=branch.id, name="Chief", role="Assistant", slug="chief")
        db.add(agent)
        await db.flush()
        t = Task(workspace_id=ws_id, title="6 PDF syarikat", brief="b", status="running", assignee_agent_id=agent.id, created_by=f"user:{owner_id}", labels=["reply-chat:120363000@g.us"])
        db.add(t)
        await db.flush()
        db.add(DocFile(workspace_id=ws_id, task_id=t.id, agent_id=agent.id, name="Jadual Sutera.pdf", mime="application/pdf", size=9, data=b"%PDF-1.4 x", status="ready", source="generated", created_by="agent"))
        await db.commit()
        assert await wa_bot.deliver_task_result(db, t, agent, True, "Siap **semua**")
        d = await db.scalar(select(Delivery).where(Delivery.channel == "whatsapp"))
        t.labels = []
        assert not await wa_bot.deliver_task_result(db, t, agent, True, "x")  # no chat: nothing
    assert d.target == f"{ch_id}:120363000@g.us" and "✅ Done: 6 PDF syarikat" in d.payload["text"]
    assert "*semua*" in d.payload["text"]  # WhatsApp formatting
    assert sent == [{"chat": "120363000@g.us", "name": "Jadual Sutera.pdf"}]


async def test_the_access_list_api(client):
    ch_id, _ = await _wa_setup(client)
    r = await client.post("/api/wa/members", json={"number": "012-777 8888", "name": "Ali", "level": "assistant"}, headers=csrf(client))
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["number"] == "60127778888" and m["daily_messages"] == 30 and m["used_today"] == {"messages": 0, "tokens": 0}
    assert (await client.post("/api/wa/members", json={"number": "60127778888"}, headers=csrf(client))).status_code == 409
    assert (await client.post("/api/wa/members", json={"number": "123456"}, headers=csrf(client))).status_code == 400
    r = await client.patch(f"/api/wa/members/{m['id']}", json={"level": "full", "chats": ["120363000@g.us"], "daily_messages": 0}, headers=csrf(client))
    assert r.json()["level"] == "full" and r.json()["chats"] == ["120363000@g.us"] and r.json()["daily_messages"] == 0
    assert len((await client.get("/api/wa/members")).json()["members"]) == 1
    assert (await client.delete(f"/api/wa/members/{m['id']}", headers={"content-type": "application/json", **csrf(client)})).status_code == 204
    assert (await client.get("/api/wa/members")).json()["members"] == []


async def test_people_with_access_get_help_within_their_level_and_limits(client, monkeypatch):
    from agentic.models import Branch

    ch_id, owner_id = await _wa_setup(client)
    async with SessionLocal() as db:
        ws_id = (await db.get(Channel, ch_id)).workspace_id
        branch = await db.scalar(select(Branch).where(Branch.workspace_id == ws_id))
        db.add(Agent(workspace_id=ws_id, branch_id=branch.id, name="Chief", role="Assistant", slug="chief", owner_user_id=owner_id, private=True))
        ali = WaMember(channel_id=ch_id, number="60177778888", name="Ali", level="assistant", daily_messages=2)
        db.add(ali)
        await db.commit()
        ali_id = ali.id

    turns: list[dict] = []

    class Reply:
        content = "Done for you, Ali."
        message_id = None

    async def fake_turn(db, agent, session, text):
        turns.append({"title": session.title, "user": session.user_id, "text": text, "held": runtime.TURN_DENY.get()})
        return Reply()

    async def fake_messages(cfg, chat_id, limit=50, media=False):
        return []

    async def fake_status(cfg):
        return {"status": "WORKING", "me": ME}

    async def no_send(db, did):
        return None

    learned: list[int] = []

    async def fake_learn(mid):
        learned.append(mid)

    monkeypatch.setattr(wa_bot.runtime, "chat_turn", fake_turn)
    monkeypatch.setattr(whatsapp, "waha_messages", fake_messages)
    monkeypatch.setattr(whatsapp, "waha_status", fake_status)
    monkeypatch.setattr(deliver, "deliver", no_send)
    monkeypatch.setattr(deliver, "learn_from_chat", fake_learn)

    async def ask(n: int):
        (msg,) = whatsapp.parse_waha(_group_payload("@60111000111 cari tempat bbq", mention=["60111000111@c.us"], sender="60177778888@c.us"))
        msg.message_id = f"m{n}"
        async with SessionLocal() as db:
            await wa_bot.handle(db, await db.get(Channel, ch_id), msg)

    await ask(1)
    (t,) = turns
    assert t["title"] == "WhatsApp chat 120363000@g.us | 60177778888"  # their own thread
    assert t["user"] == owner_id and "Ali (+60177778888) is asking, not me" in t["text"]
    assert "inbox_send" in t["held"] and "email_read" in t["held"] and "deep_research" not in t["held"]
    assert runtime.TURN_DENY.get() == frozenset()  # reset after the turn
    assert learned == []  # their chats do not teach the agent
    await ask(2)
    await ask(3)  # over the limit of 2 a day: told once
    await ask(4)  # then silence
    assert len(turns) == 2
    async with SessionLocal() as db:
        texts = [d.payload["text"] for d in (await db.scalars(select(Delivery).where(Delivery.channel == "whatsapp").order_by(Delivery.created_at))).all()]
    assert sum("reached today's limit" in x for x in texts) == 1
    assert (await wa_bot.usage_today(ali_id))["messages"] == 2  # refused ones are not counted

    # chat-only level: a plain answer, no agent turn
    guest: list[str] = []

    async def fake_guest(db, ch, msg, rule, where, key, quote):
        guest.append(where)

    monkeypatch.setattr(wa_bot, "_guest", fake_guest)
    async with SessionLocal() as db:
        m = await db.get(WaMember, ali_id)
        m.level, m.daily_messages = "chat", 0
        await db.commit()
    await ask(5)
    assert guest == ["120363000@g.us"] and len(turns) == 2

    # not allowed in this chat, expired or switched off: silence
    for change in ({"chats": ["other@g.us"]}, {"chats": [], "expires_at": datetime.now(UTC) - timedelta(days=1)}, {"expires_at": None, "enabled": False}):
        async with SessionLocal() as db:
            m = await db.get(WaMember, ali_id)
            for k, v in change.items():
                setattr(m, k, v)
            await db.commit()
        await ask(6 + len(guest))
    assert guest == ["120363000@g.us"]
