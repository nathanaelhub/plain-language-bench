"""How many planted losses does the rewrite tool's own checker catch?

The tool doesn't know the benchmark's facts: it extracts its own items from the
letter (once per notice here, so every variant of a notice is checked against
the same list) and then locates each in the rewrite. A planted loss counts as
caught if any tool item covering the target fact (its quote overlaps the fact's
quote in the letter) comes back changed or missing. A target no item covers is a
miss of a different kind: the extractor never listed it.

    PLAINBENCH_USE_LOGIN=1 uv run python -m bench.tool_eval
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import date

from plainbench import log
from plainbench import pipeline as P
from plainbench.facts import ROOT, load
from plainbench.metrics import wilson
from plainbench.text import find

from . import plants

LOG = ROOT / "runs" / "tool_eval.jsonl"


def covers(item_quote: str, fact_quote: str, letter: str) -> bool:
    a, b = find(item_quote, letter) or (0, 0), find(fact_quote, letter) or (0, 0)
    return min(a[1], b[1]) - max(a[0], b[0]) > 0


async def main_async(max_usd: float):
    vs = json.loads(plants.PLANTS.read_text())
    bases = sorted({v["base"] for v in vs})
    tasks = []
    for nid in bases:
        n = load(nid)

        async def ex(n=n):
            items, dropped, cost = await P.extract(n.text, "sonnet")
            return {"stage": "extract", "notice": n.id, "items": [asdict(i) for i in items], "cost_usd": cost,
                    "error": None if items else "no items"}
        tasks.append(log.Task(log.key(stage="tool-extract", notice=nid, prompt=log.phash(P.EXTRACT, n.text)), ex))
    await log.run(tasks, LOG, concurrency=4, max_usd=max_usd, est_usd=0.04)
    done = log.done(log.read(LOG))
    extracted = {nid: done[log.key(stage="tool-extract", notice=nid, prompt=log.phash(P.EXTRACT, load(nid).text))]["items"]
                 for nid in bases}
    tasks = []
    for v in vs:
        if not v["target"]:
            continue

        async def loc(v=v):
            items = [P.Item(**{k: x[k] for k in ("id", "type", "fact", "answer", "quote")}) for x in extracted[v["base"]]]
            cost = await P.locate(items, v["text"], "sonnet")
            return {"stage": "locate", "variant": v["id"], "items": [asdict(i) for i in items], "cost_usd": cost, "error": None}
        tasks.append(log.Task(log.key(stage="tool-locate", variant=v["id"], prompt=log.phash(P.LOCATE, v["text"])), loc))
    await log.run(tasks, LOG, concurrency=4, max_usd=max_usd, est_usd=0.03)
    done = log.done(log.read(LOG))
    out = {}
    for split in ("test", "dev"):
        caught = defaultdict(lambda: [0, 0])
        unlisted = defaultdict(int)
        for v in vs:
            if v["split"] != split or not v["target"]:
                continue
            row = done.get(log.key(stage="tool-locate", variant=v["id"], prompt=log.phash(P.LOCATE, v["text"])))
            if not row:
                continue
            n = load(v["base"])
            fq = n.fact(v["target"]).quote
            cov = [i for i in row["items"] if covers(i["quote"], fq, n.text)]
            caught[v["kind"]][1] += 1
            if not cov:
                unlisted[v["kind"]] += 1
            elif any(i["status"] != "kept" for i in cov):
                caught[v["kind"]][0] += 1
        out[split] = {k: {"k": c, "n": t, "rate": c / t if t else None, "ci": wilson(c, t), "not_listed": unlisted[k]}
                      for k, (c, t) in caught.items()}
        allk = sum(x[0] for x in caught.values())
        alln = sum(x[1] for x in caught.values())
        out[split]["ALL"] = {"k": allk, "n": alln, "rate": allk / alln if alln else None, "ci": wilson(allk, alln),
                             "not_listed": sum(unlisted.values())}
    out["cost_usd"] = log.spent(log.read(LOG))
    d = ROOT / "results" / f"{date.today().isoformat()}-gate"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tool-checker.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for split in ("test", "dev"):
        print(f"== {split}")
        for k, x in out[split].items():
            print(f"  {k:12} caught {x['k']}/{x['n']} = {x['rate']:.2f}  (target never listed by the extractor: {x['not_listed']})")
    print(f"cost ${out['cost_usd']}")


if __name__ == "__main__":
    import sys
    asyncio.run(main_async(float(sys.argv[1]) if len(sys.argv) > 1 else 6.0))
