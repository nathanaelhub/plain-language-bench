"""Draft each notice's fact list with Opus, then check it with code.

The draft is a starting point for review, not the answer key: every quote must
be found in the notice, every sentence accounted for, and the list is read by
hand before the freeze. One retry with the problems listed.

    PLAINBENCH_USE_LOGIN=1 uv run python -m bench.draft_facts [notice ...] [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from plainbench import llm, log
from plainbench.facts import CORPUS, ROOT, Notice, ids, load, problems, sentence_list

RULES = (CORPUS / "RULES.md").read_text(encoding="utf-8")
LOG = ROOT / "runs" / "draft_facts.jsonl"
MODEL = "opus"

SYSTEM = f"""You build the answer key for a benchmark that measures what gets lost when a government
letter is rewritten in plain language. Follow these rules exactly:

{RULES}

Reply with JSON only:
{{"facts": [{{"id": "F1", "type": "...", "statement": "...", "question": "...", "answer": "...",
             "quote": "an EXACT passage copied from the notice", "critical": true, "depends_on": []}}],
 "sentences": [{{"i": 0, "facts": ["F1"], "none": null, "override": null}}]}}

- Number facts F1, F2, ... in the order they first appear.
- Quotes are copied character for character from the notice (keep its punctuation and
  capitalization); keep them short, just enough to state the fact.
- One entry in "sentences" for every numbered sentence, in order. "none" is a short reason when a
  sentence carries no fact; "override" is required too if that sentence contains a number, date,
  amount, phone number or one of the marker words.
- For deadline, amount and contact facts, put the exact value (date, amount, phone, address, web
  address) in the answer."""


def prompt(n: Notice) -> str:
    numbered = "\n".join(f"[{s['i']}] {s['text']}" for s in sentence_list(n.text))
    return f"Notice: {n.meta.get('title')} ({n.meta.get('agency')})\n\nFull text:\n<notice>\n{n.text}\n</notice>\n\nSentences:\n{numbered}"


def attach(n: Notice, draft: dict) -> dict:
    """The draft with each sentence's text and offset filled in from the notice."""
    cur = sentence_list(n.text)
    by_i = {s.get("i"): s for s in draft.get("sentences", []) if isinstance(s, dict)}
    sents = []
    for c in cur:
        s = by_i.get(c["i"], {})
        sents.append({"i": c["i"], "start": c["start"], "text": c["text"], "facts": s.get("facts") or [],
                      "none": s.get("none"), "override": s.get("override")})
    return {"facts": draft.get("facts", []), "sentences": sents}


def check(n: Notice, data: dict) -> tuple[list[str], list[str]]:
    tmp = Notice(n.id, n.meta, n.text, [], data["sentences"], n.path)
    from plainbench.facts import Fact
    try:
        tmp.facts = [Fact(**{k: f[k] for k in Fact.__dataclass_fields__ if k in f}) for f in data["facts"]]
    except TypeError as exc:
        return [f"a fact is missing a field: {exc}"], []
    return problems(tmp)


async def draft(n: Notice) -> dict:
    cost, model, issues, data = 0.0, None, [], None
    base = prompt(n)
    for attempt in range(2):
        ask = base if attempt == 0 else base + "\n\nYour previous answer had these problems; fix them and send the whole JSON again:\n- " + "\n- ".join(issues[:40])
        r = await llm.call(ask, SYSTEM, model=MODEL, effort="high", timeout=900)
        cost += r.cost_usd
        model = r.model or model
        if r.error:
            issues = [r.error]
            continue
        parsed = llm.json_block(r.text)
        if not isinstance(parsed, dict):
            issues = ["the reply was not a JSON object"]
            continue
        data = attach(n, parsed)
        issues, warns = check(n, data)
        if not issues:
            break
    return {"cost_usd": cost, "error": None if data else "; ".join(issues)[:300], "model": model,
            "data": data, "problems": issues, "attempts": attempt + 1}


def save(n: Notice, row: dict) -> None:
    out = {"notice": n.id, "drafted_by": row.get("model"), "reviewed": False, "review_notes": [],
           **row["data"]}
    (n.path / "facts.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("notices", nargs="*")
    ap.add_argument("--force", action="store_true", help="redraft even if facts.json exists")
    ap.add_argument("--max-usd", type=float, default=8.0)
    a = ap.parse_args(argv)
    todo = [load(i) for i in (a.notices or ids())]
    todo = [n for n in todo if a.force or not (n.path / "facts.json").exists()]
    tasks = [log.Task(log.key(stage="draft", notice=n.id, prompt=log.phash(SYSTEM, prompt(n))), (lambda n=n: draft(n)))
             for n in todo]
    asyncio.run(log.run(tasks, LOG, concurrency=3, max_usd=a.max_usd, est_usd=0.3))
    rows = log.done(log.read(LOG))
    for n in todo:
        row = rows.get(log.key(stage="draft", notice=n.id, prompt=log.phash(SYSTEM, prompt(n))))
        if row and row.get("data"):
            save(n, row)
            print(f"{n.id}: {len(row['data']['facts'])} facts, {row['attempts']} attempt(s), "
                  f"{len(row['problems'])} problems left, ${row['cost_usd']:.2f}")


if __name__ == "__main__":
    main()
