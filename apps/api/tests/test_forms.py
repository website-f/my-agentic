"""P27: company forms people fill in and hand back by a deadline.

When rounds open and close (a window that wraps the month end, a missed round still shown as
late), reading and filling an Excel form (labels, table rows, cells, merged cells, formulas
kept), ready-made forms, who sees and manages them, handing in with attachments, the
manager's round view (handed in, missing), returning and accepting, and the AI filling a
form into the person's draft.
"""

import io
from datetime import date

from openpyxl import load_workbook

from agentic.forms import describe, fill, missed, state, window
from agentic.forms.starters import STARTERS, build

from .test_agents import llm, office, temporal  # noqa: F401

MONTHLY = {"every": "month", "from_day": 1, "to_day": 15}
WRAPS = {"every": "month", "from_day": 30, "to_day": 3}


def test_rounds_open_close_wrap_and_show_late():
    w = window(MONTHLY, date(2026, 10, 6))
    assert (w.period, w.opens, w.due) == ("2026-10", date(2026, 10, 1), date(2026, 10, 15))
    assert window(MONTHLY, date(2026, 10, 20)).period == "2026-11"  # type: ignore[union-attr]
    w = window(WRAPS, date(2026, 10, 2))  # inside September's round (30 Sep - 3 Oct)
    assert (w.period, w.due) == ("2026-09", date(2026, 10, 3))  # type: ignore[union-attr]
    assert missed(WRAPS, date(2026, 10, 6)).period == "2026-09"  # type: ignore[union-attr]
    assert missed(MONTHLY, date(2026, 10, 6)) is None
    year = window({"every": "year", "month": 12, "from_day": 1, "to_day": 31}, date(2026, 6, 1))
    assert (year.period, year.opens) == ("2026", date(2026, 12, 1))  # type: ignore[union-attr]
    assert window({"every": "none"}, date(2026, 6, 1)) is None
    assert state(window(MONTHLY, date(2026, 10, 14)), date(2026, 10, 14), None) == "due_soon"
    assert state(window(MONTHLY, date(2026, 10, 5)), date(2026, 10, 5), None) == "open"
    assert state(window(MONTHLY, date(2026, 10, 5)), date(2026, 10, 5), "submitted") == "submitted"
    assert state(missed(WRAPS, date(2026, 10, 6)), date(2026, 10, 6), None) == "late"


def test_a_round_that_closed_before_the_form_existed_is_not_late():
    from datetime import datetime

    from agentic.forms.store import shown_round
    from agentic.models import Form

    f = Form(schedule=WRAPS, created_at=datetime(2026, 10, 5, 9, 0))
    assert shown_round(f, date(2026, 10, 6), set())[0] == "2026-10"  # not September's round
    f.created_at = datetime(2026, 9, 1, 9, 0)
    assert shown_round(f, date(2026, 10, 6), set())[0] == "2026-09"  # still owed, so late


def test_ready_made_forms_read_and_fill_in_both_languages():
    for s in STARTERS:
        for lang in ("en", "ms"):
            _, data = build(s.key, lang, "Contoh Sdn Bhd")
            assert load_workbook(io.BytesIO(data)).worksheets[0]["A1"].value == "CONTOH SDN BHD"
    _, data = build("expense_claim", "ms", "Contoh Sdn Bhd")
    layout = describe(data)
    assert "A4 'Nama'" in layout and "C7 'Perkara'" in layout and "=SUM(E8:E22)" in layout
    out, report = fill(
        data,
        fields={"Nama": "Aina binti Ali", "Bulan": "Oktober 2026", "Tiada": "x"},
        rows=[
            {"Tarikh": "2026-10-03", "Perkara": "Grab ke PPD", "Jumlah (RM)": "RM23.50"},
            {"Perkara": "Kertas A4", "Jumlah (RM)": 45},
        ],
        cells={"F8": "resit hilang", "E23": 999},
    )
    ws = load_workbook(io.BytesIO(out)).worksheets[0]
    assert ws["C4"].value == "Aina binti Ali"  # the merged blank right of the label
    assert ws["C8"].value == "Grab ke PPD" and ws["E8"].value == 23.5 and ws["E9"].value == 45
    assert ws["F8"].value == "resit hilang"
    assert ws["E23"].value == "=SUM(E8:E22)"  # the total stays a formula
    assert "no label 'Tiada' in the form" in report and "kept the formula in E23" in report

