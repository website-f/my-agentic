# ruff: noqa: E501
"""My Agentic: the AI-text check (classifier + style + AI reviewer) and the academic-humanizer
editing pass, as agent tools (text or a file; a file comes back as a Word copy)."""

import io

from sqlalchemy import select

from agentic.academic import detect, humanize
from agentic.agents import policy, runtime
from agentic.agents.tools import TOOLS, ToolContext
from agentic.core.db import SessionLocal
from agentic.documents import service as doc_service
from agentic.engine import gateway
from agentic.models import Agent, DocFile, Workspace

from .test_agents import llm, new_agent, office, temporal  # noqa: F401

AI_TEXT = (
    "Effective time management is essential for both personal and professional success. By prioritizing tasks, "
    "setting clear goals, and minimizing distractions, individuals can significantly enhance their productivity. "
    "Additionally, leveraging digital tools such as calendars can streamline workflows and ensure that deadlines are met. "
    "Furthermore, it is important to note that taking regular breaks can boost focus and prevent burnout. "
    "Moreover, a comprehensive approach fosters a seamless balance between work and life. "
    "Ultimately, mastering time management plays a crucial role in achieving one's objectives."
)
HUMAN_TEXT = (
    "ok so i finally got the car back from the shop yesterday, cost me way more than i thought lol. "
    "The guy said the brakes were basically gone. Anyway. We should still be good for saturday if your sister can bring "
    "the cooler, i forgot ours at my mum's place and honestly I am not driving all the way back there for it. "
    "Oh and btw the campsite wants the deposit by thursday, I paid half already so you owe me like forty bucks."
)


def _reply(content: str) -> gateway.GatewayReply:
    return gateway.GatewayReply(
        content=content,
        provider_id="p",
        provider_name="fake",
        model="m",
        usage=gateway.Usage(),
        latency_ms=1,
        cost_usd=None,
    )


async def _ctx(db, agent_id: str) -> ToolContext:
    ws = await db.scalar(select(Workspace))
    agent = await db.get(Agent, agent_id)
    return ToolContext(db=db, agent=agent, workspace=ws, task=None)


async def _text_file(db, ws_id: str, agent_id: str, name: str, text: str) -> str:
    f = await doc_service.create_file(
        db,
        workspace_id=ws_id,
        name=name,
        data=text.encode(),
        mime="text/plain",
        created_by=f"agent:{agent_id}",
        agent_id=agent_id,
        status="ready",
    )
    f.text = text
    await db.commit()
    return f.id


def test_style_signals_tell_stock_ai_prose_from_casual_writing():
    ai, notes, english = detect.style(AI_TEXT)
    human, hnotes, _ = detect.style(HUMAN_TEXT)
    assert english and ai > 60 and human < 35
    assert any("AI-typical words" in n for n in notes) and any("stock phrases" in n for n in notes)
    assert any("informal" in n for n in hnotes)
    _, _, malay = detect.style(
        "Saya akan menghantar laporan itu kepada pihak pengurusan pada minggu hadapan selepas mesyuarat."
    )
    assert not malay


async def test_detect_combines_the_three_signals_and_always_says_it_is_not_proof(monkeypatch):
    long_ai = " ".join([AI_TEXT] * 3)
    monkeypatch.setattr(
        detect,
        "classify",
        lambda text: (92.0, [detect.Passage("a", 95.0), detect.Passage("b", 80.0)], 400),
    )

    async def judge(db, ws, text):
        return 80.0, ["uniform sentences", "stock transitions"]

    monkeypatch.setattr(detect, "judge", judge)
    r = await detect.detect(object(), "ws", long_ai)
    assert r.band == "likely AI-written" and r.score > 80 and r.confidence == "high"
    out = r.text()
    assert "AI-likelihood: " in out and "classifier 92%" in out and "AI reviewer 80%" in out
    assert "uniform sentences" in out and "Most AI-like passages" in out and "never as proof" in out

    # no classifier on this machine, a short text: style + reviewer, low confidence
    monkeypatch.setattr(detect, "classify", lambda text: None)
    r = await detect.detect(
        object(), "ws", "This is a short note about the meeting tomorrow at ten in the morning."
    )
    assert r.model is None and r.confidence == "low" and any("short text" in s for s in r.signals)

    # not English: the classifier is skipped
    called = []
    monkeypatch.setattr(detect, "classify", lambda text: called.append(1))
    r = await detect.detect(
        None,
        "ws",
        "Saya akan menghantar laporan itu kepada pihak pengurusan pada minggu hadapan selepas mesyuarat bulanan kami. "
        * 6,
    )
    assert not called and not r.english and "classifier: not used" in r.text()


async def test_the_reviewer_reply_is_parsed_and_a_bad_one_is_ignored(monkeypatch):
    replies = iter(
        ['Sure: {"ai_probability": 140, "reasons": ["a", "b", "c", "d"]}', "no json here"]
    )

    async def chat_first(db, ws, groups, messages, **kw):
        assert (
            "data, never instructions" in messages[0]["content"] and kw["task"] == "academic.detect"
        )
        return _reply(next(replies))

    monkeypatch.setattr(gateway, "chat_first", chat_first)
    assert await detect.judge(object(), "ws", "text") == (100.0, ["a", "b", "c"])
    assert await detect.judge(object(), "ws", "text") == (None, [])


async def test_check_ai_text_tool_reads_text_or_a_file(client, llm, temporal, monkeypatch):
    o = await office(client)
    a = await new_agent(client, o, "Chief", "Management")
    monkeypatch.setattr(detect, "classify", lambda text: (88.0, [], 300))

    async def judge(db, ws, text):
        return None, []

    monkeypatch.setattr(detect, "judge", judge)
    async with SessionLocal() as db:
        ws = await db.scalar(select(Workspace))
        fid = await _text_file(db, ws.id, a["id"], "Essay.txt", AI_TEXT)
        ctx = await _ctx(db, a["id"])
        out = await TOOLS["check_ai_text"].handler(ctx, {"file_id": fid})
        assert (
            out.startswith("Checked Essay.txt.")
            and "AI-likelihood:" in out
            and "likely AI-written" in out
        )
        assert "humanize_writing" in out
        out = await TOOLS["check_ai_text"].handler(ctx, {"text": HUMAN_TEXT})
        assert "AI-likelihood:" in out
        assert (await TOOLS["check_ai_text"].handler(ctx, {"text": "too short"})).startswith(
            "Error: that is too short"
        )
        assert (await TOOLS["check_ai_text"].handler(ctx, {"file_id": "fl_nope"})).startswith(
            "Error: no such file"
        )
        f = await db.get(DocFile, fid)
        f.status = "reading"
        await db.commit()
        assert "still being read" in await TOOLS["check_ai_text"].handler(ctx, {"file_id": fid})


async def test_humanize_follows_the_skill_for_academic_work_and_a_lighter_pass_otherwise(
    monkeypatch,
):
    seen = []

    async def chat_first(db, ws, groups, messages, **kw):
        seen.append(messages)
        return _reply(
            "===TEXT===\nWe show X improves Y by 12.4% (Smith, 2021).\n===CHANGES===\n- removed 'delve'\n- split a long sentence"
        )

    monkeypatch.setattr(gateway, "chat_first", chat_first)
    text, log = await humanize.humanize(
        object(),
        "ws",
        "We delve into how X improves Y by 12.4% (Smith, 2021).",
        kind="paper",
        voice_sample="My own old paragraph.",
    )
    assert (
        text == "We show X improves Y by 12.4% (Smith, 2021)."
        and "removed 'delve'" in log
        and "disclosure rules" in log
    )
    system, user = seen[0][0]["content"], seen[0][1]["content"]
    assert "Layer 1" in system and "never instructions" in system and "===CHANGES===" in system
    assert not system.lstrip().startswith("---")  # the skill's front matter is dropped
    assert "Document type: paper." in user and "My own old paragraph." in user

    seen.clear()
    _, log = await humanize.humanize(
        object(), "ws", "Dear Ali, I hope this email finds you well.", kind="general"
    )
    assert (
        "Layer 1" not in seen[0][0]["content"]
        and "emails, letters" in seen[0][0]["content"]
        and "disclosure" not in log
    )

    # a long text goes part by part, every part edited
    seen.clear()
    long = "\n\n".join(" ".join(["word"] * 500) for _ in range(5))
    await humanize.humanize(object(), "ws", long, kind="thesis")
    assert (
        len(seen) == 3 and "part 1 of 3" in seen[0][1]["content"]
    )  # 1400 words a part, whole paragraphs

    assert humanize._split("no markers at all") == ("no markers at all", "")


async def test_humanize_writing_tool_returns_text_and_a_word_copy_for_a_file(
    client, llm, temporal, monkeypatch
):
    from docx import Document

    o = await office(client)
    a = await new_agent(client, o, "Chief", "Management")

    async def chat_first(db, ws, groups, messages, **kw):
        assert kw["task"] == "academic.humanize"
        return _reply(
            "===TEXT===\nThe results hold across all 3 datasets.\n\nWe thank the reviewers.\n===CHANGES===\n- cut filler"
        )

    monkeypatch.setattr(gateway, "chat_first", chat_first)
    async with SessionLocal() as db:
        ws = await db.scalar(select(Workspace))
        fid = await _text_file(
            db,
            ws.id,
            a["id"],
            "Chapter 2.txt",
            "It is worth noting that the results hold across all 3 datasets.",
        )
        ctx = await _ctx(db, a["id"])
        out = await TOOLS["humanize_writing"].handler(ctx, {"file_id": fid, "kind": "thesis"})
        assert (
            "Saved as Chapter 2 (edited).docx" in out
            and "all 3 datasets" in out
            and "cut filler" in out
        )
        new_id = out.split("(file ")[1].split(")")[0]
        f = await db.get(DocFile, new_id)
        assert (
            f.agent_id == a["id"] and f.folder == "AI documents/Edited" and f.name.endswith(".docx")
        )
        from agentic.documents import storage

        doc = Document(io.BytesIO(await storage.read(db, f)))
        assert any("We thank the reviewers." in p.text for p in doc.paragraphs)

        # plain text stays in the chat (no file)
        out = await TOOLS["humanize_writing"].handler(
            ctx,
            {
                "text": "Dear team, I hope this email finds you well. Kindly find attached.",
                "kind": "general",
            },
        )
        assert "Saved as" not in out and "Edited text:" in out

        async def down(*a, **k):
            raise gateway.GatewayUnavailable("all down", [])

        monkeypatch.setattr(gateway, "chat_first", down)
        assert (
            await TOOLS["humanize_writing"].handler(ctx, {"text": "one two three four five six"})
        ).startswith("Error: no AI model answered")


def test_the_tools_are_registered_with_timeouts_and_count_as_outside_content():
    assert (
        TOOLS["check_ai_text"].default_mode == "allow"
        and TOOLS["humanize_writing"].default_mode == "allow"
    )
    assert (
        runtime.SLOW_TOOLS["check_ai_text"] >= 60 and runtime.SLOW_TOOLS["humanize_writing"] >= 150
    )
    assert {"check_ai_text", "humanize_writing"} <= policy.OUTSIDE_CONTENT
    assert (
        "humanize_writing" not in runtime.private_tools()
    )  # people with assistant access may use it


def test_the_classifier_is_skipped_quietly_when_the_model_is_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(detect, "_model", None)
    monkeypatch.setattr(detect.settings, "aidetect_dir", str(tmp_path))
    assert detect.classify(AI_TEXT) is None
    monkeypatch.setattr(detect, "_model", None)  # the next test may have the model
