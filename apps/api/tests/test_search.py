"""P25: search inside every document, with suggestions as you type.

Phrases, page hits, amounts ("RM700"), dates ("16hb"), prefixes, typos and quotes; scope
(staff of one company never see another's; held-back files never appear in search,
suggestions or the agent tool); draft SOP visibility; documents and templates; recent
searches per person; suggestion latency on ~2,000 passages.

All data is synthetic: made-up companies, people and amounts.
"""

import random
import statistics
import time

import httpx
import pytest
from sqlalchemy import select, text

from agentic.core.db import SessionLocal
from agentic.models import SOP, Agent, DocFile, DocTemplate, Document, User, Workspace
from agentic.search import engine, index, vocab
from agentic.search import text as tx
from agentic.search.models import SearchPassage
from agentic.search.viewer import for_agent

from .conftest import csrf, setup_owner


@pytest.fixture(autouse=True)
async def fresh_vocab():
    vocab.clear()
    yield
    from agentic.api.routers import search as router

    await router.drain()
    await vocab.drain()
    vocab.clear()


# ---------------------------------------------------------------- the words


def test_words_amounts_dates_and_roots():
    assert [t.text for t in tx.tokens("Bayaran RM1,500.50 pada 16hb.")] == [
        "bayaran",
        "rm",
        "1,500.50",
        "pada",
        "16",
        "hb",
    ]
    assert tx.norm_number("1,500.50") == ["1500.50", "1500"]
    assert tx.norm_number("700.00") == ["700.00", "700"]
    assert tx.norm_number("07") == ["07", "7"]
    assert "layak" in tx.roots("kelayakan")
    assert "bayar" in tx.roots("pembayaran")
    assert "mohon" in tx.roots("permohonan")
    assert "kerja" in tx.roots("pekerja")
    assert tx.roots("claims") == ["claim"]
    assert tx.roots("jalan") == [] and tx.roots("makan") == []
    vec = tx.tsvector("3.1 Kelayakan", "Had RM 700.00 sebulan")
    assert "'kelayakan':2B" in vec and "'layak':2C" in vec
    # Heading words 1-2, a gap, then the text from 6: had 6, rm 7, 700.00 8.
    assert "'rm':7 " in vec and "'700.00':8 " in vec and "'700':8C" in vec

    q = tx.parse('"advance gaji" RM700 kelaya')
    assert [t.parts for t in q.terms] == [["advance", "gaji"], ["rm", "700"], ["kelaya"]]
    assert q.terms[0].phrase and not q.terms[0].prefix
    assert q.tsquery() == "('advance' <-> 'gaji') & ('rm' <-> '700') & ('kelaya':* | 'kelaya')" or (
        "'kelaya':*" in q.tsquery()
    )
    # Stop words go from loose words, stay in phrases; nothing but stop words stays as is.
    assert [t.parts for t in tx.parse("apa itu advance").terms] == [["advance"]]
    assert [t.parts for t in tx.parse('"dan lain-lain"').terms] == [["dan", "lain", "lain"]]
    assert tx.parse("  ").empty

    rx = tx.parse("RM700 kelayakan").regex()
    out = tx.marked("Had <b>RM 700.00</b> ikut kelayakan & syarat", rx)
    assert out == (
        "Had &lt;b&gt;<mark>RM 700.00</mark>&lt;/b&gt; ikut <mark>kelayakan</mark> &amp; syarat"
    )
    snip = tx.snippet("x " * 400 + "kelayakan advance " + "y " * 400, tx.parse("kelayakan").regex())
    assert snip.startswith("…") and snip.endswith("…") and "<mark>kelayakan</mark>" in snip


async def test_tsvector_literals_are_valid_postgres(client):
    async with SessionLocal() as db:
        vec = tx.tsvector(
            "BAB 2 KELAYAKAN", "Pekerja layak memohon advance RM700 pada 16hb. 'Quote' \\ back"
        )
        q = tx.parse("kelayakan RM 700 16hb").tsquery()
        ok = await db.scalar(
            text("SELECT CAST(:v AS tsvector) @@ CAST(:q AS tsquery)"), {"v": vec, "q": q}
        )
        assert ok is True
        assert await db.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_trgm')")
        )


# ---------------------------------------------------------------- an office with documents

HANDBOOK_PAGES = {
    1: "BUKU PANDUAN PEKERJA\nPanduan ini untuk semua pekerja Contoh Niaga Sdn Bhd.",
    12: "BAB 4 GAJI\nGaji dibayar pada 16hb setiap bulan melalui bank.",
    23: (
        "BAB 7 KELAYAKAN ADVANCE GAJI\n"
        "Kelayakan advance: pekerja tetap boleh memohon advance gaji sehingga RM 700.00 sebulan "
        "selepas tamat percubaan."
    ),
    27: (
        "LOAD SYSTEM CALCULATION\n"
        "The load system calculation for the store racks uses 1,500.50 kg per beam."
    ),
}


def handbook() -> str:
    out = []
    for p in range(1, 31):
        body = HANDBOOK_PAGES.get(p, f"Halaman {p}. Peraturan am syarikat dan maklumat lain.")
        out.append(f"[page {p}]\n{body}")
    return "\n\n".join(out)


async def add_file(
    ws,
    owner_id,
    *,
    title,
    body,
    branch_id=None,
    library=False,
    kind="guide",
    quarantined=False,
    department_id=None,
    name=None,
    pages=None,
    folder="",
    restricted=False,
):
    async with SessionLocal() as db:
        f = DocFile(
            workspace_id=ws,
            branch_id=branch_id,
            name=name or f"{title}.pdf",
            mime="application/pdf",
            size=len(body),
            sha256=str(abs(hash(title + body))),
            data=b"%PDF-1.4",
            status="ready",
            text=body,
            pages=pages or body.count("[page "),
            kind=kind,
            title=title,
            summary=f"{title}.",
            created_by=f"user:{owner_id}",
            library=library,
            quarantined=quarantined,
            department_id=department_id,
            folder=folder,
            restricted=restricted,
        )
        db.add(f)
        await db.commit()
        return f.id


async def office_docs(client: httpx.AsyncClient) -> dict:
    """Two companies; a handbook, a form, library guides, a held-back file, SOPs (one draft),
    a prepared document and a template."""
    me = await setup_owner(client)
    a = (
        await client.post(
            "/api/branches", json={"name": "Contoh Niaga Sdn Bhd"}, headers=csrf(client)
        )
    ).json()
    b = (
        await client.post("/api/branches", json={"name": "Lain Jaya Bhd"}, headers=csrf(client))
    ).json()
    async with SessionLocal() as db:
        ws = (await db.scalars(select(Workspace.id))).one()
        owner_id = (
            await db.scalars(select(User.id).where(User.email == "owner@example.com"))
        ).one()
    depts = {d["name"]: d["id"] for d in a["departments"]}
    o = {"ws": ws, "owner": owner_id, "a": a["id"], "b": b["id"], "depts": depts, "me": me}
    o["handbook"] = await add_file(
        ws, owner_id, title="Buku Panduan Pekerja", body=handbook(), branch_id=a["id"], folder="HR"
    )
    o["form"] = await add_file(
        ws,
        owner_id,
        title="Borang Tuntutan Perjalanan",
        kind="form",
        branch_id=a["id"],
        body="[page 1]\nBORANG TUNTUTAN PERJALANAN\nNama pemohon: ____\n"
        "Jawatan: Pegawai Kewangan Kanan",
    )
    o["guide_a"] = await add_file(
        ws,
        owner_id,
        title="Panduan Keselamatan Stor",
        library=True,
        branch_id=a["id"],
        body="[page 1]\nKESELAMATAN STOR\nSemua pekerja wajib memakai topi keledar di stor.",
    )
    o["guide_b"] = await add_file(
        ws,
        owner_id,
        title="Polisi Advance Lain Jaya",
        library=True,
        branch_id=b["id"],
        kind="policy",
        body="[page 1]\nPOLISI ADVANCE\nKelayakan advance di Lain Jaya: sehingga RM900 sebulan.",
    )
    o["held"] = await add_file(
        ws,
        owner_id,
        title="Senarai Kata Laluan Portal",
        branch_id=a["id"],
        quarantined=True,
        library=True,
        body="[page 1]\nSENARAI KATA LALUAN\nKata laluan portal: Zebra@4421. "
        "Kelayakan advance rahsia.",
    )
    async with SessionLocal() as db:
        active = SOP(
            workspace_id=ws,
            scope="workspace",
            title="SOP Tuntutan Advance",
            body="## Langkah\n1. Isi borang tuntutan.\n2. Kelulusan pengurus.\nHad RM700 sebulan.",
            status="active",
            updated_by="test",
        )
        draft = SOP(
            workspace_id=ws,
            scope="workspace",
            title="SOP Draf Pembelian Stor",
            body="## Pembelian\nPembelian bawah RM5,000 diluluskan oleh pengurus stor.",
            status="draft",
            updated_by="test",
        )
        doc = Document(
            workspace_id=ws,
            branch_id=a["id"],
            title="Sebut Harga Pelanggan",
            body="Sebut harga untuk {{client}}. Jumlah {{total}}.",
            values={"client": "Pelanggan Contoh Enterprise", "total": "RM 12,345.60"},
            created_by=f"user:{owner_id}",
        )
        tpl = DocTemplate(
            workspace_id=ws,
            name="Surat Tawaran Kerja",
            description="Offer letter for new hires",
            body="Dengan sukacitanya kami menawarkan jawatan {{role}}.",
            created_by="test",
        )
        db.add_all([active, draft, doc, tpl])
        await db.commit()
        o.update(sop=active.id, draft=draft.id, doc=doc.id, tpl=tpl.id)
    async with SessionLocal() as db:
        await index.reindex_workspace(db, ws)
    return o


async def find(c: httpx.AsyncClient, q: str, **params) -> dict:
    r = await c.get("/api/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def ids(res: dict) -> list[str]:
    return [h["id"] for h in res["hits"]]


# ---------------------------------------------------------------- people search


async def test_phrases_pages_amounts_dates_prefixes_and_typos(client):
    o = await office_docs(client)

    res = await find(client, "kelayakan advance")
    # Both documents hold the phrase; the one with "advance" in its title may come first.
    assert set(ids(res)[:2]) == {o["handbook"], o["guide_b"]}
    top = next(h for h in res["hits"] if h["id"] == o["handbook"])
    assert top["type"] == "file" and top["page"] == 23 and top["pages_matched"] == 1
    assert top["url"] == f"/files?f={o['handbook']}&page=23"
    assert top["snippet"].startswith("<mark>Kelayakan advance</mark>: pekerja tetap")
    assert "memohon <mark>advance</mark> gaji" in top["snippet"]
    assert top["heading"] == "BAB 7 <mark>KELAYAKAN ADVANCE</mark> GAJI"
    assert top["company"] == "CONTOH NIAGA SDN BHD" and top["folder"] == "HR"
    assert o["held"] not in ids(res)  # held back: never, not even for the owner
    assert o["sop"] in ids(res) and o["guide_b"] in ids(res)  # the owner sees every company

    # Amounts and dates however they are written.
    for q in ("RM700", "rm 700", "700.00", "RM700.00"):
        hits = (await find(client, q))["hits"]
        assert any(h["id"] == o["handbook"] and h["page"] == 23 for h in hits), q
        assert o["sop"] in [h["id"] for h in hits], q
    for q in ("16hb", "16 hb"):
        hits = (await find(client, q))["hits"]
        assert hits[0]["id"] == o["handbook"] and hits[0]["page"] == 12, q
        assert "<mark>16hb</mark>" in hits[0]["snippet"]
    assert (await find(client, "1500.50 kg"))["hits"][0]["page"] == 27

    # Quoted phrases, prefixes, part of a word, typos, a job title in a form.
    res = await find(client, '"Load System Calculation"')
    assert res["hits"][0]["page"] == 27
    assert res["hits"][0]["heading"] == "<mark>LOAD SYSTEM CALCULATION</mark>"
    assert "The <mark>load system calculation</mark> for" in res["hits"][0]["snippet"]
    assert not (await find(client, '"calculation system load"'))["hits"]
    assert (await find(client, "kelaya"))["hits"][0]["page"] == 23
    assert (await find(client, "layak"))["hits"][0]["page"] == 23  # the root of "kelayakan"
    typo = await find(client, "kelayakkan advance")
    assert "kelayakan" in typo["corrected"]
    assert set(ids(typo)[:2]) == {o["handbook"], o["guide_b"]}
    res = await find(client, "Pegawai Kewangan")
    assert res["hits"][0]["id"] == o["form"] and res["hits"][0]["page"] == 1
    assert (await find(client, "Borang Tuntutan"))["hits"][0]["id"] == o["form"]  # by title

    # Documents (by their values) and templates.
    res = await find(client, "12,345.60")
    assert res["hits"][0]["id"] == o["doc"] and res["hits"][0]["url"] == f"/documents?d={o['doc']}"
    assert (await find(client, "Pelanggan Contoh"))["hits"][0]["type"] == "document"
    res = await find(client, "offer letter")
    assert res["hits"][0]["type"] == "template" and res["hits"][0]["id"] == o["tpl"]

    # Filters and pages of results.
    only = await find(client, "advance", type="sop")
    assert {h["type"] for h in only["hits"]} == {"sop"}
    assert ids(await find(client, "advance", branch_id=o["b"], type="file")) == [o["guide_b"]]
    assert ids(await find(client, "advance", kind="policy")) == [o["guide_b"]]
    first = await find(client, "pekerja", limit=1)
    assert first["next_cursor"] and first["total"] >= 2
    second = await find(client, "pekerja", limit=1, cursor=first["next_cursor"])
    where = [(h["id"], h["page"]) for h in first["hits"] + second["hits"]]
    assert len(set(where)) == 2  # the next hit (another page of the handbook, or another file)
    bad = await client.get("/api/search", params={"q": "x", "cursor": "zzz"})
    assert bad.status_code == 400 and bad.json()["code"] == "bad_cursor"


async def test_agents_search_documents_with_citations_never_held_back(client):
    from agentic.agents.search_tools import _search_documents
    from agentic.agents.tools import TOOLS, ToolContext, mode_of

    o = await office_docs(client)
    assert (
        TOOLS["search_documents"].default_mode == "allow"
        and TOOLS["search_documents"].risk == "low"
    )
    assert mode_of({"search_library": "deny"}, "search_documents") == "deny"
    async with SessionLocal() as db:
        a = Agent(
            workspace_id=o["ws"],
            branch_id=o["a"],
            department_id=None,
            slug="aina",
            name="Aina",
            role="Clerk",
        )
        db.add(a)
        await db.commit()
        ws = await db.get(Workspace, o["ws"])
        ctx = ToolContext(db=db, agent=a, workspace=ws, task=None)  # type: ignore[arg-type]
        out = await _search_documents(ctx, {"query": "kelayakan advance"})
        assert out.startswith("Document search for 'kelayakan advance'")
        assert "[Buku Panduan Pekerja p.23]" in out
        assert f"read_file file_id='{o['handbook']}' pages='23'" in out
        assert "<<<" in out and "<mark>" not in out
        assert "Lain Jaya" not in out  # the other company
        held = await _search_documents(ctx, {"query": "Zebra kata laluan"})
        assert held.startswith("No document matches") and "Senarai Kata Laluan" not in held
        assert "SOP Draf" not in await _search_documents(ctx, {"query": "pembelian stor"})
        none = await _search_documents(ctx, {"query": "zzzqqq"})
        assert none.startswith("No document matches")
        res = await engine.search(db, for_agent(a), "advance")
        assert o["guide_b"] not in ids({"hits": [h.__dict__ for h in res.hits]})


async def test_agents_stop_searching_after_their_budget(client, monkeypatch):
    """Found live: an agent searched 58 times in one step. Past the budget the search tools
    tell it to conclude and ask a person, instead of searching again."""
    from agentic.agents import runtime, search_tools
    from agentic.agents.library_tools import _search_library
    from agentic.agents.tools import ToolContext
    from agentic.models import Task

    monkeypatch.setattr(search_tools, "SEARCH_BUDGET", 2)
    o = await office_docs(client)
    async with SessionLocal() as db:
        a = Agent(workspace_id=o["ws"], branch_id=o["a"], slug="aina", name="Aina", role="Clerk")
        db.add(a)
        await db.flush()
        t = Task(
            workspace_id=o["ws"],
            title="Check records",
            assignee_agent_id=a.id,
            branch_id=o["a"],
            created_by="test",
            status="running",
        )
        db.add(t)
        await db.commit()
        ws = await db.get(Workspace, o["ws"])
        ctx = ToolContext(db=db, agent=a, workspace=ws, task=t)  # type: ignore[arg-type]
        for _ in range(2):
            out = await search_tools._search_documents(ctx, {"query": "kelayakan advance"})
            assert out.startswith("Document search for")
            runtime._add(db, a, "tool", task_id=t.id, content=out, name="search_documents")
            await db.flush()
        stop = await search_tools._search_documents(ctx, {"query": "kelayakan advance"})
        assert stop.startswith("Stop searching") and "ask_human" in stop
        assert (await _search_library(ctx, {"query": "advance"})).startswith("Stop searching")


# ---------------------------------------------------------------- suggestions


def test_reference_codes_complete_whole_ignoring_case():
    codes = ["PO-2026-0001", "PO-2026-0002", "TN1234567890", "EMP-1042"]
    v = vocab.Vocab([], [], sorted((c.casefold(), c) for c in codes))
    assert v.complete_code("po-2026", 5) == ["PO-2026-0001", "PO-2026-0002"]
    assert v.complete_code("tn12") == ["TN1234567890"]
    assert v.complete_code("EMP-") == ["EMP-1042"]
    assert v.complete_code("EMP-1042") == []  # already whole
    assert v.complete_code("kelaya") == []  # a word, not a code


SYLLABLES = (
    "ba bi bu ka ki ku la li lu ma mi mu na ni nu pa pi pu ra ri ru sa si su ta ti tu".split()
)


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 4)))


async def test_suggest_stays_fast_on_two_thousand_passages(client):
    o = await office_docs(client)
    rng = random.Random(7)  # noqa: S311 - made-up words, not secrets
    lexicon = [_word(rng) for _ in range(3000)]
    for n in range(20):
        sections = []
        for s in range(100):
            sections.append(f"[page {s + 1}]")
            sections.append(f"## Bahagian {n}.{s} {rng.choice(lexicon).title()}")
            sections.append(
                " ".join(rng.choice(lexicon) for _ in range(90)) + f" RM{rng.randint(100, 9999)}."
            )
        await add_file(
            o["ws"],
            o["owner"],
            title=f"Manual Operasi {n}",
            body="\n\n".join(sections),
            branch_id=o["a"],
        )
    t0 = time.perf_counter()
    async with SessionLocal() as db:
        await index.reindex_workspace(db, o["ws"])
        n_passages = await db.scalar(select(text("count(*)")).select_from(SearchPassage))
    t_index = time.perf_counter() - t0
    assert n_passages >= 2000

    t0 = time.perf_counter()
    await client.get("/api/search/suggest", params={"q": ""})
    await vocab.drain()
    t_vocab = time.perf_counter() - t0

    times = []
    for prefix in ("ba", "kala", "mu", "pira", "manual op", "bahagian 3", "sutu", "rika"):
        t0 = time.perf_counter()
        r = await client.get("/api/search/suggest", params={"q": prefix})
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200 and r.json()["suggestions"], prefix
    t0 = time.perf_counter()
    res = await find(client, lexicon[5])
    t_search = (time.perf_counter() - t0) * 1000
    assert res["hits"]
    print(
        f"\n{n_passages} passages: index {t_index:.1f}s, vocabulary {t_vocab * 1000:.0f} ms, "
        f"suggest median {statistics.median(times):.0f} ms (max {max(times):.0f}), "
        f"search {t_search:.0f} ms"
    )
    assert statistics.median(times) < 150
    assert t_search < 3000


async def test_made_by_filter_follows_provenance(client):
    o = await office_docs(client)
    async with SessionLocal() as db:
        ai = Document(
            workspace_id=o["ws"],
            branch_id=o["a"],
            title="Sebut Harga Kawalan Sekolah",
            body="Sebut harga kawalan untuk {{client}}.",
            values={"client": "Sekolah Contoh"},
            created_by="agent:test",
            origin="agent",
        )
        db.add(ai)
        await db.commit()
        await index.reindex_workspace(db, o["ws"])
    every = ids(await find(client, "sebut harga"))
    assert {o["doc"], ai.id} <= set(every)
    assert ids(await find(client, "sebut harga", source="agent")) == [ai.id]
    assert ids(await find(client, "sebut harga", source="person")) == [o["doc"]]
    assert ids(await find(client, "sebut harga", source="upload")) == []
    assert o["handbook"] in ids(await find(client, "kelayakan advance", source="upload"))
    assert ids(await find(client, "kelayakan advance", source="agent")) == []

