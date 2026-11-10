"""Generate rewrites and judge them, resumably, under a spending cap.

    PLAINBENCH_USE_LOGIN=1 uv run python -m bench.run rewrites [--notices ...] [--setups ...] [--samples 1]
    PLAINBENCH_USE_LOGIN=1 uv run python -m bench.run judge [--notices ...] [--setups ...] [--judge sonnet]
    uv run python -m bench.run costs

Rewrites go to runs/rewrites.jsonl, verdicts to runs/judge.jsonl. Each row's
key includes the hash of the prompt it was sent, so a prompt change reruns it.
The setup "original" is the notice itself, judged as if it were a rewrite:
every fact is in it, so any loss the judge reports there is a false alarm.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict

from dataclasses import asdict

from plainbench import judge as J
from plainbench import pipeline as P
from plainbench import log
from plainbench import rewrite as R
from plainbench.facts import ROOT, ids, load

REWRITES = ROOT / "runs" / "rewrites.jsonl"
JUDGED = ROOT / "runs" / "judge.jsonl"


PIPELINE = "sonnet-g6-pipeline"


def rewrite_key(setup, nid: str, sample: int, letter: str) -> str:
    if setup == PIPELINE:
        return log.key(stage="rewrite", setup=PIPELINE, notice=nid, sample=sample,
                       prompt=log.phash(P.EXTRACT, P.REWRITE, P.LOCATE, P.REVISE, P.SYSTEM, P.EFFORT, letter))
    return log.key(stage="rewrite", setup=setup.name, notice=nid, sample=sample,
                   prompt=log.phash(R.SYSTEM, setup.prompt(letter), setup.model, R.EFFORT))


def rewrites(notices: list[str], setups: list[str], samples: int) -> list[dict]:
    """The latest rewrite row for each (setup, notice, sample) asked for."""
    done = log.done(log.read(REWRITES))
    out = []
    for nid in notices:
        n = load(nid)
        for s in setups:
            if s == "original":
                out.append({"setup": "original", "notice": nid, "sample": 0, "text": n.text})
                continue
            for k in range(samples):
                row = done.get(rewrite_key(s if s == PIPELINE else R.SETUPS[s], nid, k, n.text))
                if row:
                    out.append(row)
    return out


def judge_key(row: dict, judge_model: str) -> str:
    n = load(row["notice"])
    facts = "\n".join(f"{f.id}|{f.statement}|{f.quote}|{f.answer}|{f.type}" for f in n.facts)
    return log.key(stage="judge", setup=row["setup"], notice=row["notice"], sample=row["sample"], judge=judge_model,
                   prompt=log.phash(J.SYSTEM, J.CONFIRM, J.EFFORT, row["text"], facts))


def cmd_rewrites(a) -> None:
    tasks = []
    for nid in a.notices:
        n = load(nid)
        for s in a.setups:
            if s == "original":
                continue
            if s == PIPELINE:
                for k in range(a.samples):
                    async def go_p(n=n, k=k):
                        res = await P.run(n.text, model="sonnet", grade=6)
                        return {"setup": PIPELINE, "notice": n.id, "sample": k, "text": res.rewrite, "model": "sonnet",
                                "cost_usd": res.cost_usd, "error": res.error, "revised": res.revised,
                                "items": [asdict(i) for i in res.items], "dropped": res.dropped}
                    tasks.append(log.Task(rewrite_key(PIPELINE, nid, k, n.text), go_p))
                continue
            setup = R.SETUPS[s]
            for k in range(a.samples):
                async def go(setup=setup, n=n, k=k):
                    r = await R.rewrite(setup, n.text)
                    return {"setup": setup.name, "notice": n.id, "sample": k, **r}
                tasks.append(log.Task(rewrite_key(setup, nid, k, n.text), go))
    print(asyncio.run(log.run(tasks, REWRITES, concurrency=a.concurrency, max_usd=a.max_usd, est_usd=0.03)))


def cmd_judge(a) -> None:
    tasks = []
    for row in rewrites(a.notices, a.setups, a.samples):
        n = load(row["notice"])

        async def go(row=row, n=n):
            r = await J.judge(n, row["text"], model=a.judge)
            return {"setup": row["setup"], "notice": row["notice"], "sample": row["sample"], "judge": a.judge, **r}
        tasks.append(log.Task(judge_key(row, a.judge), go))
    print(asyncio.run(log.run(tasks, JUDGED, concurrency=a.concurrency, max_usd=a.max_usd, est_usd=0.08)))


def cmd_costs(a) -> None:
    for path in (REWRITES, JUDGED, ROOT / "runs" / "draft_facts.jsonl"):
        rows = log.read(path)
        by = defaultdict(lambda: [0, 0.0, 0])
        for r in rows:
            k = r.get("setup") or r.get("key", "").split("|")[0]
            if "judge" in r and path == JUDGED:
                k = f"judge:{r['judge']}"
            by[k][0] += 1
            by[k][1] += r.get("cost_usd") or 0
            by[k][2] += bool(r.get("error"))
        print(f"{path.name}: {len(rows)} rows, ${log.spent(rows):.2f}")
        for k, (n, c, e) in sorted(by.items()):
            print(f"  {k:24} {n:4} calls  ${c:7.3f}  (${c / max(n, 1):.4f} each)  {e} errors")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["rewrites", "judge", "costs"])
    ap.add_argument("--notices", nargs="*")
    ap.add_argument("--setups", nargs="*")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--judge", default="sonnet")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--max-usd", type=float, default=40.0)
    a = ap.parse_args(argv)
    a.notices = a.notices or ids()
    a.setups = a.setups or [*R.SETUPS, PIPELINE, "original"]
    {"rewrites": cmd_rewrites, "judge": cmd_judge, "costs": cmd_costs}[a.cmd](a)


if __name__ == "__main__":
    main()
