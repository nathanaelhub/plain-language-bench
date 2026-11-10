"""Text normalization that remembers where each character came from, and sentence splitting.

A quote a model gives back ("you must reply within 30 days") rarely matches
the letter byte for byte: curly quotes, dashes, markdown bold, a line break in
the middle. `find` compares normalized forms but returns the span in the
ORIGINAL text, so the site can highlight exactly where a fact sits.
"""

from __future__ import annotations

import re
import unicodedata

SUBS = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‑": "-", " ": " "}
DROP = set("*_#|`>")  # markdown that changes how text looks, not what it says
ABBREV = {"dr", "mr", "mrs", "ms", "st", "no", "nos", "e.g", "i.e", "u.s", "u.s.c", "c.f.r", "inc", "co", "jr",
          "sr", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "etc", "vs",
          "p.o", "ft", "a.m", "p.m", "approx", "dept", "sec", "ph.d", "fig", "rev"}


def norm(s: str, lower: bool = True) -> tuple[str, list[int]]:
    """(normalized text, index in `s` of each normalized character). Whitespace runs
    become one space, markdown emphasis disappears, quotes and dashes go straight."""
    out: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(s or ""):
        ch = SUBS.get(ch, ch)
        ch = unicodedata.normalize("NFKC", ch)
        if ch in DROP:
            continue
        for c in ch:
            if c.isspace():
                if out and out[-1] == " ":
                    continue
                c = " "
            out.append(c.lower() if lower else c)
            where.append(i)
    # trim a leading/trailing space
    while out and out[0] == " ":
        out.pop(0)
        where.pop(0)
    while out and out[-1] == " ":
        out.pop()
        where.pop()
    return "".join(out), where


def flat(s: str) -> str:
    return norm(s)[0]


def find(needle: str, hay: str, start: int = 0) -> tuple[int, int] | None:
    """Span (start, end) in the original `hay` of the first match of `needle` at or after
    original index `start`, comparing normalized forms; None if it isn't there."""
    n = flat(needle)
    if not n:
        return None
    h, where = norm(hay)
    from_ = next((k for k, w in enumerate(where) if w >= start), len(h))
    k = h.find(n, from_)
    if k < 0:
        return None
    return where[k], where[k + len(n) - 1] + 1


def contains(hay: str, needle: str) -> bool:
    return find(needle, hay) is not None


LIST = re.compile(r"\s*(#|[-*•]\s|\d{1,2}[.)]\s|[a-z][.)]\s)")


def sentences(text: str) -> list[tuple[int, int]]:
    """Spans of sentences. Headings, list items and other standalone lines are their own
    units; consecutive ordinary lines form a paragraph, which is split after . ! ? when
    a space and a capital letter or digit follow, except after common abbreviations
    ("Dr.", "U.S.", "e.g.")."""
    lines, pos = [], 0
    for line in text.split("\n"):  # every line, blank ones included: a blank line ends a paragraph
        lines.append((pos, pos + len(line)))
        pos += len(line) + 1
    units: list[tuple[int, int]] = []
    para: tuple[int, int] | None = None
    for a, b in lines:
        line = text[a:b]
        if not line.strip():
            if para:
                units.append(para)
            para = None
        elif LIST.match(line):
            if para:
                units.append(para)
            para = None
            units.append((a, b))
        else:
            para = (para[0], b) if para else (a, b)
    if para:
        units.append(para)
    spans: list[tuple[int, int]] = []
    for a, b in units:
        if LIST.match(text[a:b]):
            spans.append((a, b))
            continue
        last = a
        for m in re.finditer(r"[.!?][\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])", text[a:b]):
            end = a + m.end()
            w = re.search(r"([A-Za-z.]+)[.!?][\"')\]]*\s+$", text[last:end])
            if w and w.group(1).lower().rstrip(".") in ABBREV:
                continue
            spans.append((last, end))
            last = end
        spans.append((last, b))
    return [(x, _rstrip(text, x, y)) for x, y in spans if text[x:y].strip()]


def _rstrip(text: str, a: int, b: int) -> int:
    while b > a and text[b - 1].isspace():
        b -= 1
    return b
