"""Hand alignment of benchmark facts to a real rewrite: the base for planted errors.

For each fact, this proposes the rewrite sentence(s) with the most content
words in common with the fact (no model involved), for a person to confirm or
correct. Decisions go in labels/align/<notice>__<setup>__<sample>.json:

    {"F1": {"status": "kept", "spans": ["exact text from the rewrite", ...]},
     "F2": {"status": "missing", "spans": []},
     "F3": {"status": "changed", "spans": ["..."], "note": "why"}}

Each span on its own states the whole fact (a fact repeated in the rewrite has
several). Spans must be exact substrings of the rewrite; `check` verifies.

    uv run python -m bench.align show NOTICE [--setup sonnet-g6 --sample 0]
    uv run python -m bench.align check
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from plainbench import log
from plainbench.facts import ROOT, load
from plainbench.text import sentences

ALIGN = ROOT / "labels" / "align"
STOP = set("the a an and or of to in on for is are be your you we our us it this that with by at if will can may not do".split())
BASES = {"dev": ["va-claim-info", "irs-cp21b", "cms-nomnc"], "test": ["irs-cp12", "cms-im", "va-enrollment"]}


def words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in STOP and len(w) > 2}


def rewrite_text(nid: str, setup: str = "sonnet-g6", sample: int = 0) -> str:
    rows = [r for r in log.read(ROOT / "runs" / "rewrites.jsonl")
            if r["notice"] == nid and r["setup"] == setup and r["sample"] == sample and not r.get("error")]
    return rows[-1]["text"]


def path(nid: str, setup: str = "sonnet-g6", sample: int = 0) -> Path:
    return ALIGN / f"{nid}__{setup}__{sample}.json"


def show(nid: str, setup: str, sample: int) -> None:
    n, rw = load(nid), rewrite_text(nid, setup, sample)
    sents = [rw[a:b] for a, b in sentences(rw)]
    print(f"===== {nid} / {setup} / {sample}\n")
    for i, s in enumerate(sents):
        print(f"  [{i}] {s}")
    print()
    for f in n.facts:
        fw = words(f"{f.statement} {f.quote} {f.answer}")
        ranked = sorted(range(len(sents)), key=lambda i: -len(fw & words(sents[i])))[:2]
        print(f"{f.id} {'C' if f.critical else '-'} {f.type[:5]} | {f.statement[:110]}")
        print(f"     suggest: {[(i, len(fw & words(sents[i]))) for i in ranked]}")


def check() -> list[str]:
    errs = []
    for p in sorted(ALIGN.glob("*.json")):
        nid, setup, sample = p.stem.split("__")
        n, rw = load(nid), rewrite_text(nid, setup, int(sample))
        a = json.loads(p.read_text())
        missing = [f.id for f in n.facts if f.id not in a]
        if missing:
            errs.append(f"{p.name}: facts not aligned: {missing}")
        for fid, d in a.items():
            if d["status"] not in ("kept", "changed", "missing"):
                errs.append(f"{p.name}/{fid}: bad status")
            if d["status"] == "kept" and not d["spans"]:
                errs.append(f"{p.name}/{fid}: kept with no span")
            for s in d["spans"]:
                if s not in rw:
                    errs.append(f"{p.name}/{fid}: span not an exact substring: {s[:60]!r}")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["show", "check"])
    ap.add_argument("notice", nargs="?")
    ap.add_argument("--setup", default="sonnet-g6")
    ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args(argv)
    if a.cmd == "show":
        show(a.notice, a.setup, a.sample)
    else:
        errs = check()
        print("\n".join(errs) or "all alignments check out")


if __name__ == "__main__":
    main()
