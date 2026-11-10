"""Was each fact kept, changed or lost in a rewrite? A model judges, code checks the judge.

One call per rewrite lists the notice's facts in a fixed shuffled order. For
each, the judge answers kept / changed / missing with evidence quotes from the
rewrite. Then code checks every answer:

- a "kept" or "changed" verdict must quote the rewrite (normalized substring);
- a deadline, amount or contact fact can't be "kept" if its value (date,
  amount, phone number, ZIP, web address) isn't in the rewrite.

Facts the judge didn't call kept, and kept facts code disputes, go to one
confirmation call per rewrite that sees only those facts. Where code still
says a confirmed "kept" fact's value isn't in the rewrite, code wins and the
fact is "changed", recorded as overridden. A "kept" whose quote can't be found
is left as kept but marked unverified (a misquote isn't proof of a loss), and
those go into the human sample.

The judge never says how much a loss matters: which facts are critical was
fixed in the fact list before any rewrite existed.
"""

from __future__ import annotations

import random

from . import llm
from .facts import Fact, Notice
from .text import contains
from .values import missing_from

STATUSES = ("kept", "changed", "missing")
EFFORT = "medium"

SYSTEM = """You check whether a rewritten letter still tells its reader each fact from the original.

For each fact, decide from the REWRITE ALONE:
- "kept": someone who read only the rewrite would know this fact, with the same meaning, the same
  value (date, amount, phone number, address) and the same conditions. Plain words for the same
  thing are kept: "you won't have to pay for it" keeps "you'll avoid financial liability";
  "usually within two days" keeps "generally no later than two days"; "you can ask for it in large
  print" keeps "you have the right to get it in large print".
- "changed": the rewrite says something about it, but the reader would now know less or something
  different: a different value; a vaguer one ("soon" for a date, "call us" without the number); a
  dropped condition, exception or qualifier ("only if", "unless", "right away", "certified"); a
  "must" that became a "may", a "will" that became a "may" (certain became possible), or a "can"
  that became "can't"; a broader or narrower group or choice (one option of several dropped).
- "missing": the rewrite doesn't say it at all.

A fact counts only if the rewrite states it; a reader can't be expected to infer it. Don't judge
whether a loss matters; judge only whether the fact is there.

For "kept" and "changed", give "evidence": the exact passage(s) from the rewrite, copied character
for character. For "missing", give "evidence": [].

Reply with JSON only: {"facts": [{"id": "F1", "status": "kept", "evidence": ["..."]}]}"""

CONFIRM = """Look again, carefully, at these facts only. Search the whole rewrite, including lists,
headings and the end of the letter, before saying a fact is missing."""


def fact_block(facts: list[Fact], seed: str) -> str:
    order = list(facts)
    random.Random(seed).shuffle(order)
    return "\n".join(f'{f.id}. {f.statement} (In the original: "{f.quote}")' for f in order)


def prompt(rewrite: str, facts: list[Fact], seed: str, confirm: bool = False) -> str:
    head = CONFIRM + "\n\n" if confirm else ""
    return f"{head}<rewrite>\n{rewrite}\n</rewrite>\n\nFacts from the original letter:\n{fact_block(facts, seed)}"


def parse(reply: str, facts: list[Fact]) -> dict[str, dict] | None:
    d = llm.json_block(reply)
    if not isinstance(d, dict) or not isinstance(d.get("facts"), list):
        return None
    want = {f.id for f in facts}
    out = {}
    for x in d["facts"]:
        if isinstance(x, dict) and x.get("id") in want and x.get("status") in STATUSES:
            ev = x.get("evidence") or []
            out[x["id"]] = {"status": x["status"], "evidence": [str(e) for e in ev] if isinstance(ev, list) else [str(ev)]}
    return out if set(out) == want else None


def code_check(f: Fact, verdict: dict, rewrite: str) -> list[str]:
    """Why code disagrees with this verdict (empty if it doesn't)."""
    why = []
    if verdict["status"] in ("kept", "changed"):
        if not verdict["evidence"]:
            why.append("no evidence quoted")
        bad = [e for e in verdict["evidence"] if not contains(rewrite, e)]
        if bad:
            why.append(f"evidence not in the rewrite: {bad[0][:60]!r}")
    if verdict["status"] == "kept":
        lost = missing_from(rewrite, f.needed_values())
        if lost:
            why.append(f"value not in the rewrite: {lost}")
    return why


async def judge(notice: Notice, rewrite: str, model: str = "sonnet", seed: str = "") -> dict:
    """{"verdicts": {fid: {"status", "evidence", "stage", "code": [...], "overridden": bool}}, "cost_usd", "model", "error"}"""
    facts = notice.facts
    seed = seed or notice.id
    cost, used = 0.0, None
    first = None
    for attempt in (1, 2):
        r = await llm.call(prompt(rewrite, facts, seed), SYSTEM, model=model, effort=EFFORT)
        cost += r.cost_usd
        used = r.model or used
        first = None if r.error else parse(r.text, facts)
        if first:
            break
    if not first:
        return {"verdicts": None, "cost_usd": cost, "model": used, "error": "judge reply unusable twice"}
    verdicts = {fid: {**v, "stage": "first", "code": code_check(notice.fact(fid), v, rewrite), "overridden": False}
                for fid, v in first.items()}
    recheck = [f for f in facts if verdicts[f.id]["status"] != "kept" or verdicts[f.id]["code"]]
    if recheck:
        r = await llm.call(prompt(rewrite, recheck, seed + "/confirm", confirm=True), SYSTEM, model=model, effort=EFFORT)
        cost += r.cost_usd
        second = None if r.error else parse(r.text, recheck)
        if second:
            for fid, v in second.items():
                verdicts[fid] = {**v, "stage": "confirmed", "code": code_check(notice.fact(fid), v, rewrite),
                                 "overridden": False, "first": verdicts[fid]["status"]}
    for f in facts:
        v = verdicts[f.id]
        # A misquoted passage isn't proof of a loss; a missing date or amount is.
        v["unverified"] = v["status"] == "kept" and any(not c.startswith("value") for c in v["code"])
        if v["status"] == "kept" and any(c.startswith("value") for c in v["code"]):
            v["status"], v["overridden"] = "changed", True
    return {"verdicts": verdicts, "cost_usd": cost, "model": used, "error": None}
