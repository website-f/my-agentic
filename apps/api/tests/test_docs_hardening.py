"""P29: files, packs, forms, library and parsers hardening.

Packs only reference what the person may open; office roles keep files inside what they
manage; form blanks are copied instead of pulled away from their audience; agents keep out of
people's own files, other people's private assistants' work and other departments'
guidelines; private assistants' work is hidden even from admins; parsers refuse bombs;
formula-looking text is stored as text; the secrets scan sees more; the library index never
keeps stale passages; a wrong-size embedding model degrades to keywords.
"""

import io
import zipfile

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select, update

from agentic.core.db import SessionLocal
from agentic.documents import extract, render_xlsx, service
from agentic.models import Agent, DocFile, KnowledgeChunk

from .test_agents import llm, new_agent, office, temporal  # noqa: F401
from .test_documents import inline_reading, upload  # noqa: F401
from .test_library import REFUNDS, guideline, indexing, passages, wipe_chunks  # noqa: F401


async def me(c) -> str:
    return (await c.get("/api/auth/me")).json()["user"]["id"]


async def private_assistant(
    client, o, owner_id: str, name: str = "Pa", dept: str = "Operations"
) -> Agent:
    """An agent turned into someone's private assistant."""
    a = await new_agent(client, o, name, dept)
    async with SessionLocal() as db:
        row = await db.get(Agent, a["id"])
        assert row is not None
        row.private, row.owner_user_id = True, owner_id
        await db.commit()
        await db.refresh(row)
        return row


async def made_by(agent: Agent, name: str, data: bytes, **extra) -> str:
    async with SessionLocal() as db:
        f = await service.create_file(
            db,
            workspace_id=agent.workspace_id,
            name=name,
            data=data,
            created_by=f"agent:{agent.id}",
            branch_id=agent.branch_id,
            agent_id=agent.id,
            source="generated",
            status="ready",
            **extra,
        )
        f.text = data.decode(errors="replace")
        await db.commit()
        return f.id


async def set_file(file_id: str, **values) -> None:
    async with SessionLocal() as db:
        await db.execute(update(DocFile).where(DocFile.id == file_id).values(**values))
        await db.commit()


# ================================================================ 1. packs


# ================================================================ 2. files PATCH


# ================================================================ 3. forms


# ================================================================ 4 + 5. agents, private work


# ================================================================ 6. parsers


def _bomb_docx(part_bytes: int = 4 * 1024 * 1024) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", b"\0" * part_bytes)
    return buf.getvalue()


def test_office_zip_bombs_are_refused_before_parsing():
    from agentic.forms import describe, fill

    out = extract.extract(_bomb_docx(), "x.docx")
    assert out.text == "" and "not read" in out.note
    with pytest.raises(extract.TooLarge):
        describe(_bomb_docx())
    with pytest.raises(extract.TooLarge):
        fill(_bomb_docx(), cells={"A1": 1})
    with pytest.raises(extract.TooLarge):
        extract.check_office_zip(_bomb_docx(1024 * 1024 * 2), max_unzipped=1024 * 1024)


def test_pictures_and_pages_are_capped():
    from PIL import Image

    strip = Image.new("L", (8000, 10))
    buf = io.BytesIO()
    strip.save(buf, format="PNG")
    out = extract._image(buf.getvalue())
    assert out.text == "" and "too large or too oddly shaped" in out.note
    assert extract.ocr_image(strip) == ""

    class Page:
        def __init__(self, w, h):
            self.size = (w, h)

        def get_size(self):
            return self.size

    a4 = extract._render_scale(Page(595, 842))
    assert a4 == extract.OCR_SCALE
    poster = extract._render_scale(Page(14400, 14400))
    assert (14400 * poster) ** 2 <= extract.OCR_MAX_PIXELS * 1.01


def test_unpack_report_keeps_at_most_200_skips():
    from agentic.intake import unpack

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(300):
            z.writestr(f"docs/empty{i}.txt", b"")
        z.writestr("docs/real.txt", b"hello")
    items = list(unpack.entries(buf.getvalue(), "u.zip"))
    report = items[-1]
    assert isinstance(report, unpack.Report)
    assert len(report.skipped) == unpack.MAX_SKIPPED and report.skipped_more == 100
    assert [e.name for e in items[:-1]] == ["real.txt"]
    # The upload's own buffer is read in place.
    again = list(unpack.entries(io.BytesIO(buf.getvalue()), "u.zip"))
    assert [e.name for e in again[:-1]] == ["real.txt"]


def test_form_sheets_are_scanned_within_a_cap():
    from agentic.forms import MAX_SCAN_ROWS, _scan

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.cell(row=5000, column=1, value="far away")
    ws["A1"] = "Nama"
    rows = list(_scan(ws))
    assert len(rows) == MAX_SCAN_ROWS


# ================================================================ 7. formulas


def test_formula_looking_text_is_stored_as_text():
    from agentic.forms import fill

    data = render_xlsx.render(
        '| Item | Note |\n|---|---|\n| =HYPERLINK("http://x","y") | @SUM(A1) |\n| 5 | -3 |',
        [("Client", "=cmd|' /C calc'!A0")],
        "=1+1",
    )
    wb = load_workbook(io.BytesIO(data))
    det, table = wb["Details"], wb.worksheets[1]
    assert det["A1"].data_type == "s" and det["B3"].data_type == "s"
    assert table["A2"].data_type == "s" and table["B2"].data_type == "s"
    assert table["A3"].value == 5 and table["B3"].value == -3  # numbers stay numbers

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws["A1"], ws["C1"] = "Nama", "=SUM(1,2)"
    buf = io.BytesIO()
    wb.save(buf)
    out, _ = fill(buf.getvalue(), cells={"B5": "=1+1", "C1": "x"}, fields={"Nama": "+60123"})
    ws2 = load_workbook(io.BytesIO(out)).active
    assert ws2 is not None
    assert ws2["B5"].data_type == "s" and ws2["B5"].value == "=1+1"
    assert ws2["B1"].data_type == "s"
    assert ws2["C1"].data_type == "f"  # the form's own formula is kept


# ================================================================ 8. secrets scan


def _docx_with_header(header: str, body: str) -> bytes:
    from docx import Document as Docx

    d = Docx()
    d.add_paragraph(body)
    d.sections[0].header.paragraphs[0].text = header
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_scan_finds_new_key_kinds_and_office_parts():
    from agentic.intake import scan

    found = scan.scan("key: sk-ant-api03-" + "Ab1" * 10)
    assert "api_key" in found.record()["credentials"]
    url = "DATABASE_URL=postgres://app:S3cret_pw@db.internal:5432/app"
    found = scan.scan(url)
    assert "password" in found.record()["credentials"]
    assert "S3cret_pw" not in scan.mask(url, found)
    assert not scan.scan("postgres://user:password@localhost/db").any  # a placeholder
    data = _docx_with_header("Portal password: Xy7#kLm9q", "An ordinary letter.")
    assert "Xy7#kLm9q" in scan.office_text(data)
    assert "password" in scan.scan_bytes(data, "a.docx").record()["credentials"]


async def test_header_secrets_hold_uploads_and_generated_files_are_noted(
    client,
    llm,  # noqa: F811
    temporal,  # noqa: F811
    inline_reading,  # noqa: F811
):
    o = await office(client)
    bid = o["branch"]["id"]
    data = _docx_with_header("Portal password: Xy7#kLm9q", "An ordinary letter.")
    f = (await upload(client, "letter.docx", data, branch_id=bid)).json()
    got = (await client.get(f"/api/files/{f['id']}")).json()
    assert got["quarantined"] and "password" in got["sensitive"]["credentials"]

    agent = await new_agent(client, o, "Coder")
    async with SessionLocal() as db:
        a = await db.get(Agent, agent["id"])
        assert a is not None
    made = await made_by(
        a, "out.csv", b"user,password\nadmin,Pw: hunter2x9\nkey sk-ant-" + b"x1" * 15
    )
    async with SessionLocal() as db:
        g = await db.get(DocFile, made)
        assert g is not None and not g.quarantined
        assert "api_key" in g.sensitive["credentials"]


# ================================================================ 9. index race


async def test_index_file_drops_passages_when_the_file_leaves_the_library_meanwhile(
    client,
    llm,  # noqa: F811
    temporal,  # noqa: F811
    inline_reading,  # noqa: F811
    indexing,  # noqa: F811
    monkeypatch,
):
    from agentic.brain import embed
    from agentic.knowledge import indexer

    await office(client)
    g = await guideline(client, "refunds.txt", REFUNDS)
    assert await passages(g["id"]) > 0
    real = embed.embed

    async def slow_embed(texts):
        # Someone takes the file out of the library while its passages are being built.
        async with SessionLocal() as other:
            await other.execute(update(DocFile).where(DocFile.id == g["id"]).values(library=False))
            await other.commit()
        return await real(texts)

    monkeypatch.setattr(embed, "embed", slow_embed)
    async with SessionLocal() as db:
        assert await indexer.index_file(db, g["id"]) == 0
    assert await passages(g["id"]) == 0


# ================================================================ 10. embeddings


async def test_a_wrong_size_model_falls_back_to_keywords(
    client,
    llm,  # noqa: F811
    temporal,  # noqa: F811
    inline_reading,  # noqa: F811
    indexing,  # noqa: F811
    monkeypatch,
):
    from agentic.brain import embed
    from agentic.knowledge import indexer
    from agentic.knowledge import search as library

    await office(client)
    g = await guideline(client, "refunds.txt", REFUNDS)
    assert not indexer.dims_ok([0.0] * 10) and indexer.dims_ok(None)

    async def wrong(texts):
        return [[0.1] * 12 for _ in texts]

    monkeypatch.setattr(embed, "embed", wrong)
    async with SessionLocal() as db:
        assert await indexer.index_file(db, g["id"]) > 0  # stored without vectors
        n = await db.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.source_id == g["id"], KnowledgeChunk.embedding.is_not(None))
        )
        assert n == 0
        ws = (await db.get(DocFile, g["id"])).workspace_id  # type: ignore[union-attr]
        hits = await library.search(db, library.Reader(ws, everything=True), "damaged goods")
        assert hits and hits[0].source_id == g["id"]
