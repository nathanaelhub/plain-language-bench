"""The rewrite tool: list what the letter tells its reader, rewrite it, then check each item survived.

1. Extract: the model lists every deadline, amount, action, consequence, right,
   condition and contact, each with an exact quote; code drops any item whose
   quote isn't in the letter.
2. Rewrite at the target grade, with the list as a checklist.
3. Check: for each item, the model points to where the rewrite says it (or
   says it doesn't), and code checks the pointer is real and that dates,
   amounts and phone numbers are actually there.
4. Revise once if anything was lost, then check again.
5. Report every item as kept, changed or missing.

These prompts are deliberately different from the benchmark's judge, and the
tool works from its own extracted list, not the benchmark's answer key, so the
benchmark isn't grading the tool with its own checker.

With `redact=True`, Social Security, claim and case numbers and street
addresses are swapped for tokens like [SSN-1] before anything is sent, and
put back afterwards.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import llm
from .facts import Fact
from .readability import measure
from .text import contains, find
from .values import missing_from, not_in_source

EXTRACT = """List everything a reader of this letter needs to know or do: every deadline or date that
applies to them, amount of money, action they must or can take, consequence for them, right they
have, condition or exception on any of those, and way to contact the sender.

One item per fact, small enough to be kept or lost on its own; a condition ("only if", "unless")
is its own item. For each, copy an exact quote from the letter that states it.

Reply with JSON only: {"items": [{"id": "1", "type": "deadline|amount|action|consequence|right|condition|contact|subject",
"fact": "the fact in plain words", "answer": "the key value or detail", "quote": "exact words from the letter"}]}"""

REWRITE = """Rewrite this letter in plain language so that someone who reads at a {grade}th-grade level
can understand it. Use short sentences, everyday words, and headings or lists where they help.

The reader must still learn every item on the checklist below, with the same dates, amounts, phone
numbers and conditions. Don't add facts the letter doesn't contain.

Put the rewritten letter between <letter> and </letter>.

Checklist:
{checklist}

<original>
{letter}
</original>"""

LOCATE = """For each numbered item from an original letter, find where the REWRITTEN letter tells the
reader that item. Report:
- "found" and the exact words from the rewrite, if it says the item with the same meaning, values
  and conditions;
- "partly" and the exact words, if it says only part of it, or with a different or vaguer value,
  or without its condition;
- "not found", if it doesn't say it.

Reply with JSON only: {"items": [{"id": "1", "result": "found|partly|not found", "where": "exact words from the rewrite"}]}"""

REVISE = """This plain-language rewrite lost some things the original letter told its reader. Revise it
so the reader learns each item below, with its exact dates, amounts, phone numbers and conditions,
keeping the rest of the rewrite and its reading level. Put the revised letter between <letter> and </letter>.

Items to put back:
{missing}

<rewrite>
{rewrite}
</rewrite>"""

SYSTEM = "You help nonprofit staff rewrite official letters in plain language without losing anything the reader needs."
EFFORT = "medium"
STATUS = {"found": "kept", "partly": "changed", "not found": "missing"}


# ---- redaction ----------------------------------------------------------------

REDACT = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CASE", re.compile(r"\b(?:claim|case|file|account|reference)\s+(?:number|no\.?|#)\s*:?\s*([A-Z0-9-]{5,})", re.I)),
    ("ADDRESS", re.compile(r"\b\d{1,6}\s+(?:[A-Z][a-z]+\.?\s){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|Boulevard|Blvd|Way|Pike|Place|Pl|Circle|Cir|Run)\b\.?")),
]


def redact(text: str) -> tuple[str, dict[str, str]]:
    """Swap identifiers for tokens; return the redacted text and token -> original."""
    mapping: dict[str, str] = {}
    counts: dict[str, int] = {}

    def sub(kind):
        def repl(m):
            original = m.group(0)
            for tok, orig in mapping.items():
                if orig == original:
                    return tok
            counts[kind] = counts.get(kind, 0) + 1
            tok = f"[{kind}-{counts[kind]}]"
            mapping[tok] = original
            return tok
        return repl

    for kind, rx in REDACT:
        text = rx.sub(sub(kind), text)
    return text, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    for tok, orig in mapping.items():
        text = text.replace(tok, orig)
    return text


# ---- steps ----------------------------------------------------------------------

@dataclass
class Item:
    id: str
    type: str
    fact: str
    answer: str
    quote: str
    status: str = "unchecked"  # kept | changed | missing
    where: str = ""
    code: list[str] = field(default_factory=list)

    def as_fact(self) -> Fact:
        return Fact(self.id, self.type if self.type in {"deadline", "amount", "contact"} else "action",
                    self.fact, "", self.answer, self.quote, True)


@dataclass
class Result:
    rewrite: str | None
    items: list[Item]
    dropped: list[dict]  # extracted items whose quote wasn't in the letter
    grade_before: float | None
    grade_after: float | None
    revised: bool
    not_in_source: list[str]
    cost_usd: float
    error: str | None = None

    @property
    def lost(self) -> list[Item]:
        return [i for i in self.items if i.status != "kept"]


async def extract(letter: str, model: str) -> tuple[list[Item], list[dict], float]:
    r = await llm.call(f"<letter>\n{letter}\n</letter>", EXTRACT, model=model, effort=EFFORT)
    d = llm.json_block(r.text) if not r.error else None
    items, dropped = [], []
    for x in (d or {}).get("items", []) if isinstance(d, dict) else []:
        if not isinstance(x, dict):
            continue
        it = Item(str(x.get("id", len(items) + 1)), str(x.get("type", "")), str(x.get("fact", "")),
                  str(x.get("answer", "")), str(x.get("quote", "")))
        if it.quote and find(it.quote, letter):
            items.append(it)
        else:
            dropped.append(asdict(it))
    return items, dropped, r.cost_usd


async def locate(items: list[Item], rewrite: str, model: str) -> float:
    listing = "\n".join(f"{i.id}. {i.fact} (original: \"{i.quote}\")" for i in items)
    r = await llm.call(f"<rewrite>\n{rewrite}\n</rewrite>\n\nItems:\n{listing}", LOCATE, model=model, effort=EFFORT)
    d = llm.json_block(r.text) if not r.error else None
    got = {str(x.get("id")): x for x in (d or {}).get("items", []) if isinstance(x, dict)} if isinstance(d, dict) else {}
    for it in items:
        x = got.get(it.id, {})
        it.status = STATUS.get(str(x.get("result", "")).lower(), "missing")
        it.where = str(x.get("where") or "")
        it.code = []
        if it.status != "missing" and it.where and not contains(rewrite, it.where):
            it.code.append("the quoted words aren't in the rewrite")
        lost = missing_from(rewrite, it.as_fact().needed_values())
        if lost:
            it.code.append(f"value not in the rewrite: {lost}")
            if it.status == "kept":
                it.status = "changed"
    return r.cost_usd


async def run(letter: str, model: str = "sonnet", grade: int = 6, use_redact: bool = False) -> Result:
    text, mapping = redact(letter) if use_redact else (letter, {})
    cost = 0.0
    items, dropped, c = await extract(text, model)
    cost += c
    if not items:
        return Result(None, [], dropped, measure(letter)["grade"], None, False, [], cost, "no items could be extracted")
    checklist = "\n".join(f"- {i.fact}" + (f" ({i.answer})" if i.answer else "") for i in items)
    r = await llm.call(REWRITE.format(grade=grade, checklist=checklist, letter=text), SYSTEM, model=model, effort=EFFORT)
    cost += r.cost_usd
    rewrite = llm.tagged(r.text, "letter") if not r.error else None
    if not rewrite:
        return Result(None, items, dropped, measure(letter)["grade"], None, False, [], cost, r.error or "no <letter> tags")
    cost += await locate(items, rewrite, model)
    revised = False
    lost = [i for i in items if i.status != "kept"]
    if lost:
        missing = "\n".join(f'- {i.fact} (original: "{i.quote}")' for i in lost)
        r = await llm.call(REVISE.format(missing=missing, rewrite=rewrite), SYSTEM, model=model, effort=EFFORT)
        cost += r.cost_usd
        second = llm.tagged(r.text, "letter") if not r.error else None
        if second:
            rewrite, revised = second, True
            cost += await locate(items, rewrite, model)
    final = restore(rewrite, mapping)
    for it in items:
        it.quote, it.where = restore(it.quote, mapping), restore(it.where, mapping)
    extra = [f"{v.kind} {final[v.start:v.end]!r}" for v in not_in_source(final, letter)]
    return Result(final, items, dropped, measure(letter)["grade"], measure(final)["grade"], revised, extra, cost)


async def check(letter: str, rewrite: str, model: str = "sonnet", use_redact: bool = False) -> Result:
    """Check a rewrite someone already wrote: extract the letter's items, then locate each."""
    text, mapping = redact(letter) if use_redact else (letter, {})
    rw = redact(rewrite)[0] if use_redact else rewrite
    items, dropped, cost = await extract(text, model)
    if not items:
        return Result(rewrite, [], dropped, measure(letter)["grade"], measure(rewrite)["grade"], False, [], cost,
                      "no items could be extracted")
    cost += await locate(items, rw, model)
    for it in items:
        it.quote, it.where = restore(it.quote, mapping), restore(it.where, mapping)
    extra = [f"{v.kind} {rewrite[v.start:v.end]!r}" for v in not_in_source(rewrite, letter)]
    return Result(rewrite, items, dropped, measure(letter)["grade"], measure(rewrite)["grade"], False, extra, cost)


# ---- report -----------------------------------------------------------------------

DETECTION_NOTE = ("These checks are measured in the plain-language-bench evaluation; see its README for how "
                  "many planted losses they catch. A clean checklist means no losses were found, not that "
                  "nothing was lost: read the rewrite against the letter before sending it.")


def markdown(res: Result) -> str:
    if res.error:
        return f"# Rewrite failed\n\n{res.error}\n"
    rows = "\n".join(f"| {'✅' if i.status == 'kept' else '⚠️' if i.status == 'changed' else '❌'} {i.status} | {i.type} | "
                     f"{i.fact} | {i.where.replace('|', '/')[:120]} |" for i in res.items)
    lost = len(res.lost)
    head = (f"**{lost} item{'s' if lost != 1 else ''} may be lost or changed. Fix them before sending.**" if lost
            else "**No losses found by these checks.**")
    extra = ("\n\nIn the rewrite but not in the letter (check these are right): " + ", ".join(res.not_in_source)) if res.not_in_source else ""
    dropped = (f"\n\n{len(res.dropped)} extracted item(s) were set aside because their quote wasn't found in the letter."
               if res.dropped else "")
    return (f"# Plain-language rewrite\n\nReading grade: {res.grade_before} before, {res.grade_after} after"
            f"{' (revised once to put lost items back)' if res.revised else ''}.\n\n{head}{extra}{dropped}\n\n"
            f"## The rewrite\n\n{res.rewrite}\n\n## Checklist\n\n| Status | Type | What the letter says | Where the rewrite says it |\n"
            f"|---|---|---|---|\n{rows}\n\n{DETECTION_NOTE}\n")
