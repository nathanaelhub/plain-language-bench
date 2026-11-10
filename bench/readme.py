"""Write the README's findings block from results.json, so every figure in it is traceable.

    uv run python -m bench.readme
"""

from __future__ import annotations

import json
import re

from plainbench.facts import ROOT

START, END = "<!-- findings:start -->", "<!-- findings:end -->"


def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def findings(res: dict) -> str:
    s = res["setups"]
    pairs = {k: v for p in res["preregistered"] for k, v in p.get("pairs", {}).items()}
    d46 = pairs["sonnet-g6 - sonnet-g4"]
    keep, tool = pairs["sonnet-g6-keep - sonnet-g6"], pairs["sonnet-g6-pipeline - sonnet-g6"]
    g = res["gate"]
    ch = g["agreement_on_unedited_rewrites"].get("changed", {"k": 0, "n": 0})
    ja = res["judge_agreement"]
    rows = "\n".join(f"| {r['label']} | {pct(r['retention'])} | {pct(r['ci'][0])}–{pct(r['ci'][1])} | {r['lost_per_rewrite']:.1f} | "
                     f"{pct(r['any_loss'], 0)} | {r['grade_median']} |" for r in (s[k] for k in s))
    caught = "\n".join(f"| {k.title()} | {v['k']} of {v['n']} |" for k, v in g["caught"].items())
    human = res.get("human")
    hum = ("\n\n**5. A person's check.** Pending: 40 blinded items are being labelled; this section will report agreement by group."
           if not human else "\n\n**5. A person's check.** " + "; ".join(
               f"{k}: agreed with the judge on {v['agree']} of {v['n']}" + (f" ({v['unsure']} unsure)" if v["unsure"] else "")
               for k, v in human.items()) + ".")
    return f"""Results for the {res['notices']['test']} test notices; the 3 dev notices, used to tune the judge, are reported
separately in `results/`. "Critical facts" are the ones a reader needs to act or to know what happens to them
(see [corpus/RULES.md](corpus/RULES.md)); all figures count those.

| Setup | Critical facts kept | 95% range | Lost per letter | Letters with a loss | Reading grade |
|---|---|---|---|---|---|
{rows}

**1. Plain enough costs little; plainer costs more.** At grade 6, Sonnet's rewrites kept {pct(s['sonnet-g6']['retention'])} of
critical facts. Asking for grade 4 cost {abs(d46['diff']) * 100:.1f} points more (95% range {min(abs(c) for c in d46['ci']) * 100:.1f} to
{max(abs(c) for c in d46['ci']) * 100:.1f}), and {pct(s['sonnet-g4']['any_loss'], 0)} of grade-4 rewrites lost at least one critical fact.
Asking for grade 8 changed nothing: the rewrites landed at grade {s['sonnet-g8']['grade_median']} anyway.

**2. Prompts, models and the tool: no difference bigger than noise.** The same setup run twice differed by
{res['noise']['mean_abs_diff'] * 100:.1f} points per letter on average. The "keep everything" prompt ({keep['diff'] * 100:+.1f} points,
95% range {keep['ci'][0] * 100:+.1f} to {keep['ci'][1] * 100:+.1f}) and the rewrite tool ({tool['diff'] * 100:+.1f}, {tool['ci'][0] * 100:+.1f}
to {tool['ci'][1] * 100:+.1f}) both point the right way but can't be told apart from it; neither can Haiku, Sonnet and Opus.

**3. The judge catches planted losses, and misses some real ones.** On errors planted in hand-checked rewrites (labels known by
construction), the judge caught:

| Planted error | Caught (test) |
|---|---|
{caught}

A "must" that became a "may" was the one type under the bar set in advance (0.70). False alarms: {pct(g['false_alarm']['rate'])} of
critical facts that were kept. On unedited rewrites it agreed with only {ch['k']} of {ch['n']} subtle real changes found by hand
(for example, CP12's 60-day reversal right losing "in writing"), so the retention figures are best read as an **upper bound**.

**4. The Sonnet judge doesn't favour the tool.** The tool's own checker is Sonnet too, so Opus re-judged the tool's rewrites in
full: it found {ja['sonnet-g6-pipeline']['lost_opus_judge']} losses where Sonnet found {ja['sonnet-g6-pipeline']['lost_sonnet_judge']}.
The tool's checker, scored on the same planted errors, caught {res['tool_checker']['ALL']['k']} of {res['tool_checker']['ALL']['n']}.{hum}

Total cost: ${res['cost_usd']['total']:.2f} (nominal, on a Claude plan login)."""


def main():
    res = json.loads(sorted((ROOT / "results").glob("2*/results.json"))[-1].read_text())
    p = ROOT / "README.md"
    text = p.read_text()
    block = f"{START}\n{findings(res)}\n{END}"
    text = re.sub(re.escape(START) + ".*?" + re.escape(END), lambda m: block, text, flags=re.S) if START in text else text + "\n" + block + "\n"
    p.write_text(text)
    print("README findings updated")


if __name__ == "__main__":
    main()
