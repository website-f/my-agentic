"""My Agentic: the AI edits the person's own files in place, remembers their formats, and runs
long jobs in the background.

- copy_file_with_changes: a copy of a PDF / Word / Excel file with some details changed (names,
  amounts, percentages, dates) and everything else exactly as it was (documents/edit.py).
- save_format: keep a file as a named format ("Jadual Harga Tawaran", "Analisis Kewangan"), so
  the next "make another one" starts from it. Saved formats are templates (kind saved_format)
  whose source is the file; list_templates shows them.
- work_in_background: a long job (several files, much reading) becomes a task the agent works
  on by itself; the chat gets an answer at once, and the result and its files are posted back
  in the same WhatsApp chat when it is done (runtime._finish -> deliver_to_chat).
"""

import re
from typing import Any

from sqlalchemy import func, select

from ..documents import edit
from ..documents import service as doc_service
from ..models import ChatSession, DocFile, DocTemplate, Task
from .tools import Tool, ToolContext

SAVED_FORMAT = "saved_format"
EDITED_FOLDER = "AI documents/Edited"
CHAT_LABEL = "reply-chat:"  # a background task's label: where its result goes (WhatsApp)


async def _source(ctx: ToolContext, args: dict[str, Any]) -> tuple[DocFile | None, str]:
    from .doc_tools import _file

    ref = str(args.get("file_id") or "").strip()
    if not ref and args.get("format"):
        t = await doc_service.template_by_ref(ctx.db, ctx.workspace.id, str(args["format"]))
        if t is None or t.kind != SAVED_FORMAT or not t.docx_file_id:
            return None, "Error: no saved format by that name. list_templates shows them."
        ref = t.docx_file_id
    if not ref:
        return None, "Error: give the file_id of the file to copy (or format=a saved format)."
    f = await _file(ctx, ref)
    if f is None:
        return None, "Error: no such file for you. Use list_files to see the ids."
    return f, ""


def _changes(raw: Any) -> list[tuple[str, str]]:
    out = []
    for c in raw or []:
        if isinstance(c, dict) and str(c.get("find") or "").strip():
            out.append(
                (str(c["find"]), str(c.get("replace") if c.get("replace") is not None else ""))
            )
    return out


def _name(base: str, wanted: str, ext: str) -> str:
    name = (wanted or "").strip() or f"{re.sub(r'[.][A-Za-z0-9]{2,5}$', '', base)} (edited)"
    name = re.sub(r'[\\/:*?"<>|]+', "-", name)[:150]
    return name if name.lower().endswith(ext) else f"{name}{ext}"


async def _copy_file_with_changes(ctx: ToolContext, args: dict[str, Any]) -> str:
    from ..documents import storage

    f, err = await _source(ctx, args)
    if f is None:
        return err
    changes = _changes(args.get("changes"))
    cells = args.get("cells") if isinstance(args.get("cells"), dict) else None
    if not changes and not cells:
        return "Error: give changes=[{find, replace}] (the exact old text and the new text)."
    mime = (f.mime or "").split(";")[0].lower()
    if mime not in edit.EDITABLE:
        return (
            f"Error: {f.name} is {mime or 'an unknown type'}; I edit PDF, Word (.docx) and Excel "
            "(.xlsx) in place. For other files, draft a document instead."
        )
    data = await storage.read(ctx.db, f)
    try:
        import asyncio

        new, rep = await asyncio.to_thread(edit.edit, data, mime, changes, cells)
    except edit.EditError as e:
        return f"Error: {e}"
    ext = {edit.PDF: ".pdf", edit.DOCX: ".docx", edit.XLSX: ".xlsx"}[mime]
    person = ctx.person or ctx.agent.owner_user_id
    out = await doc_service.create_file(
        ctx.db,
        workspace_id=ctx.workspace.id,
        name=_name(f.name, str(args.get("new_name") or ""), ext),
        data=new,
        mime=mime,
        created_by=f"agent:{ctx.agent.id}",
        branch_id=f.branch_id,
        task_id=ctx.task.id if ctx.task else None,
        agent_id=ctx.agent.id,
        source="generated",
        folder=EDITED_FOLDER,
        source_path=f"edited from {f.id}",
        owner_user_id=person,
        status="ready",
    )
    await ctx.db.commit()
    changes_text = rep.text(changes)
    return (
        f"Made {out.name} (file {out.id}) from {f.name}, same format.\n{changes_text}\n"
        "Check the NOT found items against the file's exact text (read_file) and run again for "
        "those. On WhatsApp the file is attached to your answer by itself."
    )


async def _save_format(ctx: ToolContext, args: dict[str, Any]) -> str:
    from .doc_tools import _file

    f = await _file(ctx, str(args.get("file_id") or ""))
    if f is None:
        return "Error: no such file for you. Use list_files to see the ids."
    name = str(args.get("name") or "").strip()[:120]
    if not name:
        return "Error: give the format a name (e.g. 'Jadual Harga Tawaran')."
    kind = str(args.get("kind") or "document").strip()[:40]
    about = str(args.get("description") or "").strip()
    existing = await ctx.db.scalar(
        select(DocTemplate).where(
            DocTemplate.workspace_id == ctx.workspace.id,
            func.lower(DocTemplate.name) == name.lower(),
        )
    )
    desc = f"Saved format ({kind}, {f.name}): {about}"[:300]
    if existing is not None and existing.kind != SAVED_FORMAT:
        return f"Error: a template called {name} exists already. Pick another name."
    if existing is None:
        existing = DocTemplate(
            workspace_id=ctx.workspace.id,
            name=name,
            kind=SAVED_FORMAT,
            body="",
            fields=[],
            created_by=f"agent:{ctx.agent.id}",
        )
        ctx.db.add(existing)
    existing.description = desc
    existing.docx_file_id = f.id
    await ctx.db.commit()
    return (
        f"Saved {f.name} as the format '{name}' ({kind}). Next time, list_templates shows it: "
        f"copy_file_with_changes(format='{name}', changes=[...]) makes a new one in this format."
    )


async def _chat_of(ctx: ToolContext) -> str:
    if not ctx.session_id:
        return ""
    s = await ctx.db.get(ChatSession, ctx.session_id)
    title = (s.title if s else "") or ""
    return (
        title[len("WhatsApp chat ") :].split(" | ")[0] if title.startswith("WhatsApp chat ") else ""
    )


async def _work_in_background(ctx: ToolContext, args: dict[str, Any]) -> str:
    from . import launch, runtime

    title = str(args.get("title") or "").strip()[:200]
    brief = str(args.get("instructions") or "").strip()
    if not title or not brief:
        return "Error: give a title and the full instructions (with the file ids to use)."
    if ctx.task is not None:
        return "Error: you are already working in the background. Do the work now."
    chat = await _chat_of(ctx)
    person = ctx.person or ctx.agent.owner_user_id
    lowest = (
        await ctx.db.scalar(
            select(func.min(Task.position)).where(Task.workspace_id == ctx.workspace.id)
        )
        or 0
    )
    t = Task(
        workspace_id=ctx.workspace.id,
        branch_id=ctx.agent.branch_id,
        title=title,
        brief=brief
        + "\n\nWork through all of it now with your tools and finish with a short summary of "
        "what you made (the files you created are sent with it).",
        priority="high",
        assignee_agent_id=ctx.agent.id,
        created_by=f"user:{person}" if person else f"agent:{ctx.agent.id}",
        source="chat",
        requires_review=False,
        status="ready",
        position=float(lowest) - 1,
        labels=[f"{CHAT_LABEL}{chat}"] if chat else [],
    )
    ctx.db.add(t)
    await ctx.db.flush()
    await ctx.db.commit()
    await runtime.task_event(ctx.db, t, "created", f"agent:{ctx.agent.id}", "started from chat")
    try:
        await launch.launch(ctx.db, t, f"agent:{ctx.agent.id}")
    except launch.LaunchError as e:
        return f"Error: the background job could not start ({e.message}). Do it now instead."
    where = "in this chat" if chat else "on the Tasks page"
    return (
        f"Started background job {t.id}: {title}. Tell the person it is being done and that the "
        f"result and files will arrive {where} when it is finished. Do not wait for it."
    )


_CHANGES = {
    "type": "array",
    "description": "Each change: the exact old text as it appears in the file, and the new text",
    "items": {
        "type": "object",
        "properties": {"find": {"type": "string"}, "replace": {"type": "string"}},
        "required": ["find", "replace"],
    },
}

FILE_EDIT_TOOLS = (
    Tool(
        "copy_file_with_changes",
        "Copy a file with changes",
        "USE THIS when the person gives a document (PDF, Word, Excel) and wants the same "
        "document with other details: another company, recalculated amounts, new percentages "
        "or dates. It keeps the exact format and layout and changes only the texts you list. "
        "Steps: read_file to see the exact texts; calc the new values; then call this with "
        "every old text -> new text (amounts exactly as printed, e.g. '21,239,660.97'). For "
        "Excel you may also set cells ({'Sheet1!B5': 1234}). Never rebuild such a document "
        "with draft_document. One call per output file; for several files call it for each "
        "(or use work_in_background when there are many).",
        {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The file to copy"},
                "format": {"type": "string", "description": "Or a saved format's name"},
                "changes": _CHANGES,
                "cells": {"type": "object", "description": "Excel only: cell -> new value"},
                "new_name": {"type": "string", "description": "The new file's name"},
            },
            "required": ["changes"],
        },
        "low",
        "allow",
        _copy_file_with_changes,
    ),
    Tool(
        "save_format",
        "Remember a file's format",
        "Keep a file the person gave as a named format, so next time 'make another one' starts "
        "from it (copy_file_with_changes(format=...)). Offer it after you made a copy of their "
        "document, or save it when they ask you to remember it.",
        {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "name": {"type": "string", "description": "e.g. Jadual Harga Tawaran"},
                "kind": {
                    "type": "string",
                    "description": "e.g. price schedule, financial analysis",
                },
                "description": {"type": "string", "description": "What it is and when to use it"},
            },
            "required": ["file_id", "name"],
        },
        "low",
        "allow",
        _save_format,
    ),
    Tool(
        "work_in_background",
        "Work on it in the background",
        "For a long job (several files to make, much reading or many steps): start it as a "
        "background job and answer the person at once. The result and the files are posted "
        "back in this chat when it is done. Give complete instructions with every file id and "
        "value needed. Never just promise to do something later: either do it now or start it "
        "here.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "instructions": {"type": "string"},
            },
            "required": ["title", "instructions"],
        },
        "low",
        "allow",
        _work_in_background,
    ),
)
