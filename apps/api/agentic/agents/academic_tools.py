"""My Agentic: help with academic and everyday writing.

- check_ai_text: how likely a text (pasted, or a file: PDF, Word, text) is AI-written, as a
  percentage with the signals and passages behind it (academic/detect.py). Never proof.
- humanize_writing: the academic-humanizer skill (academic/humanize.py) as an editing pass:
  clearer, more natural writing in the author's voice, with every number, claim and citation
  kept. A file comes back as a Word copy (sent on WhatsApp by itself).
"""

import re
from typing import Any

from sqlalchemy import select

from ..academic import detect, humanize
from ..documents import service as doc_service
from ..models import DocFile
from .tools import Tool, ToolContext

EDITED_FOLDER = "AI documents/Edited"
MIN_WORDS = 15


async def _text(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, DocFile | None, str]:
    """(the text, its file if it came from one, an error)."""
    from .doc_tools import _file

    ref = str(args.get("file_id") or "").strip()
    if ref:
        f = await _file(ctx, ref)
        if f is None:
            return "", None, "Error: no such file for you. Use list_files to see the ids."
        if f.quarantined:
            return "", None, "Error: that file is held back and cannot be read."
        if f.status == "reading":
            return "", None, f"{f.name} is still being read. Try again in a minute."
        text = await ctx.db.scalar(select(DocFile.text).where(DocFile.id == f.id)) or ""
        if not text.strip():
            return "", None, f"Error: no text could be read from {f.name}."
        return text, f, ""
    text = str(args.get("text") or "")
    if not text.strip():
        return "", None, "Error: give the text, or file_id of the file to check."
    return text, None, ""


async def _check_ai_text(ctx: ToolContext, args: dict[str, Any]) -> str:
    text, f, err = await _text(ctx, args)
    if err:
        return err
    if len(text.split()) < MIN_WORDS:
        return "Error: that is too short to judge; give at least a few sentences."
    report = await detect.detect(ctx.db, ctx.workspace.id, text)
    head = f"Checked {f.name}.\n" if f else ""
    return (
        head
        + report.text()
        + "\n\nGive the person the percentage, the band and confidence, the main reasons, and "
        "the caveat in their language. If they want the writing improved, humanize_writing edits "
        "it for clarity and voice (it does not aim at any detector score)."
    )


def _docx_name(base: str) -> str:
    stem = re.sub(r"[.][A-Za-z0-9]{2,5}$", "", base or "Edited text")
    return re.sub(r'[\\/:*?"<>|]+', "-", f"{stem} (edited)")[:150] + ".docx"


async def _humanize_writing(ctx: ToolContext, args: dict[str, Any]) -> str:
    from ..documents import render_docx
    from ..engine import gateway

    text, f, err = await _text(ctx, args)
    if err:
        return err
    if len(text.split()) < 5:
        return "Error: give the text to edit."
    kind = str(args.get("kind") or "general").strip().lower()
    voice = str(args.get("voice_sample") or "")
    if args.get("voice_file_id"):
        sample, _, verr = await _text(ctx, {"file_id": args["voice_file_id"]})
        if verr:
            return verr
        voice = sample
    try:
        edited, changes = await humanize.humanize(
            ctx.db,
            ctx.workspace.id,
            text,
            kind=kind,
            voice_sample=voice,
            instructions=str(args.get("instructions") or ""),
        )
    except gateway.GatewayUnavailable as e:
        return f"Error: no AI model answered ({e}). Try again shortly."
    if not edited:
        return "Error: the editor returned nothing. Try again."
    out_line = ""
    if f is not None or args.get("save_as_file") or len(edited.split()) > 600:
        name = _docx_name(f.name if f else str(args.get("title") or "Edited text"))
        data = render_docx.render(edited, name.rsplit(".", 1)[0])
        out = await doc_service.create_file(
            ctx.db,
            workspace_id=ctx.workspace.id,
            name=name,
            data=data,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            created_by=f"agent:{ctx.agent.id}",
            branch_id=f.branch_id if f else ctx.agent.branch_id,
            task_id=ctx.task.id if ctx.task else None,
            agent_id=ctx.agent.id,
            source="generated",
            folder=EDITED_FOLDER,
            source_path=f"edited from {f.id}" if f else "edited text",
            owner_user_id=ctx.person or ctx.agent.owner_user_id,
            status="ready",
        )
        await ctx.db.commit()
        out_line = f"Saved as {out.name} (file {out.id}); on WhatsApp it is attached by itself.\n\n"
    shown = edited if len(edited) <= 6000 else edited[:6000] + "\n[... the rest is in the file]"
    return (
        f"{out_line}Edited text:\n{shown}\n\nWhat changed:\n{changes or '-'}\n\n"
        "Give the person the edited text (or say the file is attached) and the main changes. "
        "Numbers, results, claims and citations were kept as written; tell them to check facts "
        "and to follow their school's or venue's rules on AI use."
    )


ACADEMIC_TOOLS = (
    Tool(
        "check_ai_text",
        "Check if a text is AI-written",
        "How likely a text is AI-written, as a percentage (0-100) with a band (likely human / "
        "mixed / likely AI), a confidence, the signals and the most AI-like passages. Use when "
        "asked 'check this text/PDF/file, what is the AI percentage'. Give text, or file_id of a "
        "PDF / Word / text file (files shared in WhatsApp have ids too). Best on English text of "
        "a paragraph or more; detectors are never proof, say so.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to check"},
                "file_id": {"type": "string", "description": "Or the file to check"},
            },
        },
        "low",
        "allow",
        _check_ai_text,
    ),
    Tool(
        "humanize_writing",
        "Edit writing to sound natural",
        "Edit AI-assisted or stiff writing so it reads clearly and naturally in the author's own "
        "voice (the academic-humanizer skill): removes AI tells (inflated words, filler, "
        "em-dashes, formulaic structure), keeps every number, result, claim and citation exactly. "
        "kind: paper, thesis, abstract, rebuttal, proposal (academic, follows the full skill) or "
        "general (emails, letters, posts, reports). Give text or file_id; a file comes back as a "
        "Word copy. voice_sample / voice_file_id: the author's own earlier writing to match. "
        "It is an editing aid; it does not target AI-detector scores.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to edit"},
                "file_id": {"type": "string", "description": "Or the file to edit"},
                "kind": {
                    "type": "string",
                    "description": "paper | thesis | abstract | rebuttal | proposal | general",
                },
                "voice_sample": {"type": "string", "description": "The author's own writing"},
                "voice_file_id": {"type": "string", "description": "Or a file of their writing"},
                "instructions": {"type": "string", "description": "Anything else to follow"},
                "save_as_file": {"type": "boolean", "description": "Also save a Word file"},
                "title": {"type": "string", "description": "The Word file's name"},
            },
        },
        "low",
        "allow",
        _humanize_writing,
    ),
)
