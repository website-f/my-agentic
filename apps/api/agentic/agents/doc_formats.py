"""My Agentic: the standard layout of common documents, for the AI to follow before drafting.

document_format(kind) returns the layout of one kind (the parts in order, the wording each part
usually takes, the closing) plus the house rules every document follows. The renderer prints
markdown (documents/render_pdf.py): **bold**, paragraphs, lists, tables, a line of underscores
for a signature; a letter's subject is a bold line, never a # heading.
"""

from typing import Any

from .tools import Tool, ToolContext

RULES = """House rules for every document:
- Use the template that fits (list_templates) before writing free-form: Resignation letter,
  Surat peletakan jawatan, Personal letter, Official letter, Surat rasmi, Quotation, Invoice...
- Never invent a fact (a name, a date, an amount, an address). Write [[What is needed]] where it
  is missing; the person fills it in.
- Template fields hold only their own part: a letter's "text" field is the paragraphs only, never
  a "Dear ..." line or a closing (the template already has them). No duplicate salutation.
- Dates written out: 25 November 2026 (Malay: 25 November 2026 / 25 Nov 2026). Money: RM 1,250.00.
- Plain, professional language; short paragraphs (2-4 sentences); one idea per paragraph.
- A letter's subject is one bold line in capitals or title case: **RESIGNATION FROM ...**.
- Leave room to sign: a line of underscores, then the name under it.
- A letter from the person (resignation, complaint, application) is a personal letter: their
  own name and address at the top, NOT the company letterhead or "Our ref"."""

FORMATS: dict[str, str] = {
    "resignation_letter": """Resignation letter (English). Use the template "Resignation letter".
1. Your name (bold), address, phone, email
2. Date
3. Recipient: name, position, company, address
4. Dear [Name],
5. Subject: **RESIGNATION FROM THE POSITION OF [POSITION]**
6. Notice: formal notice of resignation from [position] at [company]; notice period; last
   working day [date]
7. Optional: a short positive reason (one sentence), never complaints
8. Thanks for the opportunity and what you learned
9. Handover: you will complete/hand over [tasks] and help a smooth transition
10. Yours sincerely, / signature line / your name""",
    "surat_peletakan_jawatan": """Surat peletakan jawatan (Bahasa Melayu, format surat rasmi).
Gunakan templat "Surat peletakan jawatan".
1. Nama (tebal), alamat, telefon, e-mel pengirim
2. Penerima: nama, jawatan, syarikat, alamat
3. Tarikh: [tarikh]
4. Tuan/Puan,
5. Perkara (tebal, huruf besar): **PERLETAKAN JAWATAN SEBAGAI [JAWATAN]**
6. "Dengan segala hormatnya saya merujuk kepada perkara di atas." (tanpa nombor)
7. Perenggan bernombor bermula 2.: notis, tempoh notis, hari terakhir; 3.: serahan tugas;
   4.: penghargaan
8. Sekian, terima kasih. / Yang benar, / garisan tandatangan / (Nama)""",
    "personal_letter": """Formal personal letter (request, complaint, appeal, application, notice).
Use the template "Personal letter".
1. Your details  2. Date  3. Recipient block  4. Dear [Name], (or Dear Sir/Madam, when unknown)
5. Bold subject  6. Opening: why you write (one sentence)  7. Details: facts, dates, reference
numbers  8. What you ask for, and by when  9. Thanks  10. Yours sincerely, (Yours faithfully,
after Dear Sir/Madam) / signature / name""",
    "complaint_letter": """Complaint letter: personal letter layout. Subject: **COMPLAINT
REGARDING [ITEM/SERVICE], [REFERENCE]**. Paragraphs: what happened (date, place, reference),
the impact, what you already did, the remedy you want and a deadline, attachments listed
("Enclosed: copy of receipt"). Firm and polite, no insults.""",
    "job_application": """Job application / cover letter: personal letter layout. Subject:
**APPLICATION FOR THE POSITION OF [POSITION]** (+ reference). Paragraphs: the role and where you
saw it; why you fit (2-3 achievements with numbers); why this company; availability and
"Enclosed: CV". Close asking for an interview.""",
    "official_letter": """Company letter (on the letterhead). Use "Official letter" / "Surat rasmi".
Our ref / Your ref / Date; recipient block; Attention: [name]; Dear Sir/Madam (or name); bold
subject; numbered or short paragraphs; Thank you.; Yours faithfully, (sincerely when named);
signature; signatory name, position, company.""",
    "surat_rasmi": """Surat rasmi syarikat (BM): Rujukan kami / Rujukan tuan / Tarikh; penerima;
"Tuan/Puan,"; PERKARA tebal huruf besar; "Dengan hormatnya perkara di atas adalah dirujuk.";
perenggan bernombor dari 2.; "Sekian, terima kasih."; (cogan kata jika ada); "Saya yang
menjalankan amanah," / "Yang benar,"; tandatangan; nama, jawatan, syarikat; s.k. (salinan
kepada) jika perlu.""",
    "offer_letter": """Offer of employment (company letterhead): date, candidate address,
**OFFER OF EMPLOYMENT - [POSITION]**, then numbered terms: position and reporting line;
commencement date; probation; salary and allowances (RM, monthly); working hours and place;
leave; benefits (EPF, SOCSO, EIS, medical); notice period; confidentiality; acceptance by
[date]. Signature of the company, then an acceptance block for the candidate (name, IC,
signature, date).""",
    "warning_letter": """Warning / show-cause letter (company letterhead): Private &
Confidential; date; employee name, ID, position, department; **SHOW CAUSE / FIRST WRITTEN
WARNING - [MATTER]**; the facts (dates, what happened, the rule or policy breached); earlier
warnings; what is expected; for show-cause: reply in writing within [7] days; consequences;
signature; acknowledgement block for the employee.""",
    "recommendation_letter": """Recommendation / reference letter: letterhead or personal; TO
WHOM IT MAY CONCERN (or named); **LETTER OF RECOMMENDATION - [NAME]**; how you know them and
for how long; their role and 2-3 strengths with examples; recommendation sentence; contact for
follow-up; signature, name, position.""",
    "memo": """Internal memo: **MEMO** title; To: / From: / Date: / Subject: lines; a rule; purpose
(one paragraph), details (bullets), action required and deadline; no salutation or signature
line (initials optional).""",
    "notice": """Notice / announcement: bold title (NOTICE: ...); date; who it is for; what,
when, where; what people must do; contact person; issued by (name, position).""",
    "leave_application": """Leave application: personal letter layout to the manager/HR; subject
**APPLICATION FOR [ANNUAL/MEDICAL/EMERGENCY] LEAVE**; dates (from-to, number of days); reason
(brief); who covers the work; contact while away; thanks.""",
    "minutes": """Meeting minutes: use the template "Meeting minutes". Title, date, time, venue;
attendees, absent with apologies; agenda; per item: discussion summary, decision, action
(who, by when) in a table; next meeting; prepared by / confirmed by.""",
    "quotation": """Quotation: use the template "Quotation" (company details, quote number, date,
validity, client block, item table with qty/unit price/amount, subtotal, tax, total, amount in
words, terms: payment, delivery, validity; signature).""",
    "invoice": """Invoice: use the template "Invoice" (invoice number, date, due date, bill-to,
items table, subtotal, tax, total, amount in words, bank details, payment terms).""",
    "proposal": """Proposal: use the template "Proposal". Cover (title, client, date); executive
summary; background / needs; proposed solution; scope and deliverables; timeline (table); team;
pricing (table); terms; next steps; contact.""",
    "report": """Report: title and date; executive summary (5 lines); background / objective;
method; findings (headings, bullets, tables); conclusions; recommendations (numbered, with
owner and timing); appendices.""",
    "agreement": """Agreement / MoU: title (AGREEMENT / MEMORANDUM OF UNDERSTANDING); date; parties
(names, registration numbers, addresses: "Party A" / "Party B"); recitals (WHEREAS ...);
numbered clauses: definitions, scope, term, payment, obligations of each party,
confidentiality, termination, liability, governing law (Malaysia), notices, entire agreement;
signature blocks for both parties with witness lines. Mark it a draft for legal review.""",
    "cv": """CV / resume: name (large, bold) and contact line; profile (3 lines); experience
(newest first: position, company, dates, 3-5 achievement bullets with numbers); education;
skills; certifications; languages; references available on request.""",
}

ALIASES = {
    "resignation": "resignation_letter",
    "letter of resignation": "resignation_letter",
    "surat letak jawatan": "surat_peletakan_jawatan",
    "peletakan jawatan": "surat_peletakan_jawatan",
    "cover letter": "job_application",
    "application letter": "job_application",
    "show cause": "warning_letter",
    "warning": "warning_letter",
    "reference letter": "recommendation_letter",
    "mou": "agreement",
    "contract": "agreement",
    "resume": "cv",
    "meeting minutes": "minutes",
    "letter": "personal_letter",
    "complaint": "complaint_letter",
    "leave": "leave_application",
    "announcement": "notice",
    "company letter": "official_letter",
}


def find(kind: str) -> str | None:
    k = " ".join((kind or "").lower().replace("_", " ").replace("-", " ").split())
    if not k:
        return None
    key = k.replace(" ", "_")
    if key in FORMATS:
        return key
    if k in ALIASES:
        return ALIASES[k]
    for alias, target in ALIASES.items():
        if alias in k:
            return target
    for name in FORMATS:
        if name.replace("_", " ") in k:
            return name
    return None


async def _document_format(ctx: ToolContext, args: dict[str, Any]) -> str:
    kind = find(str(args.get("kind") or ""))
    if kind is None:
        names = ", ".join(sorted(FORMATS))
        return f"No layout for that kind. Known kinds: {names}.\n\n{RULES}"
    return f"Standard layout - {kind}:\n{FORMATS[kind]}\n\n{RULES}"


DOC_FORMAT_TOOLS = (
    Tool(
        "document_format",
        "Standard document layout",
        "BEFORE drafting any letter or document, get its standard layout and the house rules: "
        "kind = resignation_letter, surat_peletakan_jawatan, personal_letter, complaint_letter, "
        "job_application, official_letter, surat_rasmi, offer_letter, warning_letter, "
        "recommendation_letter, memo, notice, leave_application, minutes, quotation, invoice, "
        "proposal, report, agreement, cv (or describe it). Then draft_document following it.",
        {
            "type": "object",
            "properties": {"kind": {"type": "string", "description": "The kind of document"}},
            "required": ["kind"],
        },
        "low",
        "allow",
        _document_format,
    ),
)
