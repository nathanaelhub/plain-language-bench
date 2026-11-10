"""Planted errors in real, hand-aligned rewrites, with labels known by construction.

Each variant changes one fact of an aligned rewrite (labels/align/*.json) in one
way, and `label_plant` works out every fact's true status from character spans:

- the target gets the planted label;
- another fact whose every span was removed becomes "missing";
- another fact with at least one span untouched, and no dependency link to the
  target either way, keeps its aligned status (these are scored for false alarms);
- anything else (partly overlapped, or linked to the target) is EXCLUDED: never guessed.

Plant types:
    DELETE      remove the sentence(s)/list item(s) holding every span of the fact -> missing
    VALUE       a plausible change to a date, amount, duration or phone number    -> changed
    CONDITION   cut a condition fact's clause                                      -> missing
    ALTERNATIVE drop one "or ..." alternative inside the fact                      -> changed
    MODAL       must->may, cannot->can, will not->will, ...                        -> changed
    VAGUE       a date/duration becomes "soon", a phone number disappears           -> changed
    NULL        meaning-preserving edits (contractions, numbers as words)           -> no change

    uv run python -m bench.plants build      # writes runs/plants.json
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass

from bench.align import ALIGN, rewrite_text
from plainbench.facts import ROOT, load
from plainbench.text import sentences
from plainbench.values import extract

PLANTS = ROOT / "runs" / "plants.json"
EXCLUDED = "EXCLUDED"
MODAL = [(r"\bmust\b", "may"), (r"\bwill not\b", "will"), (r"\bwon't\b", "will"), (r"\bcannot\b", "can"),
         (r"\bcan't\b", "can"), (r"\bdo not need to\b", "need to"), (r"\bdon't need to\b", "need to"),
         (r"\bhave the right to\b", "may be able to"), (r"\bwill\b", "may"), (r"\bcan\b", "cannot")]
NULL = [(r"\bdo not\b", "don't"), (r"\bwill not\b", "won't"), (r"\byou will\b", "you'll"), (r"\bwe will\b", "we'll"),
        (r"\bdoes not\b", "doesn't"), (r"\bcannot\b", "can't"), (r"\b30 days\b", "thirty days"),
        (r"\b60 days\b", "sixty days"), (r"\b2 days\b", "two days")]
COUNTS = {"DELETE": 3, "VALUE": 5, "CONDITION": 2, "ALTERNATIVE": 2, "MODAL": 3, "VAGUE": 4, "NULL": 2}


@dataclass
class Variant:
    id: str
    base: str  # notice id
    split: str
    kind: str
    target: str | None
    text: str
    labels: dict  # fid -> kept|changed|missing|EXCLUDED
    edit: str  # what was done, for the record


# ---- edits: return (new text, list of (start, end) ranges in the OLD text that changed) ----

def apply(text: str, ranges: list[tuple[int, int]], repl: list[str]) -> str:
    out, last = [], 0
    for (a, b), r in sorted(zip(ranges, repl)):
        out.append(text[last:a])
        out.append(r)
        last = b
    out.append(text[last:])
    return "".join(out)


def tidy(text: str) -> str:
    """Clean what a cut leaves behind: a comma opening a sentence or bullet, doubled spaces."""
    text = re.sub(r"(^|[-*•]\s|[.!?:]\s)\s*,\s*([a-z])", lambda m: m.group(1) + m.group(2).upper(), text, flags=re.M)
    text = re.sub(r",\s*,", ",", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def spans_of(rw: str, al: dict, fid: str) -> list[tuple[int, int]]:
    out = []
    for s in al[fid]["spans"]:
        i = rw.find(s)
        while i >= 0:
            out.append((i, i + len(s)))
            i = rw.find(s, i + 1)
    return out


def units_covering(rw: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The sentence/list-item units that overlap any of the spans (merged)."""
    us = [(a, b) for a, b in sentences(rw) if any(a < y and x < b for x, y in spans)]
    return us


# ---- labels ----

def overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def label_plant(notice, rw: str, al: dict, target: str | None, planted: str | None,
                changed_ranges: list[tuple[int, int]], removal: bool) -> dict:
    """Every fact's true status after an edit to `changed_ranges` of the aligned rewrite `rw`.
    `removal` says the ranges were deleted (vs replaced)."""
    linked = set()
    if target:
        t = notice.fact(target)
        linked = set(t.depends_on) | {f.id for f in notice.facts if target in f.depends_on}
    labels = {}
    for f in notice.facts:
        base = al[f.id]["status"]
        if f.id == target:
            labels[f.id] = planted
        elif f.id in linked:
            labels[f.id] = EXCLUDED
        else:
            sp = spans_of(rw, al, f.id)
            untouched = [x for x in sp if all(overlap(x, r) == 0 for r in changed_ranges)]
            if not sp or untouched:
                labels[f.id] = base  # still stated somewhere the edit didn't reach
            elif removal and all(any(r[0] <= x[0] and x[1] <= r[1] for r in changed_ranges) for x in sp):
                labels[f.id] = "missing"  # every place it was stated is gone
            else:
                labels[f.id] = EXCLUDED  # partly touched: never guessed
    return labels


# ---- builders ----

def delete(rw, al, fid):
    sp = spans_of(rw, al, fid)
    us = units_covering(rw, sp)
    if not us:
        return None
    return apply(rw, us, [""] * len(us)), us, f"deleted {len(us)} unit(s)"


def value(rw, al, fid, notice):
    """Change the fact's value in EVERY place the fact is stated; skip if the old value
    would still appear anywhere in the rewrite (then the fact isn't really changed)."""
    need = notice.fact(fid).needed_values()
    edits = []
    for a, b in spans_of(rw, al, fid):
        hit = None
        for v in extract(rw[a:b]):
            ok = (v.kind, v.value) in need or any(k in ("money", "number") and x == v.value for k, x in need)
            if ok:
                new = _plausible(v.kind, rw[a + v.start:a + v.end])
                if new and new != rw[a + v.start:a + v.end]:
                    hit = (a + v.start, a + v.end, new)
                    break
        if not hit:
            return None
        edits.append(hit)
    if not edits:
        return None
    edits = sorted(set(edits))
    out = apply(rw, [(s_, e_) for s_, e_, _ in edits], [n_ for _, _, n_ in edits])
    olds = {rw[s_:e_] for s_, e_, _ in edits}
    if any(o in out for o in olds):
        return None
    return out, [(s_, e_) for s_, e_, _ in edits], f"value {sorted(olds)} -> {[n_ for *_, n_ in edits]}"


def _plausible(kind: str, old: str) -> str | None:
    if kind == "date":
        m = re.search(r"\b(\d{1,2})(st|nd|rd|th)?\b(?!,?\s*\d{3})", old)
        if m and not re.fullmatch(r"\d{4}", m.group(1)):
            d = int(m.group(1))
            nd = d + 7 if d <= 21 else d - 7
            return old[:m.start(1)] + str(nd) + old[m.end(1):]
        return None
    if kind == "duration":
        m = re.search(r"\d+", old)
        if m:
            n = int(m.group())
            return old[:m.start()] + str(n * 2 if n > 1 else 2) + old[m.end():]
        words = {"two": "four", "three": "six", "one": "two", "six": "twelve", "thirty": "sixty"}
        for w, r in words.items():
            if re.search(rf"\b{w}\b", old, re.I):
                new = re.sub(rf"\b{w}\b", r, old, count=1, flags=re.I)
                return re.sub(r"\b(day|week|month|year|hour)\b(?!s)", r"\1s", new) if w == "one" else new
        return None
    if kind == "phone":
        m = re.search(r"(\d)(\D*)$", old)
        return old[:m.start(1)] + str((int(m.group(1)) + 1) % 10) + m.group(2) if m else None
    if kind in ("money", "number"):
        m = re.search(r"\d[\d,]*(?:\.\d+)?", old)
        if not m:
            return None
        x = float(m.group().replace(",", ""))
        y = round(x * 1.5, 2)
        txt = f"{y:,.2f}" if "." in m.group() else f"{int(y):,}" if "," in m.group() else str(int(y))
        return old[:m.start()] + txt + old[m.end():]
    return None


def condition(rw, al, fid):
    sp = spans_of(rw, al, fid)
    if not sp:
        return None
    # a span that's a clause (shorter than its sentence): cut just it; otherwise cut the sentence
    ranges = []
    for a, b in sp:
        unit = next(((x, y) for x, y in sentences(rw) if x <= a and b <= y), None)
        ranges.append((a, b) if unit and (b - a) < (unit[1] - unit[0]) * 0.8 else (unit or (a, b)))
    ranges = sorted(set(ranges))
    return tidy(apply(rw, ranges, [""] * len(ranges))), ranges, "cut the condition"


def alternative(rw, al, fid):
    for a, b in spans_of(rw, al, fid):
        m = re.search(r",? or ([^.,;:\n]{3,80})", rw[a:b])
        if m:
            s, e = a + m.start(), a + m.end()
            return rw[:s] + rw[e:], [(s, e)], f"dropped alternative {rw[s:e]!r}"
    return None


MODAL_TYPES = {"action", "right", "consequence", "deadline", "condition"}


def modal(rw, al, fid, notice):
    """Flip a modal in every span of the fact; only facts whose spans are single sentences,
    so the flipped word belongs to this fact and not a neighbour."""
    if notice.fact(fid).type not in MODAL_TYPES:
        return None
    units = sentences(rw)
    edits = []
    for a, b in spans_of(rw, al, fid):
        if sum(1 for x, y in units if a < y and x < b) != 1:
            return None
        seg, hit = rw[a:b], None
        for pat, rep in MODAL:
            m = re.search(pat, seg, re.I)
            if m:
                hit = (a + m.start(), a + m.end(), rep)
                break
        if not hit:
            return None
        edits.append(hit)
    if not edits:
        return None
    edits = sorted(set(edits))
    return (apply(rw, [(s_, e_) for s_, e_, _ in edits], [r for *_, r in edits]), [(s_, e_) for s_, e_, _ in edits],
            f"{[rw[s_:e_] for s_, e_, _ in edits]} -> {[r for *_, r in edits]}")


def _vague_one(rw, a, b, need):
    for v in extract(rw[a:b]):
        if (v.kind, v.value) not in need and not any(v.value.endswith(x[-5:]) for k, x in need if k == v.kind == "date"):
            continue  # only a value this fact itself needs
        s, e = a + v.start, a + v.end
        if v.kind in ("date", "duration"):
            if rw[e:e + 4] == " of " or rw[e:e + 6] == " from ":
                continue  # "within 3 years of the day ..." has no natural vague form
            pre = re.search(r"\b(by|before|within|in|on|than)\s+$", rw[max(a, s - 9):s], re.I)
            if not pre or pre.group(1).lower() == "than":
                continue
            s -= len(pre.group())
            word = "recently" if pre.group(1).lower() == "on" else "soon"
            return s, e, word.capitalize() if rw[s:s + 1].isupper() else word
        if v.kind == "phone":
            pre = re.search(r"\s*(at|on)?\s*$", rw[max(a, s - 4):s])
            return s - (len(pre.group()) if pre else 0), e, ""
    return None


def vague(rw, al, fid, notice):
    need = notice.fact(fid).needed_values()
    edits = []
    for a, b in spans_of(rw, al, fid):
        hit = _vague_one(rw, a, b, need)
        if not hit:
            return None
        edits.append(hit)
    if not edits:
        return None
    edits = sorted(set(edits))
    out = apply(rw, [(s_, e_) for s_, e_, _ in edits], [r for *_, r in edits])
    removed = [rw[s_:e_].strip() for s_, e_, _ in edits]
    if any(re.sub(r"^(at|on|by|before|within|in)\s+", "", r, flags=re.I) in out for r in removed):
        return None  # the value is still stated elsewhere
    for s_, e_, r in edits:
        line_start = out.rfind("\n", 0, s_) + 1
        line_end = out.find("\n", s_)
        line = out[line_start: line_end if line_end >= 0 else len(out)]
        if re.search(r"\*\*\s*\*\*|(phone|number|tty)\W*(is)?\W*$|\bcall\s+or\b|\bcall\W*$", line, re.I):
            return None  # the hole would show ("Their phone number is ****.")
    return out, [(s_, e_) for s_, e_, _ in edits], f"{removed} -> {[r or '(removed)' for *_, r in edits]}"


def null(rw, rng):
    hits = [(m.start(), m.end(), rep) for pat, rep in NULL for m in re.finditer(pat, rw, re.I)]
    if not hits:
        return None
    rng.shuffle(hits)
    chosen, used = [], []
    for s, e, rep in hits:
        if all(e <= a or s >= b for a, b in used):
            chosen.append((s, e, rep))
            used.append((s, e))
        if len(chosen) >= 3:
            break
    chosen.sort()
    reps = [r[0].upper() + r[1:] if rw[s].isupper() else r for s, e, r in chosen]
    return apply(rw, [(s, e) for s, e, _ in chosen], reps), [], f"{len(chosen)} meaning-preserving edit(s)"


def build(seed: int = 20261110) -> list[Variant]:
    split = json.loads((ROOT / "corpus" / "split.json").read_text())
    out: list[Variant] = []
    for p in sorted(ALIGN.glob("*.json")):
        nid, setup, sample = p.stem.split("__")
        n, rw, al = load(nid), rewrite_text(nid, setup, int(sample)), json.loads(p.read_text())
        sp = "dev" if nid in split["dev"] else "test"
        rng = random.Random(f"{seed}/{nid}")
        out.append(Variant(f"{nid}/BASE", nid, sp, "BASE", None, rw, {f: al[f]["status"] for f in al}, "no edit"))
        kept = [f.id for f in n.facts if f.critical and al[f.id]["status"] == "kept" and al[f.id]["spans"]]
        for kind, k in COUNTS.items():
            pool = list(kept)
            rng.shuffle(pool)
            made = 0
            if kind == "NULL":
                for i in range(k):
                    r = null(rw, random.Random(f"{seed}/{nid}/null/{i}"))
                    if r:
                        text, ranges, what = r
                        out.append(Variant(f"{nid}/NULL{i}", nid, sp, kind, None, text,
                                           {f: al[f]["status"] for f in al}, what))
                continue
            if kind == "CONDITION":
                pool = [f for f in pool if n.fact(f).type == "condition"]
            for fid in pool:
                if made >= k:
                    break
                fn = {"DELETE": lambda: delete(rw, al, fid), "VALUE": lambda: value(rw, al, fid, n),
                      "CONDITION": lambda: condition(rw, al, fid), "ALTERNATIVE": lambda: alternative(rw, al, fid),
                      "MODAL": lambda: modal(rw, al, fid, n), "VAGUE": lambda: vague(rw, al, fid, n)}[kind]
                r = fn()
                if not r:
                    continue
                text, ranges, what = r
                planted = "missing" if kind in ("DELETE", "CONDITION") else "changed"
                labels = label_plant(n, rw, al, fid, planted, ranges, removal=kind in ("DELETE", "CONDITION", "ALTERNATIVE"))
                out.append(Variant(f"{nid}/{kind}/{fid}", nid, sp, kind, fid, text, labels, what))
                made += 1
    return out


def main():
    vs = build()
    PLANTS.write_text(json.dumps([asdict(v) for v in vs], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    from collections import Counter
    print(len(vs), "variants;", dict(Counter((v.split, v.kind) for v in vs)))
    ex = sum(1 for v in vs for x in v.labels.values() if x == EXCLUDED)
    print("excluded fact labels:", ex)


if __name__ == "__main__":
    main()
