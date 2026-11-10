"""Turn the judged rewrites into the benchmark's results (results/<date>/results.json).

Headline measures count CRITICAL facts and use the final Sonnet verdicts:
- retention: share of a notice's critical facts kept, averaged over notices,
  with a bootstrap 95% interval over notices;
- lost per rewrite, and the share of rewrites that lost at least one;
- the expected false-loss band: how often a perfect rewrite would still show
  a loss, from the false-alarm rate measured in the gate.

Setups are compared in pairs on the same notices (paired bootstrap). Three
comparisons were fixed before any test rewrite was judged; everything else is
exploratory. Main results use the 15 test notices; dev is reported apart.

    uv run python -m bench.analyze
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

from plainbench import log
from plainbench.facts import ROOT, ids, load
from plainbench.metrics import bootstrap_ci, cohen_kappa, false_loss_band, paired_diff, wilson
from plainbench.readability import measure
from plainbench.values import not_in_source

from .run import judge_key, rewrites

SETUPS = ["original", "haiku-g6", "sonnet-g6", "opus-g6", "sonnet-g4", "sonnet-g8", "sonnet-g6-keep", "sonnet-g6-pipeline"]
LABEL = {"original": "The original letter", "haiku-g6": "Haiku, grade 6", "sonnet-g6": "Sonnet, grade 6",
         "opus-g6": "Opus, grade 6", "sonnet-g4": "Sonnet, grade 4", "sonnet-g8": "Sonnet, grade 8",
         "sonnet-g6-keep": "Sonnet, grade 6, 'keep everything' prompt", "sonnet-g6-pipeline": "Rewrite tool (Sonnet, grade 6)"}
PREREGISTERED = [
    ("Critical facts kept vs the reading grade each rewrite reached", "grade"),
    ("Plain prompt vs 'keep everything' prompt vs the rewrite tool", [("sonnet-g6-keep", "sonnet-g6"), ("sonnet-g6-pipeline", "sonnet-g6"), ("sonnet-g6-pipeline", "sonnet-g6-keep")]),
    ("Model size at the same prompt", [("opus-g6", "sonnet-g6"), ("sonnet-g6", "haiku-g6"), ("opus-g6", "haiku-g6")]),
]


def verdict_rows(judge: str = "sonnet") -> list[dict]:
    done = log.done(log.read(ROOT / "runs" / "judge.jsonl"))
    out = []
    for r in rewrites(ids(), SETUPS, 2):
        v = done.get(judge_key(r, judge))
        if v and v.get("verdicts"):
            out.append({**r, "verdicts": v["verdicts"]})
    return out


def per_rewrite(r: dict) -> dict:
    n = load(r["notice"])
    crit = n.critical
    lost = [f.id for f in crit if r["verdicts"][f.id]["status"] != "kept"]
    m = measure(r["text"])
    return {"notice": r["notice"], "setup": r["setup"], "sample": r["sample"], "critical": len(crit),
            "kept": len(crit) - len(lost), "lost": lost, "retention": (len(crit) - len(lost)) / len(crit),
            "grade": m["grade"], "words": m["words"],
            "not_in_source": [f"{v.kind}:{v.value}" for v in not_in_source(r["text"], n.text)] if r["setup"] != "original" else [],
            "by_type": {t: [sum(1 for f in crit if f.type == t and f.id not in lost), sum(1 for f in crit if f.type == t)]
                        for t in {f.type for f in crit}}}


def summarize(rows: list[dict], fa_rate: float) -> dict:
    by_setup = defaultdict(list)
    for r in rows:
        by_setup[r["setup"]].append(r)
    out = {}
    for s, rs in by_setup.items():
        first = [r for r in rs if r["sample"] == 0]
        ret = {r["notice"]: r["retention"] for r in first}
        mean = lambda ks: statistics.fmean(ret[k] for k in ks)  # noqa: E731
        types = defaultdict(lambda: [0, 0])
        for r in first:
            for t, (k, n) in r["by_type"].items():
                types[t][0] += k
                types[t][1] += n
        grades = [r["grade"] for r in first if r["grade"] is not None]
        out[s] = {
            "label": LABEL[s], "rewrites": len(first), "retention": mean(list(ret)), "ci": bootstrap_ci(mean, list(ret)),
            "lost_per_rewrite": statistics.fmean(len(r["lost"]) for r in first),
            "any_loss": sum(bool(r["lost"]) for r in first) / len(first),
            "false_loss_band": statistics.fmean(false_loss_band(fa_rate, r["critical"]) for r in first),
            "grade_median": statistics.median(grades) if grades else None,
            "grade_mean": statistics.fmean(grades) if grades else None,
            "words_median": statistics.median(r["words"] for r in first),
            "not_in_source": sum(len(r["not_in_source"]) for r in first),
            "by_type": {t: {"kept": k, "n": n, "rate": k / n} for t, (k, n) in sorted(types.items())},
        }
    return out


def paired(rows, a, b):
    ra = {r["notice"]: r["retention"] for r in rows if r["setup"] == a and r["sample"] == 0}
    rb = {r["notice"]: r["retention"] for r in rows if r["setup"] == b and r["sample"] == 0}
    return paired_diff(ra, rb)


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def main() -> dict:
    split = json.loads((ROOT / "corpus" / "split.json").read_text())
    gate = json.loads(sorted((ROOT / "results").glob("*-gate/gate-sonnet.json"))[-1].read_text())
    tool = json.loads(sorted((ROOT / "results").glob("*-gate/tool-checker.json"))[-1].read_text())
    fa = gate["test"]["false_alarm"]["rate"]
    rows = [per_rewrite(r) for r in verdict_rows("sonnet")]
    test = [r for r in rows if r["notice"] not in split["dev"]]
    dev = [r for r in rows if r["notice"] in split["dev"]]
    res = {"generated": date.today().isoformat(), "notices": {"test": len({r["notice"] for r in test}), "dev": len(split["dev"])},
           "false_alarm_rate": fa, "setups": summarize(test, fa), "dev_setups": summarize(dev, fa)}
    # noise: the same setup run twice
    s0 = {r["notice"]: r["retention"] for r in test if r["setup"] == "sonnet-g6" and r["sample"] == 0}
    s1 = {r["notice"]: r["retention"] for r in test if r["setup"] == "sonnet-g6" and r["sample"] == 1}
    res["noise"] = {**paired_diff(s1, s0), "mean_abs_diff": statistics.fmean(abs(s1[k] - s0[k]) for k in s0.keys() & s1.keys())}
    pre = []
    rw = [r for r in test if r["setup"] != "original" and r["sample"] == 0 and r["grade"] is not None]
    pre.append({"question": PREREGISTERED[0][0], "spearman_grade_vs_retention": spearman([r["grade"] for r in rw], [r["retention"] for r in rw]),
                "n": len(rw), "grade_sweep": {s: res["setups"][s]["retention"] for s in ("sonnet-g4", "sonnet-g6", "sonnet-g8")},
                "pairs": {f"{a} - {b}": paired(test, a, b) for a, b in (("sonnet-g8", "sonnet-g6"), ("sonnet-g6", "sonnet-g4"), ("sonnet-g8", "sonnet-g4"))}})
    for q, pairs in PREREGISTERED[1:]:
        pre.append({"question": q, "pairs": {f"{a} - {b}": paired(test, a, b) for a, b in pairs}})
    res["preregistered"] = pre
    # judges: does the Sonnet judge favour the tool? Opus re-judged two setups in full.
    opus = {(r["notice"], r["setup"]): r for r in (per_rewrite(x) for x in verdict_rows("opus"))}
    agree = {}
    for s in ("sonnet-g6", "sonnet-g6-pipeline"):
        a, b, ls, lo = {}, {}, 0, 0
        for r in rows:
            if r["setup"] == s and r["sample"] == 0 and (r["notice"], s) in opus:
                n = load(r["notice"])
                o = opus[(r["notice"], s)]
                for f in n.critical:
                    a[f"{r['notice']}/{f.id}"] = f.id in r["lost"]
                    b[f"{r['notice']}/{f.id}"] = f.id in o["lost"]
                ls += len(r["lost"])
                lo += len(o["lost"])
        agree[s] = {"kappa": cohen_kappa(a, b), "facts": len(a), "agree": sum(a[k] == b[k] for k in a) / len(a) if a else None,
                    "lost_sonnet_judge": ls, "lost_opus_judge": lo}
    res["judge_agreement"] = agree
    # sentence-level sensitivity: a source sentence counts as kept only if all its critical facts are
    sent = {}
    for s in SETUPS:
        ks = []
        for r in test:
            if r["setup"] != s or r["sample"] != 0:
                continue
            n = load(r["notice"])
            crit = {f.id for f in n.critical}
            for x in n.sentences:
                fs = [f for f in (x.get("facts") or []) if f in crit]
                if fs:
                    ks.append(all(f not in r["lost"] for f in fs))
        sent[s] = sum(ks) / len(ks) if ks else None
    res["sentence_level_retention"] = sent
    plain_ids = [nid for nid in ids() if load(nid).meta.get("already_plain") is True and nid not in split["dev"]]
    res["already_plain_vs_dense"] = {s: {"already_plain": statistics.fmean(r["retention"] for r in test if r["setup"] == s and r["sample"] == 0 and r["notice"] in plain_ids),
                                         "dense": statistics.fmean(r["retention"] for r in test if r["setup"] == s and r["sample"] == 0 and r["notice"] not in plain_ids)}
                                     for s in SETUPS if s != "original"}
    res["gate"] = {k: gate["test"][k] for k in ("caught", "false_alarm", "false_alarm_null", "agreement_on_unedited_rewrites", "passed")}
    res["tool_checker"] = tool["test"]
    res["rows"] = rows
    hl = ROOT / "labels"
    humans = sorted(hl.glob("human-*.json"))
    if humans:
        res["human"] = human_agreement(humans[-1])
    res["cost_usd"] = {f: log.spent(log.read(ROOT / "runs" / f"{f}.jsonl")) for f in ("draft_facts", "rewrites", "judge", "plant_judge", "tool_eval")}
    res["cost_usd"]["total"] = round(sum(res["cost_usd"].values()), 2)
    d = ROOT / "results" / date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return res


def human_agreement(path: Path) -> dict:
    sample = json.loads((ROOT / "labels" / "sample.json").read_text())
    labels = json.loads(path.read_text())["labels"]
    groups = defaultdict(lambda: {"agree": 0, "n": 0, "unsure": 0, "items": []})
    for it in sample["items"]:
        lab = labels[str(it["n"])]["status"]
        g = groups[it["group"]]
        truth = it.get("truth") or it.get("judge")
        if it["group"] == "repeat":
            first = labels[str(sample["items"][it["repeat_of"]]["n"])]["status"]
            g["n"] += 1
            g["agree"] += lab == first
            continue
        if lab == "unsure":
            g["unsure"] += 1
            continue
        g["n"] += 1
        same = (lab == "kept") == (truth == "kept")  # loss vs no loss, the judge's question
        g["agree"] += same
        g["items"].append({"n": it["n"], "notice": it["notice"], "fact": it["fact"], "human": lab, "judge": it.get("judge"),
                           "opus": it.get("opus"), "note": labels[str(it["n"])].get("note", "")})
    return {k: {**v, "ci": wilson(v["agree"], v["n"])} for k, v in groups.items()}


if __name__ == "__main__":
    r = main()
    for s, x in r["setups"].items():
        print(f"{s:20} kept {x['retention']:.3f} [{x['ci'][0]:.3f}-{x['ci'][1]:.3f}]  lost/rewrite {x['lost_per_rewrite']:.2f}"
              f"  any loss {x['any_loss']:.2f} (false-loss band {x['false_loss_band']:.2f})  grade {x['grade_median']}  words {x['words_median']}  not-in-source {x['not_in_source']}")
    print("noise (sonnet-g6 run twice):", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r["noise"].items()})
    for p in r["preregistered"]:
        print(p["question"])
        for k, v in p.get("pairs", {}).items():
            print(f"   {k:40} {v['diff']:+.3f}  [{v['ci'][0]:+.3f}, {v['ci'][1]:+.3f}]")
        if "spearman_grade_vs_retention" in p:
            print("   spearman", round(p["spearman_grade_vs_retention"], 3), "n", p["n"])
    print("judge agreement", r["judge_agreement"])
    print("sentence-level", {k: round(v, 3) for k, v in r["sentence_level_retention"].items()})
    print("plain vs dense", {k: {a: round(b, 3) for a, b in v.items()} for k, v in r["already_plain_vs_dense"].items()})
    print("cost", r["cost_usd"])
