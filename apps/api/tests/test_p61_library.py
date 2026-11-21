"""P61 Library: copying files, folders that exist while empty, labels, the in-place view of
Excel / CSV / Word / text, and inline downloads that never show HTML."""

import io

import httpx

from agentic.documents import render_pdf, viewer

from .conftest import csrf
from .test_agents import llm, office, temporal  # noqa: F401
from .test_documents import inline_reading, upload  # noqa: F401

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


def _xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Item", "Qty", "Price"])
    ws.append(["Kopi", 2, 3.5])
    ws.append(["<script>x</script>", None, 10])
    other = wb.create_sheet("Big")
    for i in range(viewer.MAX_ROWS + 20):
        other.append([i] * (viewer.MAX_COLS + 5))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _docx() -> bytes:
    from docx import Document

    d = Document()
    d.add_heading("Quarterly <report>", level=1)
    p = d.add_paragraph("Plain ")
    p.add_run("bold").bold = True
    p.add_run(" and ")
    p.add_run("italic").italic = True
    d.add_paragraph("first point", style="List Bullet")
    d.add_paragraph("second point", style="List Bullet")
    d.add_paragraph("step one", style="List Number")
    d.add_paragraph('<img src=x onerror="alert(1)">')
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Name", "Total"
    t.cell(1, 0).text, t.cell(1, 1).text = "Aina & Co", "RM 10"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


async def post_file(c: httpx.AsyncClient, name: str, data: bytes, mime: str = "") -> dict:
    r = await c.post(
        "/api/files",
        params={"name": name},
        content=data,
        headers={**csrf(c), "content-type": "application/octet-stream", "x-file-type": mime},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def move(c: httpx.AsyncClient, ids: list[str], folder: str) -> None:
    r = await c.post("/api/files/move", json={"ids": ids, "folder": folder}, headers=csrf(c))
    assert r.status_code == 200, r.text


async def tree(c: httpx.AsyncClient, **params) -> dict[str, dict]:
    r = await c.get("/api/files/tree", params=params)
    assert r.status_code == 200, r.text
    return {f["path"]: f for f in r.json()["folders"]}


# ================================================================ the viewer (pure)


def test_viewer_tables_from_excel_and_csv():
    out = viewer.view(_xlsx(), "sales.xlsx")
    assert out["type"] == "table" and [s["name"] for s in out["sheets"]] == ["Sales", "Big"]
    sales, big = out["sheets"]
    assert sales["rows"][0] == ["Item", "Qty", "Price"]
    assert sales["rows"][1] == ["Kopi", 2, 3.5] and sales["rows"][2][1] is None
    assert sales["columns"] == 3 and sales["truncated"] is False
    assert len(big["rows"]) == viewer.MAX_ROWS and big["columns"] == viewer.MAX_COLS
    assert big["truncated"] is True

    semi = viewer.view(b"a;b;c\n1;2;3\n4;;6\n", "x.csv")
    assert semi["type"] == "table" and semi["sheets"][0]["rows"] == [
        ["a", "b", "c"],
        ["1", "2", "3"],
        ["4", None, "6"],
    ]
    tsv = viewer.view("nama\tbandar\nAina\tKL\n".encode("cp1252"), "x.tsv")
    assert tsv["sheets"][0]["rows"][1] == ["Aina", "KL"]
    latin = viewer.view("caf\xe9,1\n".encode("cp1252"), "y.csv")
    assert latin["sheets"][0]["rows"][0] == ["caf\xe9", "1"]
    # An old .xls openpyxl cannot read: the read text instead, or nothing.
    assert viewer.view(b"\xd0\xcf\x11\xe0junk", "old.xls", text="A1 B1") == {
        "type": "text",
        "text": "A1 B1",
    }
    assert viewer.view(b"\xd0\xcf\x11\xe0junk", "old.xls") == {"type": "none"}


def test_viewer_word_is_escaped_html_with_only_safe_tags():
    import re

    out = viewer.view(_docx(), "report.docx")
    assert out["type"] == "html"
    h = out["html"]
    assert "<h1>Quarterly &lt;report&gt;</h1>" in h
    assert "<p>Plain <strong>bold</strong> and <em>italic</em></p>" in h
    assert "<ul><li>first point</li><li>second point</li></ul><ol><li>step one</li></ol>" in h
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in h and "<img" not in h
    assert "<thead><tr><th>Name</th><th>Total</th></tr></thead>" in h
    assert "<td>Aina &amp; Co</td>" in h
    allowed = set("h1 h2 h3 h4 p strong em ul ol li table thead tbody tr th td section hr".split())
    assert set(re.findall(r"</?([a-z0-9]+)", h)) <= allowed


def test_viewer_text_pdf_image_media_and_none():
    assert viewer.view(b"hello\nworld", "notes.txt") == {"type": "text", "text": "hello\nworld"}
    assert viewer.view(b'{"a": 1}', "data.json")["type"] == "text"
    assert viewer.view(b"<b>hi</b>", "page.html") == {"type": "text", "text": "<b>hi</b>"}
    long = viewer.view(b"x" * (viewer.MAX_TEXT + 10), "big.log")
    assert len(long["text"]) == viewer.MAX_TEXT
    pdf = render_pdf.render("Hello", "Doc")
    assert viewer.view(pdf, "a.pdf", "application/pdf") == {"type": "pdf"}
    assert viewer.view(PNG, "a.png", "image/png") == {"type": "image"}
    assert viewer.view(b"ID3....", "song.mp3") == {"type": "media", "mime": "audio/mpeg"}
    assert viewer.view(b"\x00\x00", "clip.bin", "video/mp4") == {
        "type": "media",
        "mime": "video/mp4",
    }
    assert viewer.view(b"\x00\x01\x02", "blob.bin") == {"type": "none"}
    assert viewer.view(b"\x00\x01\x02", "blob.bin", text="read text") == {
        "type": "text",
        "text": "read text",
    }
    # A media type that carries markup is never one to play.
    assert viewer.media_mime("x.bin", "video/svg+xml") is None


# ================================================================ copy


# ================================================================ folders


# ================================================================ labels


# ================================================================ view and inline downloads

