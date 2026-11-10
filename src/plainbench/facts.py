"""Notices and their key facts: loading, and the checks every fact list must pass.

See corpus/RULES.md for what a fact is and which facts are critical.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .text import find, sentences
from .values import extract, values

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
TYPES = {"deadline", "amount", "action", "consequence", "right", "condition", "contact", "subject"}
VALUE_TYPES = {"deadline", "amount", "contact"}  # their answer must carry a checkable value
KEYWORDS = re.compile(r"\b(must|may|if|unless|except|only|within|before|after|rights?|appeal|hearing|deny|denied|"
                      r"penalt(?:y|ies)|cannot|can't|will not|won't|required|responsible)\b", re.I)


@dataclass
class Fact:
    id: str
    type: str
    statement: str
    question: str
    answer: str
    quote: str
    critical: bool
    depends_on: list[str] = field(default_factory=list)

    def needed_values(self) -> set[tuple[str, str]]:
        """Values a rewrite must contain to keep this fact: those in its answer that the
        quote also has (bare numbers only for amounts)."""
        if self.type not in VALUE_TYPES:
            return set()
        a, q = values(self.answer), values(self.quote)
        if self.type == "amount":
            # "$963.00" in the answer, "– 963.00" in a billing table: same amount
            num = lambda vs: {v for k, v in vs if k in ("money", "number")}  # noqa: E731
            return {("number", v) for v in num(a) & num(q)} | {v for v in a & q if v[0] not in ("money", "number")}
        return {v for v in a & q if v[0] != "number"}


@dataclass
class Notice:
    id: str
    meta: dict
    text: str
    facts: list[Fact]
    sentences: list[dict]  # {"i", "start", "text", "facts": [...], "none": reason|None, "override": reason|None}
    path: Path

    def fact(self, fid: str) -> Fact:
        return next(f for f in self.facts if f.id == fid)

    @property
    def critical(self) -> list[Fact]:
        return [f for f in self.facts if f.critical]


def split_frontmatter(raw: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n", raw, re.S)
    if not m:
        return {}, raw
    meta: dict = {}
    cur = None
    for line in m.group(1).splitlines():
        if re.match(r"^\s+\S", line) and cur:
            k, _, v = line.strip().partition(":")
            meta[cur][k.strip().strip('"')] = v.strip()
        else:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if v == "":
                meta[k] = {}
                cur = k
            else:
                meta[k] = {"true": True, "false": False}.get(v, v.strip('"'))
                cur = None
    return meta, raw[m.end():].lstrip("\n")


def body(path: Path) -> tuple[dict, str]:
    return split_frontmatter(path.read_text(encoding="utf-8"))


def sentence_list(text: str) -> list[dict]:
    return [{"i": i, "start": a, "text": text[a:b]} for i, (a, b) in enumerate(sentences(text))]


def load(nid: str, corpus: Path = CORPUS) -> Notice:
    d = corpus / nid
    meta, text = body(d / "source.md")
    fj = d / "facts.json"
    facts, sents = [], []
    if fj.exists():
        data = json.loads(fj.read_text(encoding="utf-8"))
        facts = [Fact(**{k: f[k] for k in Fact.__dataclass_fields__ if k in f}) for f in data["facts"]]
        sents = data.get("sentences", [])
    return Notice(nid, meta, text, facts, sents, d)


def ids(corpus: Path = CORPUS) -> list[str]:
    return sorted(p.name for p in corpus.iterdir() if (p / "source.md").exists())


def markers(sentence: str) -> int:
    return len(extract(sentence)) + len(KEYWORDS.findall(sentence))


def problems(n: Notice) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a notice's fact list. Errors block the freeze."""
    errs, warns = [], []
    if not n.facts:
        return [f"{n.id}: no facts"], []
    seen = set()
    for f in n.facts:
        where = f"{n.id}/{f.id}"
        if f.id in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(f.id)
        if f.type not in TYPES:
            errs.append(f"{where}: unknown type {f.type!r}")
        for k in ("statement", "question", "answer", "quote"):
            if not str(getattr(f, k)).strip():
                errs.append(f"{where}: empty {k}")
        if f.quote and find(f.quote, n.text) is None:
            errs.append(f"{where}: quote not found in the notice: {f.quote[:70]!r}")
        if f.type == "condition" and not f.depends_on:
            errs.append(f"{where}: a condition must say which fact it limits (depends_on)")
        if f.type in VALUE_TYPES and not f.needed_values():
            warns.append(f"{where}: a {f.type} with no value shared by its answer and quote; code can't check it")
    for f in n.facts:
        for d in f.depends_on:
            if d not in seen:
                errs.append(f"{n.id}/{f.id}: depends_on {d!r} doesn't exist")
    current = sentence_list(n.text)
    if len(n.sentences) != len(current):
        errs.append(f"{n.id}: {len(n.sentences)} sentences accounted for, the notice has {len(current)}")
    else:
        for s, c in zip(n.sentences, current):
            where = f"{n.id}/sentence {c['i']}"
            if s.get("text", "")[:40] != c["text"][:40]:
                errs.append(f"{where}: accounting is for a different sentence ({s.get('text', '')[:40]!r})")
                continue
            fs = s.get("facts") or []
            for fid in fs:
                if fid not in seen:
                    errs.append(f"{where}: maps to unknown fact {fid}")
            if not fs:
                if not s.get("none"):
                    errs.append(f"{where}: maps to no facts and gives no reason")
                elif markers(c["text"]) and not s.get("override"):
                    errs.append(f"{where}: has markers ({c['text'][:60]!r}) but maps to no facts and has no override")
            elif markers(c["text"]) > len(fs) + 2:
                warns.append(f"{where}: {markers(c['text'])} markers but {len(fs)} facts; second look")
    mapped = {fid for s in n.sentences for fid in (s.get("facts") or [])}
    for f in n.facts:
        if f.id not in mapped:
            errs.append(f"{n.id}/{f.id}: no sentence maps to it")
    return errs, warns


def corpus_hash(corpus: Path = CORPUS) -> dict[str, str]:
    """sha256 of each notice's source and facts, for the freeze."""
    out = {}
    for nid in ids(corpus):
        d = corpus / nid
        h = hashlib.sha256()
        for name in ("source.md", "facts.json"):
            p = d / name
            h.update(p.read_bytes() if p.exists() else b"")
        out[nid] = h.hexdigest()[:16]
    return out
