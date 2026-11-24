"""My Agentic: AI answers (Markdown) as WhatsApp text, and long ones in parts.

WhatsApp has its own small format: *bold*, _italic_, ~strike~, `code`, ```blocks```, "> "
quotes and "- " / "• " lists. It shows Markdown's "# Heading", "**bold**", tables and
[text](url) links as raw symbols, so `to_whatsapp` turns them into what WhatsApp shows well.
`parts` splits a long answer at paragraph breaks into numbered messages.
"""

import re

PART_CHARS = 3500  # one WhatsApp message stays readable well below its hard limit

_FENCE = re.compile(r"```.*?```", re.S)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[*+-]\s+(?=\S)")
_NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LINK = re.compile(r"!?\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")


def _inline(line: str) -> str:
    line = _LINK.sub(lambda m: f"{m.group(1)}: {m.group(2)}", line)
    line = _ITALIC.sub(r"_\1_", line)  # Markdown *italic* first, before **bold** becomes *bold*
    line = _BOLD.sub(r"*\2*", line)
    line = _STRIKE.sub(r"~\1~", line)
    return line


def _table_row(line: str) -> str:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return " - ".join(c for c in cells if c)


def to_whatsapp(text: str) -> str:
    """Markdown as WhatsApp formatting. Code blocks are left exactly as they are."""
    if not text:
        return text
    blocks: list[str] = []

    def keep(m: re.Match[str]) -> str:
        blocks.append(m.group(0))
        return f"\x00{len(blocks) - 1}\x00"

    text = _FENCE.sub(keep, text.replace("\r\n", "\n"))
    out: list[str] = []
    for line in text.split("\n"):
        if _RULE.match(line) or _TABLE_SEP.match(line):
            continue  # dividers and a table's |---| row show as noise
        h = _HEADING.match(line)
        if h:
            title = _BOLD.sub(r"\2", h.group(1)).strip("*_ ")
            if out and out[-1].strip():
                out.append("")
            out.append(f"*{title}*")
            continue
        if line.strip().startswith("|") and line.strip().endswith("|"):
            out.append("• " + _inline(_table_row(line)))
            continue
        b = _BULLET.match(line)
        if b:
            indent = "  " * (len(b.group(1)) // 2)
            out.append(indent + "• " + _inline(line[b.end() :]))
            continue
        n = _NUMBERED.match(line)
        if n:
            out.append(f"{'  ' * (len(n.group(1)) // 2)}{n.group(2)}. {_inline(line[n.end() :])}")
            continue
        out.append(_inline(line))
    joined = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return re.sub(r"\x00(\d+)\x00", lambda m: blocks[int(m.group(1))], joined)


def parts(text: str, limit: int = PART_CHARS) -> list[str]:
    """A long message as several, cut at paragraph breaks (else line breaks), numbered."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for para in text.split("\n\n"):
        piece = f"{cur}\n\n{para}" if cur else para
        if len(piece) <= limit:
            cur = piece
            continue
        if cur:
            chunks.append(cur)
        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            cut = cut if cut > limit // 2 else limit
            chunks.append(para[:cut].rstrip())
            para = para[cut:].lstrip("\n")
        cur = para
    if cur:
        chunks.append(cur)
    total = len(chunks)
    return [f"{c}\n\n({i}/{total})" for i, c in enumerate(chunks, 1)]
