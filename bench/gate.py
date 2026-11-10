"""Judge the planted-error variants and score the judge against labels known by construction.

    PLAINBENCH_USE_LOGIN=1 uv run python -m bench.gate run [--judge sonnet]
    uv run python -m bench.gate score [--judge sonnet]      # writes results/<date>-gate/gate-<judge>.json

Caught = the judge's final status for the target isn't "kept". A false alarm =
a critical fact whose true label is "kept" (aligned kept, and untouched by the
edit) that the judge didn't call kept (critical facts, like the headline; all
facts are reported too, and how many distinct facts the alarms fall on, since
the same misjudged fact repeats across a base's variants). Gate thresholds were set in the plan before any
variant was judged:

    DELETE >= 0.90; VALUE (code + judge) >= 0.95; CONDITION, ALTERNATIVE, MODAL, VAGUE >= 0.70 each;
    false alarms <= 5% on untouched kept facts, <= 3% on NULL-edit variants.

Only test variants decide the gate; dev variants are shown separately.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import date

from plainbench import judge as J
from plainbench import log
from plainbench.facts import ROOT, load
from plainbench.metrics import wilson

from . import plants

LOG = ROOT / "runs" / "plant_judge.jsonl"
THRESHOLDS = {"DELETE": 0.90, "VALUE": 0.95, "CONDITION": 0.70, "ALTERNATIVE": 0.70, "MODAL": 0.70, "VAGUE": 0.70}
MAX_FALSE_ALARM = 0.05
MAX_FALSE_ALARM_NULL = 0.03


def key(v: dict, judge: str) -> str:
    return log.key(stage="plant", variant=v["id"], judge=judge,
                   prompt=log.phash(J.SYSTEM, J.CONFIRM, J.EFFORT, v["text"]))


def run(judge: str, max_usd: float, split: str | None = None) -> None:
    vs = [v for v in json.loads(plants.PLANTS.read_text()) if split is None or v["split"] == split]
    tasks = []
    for v in vs:
        n = load(v["base"])

        async def go(v=v, n=n):
            r = await J.judge(n, v["text"], model=judge)
            return {"variant": v["id"], "judge": judge, **r}
        tasks.append(log.Task(key(v, judge), go))
    print(asyncio.run(log.run(tasks, LOG, concurrency=4, max_usd=max_usd, est_usd=0.06)))


def score(judge: str) -> dict:
    vs = json.loads(plants.PLANTS.read_text())
    done = log.done(log.read(LOG))
    out = {}
    for split in ("test", "dev"):
        caught = defaultdict(lambda: [0, 0])  # kind -> [caught, n]
        exact = defaultdict(lambda: [0, 0])
        fa = [0, 0]
        fa_null = [0, 0]
        allfa = [0, 0]  # every fact, critical or not
        base_agree = defaultdict(lambda: [0, 0])  # aligned status -> [judge agrees, n] on unedited rewrites
        misses, alarms = [], []
        for v in vs:
            if v["split"] != split:
                continue
            row = done.get(key(v, judge))
            if not row or not row.get("verdicts"):
                continue
            ver = row["verdicts"]
            if v["target"]:
                st = ver[v["target"]]["status"]
                caught[v["kind"]][1] += 1
                caught[v["kind"]][0] += st != "kept"
                exact[v["kind"]][1] += 1
                exact[v["kind"]][0] += st == v["labels"][v["target"]]
                if st == "kept":
                    misses.append({"variant": v["id"], "edit": v["edit"], "evidence": ver[v["target"]]["evidence"]})
            notice = load(v["base"])
            for fid, lab in v["labels"].items():
                if fid == v["target"] or lab != "kept":
                    continue
                if not notice.fact(fid).critical:
                    allfa[1] += 1
                    allfa[0] += ver[fid]["status"] != "kept"
                    continue
                allfa[1] += 1
                allfa[0] += ver[fid]["status"] != "kept"
                bad = ver[fid]["status"] != "kept"
                (fa_null if v["kind"] == "NULL" else fa)[1] += 1
                (fa_null if v["kind"] == "NULL" else fa)[0] += bad
                if bad:
                    alarms.append({"variant": v["id"], "fact": fid, "said": ver[fid]["status"], "evidence": ver[fid]["evidence"]})
            if v["kind"] == "BASE":
                for fid, lab in v["labels"].items():
                    base_agree[lab][1] += 1
                    base_agree[lab][0] += (ver[fid]["status"] == lab) if lab != "kept" else (ver[fid]["status"] == "kept")
        rate = lambda k, n: {"k": k, "n": n, "rate": k / n if n else None, "ci": wilson(k, n)}  # noqa: E731
        res = {
            "caught": {k: rate(*caught[k]) for k in THRESHOLDS if caught[k][1]},
            "exact_label": {k: rate(*exact[k]) for k in THRESHOLDS if exact[k][1]},
            "false_alarm": rate(*fa), "false_alarm_null": rate(*fa_null), "false_alarm_all_facts": rate(*allfa),
            "false_alarm_distinct_facts": len({(a["variant"].split("/")[0], a["fact"]) for a in alarms}),
            "agreement_on_unedited_rewrites": {k: rate(*v) for k, v in base_agree.items()},
            "misses": misses, "false_alarms": alarms,
        }
        res["passed"] = {k: (res["caught"][k]["rate"] >= t) for k, t in THRESHOLDS.items() if k in res["caught"]}
        res["passed"]["false_alarm"] = fa[1] > 0 and fa[0] / fa[1] <= MAX_FALSE_ALARM
        res["passed"]["false_alarm_null"] = fa_null[1] > 0 and fa_null[0] / fa_null[1] <= MAX_FALSE_ALARM_NULL
        out[split] = res
    out["judge"] = judge
    out["cost_usd"] = round(sum(r.get("cost_usd") or 0 for r in log.read(LOG) if r.get("judge") == judge), 3)
    d = ROOT / "results" / f"{date.today().isoformat()}-gate"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"gate-{judge}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def show(out: dict) -> None:
    for split in ("test", "dev"):
        r = out[split]
        print(f"== {split} ({out['judge']})")
        for k, x in r["caught"].items():
            print(f"  {k:12} caught {x['k']:2}/{x['n']:2} = {x['rate']:.2f}  [{x['ci'][0]:.2f}-{x['ci'][1]:.2f}]"
                  f"  exact label {r['exact_label'][k]['k']}/{r['exact_label'][k]['n']}  {'PASS' if r['passed'][k] else 'FAIL'}")
        for name in ("false_alarm", "false_alarm_null"):
            x = r[name]
            print(f"  {name:17} {x['k']}/{x['n']} = {x['rate'] or 0:.3f}  {'PASS' if r['passed'][name] else 'FAIL'}")
        for lab, x in r["agreement_on_unedited_rewrites"].items():
            print(f"  unedited, aligned {lab:8}: judge agrees {x['k']}/{x['n']}")
    print(f"cost ${out['cost_usd']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--judge", default="sonnet")
    ap.add_argument("--max-usd", type=float, default=40.0)
    ap.add_argument("--split", choices=["dev", "test"], help="judge only this split's variants")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(a.judge, a.max_usd, a.split)
    show(score(a.judge))


if __name__ == "__main__":
    main()
