"""My Agentic: change a few details inside a PDF, Word or Excel file and keep everything else.

The person sends a document (a price schedule, a financial analysis, a letter) and wants the
same document with other names, amounts or percentages. Rebuilding it loses the layout, so the
file itself is edited:

- PDF: each old text is found on its page (PDFium: exact position, font size, weight), covered
  with the colour around it, and the new text is written in the same place and size (numbers
  right-aligned to where the old number ended). Everything else is the original page.
- Word (.docx): the text is replaced inside its runs, so fonts, tables, headers and footers stay.
- Excel (.xlsx): matching cells are replaced and given cells set; formulas stay and Excel
  recalculates them when the file is opened.

Each change is {find, replace}; a find matches as a whole token (finding "1,000" does not change
"11,000.00"). The report says how many times each was found, so the AI can see what it missed.
"""

import ctypes
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"
EDITABLE = (PDF, DOCX, XLSX)
MAX_CHANGES = 400
_NUM = re.compile(r"^[\s(]*[-+]?(RM|\$|USD|MYR)?\s*[\d.,]+%?\s*\)?$", re.I)


class EditError(Exception):
    pass


@dataclass
class Report:
    found: Counter[str] = field(default_factory=Counter)
    cells: int = 0
    notes: list[str] = field(default_factory=list)

    def text(self, changes: list[tuple[str, str]]) -> str:
        done = [f"{f!r} -> {r!r} x{self.found[f]}" for f, r in changes if self.found[f]]
        missed = [repr(f) for f, _ in changes if not self.found[f]]
        out = []
        if done:
            out.append("Changed: " + "; ".join(done[:60]) + (" ..." if len(done) > 60 else ""))
        if self.cells:
            out.append(f"Cells set: {self.cells}")
        if missed:
            out.append(
                "NOT found (check the exact text as it appears in the file): "
                + ", ".join(missed[:40])
            )
        out.extend(self.notes)
        return "\n".join(out) or "Nothing was changed."


def _token_ok(find: str, before: str, after: str) -> bool:
    """A match is a whole token: a digit is not glued to a digit, nor a letter to a letter
    ("1,000" in "11,000.00" or in "1,000.50" is not a match; "RM1,000" and "1,000." are).
    `after` holds the next two characters."""
    if not find:
        return False
    a1, a2 = after[:1], after[1:2]
    if before and (
        (before.isdigit() and find[0].isdigit()) or (before.isalpha() and find[0].isalpha())
    ):
        return False
    if a1 and ((a1.isdigit() and find[-1].isdigit()) or (a1.isalpha() and find[-1].isalpha())):
        return False
    if find[-1].isdigit() and a1 in ".," and a2.isdigit():  # 1,000 inside 1,000.50
        return False
    if find[0].isdigit() and before in ".,":  # 000 inside 1,000
        return False
    return True


def _is_number(text: str) -> bool:
    return bool(_NUM.match(text or "")) and any(c.isdigit() for c in text)


# ---------------------------------------------------------------- PDF


def edit_pdf(data: bytes, changes: list[tuple[str, str]]) -> tuple[bytes, Report]:
    import pypdfium2 as pdfium
    from fpdf import FPDF
    from pypdf import PdfReader, PdfWriter

    from .extract import _PDFIUM
    from .render_pdf import _fonts

    rep = Report()
    hits: dict[int, list[dict[str, Any]]] = {}
    sizes: list[tuple[float, float]] = []
    colours: dict[int, Any] = {}
    cleaned = False
    kept_under = 0  # changed text that sits inside a longer line: covered, not removed
    with _PDFIUM:  # PDFium is not thread-safe
        try:
            pdf = pdfium.PdfDocument(data)
        except Exception as e:  # noqa: BLE001 - damaged or encrypted
            raise EditError("This PDF could not be opened (damaged or password-protected).") from e
        try:
            for pi in range(len(pdf)):
                page = pdf[pi]
                w, h = page.get_size()
                sizes.append((w, h))
                tp = page.get_textpage()
                total = tp.count_chars()
                for find, new in changes:
                    if not find:
                        continue
                    searcher = tp.search(find, match_case=True)
                    while (occ := searcher.get_next()) is not None:
                        idx, count = occ
                        before = tp.get_text_range(idx - 1, 1) if idx > 0 else ""
                        after = (
                            tp.get_text_range(idx + count, min(2, total - idx - count))
                            if idx + count < total
                            else ""
                        )
                        if not _token_ok(find, before, after):
                            continue
                        boxes = [tp.get_charbox(i) for i in range(idx, idx + count)]
                        boxes = [b for b in boxes if b[2] > b[0]]
                        if not boxes:
                            continue
                        size = float(pdfium.raw.FPDFText_GetFontSize(tp.raw, idx) or 0)
                        ox, oy = ctypes.c_double(0), ctypes.c_double(0)
                        base = (
                            oy.value
                            if pdfium.raw.FPDFText_GetCharOrigin(
                                tp.raw, idx, ctypes.byref(ox), ctypes.byref(oy)
                            )
                            else None
                        )
                        weight = int(pdfium.raw.FPDFText_GetFontWeight(tp.raw, idx) or 400)
                        hits.setdefault(pi, []).append(
                            {
                                "l": min(b[0] for b in boxes),
                                "b": min(b[1] for b in boxes),
                                "r": max(b[2] for b in boxes),
                                "t": max(b[3] for b in boxes),
                                "size": size,
                                "bold": weight >= 600,
                                "new": new,
                                "base": base,
                                # a number that ends its line (a table cell) keeps its right
                                # edge; inside a sentence it starts where the old one started
                                "num": _is_number(find) and not after.strip(),
                            }
                        )
                        rep.found[find] += 1
                    searcher.close()
                if pi in hits:  # the colour around each text, so the cover blends in
                    colours[pi] = page.render(scale=1).to_pil().convert("RGB")
                    tp.close()
                    # The old text itself goes when it is its own text object (a table
                    # cell), so copying or reading the file never shows the old value.
                    removed = 0
                    for obj in list(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_TEXT])):
                        try:
                            ol, ob, orr, ot = obj.get_bounds()
                        except Exception:  # noqa: BLE001, S112 - an object without bounds
                            continue
                        if any(
                            ol >= x["l"] - 1.5
                            and orr <= x["r"] + 1.5
                            and ob >= x["b"] - 1.5
                            and ot <= x["t"] + 1.5
                            for x in hits[pi]
                        ):
                            page.remove_obj(obj)
                            obj.close()  # a removed object is ours to free
                            removed += 1
                        else:
                            kept_under += (
                                1
                                if any(
                                    ol <= x["l"] + 1
                                    and orr >= x["r"] - 1
                                    and ob <= x["t"]
                                    and ot >= x["b"]
                                    for x in hits[pi]
                                )
                                else 0
                            )
                    if removed:
                        page.gen_content()
                        cleaned = True
                else:
                    tp.close()
                page.close()
            if cleaned:
                buf = io.BytesIO()
                pdf.save(buf)
                data = buf.getvalue()
        finally:
            pdf.close()
    if not hits:
        return data, rep
    if kept_under:
        rep.notes.append(
            f"{kept_under} change(s) sit inside a longer line of text: the new text is drawn over "
            "it, and the old text stays in the file's text layer (copy-paste could show it)."
        )

    fonts = _fonts()
    ov = FPDF(unit="pt")
    ov.set_auto_page_break(False)
    if fonts:
        for style, path in zip(("", "B", "I", "BI"), fonts, strict=True):
            ov.add_font("body", style, path)
        family = "body"
    else:
        family = "helvetica"
    for pi, (w, h) in enumerate(sizes):
        ov.add_page(format=(w, h))
        img = colours.get(pi)
        for hit in hits.get(pi, []):
            l, b, r, t = hit["l"], hit["b"], hit["r"], hit["t"]  # noqa: E741 - left, bottom...
            bg = (255, 255, 255)
            if img is not None:
                pts = []
                for x, y in ((l - 2, t + 1), (r + 2, t + 1), (l - 2, b - 1), (r + 2, b - 1)):
                    px, py = (
                        int(max(0, min(img.width - 1, x))),
                        int(max(0, min(img.height - 1, h - y))),
                    )
                    pts.append(img.getpixel((px, py)))
                bg = Counter(pts).most_common(1)[0][0]
            ov.set_fill_color(*bg)
            ov.rect(l - 0.5, h - t - 0.8, (r - l) + 1.0, (t - b) + 1.6, style="F")
            size = hit["size"] or max(5.0, (t - b) * 1.25)
            ov.set_font(family, "B" if hit["bold"] else "", size)
            new = hit["new"] if fonts else hit["new"].encode("latin-1", "replace").decode("latin-1")
            width = ov.get_string_width(new)
            room = (r - l) * (1.6 if hit["num"] else 3.0) + 12
            while width > room and size > 5:
                size -= 0.5
                ov.set_font(family, "B" if hit["bold"] else "", size)
                width = ov.get_string_width(new)
            x = r - width if hit["num"] else l
            ov.set_text_color(20, 20, 20)
            ov.text(x, h - (hit["base"] if hit["base"] is not None else b), new)
    overlay = PdfReader(io.BytesIO(bytes(ov.output())))
    src = PdfReader(io.BytesIO(data))
    out = PdfWriter()
    for pi, page in enumerate(src.pages):
        if pi in hits:
            page.merge_page(overlay.pages[pi])
        out.add_page(page)
    buf = io.BytesIO()
    out.write(buf)
    return buf.getvalue(), rep


# ---------------------------------------------------------------- Word


def _replace_in_paragraph(p: Any, find: str, new: str) -> int:
    n = 0
    start = 0
    while True:
        runs = list(p.runs)
        text = "".join(r.text for r in runs)
        i = text.find(find, start)
        if i < 0:
            return n
        before = text[i - 1] if i > 0 else ""
        after = text[i + len(find) : i + len(find) + 2]
        if not _token_ok(find, before, after):
            start = i + 1
            continue
        pos, s_run, s_off, e_run, e_off = 0, None, 0, None, 0
        for ri, r in enumerate(runs):
            rl = len(r.text)
            if s_run is None and i < pos + rl:
                s_run, s_off = ri, i - pos
            if s_run is not None and i + len(find) <= pos + rl:
                e_run, e_off = ri, i + len(find) - pos
                break
            pos += rl
        if s_run is None or e_run is None:
            return n
        if s_run == e_run:
            r = runs[s_run]
            r.text = r.text[:s_off] + new + r.text[e_off:]
        else:
            runs[s_run].text = runs[s_run].text[:s_off] + new
            for k in range(s_run + 1, e_run):
                runs[k].text = ""
            runs[e_run].text = runs[e_run].text[e_off:]
        n += 1
        start = i + len(new)


def _paragraphs(doc: Any) -> Any:
    def walk(container: Any) -> Any:
        yield from container.paragraphs
        for table in getattr(container, "tables", []):
            for row in table.rows:
                for cell in row.cells:
                    yield from walk(cell)

    yield from walk(doc)
    for section in doc.sections:
        for part in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
        ):
            try:
                yield from walk(part)
            except Exception:  # noqa: BLE001, S112 - a section without that part
                continue


def edit_docx(data: bytes, changes: list[tuple[str, str]]) -> tuple[bytes, Report]:
    from docx import Document

    rep = Report()
    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise EditError("This Word file could not be opened.") from e
    seen: set[int] = set()
    for p in _paragraphs(doc):
        if id(p._p) in seen:  # merged table cells repeat the same paragraph
            continue
        seen.add(id(p._p))
        for find, new in changes:
            if find:
                rep.found[find] += _replace_in_paragraph(p, find, new)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), rep


# ---------------------------------------------------------------- Excel


def _as_number(text: str) -> float | None:
    t = re.sub(r"(RM|MYR|USD|\$|\s|,)", "", text or "", flags=re.I)
    pct = t.endswith("%")
    t = t.rstrip("%")
    try:
        v = float(t)
    except ValueError:
        return None
    return v / 100 if pct else v


def edit_xlsx(
    data: bytes, changes: list[tuple[str, str]], cells: dict[str, Any] | None = None
) -> tuple[bytes, Report]:
    from openpyxl import load_workbook

    rep = Report()
    try:
        wb = load_workbook(io.BytesIO(data))  # formulas kept (not data_only)
    except Exception as e:  # noqa: BLE001
        raise EditError("This Excel file could not be opened.") from e
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if v is None or (isinstance(v, str) and v.startswith("=")):
                    continue
                for find, new in changes:
                    if not find:
                        continue
                    if isinstance(v, str) and find in v:
                        c.value = new if v.strip() == find.strip() else v.replace(find, new)
                        rep.found[find] += 1
                        break
                    if isinstance(v, int | float) and not isinstance(v, bool):
                        want = _as_number(find)
                        if want is not None and abs(float(v) - want) < 1e-9:
                            num = _as_number(new)
                            c.value = num if num is not None else new
                            rep.found[find] += 1
                            break
    for addr, value in (cells or {}).items():
        sheet, _, ref = str(addr).rpartition("!")
        ws = (
            wb[sheet.strip("'")]
            if sheet and sheet.strip("'") in wb.sheetnames
            else wb.worksheets[0]
        )
        if isinstance(value, str) and not value.startswith("=") and _is_number(value):
            num = _as_number(value)
            value = num if num is not None else value
        ws[ref.strip()] = value
        rep.cells += 1
    try:
        wb.calculation.fullCalcOnLoad = True  # Excel works the formulas out again on open
    except Exception:  # noqa: BLE001, S110 - an old workbook without calc settings
        pass
    rep.notes.append("Formulas are kept; Excel recalculates them when the file is opened.")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), rep


def edit(
    data: bytes, mime: str, changes: list[tuple[str, str]], cells: dict[str, Any] | None = None
) -> tuple[bytes, Report]:
    """The edited file (same format) and what changed. Raises EditError."""
    changes = [(str(f), str(r)) for f, r in changes if str(f)][:MAX_CHANGES]
    # Longer finds first, so "21,239,660.97" is placed before a shorter text inside it.
    changes.sort(key=lambda fr: len(fr[0]), reverse=True)
    m = (mime or "").split(";")[0].strip().lower()
    if m == PDF:
        if cells:
            raise EditError("Cells are for Excel files; give find/replace changes for a PDF.")
        return edit_pdf(data, changes)
    if m == DOCX:
        return edit_docx(data, changes)
    if m == XLSX:
        return edit_xlsx(data, changes, cells)
    raise EditError("I can edit PDF, Word (.docx) and Excel (.xlsx) files in place.")
