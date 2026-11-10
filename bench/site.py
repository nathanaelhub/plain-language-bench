"""Build the static results site from committed data only (no model calls).

    uv run python -m bench.site      # writes _site/
"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

from plainbench.facts import ROOT, ids, load
from plainbench.text import find

from .analyze import LABEL, SETUPS
from .run import rewrites

OUT = ROOT / "_site"
REPO = "https://github.com/nathanaelhub/plain-language-bench"
e = html.escape

CSS = """
.viz-root,:root{color-scheme:light;--bg:#f7f5f0;--surface-1:#fcfcfb;--panel:#fff;--ink:#1d2320;--text-secondary:#52514e;--muted:#5b625e;--line:#dcd8cf;
--accent:#1f5f8a;--series-1:#2a78d6;--neutral:#8a8983;--grid:#e6e3dc;--lost:#8a2f24;--lost-bg:#f6e2df;--changed:#8a5a00;--changed-bg:#fbefd5;--kept-bg:#e2f1ec}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#141618;--surface-1:#1a1a19;--panel:#1c1f22;--ink:#e8ebe9;--text-secondary:#c3c2b7;
--muted:#a3aba7;--line:#31363a;--accent:#8cc3ea;--series-1:#3987e5;--grid:#2c2f33;--lost:#f2a297;--lost-bg:#3d2522;--changed:#f0c36b;--changed-bg:#3a3020;--kept-bg:#1d3530}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:0 16px 56px}header.top{border-bottom:1px solid var(--line);background:var(--panel)}
header.top p{margin:0 auto;max-width:900px;padding:12px 16px;font-weight:600}header.top a{color:inherit;text-decoration:none}
h1{font-size:30px;line-height:1.2;margin:28px 0 8px}h2{font-size:21px;margin:36px 0 8px}h3{font-size:17px;margin:20px 0 6px}
a{color:var(--accent)}.lede{font-size:18px}.muted,.hint{color:var(--muted);font-size:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:12px 0}
.big{font-size:17px}.big b{font-size:22px}
table{border-collapse:collapse;width:100%;font-size:14px;background:var(--panel)}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
thead th{color:var(--muted);font-weight:500}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.scroll{overflow-x:auto}
.chart text{fill:var(--text-secondary);font-size:13px}.chart .lab{fill:var(--ink)}.chart line.grid{stroke:var(--grid)}
.chart line.ci{stroke:var(--series-1);stroke-width:2;stroke-linecap:round}.chart circle{fill:var(--series-1);stroke:var(--surface-1);stroke-width:2}
.chart.compact{display:none}@media (max-width:600px){.chart.wide{display:none}.chart.compact{display:block}}
.chart .ref line.ci{stroke:var(--neutral)}.chart .ref circle{fill:var(--neutral)}.chart g.row:hover rect.hit{fill:var(--grid)}
.letter{white-space:pre-wrap;font-size:15px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-wrap:anywhere}
mark.f{background:var(--kept-bg);color:inherit;border-radius:3px}
.tag{display:inline-block;border-radius:999px;padding:0 9px;font-size:13px;font-weight:600}.tag.missing{color:var(--lost);background:var(--lost-bg)}
.tag.changed{color:var(--changed);background:var(--changed-bg)}details{margin:10px 0}summary{cursor:pointer;font-weight:600}
ul.loss li{margin:6px 0}.note{border-left:4px solid var(--line);padding:4px 12px;color:var(--muted)}
"""


def page(title: str, body: str, depth: int = 0) -> str:
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><meta name="description" content="What gets lost when a government letter is rewritten in plain language: 18 federal notices, 8 ways of rewriting them, every deadline, amount and right checked.">
<style>{CSS}</style></head><body><header class="top"><p><a href="{up}index.html">Plain-language bench</a></p></header>
<main class="wrap">{body}</main></body></html>"""


def pct(x, d=1):
    return "–" if x is None else f"{100 * x:.{d}f}%"


def chart(setups: dict, compact: bool = False) -> str:
    """Dot (share kept) and line (95% interval) per setup. The wide version puts labels left of
    the plot; the compact one (phones) puts each label on its own line above its interval."""
    order = SETUPS
    w, row, left, right, top = (360, 46, 0, 8, 30) if compact else (860, 34, 300, 40, 24)
    lo, hi = 0.85, 1.0
    h = row * len(order) + top + 16
    x = lambda v: left + (w - left - right) * (v - lo) / (hi - lo)  # noqa: E731
    cls = "chart compact" if compact else "chart wide"
    parts = [f'<svg class="{cls}" viewBox="0 0 {w} {h}" role="img" aria-label="Share of critical facts kept, by rewriting setup, with 95% intervals" style="width:100%;height:auto">']
    for t in (0.85, 0.90, 0.95, 1.0):
        anchor = "start" if t == lo and compact else "end" if t == hi and compact else "middle"
        parts.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="10" y2="{h - 24}"/><text x="{x(t):.1f}" y="{h - 6}" text-anchor="{anchor}">{int(t * 100)}%</text>')
    for i, sname in enumerate(order):
        r = setups[sname]
        y = top + i * row + (14 if compact else 0)
        a_, b_ = r["ci"]
        g = "row ref" if sname == "original" else "row"
        tip = f'{r["label"]}: {pct(r["retention"])} of critical facts kept (95% range {pct(a_)} to {pct(b_)}); reading grade {r["grade_median"]}'
        label = (f'<text class="lab" x="0" y="{y - 12}">{e(r["label"])} · {pct(r["retention"])}</text>' if compact
                 else f'<text class="lab" x="0" y="{y + 4}">{e(r["label"])}</text>')
        value = "" if compact else (f'<text x="{x(b_) + 8:.1f}" y="{y + 4}">{pct(r["retention"])}</text>' if x(b_) + 60 < w
                                    else f'<text x="{x(max(lo, a_)) - 8:.1f}" y="{y + 4}" text-anchor="end">{pct(r["retention"])}</text>')
        parts.append(f'<g class="{g}"><title>{e(tip)}</title><rect class="hit" x="0" y="{y - row / 2 - (6 if compact else 0)}" width="{w}" height="{row}" fill="transparent"/>'
                     f'{label}<line class="ci" x1="{x(max(lo, a_)):.1f}" x2="{x(b_):.1f}" y1="{y}" y2="{y}"/>'
                     f'<circle cx="{x(r["retention"]):.1f}" cy="{y}" r="5"/>{value}</g>')
    parts.append("</svg>")
    return "".join(parts)


def table(setups: dict) -> str:
    rows = "".join(
        f'<tr><th scope=row>{e(r["label"])}</th><td class=num>{pct(r["retention"])}</td><td class=num>{pct(r["ci"][0])}–{pct(r["ci"][1])}</td>'
        f'<td class=num>{r["lost_per_rewrite"]:.1f}</td><td class=num>{pct(r["any_loss"], 0)}</td><td class=num>{r["grade_median"]}</td>'
        f'<td class=num>{int(r["words_median"])}</td></tr>' for s, r in ((s, setups[s]) for s in SETUPS))
    return ('<div class="scroll"><table><thead><tr><th></th><th class=num>Critical facts kept</th><th class=num>95% range</th>'
            '<th class=num>Lost per letter</th><th class=num>Letters with a loss</th><th class=num>Reading grade</th><th class=num>Words</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def highlight(text: str, quotes: list[str]) -> str:
    spans = sorted({find(q, text) for q in quotes if q and find(q, text)})
    out, last = [], 0
    for a, b in spans:
        if a < last:
            continue
        out.append(e(text[last:a]))
        out.append(f'<mark class="f">{e(text[a:b])}</mark>')
        last = b
    out.append(e(text[last:]))
    return "".join(out)


def notice_page(nid: str, res: dict, split: dict) -> str:
    n = load(nid)
    rows = {(r["setup"], r["sample"]): r for r in res["rows"] if r["notice"] == nid}
    texts = {(r["setup"], r["sample"]): r["text"] for r in rewrites([nid], SETUPS, 2)}
    from .analyze import verdict_rows
    verdicts = {(r["setup"], r["sample"]): r["verdicts"] for r in verdict_rows("sonnet") if r["notice"] == nid}
    blocks = []
    for s in SETUPS:
        if s == "original" or (s, 0) not in rows:
            continue
        r = rows[(s, 0)]
        lost = "".join(f'<li><span class="tag {verdicts[(s, 0)][fid]["status"]}">{verdicts[(s, 0)][fid]["status"]}</span> '
                       f'{e(n.fact(fid).statement)}<br><span class="muted">The letter: “{e(n.fact(fid).quote)}”'
                       + (f' · The rewrite: “{e(" … ".join(verdicts[(s, 0)][fid]["evidence"])[:300])}”' if verdicts[(s, 0)][fid]["evidence"] else "")
                       + "</span></li>" for fid in r["lost"])
        blocks.append(f'<details><summary>{e(LABEL[s])}: {r["kept"]} of {r["critical"]} critical facts kept · grade {r["grade"]}</summary>'
                      f'{"<h3>What the judge found lost or changed</h3><ul class=loss>" + lost + "</ul>" if lost else "<p class=muted>The judge found nothing lost.</p>"}'
                      f'<h3>The rewrite</h3><div class="letter">{e(texts[(s, 0)])}</div></details>')
    crit = [f.quote for f in n.critical]
    meta = n.meta
    body = (f'<p class="muted"><a href="../index.html">All notices</a> · {"dev notice (used to tune the judge)" if nid in split["dev"] else "test notice"}</p>'
            f'<h1>{e(meta.get("title", nid))}</h1><p class="muted">{e(meta.get("agency", ""))} · source: <a href="{e(meta.get("url", ""))}">{e(meta.get("source", ""))}</a>'
            f' · {len(n.critical)} critical facts of {len(n.facts)}</p>'
            f'<p class="hint">Placeholders in the agency\'s template were filled with made-up values; see the notice\'s source file in the repo.</p>'
            f'<h2>Rewrites</h2>{"".join(blocks)}'
            f'<h2>The original letter</h2><p class="hint">Highlighted: the passages behind the {len(crit)} critical facts.</p>'
            f'<div class="letter">{highlight(n.text, crit)}</div>')
    return page(f"{meta.get('title', nid)}: plain-language bench", body, depth=1)


def index(res: dict, split: dict) -> str:
    s = res["setups"]
    g4, g6 = s["sonnet-g4"], s["sonnet-g6"]
    pairs = {k: v for p in res["preregistered"] for k, v in p.get("pairs", {}).items()}
    d46 = pairs["sonnet-g6 - sonnet-g4"]
    gate = res["gate"]
    human = res.get("human")
    notices = "".join(f'<li><a href="notices/{nid}.html">{e(load(nid).meta.get("title", nid))}</a> <span class="muted">({e(load(nid).meta.get("agency", ""))}'
                      f'{", dev" if nid in split["dev"] else ""})</span></li>' for nid in ids())
    caught = "".join(f'<tr><th scope=row>{k.title()}</th><td class=num>{v["k"]}/{v["n"]}</td></tr>' for k, v in gate["caught"].items())
    human_html = ""
    if human:
        names = {"losses": "Losses the judge reported", "kept-hard": "Conditions, rights and consequences it called kept",
                 "disagree": "Where the two judges or code disagreed", "claims": "Facts behind this page's examples",
                 "attention": "Planted deletions (answer known)", "repeat": "Repeated items (labeller's consistency)"}
        human_html = ("<h2>Checked by a person</h2><p>A person labelled 40 items without seeing which setup wrote the rewrite or what the judge said.</p>"
                      '<div class="scroll"><table><thead><tr><th></th><th class=num>Agreed with the judge</th><th class=num>Unsure</th></tr></thead><tbody>'
                      + "".join(f'<tr><th scope=row>{names.get(k, k)}</th><td class=num>{v["agree"]}/{v["n"]}</td><td class=num>{v["unsure"]}</td></tr>'
                                for k, v in human.items()) + "</tbody></table></div>")
    body = f"""
<h1>What gets lost when a government letter is rewritten in plain language?</h1>
<p class="lede">18 real federal notices (IRS, Medicare, VA), rewritten 8 ways by Claude, with every deadline, amount, right,
condition and contact the reader needs checked one by one. Results below are for the {res['notices']['test']} test notices.</p>
<div class="card big"><p>At grade 6, Claude's rewrites kept <b>{pct(g6['retention'], 0)}</b> of reader-critical facts. Pushing to grade 4
cost <b>{abs(d46['diff']) * 100:.0f} points</b> more (95% range {min(abs(c) for c in d46['ci']) * 100:.0f} to {max(abs(c) for c in d46['ci']) * 100:.0f}), and
{pct(g4['any_loss'], 0)} of grade-4 rewrites lost at least one critical fact.</p>
<p class="muted">Every other difference (bigger models, a "keep everything" prompt, the rewrite tool) was smaller than the gap between two
runs of the same setup ({res['noise']['mean_abs_diff'] * 100:.1f} points per letter on average).</p></div>

<h2>Critical facts kept, by setup</h2>
{chart(s)}{chart(s, compact=True)}
{table(s)}
<p class="hint">"Letters with a loss" needs care: the judge wrongly flags {pct(res['false_alarm_rate'])} of facts that were kept, so with about
30 critical facts per letter a perfect rewrite would still show a loss {pct(s['sonnet-g6']['false_loss_band'], 0)} of the time.
Reading grade is Flesch-Kincaid, measured on the rewrite; a grade says how long the words and sentences are, not whether anyone understands.</p>

<h2>How far the judge can be trusted</h2>
<p>Errors were planted in real rewrites that had been checked by hand, with the right answer known by construction. The judge (Claude Sonnet,
checked by code for exact quotes and values) caught:</p>
<div class="scroll"><table><thead><tr><th>Planted error</th><th class=num>Caught (test)</th></tr></thead><tbody>{caught}</tbody></table></div>
<p class="note">It's weakest on a "must" that becomes a "may" (the one type below the bar set in advance), and on unedited rewrites it agreed with
only {gate['agreement_on_unedited_rewrites'].get('changed', {}).get('k', 0)} of {gate['agreement_on_unedited_rewrites'].get('changed', {}).get('n', 0)}
subtle real changes found by hand, such as a 60-day deadline that dropped "in writing". So the numbers above are likely an
<b>upper bound</b> on what's kept.</p>
{human_html}

<h2>The notices</h2><ul>{notices}</ul>
<h2>How it was done</h2>
<ul><li>Facts were drafted by Claude Opus, checked by code (every quote must be in the letter, every sentence accounted for) and reviewed by hand,
then frozen before any rewrite was generated. "Critical" was decided by a written rule, not by the judge.</li>
<li>The judge prompt was tuned on three dev notices only, then frozen; the planted-error gate ran once on test notices.</li>
<li>Everything is in the repository: <a href="{REPO}">code, data, every rewrite and every verdict</a>. Total cost about ${res['cost_usd']['total']:.0f}.</li></ul>
"""
    return page("Plain-language bench", body)


def main():
    res = json.loads(sorted((ROOT / "results").glob("2*/results.json"))[-1].read_text())
    split = json.loads((ROOT / "corpus" / "split.json").read_text())
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "notices").mkdir(parents=True)
    (OUT / "index.html").write_text(index(res, split), encoding="utf-8")
    for nid in ids():
        (OUT / "notices" / f"{nid}.html").write_text(notice_page(nid, res, split), encoding="utf-8")
    shutil.copy(sorted((ROOT / "results").glob("2*/results.json"))[-1], OUT / "results.json")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
