"""Draw the 40-item human check and write its review page.

Groups (from the plan), drawn with a fixed seed from the final Sonnet verdicts:
    losses       14  critical facts the judge called changed/missing, spread over setups
    kept-hard    12  critical condition/right/consequence facts judged kept
                     (6 from the pipeline and keep-facts setups, 6 from the others)
    disagree      6  Sonnet and Opus disagree, or code overrode/doubted the judge
    claims        4  facts behind claims in the README
    attention     2  planted deletions (the right answer is known: missing)
    repeat        2  two earlier items shown again (the labeller's own consistency)

The page never shows which setup wrote the rewrite or what the judge said.

    uv run python -m bench.sample      # writes labels/sample.json and labels/review.html
"""

from __future__ import annotations

import hashlib
import html
import json
import random
import re

from plainbench import log
from plainbench.facts import ROOT, ids, load
from plainbench.text import sentences

from . import plants
from .run import judge_key, rewrites

SEED = 20261110
SETUPS = ["haiku-g6", "sonnet-g6", "opus-g6", "sonnet-g4", "sonnet-g8", "sonnet-g6-keep", "sonnet-g6-pipeline"]
CLAIMS = [("irs-cp12", "sonnet-g6", 0, "F13"), ("irs-cp12", "sonnet-g6", 0, "F14"),
          ("cms-im", "sonnet-g6", 0, "F34"), ("va-claim-info", "sonnet-g6", 0, "F13")]
OUT = ROOT / "labels"
STOP = set("the a an and or of to in on for is are be your you we our us it this that with by at if will can may not do".split())


def words(t):
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in STOP and len(w) > 2}


def best_sentence(text: str, fact) -> str:
    fw = words(f"{fact.statement} {fact.quote} {fact.answer}")
    ss = [text[a:b] for a, b in sentences(text)]
    return max(ss, key=lambda s: len(fw & words(s))) if ss else ""


def draw() -> list[dict]:
    rng = random.Random(SEED)
    done = log.done(log.read(ROOT / "runs" / "judge.jsonl"))
    rows = rewrites(ids(), SETUPS, 2)
    cells = []  # (row, fact, sonnet verdict, opus verdict or None)
    for r in rows:
        s = done.get(judge_key(r, "sonnet"))
        if not s or not s.get("verdicts"):
            continue
        o = done.get(judge_key(r, "opus"))
        n = load(r["notice"])
        for f in n.critical:
            cells.append((r, f, s["verdicts"][f.id], (o or {}).get("verdicts", {}).get(f.id)))
    rng.shuffle(cells)
    taken: set = set()
    items = []

    def take(group, cell):
        r, f = cell[0], cell[1]
        k = (r["notice"], r["setup"], r["sample"], f.id)
        if k in taken:
            return False
        taken.add(k)
        items.append({"group": group, "notice": r["notice"], "setup": r["setup"], "sample": r["sample"], "fact": f.id,
                      "text": r["text"], "judge": cell[2]["status"], "opus": (cell[3] or {}).get("status")})
        return True

    # losses: one per setup first, then any
    losses = [c for c in cells if c[2]["status"] != "kept"]
    for s in SETUPS:
        for c in losses:
            if c[0]["setup"] == s and take("losses", c):
                break
    for c in losses:
        if sum(i["group"] == "losses" for i in items) >= 14:
            break
        take("losses", c)
    hard = [c for c in cells if c[2]["status"] == "kept" and c[1].type in ("condition", "right", "consequence")]
    for want, pool in ((6, [c for c in hard if c[0]["setup"] in ("sonnet-g6-pipeline", "sonnet-g6-keep")]),
                       (6, [c for c in hard if c[0]["setup"] not in ("sonnet-g6-pipeline", "sonnet-g6-keep")])):
        got = 0
        for c in pool:
            if got >= want:
                break
            got += take("kept-hard", c)
    dis = [c for c in cells if (c[3] and c[3]["status"] != c[2]["status"]) or c[2].get("overridden") or c[2].get("unverified")]
    got = 0
    for c in dis:
        if got >= 6:
            break
        got += take("disagree", c)
    by_key = {(c[0]["notice"], c[0]["setup"], c[0]["sample"], c[1].id): c for c in cells}
    for k in CLAIMS:
        if k in by_key:
            take("claims", by_key[k])
    # attention checks: planted deletions, shown as if they were rewrites
    vs = [v for v in json.loads(plants.PLANTS.read_text()) if v["kind"] == "DELETE" and v["split"] == "test"]
    rng.shuffle(vs)
    for v in vs[:2]:
        items.append({"group": "attention", "notice": v["base"], "setup": "planted", "sample": 0, "fact": v["target"],
                      "text": v["text"], "judge": None, "opus": None, "truth": "missing"})
    rng.shuffle(items)
    for it in rng.sample([i for i in items if i["group"] != "attention"], 2):
        items.append({**it, "group": "repeat", "repeat_of": items.index(it)})
    for i, it in enumerate(items):
        n = load(it["notice"])
        f = n.fact(it["fact"])
        it.update({"n": i + 1, "question": f.question, "answer": f.answer, "source_quote": f.quote,
                   "statement": f.statement, "hint": best_sentence(it["text"], f)})
    return items


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Plain-language check: review</title>
<style>
:root{--bg:#f7f5f0;--panel:#fff;--ink:#1d2320;--muted:#5b625e;--line:#dcd8cf;--accent:#1f5f8a;--mark:#fbefd5}
@media (prefers-color-scheme:dark){:root{--bg:#141618;--panel:#1c1f22;--ink:#e8ebe9;--muted:#a3aba7;--line:#31363a;--accent:#8cc3ea;--mark:#3a3020}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 4px}.muted{color:var(--muted);font-size:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}
.q{font-size:18px;font-weight:600}.rewrite{white-space:pre-wrap;max-height:55vh;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:12px;font-size:15px}
mark{background:var(--mark);color:inherit}.btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;min-height:42px}
button.on{background:var(--accent);color:var(--panel);border-color:var(--accent)}input{font:inherit;width:100%;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink)}
.bar{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
</style></head><body><main>
<h1>Did the rewrite keep this fact?</h1>
<p class="muted">40 items, about 30 seconds each. For each: read the question and the answer the original letter gives, then decide
from the <b>rewrite alone</b> whether a reader would know the same thing. <b>Kept</b>: same meaning, values and conditions (different
words are fine). <b>Changed</b>: it's there but different or less: another value, vaguer, a lost condition, "must" became "may".
<b>Missing</b>: not there. <b>Unsure</b> is fine. Keys: k / c / m / u, n = next, p = back. Your answers save in this browser;
press <b>Download labels</b> at the end and send me the file.</p>
<div class="bar"><span id="pos" class="muted"></span><span><button id="prev">Back (p)</button> <button id="next">Next (n)</button>
<button id="dl">Download labels</button></span></div>
<div id="item"></div>
</main>
<script>
const ITEMS = __ITEMS__;
const KEY = "plainbench-labels-__HASH__";
let labels = {}; try { labels = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
let i = 0;
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function save(){ try { localStorage.setItem(KEY, JSON.stringify(labels)); } catch (e) {} }
function render(){
  const it = ITEMS[i], lab = labels[it.n] || {};
  let rw = esc(it.text); const h = esc(it.hint);
  if (h && rw.includes(h)) rw = rw.replace(h, "<mark>" + h + "</mark>");
  document.getElementById("pos").textContent = `Item ${i+1} of ${ITEMS.length} · ${Object.keys(labels).length} answered`;
  document.getElementById("item").innerHTML = `<div class="card"><div class="q">${esc(it.question)}</div>
   <p>The original letter's answer: <b>${esc(it.answer)}</b><br><span class="muted">Original wording: “${esc(it.source_quote)}”</span></p>
   <div class="btns">${["kept","changed","missing","unsure"].map(s=>`<button data-s="${s}" class="${lab.status===s?"on":""}">${s[0].toUpperCase()+s.slice(1)} (${s[0]})</button>`).join("")}</div>
   <p><input id="note" placeholder="Optional note" value="${esc(lab.note||"")}"></p></div>
   <div class="card"><div class="muted">The rewrite (the sentence with the most words in common is highlighted, but read around it):</div>
   <div class="rewrite">${rw}</div></div>`;
  document.querySelectorAll("[data-s]").forEach(b => b.onclick = () => set(b.dataset.s));
  document.getElementById("note").oninput = e => { labels[it.n] = {...(labels[it.n]||{}), note: e.target.value}; save(); };
}
function set(s){ const it = ITEMS[i]; labels[it.n] = {...(labels[it.n]||{}), status: s}; save(); render(); }
function go(d){ i = Math.max(0, Math.min(ITEMS.length-1, i+d)); render(); window.scrollTo(0,0); }
document.getElementById("prev").onclick = () => go(-1);
document.getElementById("next").onclick = () => go(1);
document.getElementById("dl").onclick = () => {
  const blob = new Blob([JSON.stringify({sample: "__HASH__", labels}, null, 1)], {type: "application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "labels-__HASH__.json"; a.click();
};
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  const m = {k:"kept", c:"changed", m:"missing", u:"unsure"}[e.key];
  if (m) set(m); else if (e.key === "n") go(1); else if (e.key === "p") go(-1);
});
render();
</script></body></html>
"""


def main():
    items = draw()
    blob = json.dumps(items, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(blob.encode()).hexdigest()[:10]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sample.json").write_text(json.dumps({"hash": h, "seed": SEED, "items": items}, indent=1, ensure_ascii=False) + "\n")
    public = [{k: it[k] for k in ("n", "question", "answer", "source_quote", "text", "hint")} for it in items]
    page = PAGE.replace("__ITEMS__", json.dumps(public, ensure_ascii=False).replace("</", "<\\/")).replace("__HASH__", h)
    (OUT / "review.html").write_text(page, encoding="utf-8")
    from collections import Counter
    print(len(items), "items", dict(Counter(i["group"] for i in items)), "hash", h)


if __name__ == "__main__":
    main()
