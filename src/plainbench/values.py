"""Find the checkable values in a letter, normalized so different spellings compare equal.

Kinds: money ("$1,287.40", "$6 million"), date ("March 14, 2025", "3/14/2025",
"June 1st"), duration ("30 days", "thirty (30) days", "one year"), phone
("1-800-827-1000", "(800) 827-1000"), code (form and notice numbers:
"VA Form 21-4138", "CMS-R-131", "CP14"), url/email, percent, and any other number
(digits or words). Money normalization follows the council digest's verify.py,
so "$6 million" equals "$6,000,000".

Code uses these two ways:
- a fact whose answer carries a value (a deadline, an amount, a phone number)
  can't be "kept" by a rewrite that doesn't contain that value;
- a value in a rewrite that isn't anywhere in the source is reported as
  "not in source" (not "invented": an added phone number may well be right).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import flat

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
ONES = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
     "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"])}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9}
UNITS = {"day": "day", "days": "day", "business day": "business day", "business days": "business day",
         "calendar day": "day", "calendar days": "day", "week": "week", "weeks": "week", "month": "month",
         "months": "month", "year": "year", "years": "year", "hour": "hour", "hours": "hour"}

MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
NUMWORD = r"(?:" + "|".join(sorted(list(TENS) + list(ONES), key=len, reverse=True)) + r")(?:[- ](?:" + "|".join(
    k for k in ONES if ONES[k] and ONES[k] < 10) + r"))?"

PATTERNS = [
    ("url", re.compile(r"\b(?:https?://|www\.)[^\s)>\]]+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("money", re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)(?:\s*(thousand|million|billion)\b)?")),
    ("phone", re.compile(r"(?<![\d-])(?:1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?![\d-])")),
    ("date", re.compile(rf"\b{MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b"
                        rf"|\b(\d{{1,2}})\s+{MON}\s+(\d{{4}})\b"
                        r"|\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b|\b(\d{4})-(\d{2})-(\d{2})\b", re.I)),
    ("code", re.compile(r"\b(?:form|publication|pub\.|notice|letter)\s+([A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*)"
                        r"|\b([A-Z]{2,5}-[A-Z0-9]{1,4}(?:-[A-Z0-9]{1,5})?)\b|\b((?:CP|LT|LTR)\s?\d{1,4}[A-Z]?)\b", re.I)),
    ("duration", re.compile(rf"\b(\d{{1,4}}|{NUMWORD})(?:\s*\(\d{{1,4}}\))?[- ](business days?|calendar days?|days?|weeks?|months?|years?|hours?)\b", re.I)),
    ("percent", re.compile(r"\b(\d+(?:\.\d+)?)\s?(?:%|percent\b)")),
    ("number", re.compile(rf"(?<![\w$.,/-])(\d[\d,]*(?:\.\d+)?)(?![\w/-])|\b({NUMWORD})\b(?!\s*\(\d)", re.I)),
]


@dataclass(frozen=True)
class Value:
    kind: str
    value: str
    start: int
    end: int


def word_number(w: str) -> int | None:
    parts = re.split(r"[- ]", w.lower())
    total = 0
    for p in parts:
        if p in TENS:
            total += TENS[p]
        elif p in ONES:
            total += ONES[p]
        else:
            return None
    return total


def _num(s: str) -> float | None:
    s = s.strip().lower()
    if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", s):
        return float(s.replace(",", ""))
    n = word_number(s)
    return float(n) if n is not None else None


def _fmt(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:.2f}".rstrip("0").rstrip(".")


def _date(m: re.Match) -> str | None:
    t = m.group(0).lower()
    g = m.groups()
    if g[0] is not None:  # Month day[, year]
        mon = MONTHS.get(re.match(r"[a-z]+", t).group())
        day, year = int(g[0]), g[1]
    elif g[2] is not None:  # day Month year
        day, year = int(g[2]), g[3]
        mon = MONTHS.get(re.search(r"[a-z]+", t).group())
    elif g[4] is not None:  # m/d/y
        mon, day, year = int(g[4]), int(g[5]), g[6]
        if len(year) == 2:
            year = "20" + year
    else:  # yyyy-mm-dd
        year, mon, day = g[7], int(g[8]), int(g[9])
    if not mon or not 1 <= mon <= 12 or not 1 <= day <= 31:
        return None
    return f"{year + '-' if year else ''}{mon:02d}-{day:02d}"


def extract(text: str) -> list[Value]:
    """Values in reading order; each character belongs to at most one value, earlier
    kinds in PATTERNS winning (a phone number's digits aren't also numbers)."""
    taken = [False] * len(text)
    out: list[Value] = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            a, b = m.span()
            if any(taken[a:b]):
                continue
            v = _value(kind, m)
            if v is None:
                continue
            out.append(Value(kind, v, a, b))
            for i in range(a, b):
                taken[i] = True
    return sorted(out, key=lambda v: v.start)


def _value(kind: str, m: re.Match) -> str | None:
    if kind == "url":
        return m.group(0).lower().rstrip(".,;").removeprefix("https://").removeprefix("http://").removeprefix("www.")
    if kind == "money":
        return _fmt(round(float(m.group(1).replace(",", "")) * SCALE.get((m.group(2) or "").lower(), 1), 2))
    if kind == "phone":
        d = re.sub(r"\D", "", m.group(0))
        return d[-10:]
    if kind == "date":
        return _date(m)
    if kind == "code":
        c = next(g for g in m.groups() if g)
        return re.sub(r"\s+", "", c).upper()
    if kind == "duration":
        n = _num(m.group(1))
        unit = UNITS.get(m.group(2).lower())
        return None if n is None or unit is None else f"{_fmt(n)} {unit}"
    if kind == "percent":
        return _fmt(float(m.group(1)))
    if kind == "number":
        n = _num(m.group(1) or m.group(2))
        return None if n is None else _fmt(n)
    return None


def values(text: str) -> set[tuple[str, str]]:
    return {(v.kind, v.value) for v in extract(text)}


def _matches(kind: str, value: str, pool: set[tuple[str, str]]) -> bool:
    """Is (kind, value) in the pool, allowing a date without a year to match one with a
    year (and the reverse), and a bare number to match a duration or money amount with it?"""
    if (kind, value) in pool:
        return True
    if kind == "date":
        md = value[-5:]
        return any(k == "date" and v[-5:] == md for k, v in pool)
    if kind == "number":
        return any(k in ("duration", "money", "percent") and v.split(" ")[0] == value for k, v in pool)
    return False


def missing_from(text: str, needed: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """Which of the `needed` values aren't in `text`."""
    pool = values(text)
    return sorted(v for v in needed if not _matches(*v, pool))


def not_in_source(rewrite: str, source: str, ignore: tuple[str, ...] = ("number",)) -> list[Value]:
    """Values in the rewrite that the source doesn't have. Bare numbers are ignored by
    default: a rewrite numbers its steps ("1.", "2.") and lists items ("3 things")."""
    pool = values(source)
    return [v for v in extract(rewrite) if v.kind not in ignore and not _matches(v.kind, v.value, pool)]


def same_text(a: str, b: str) -> bool:
    return flat(a) == flat(b)
