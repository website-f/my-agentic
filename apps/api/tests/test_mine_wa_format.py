"""My Agentic: AI answers in WhatsApp's own formatting, and long ones in parts."""

from agentic.channels.wa_format import parts, to_whatsapp

REPORT = """# Outing BBQ — 19 Disember 2026

## Bottom line
Tarikh 19 Disember **boleh diteruskan**, tapi *kena* ada plan B.

---

## Top options
- **Taman Eko Rimba Templer** — ada kawasan BBQ [10]
  - Kos: ~~RM200~~ RM150
* Sojuk Riverside, see [their page](https://sojuk.example.com/bbq)
1) Tempah awal

| Venue | Kos |
|---|---|
| ASAP & Soul | RM50 |

```
code stays **as is**
```
"""


def test_markdown_becomes_whatsapp_formatting():
    out = to_whatsapp(REPORT)
    lines = out.splitlines()
    assert lines[0] == "*Outing BBQ — 19 Disember 2026*"  # a heading is a bold line
    assert "*Bottom line*" in lines and "#" not in out.replace("```", "")
    assert "Tarikh 19 Disember *boleh diteruskan*, tapi _kena_ ada plan B." in lines
    assert "---" not in out and "|---|" not in out  # dividers and table rules are gone
    assert "• *Taman Eko Rimba Templer* — ada kawasan BBQ [10]" in lines
    assert "  • Kos: ~RM200~ RM150" in lines
    assert "• Sojuk Riverside, see their page: https://sojuk.example.com/bbq" in lines
    assert "1. Tempah awal" in lines
    assert "• ASAP & Soul - RM50" in lines  # a table row reads as a line
    assert "```\ncode stays **as is**\n```" in out  # code is left alone
    assert "**" not in out.replace("code stays **as is**", "")


def test_whatsapp_text_and_names_stay_as_they_are():
    assert to_whatsapp("Hai! Jumpa *esok* jam 3.") == "Hai! Jumpa _esok_ jam 3."
    assert to_whatsapp("5 * 3 = 15 and a*b") == "5 * 3 = 15 and a*b"  # arithmetic is not italic
    assert to_whatsapp("") == ""


def test_a_long_answer_goes_in_numbered_parts():
    para = "Ayat panjang tentang tempat BBQ. " * 40  # ~1300 characters
    text = "\n\n".join([para] * 6)
    got = parts(text)
    assert len(got) >= 2 and all(len(p) <= 3600 for p in got)
    assert got[0].endswith(f"(1/{len(got)})") and got[-1].endswith(f"({len(got)}/{len(got)})")
    assert parts("short") == ["short"]
