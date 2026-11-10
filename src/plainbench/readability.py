"""Flesch-Kincaid grade level, one implementation for every text in the benchmark.

Taken from nonprofit-ai-workshop's `readability.grade`, with three changes
found when comparing the three versions in this portfolio:
- markdown (links, emphasis, table bars) is stripped first, as the TN benefits
  screener does, so formatting doesn't count as words;
- sentences come from `text.sentences`, so each bullet item counts as a
  sentence but headings, sign-offs and address lines are left out (they're
  short fragments that would pull the grade down for free);
- the syllable counter keeps a final "-le" and "-ee" as syllables ("table",
  "agree").

A reading grade measures sentence and word length, not understanding: a
rewrite can reach grade 4 by dropping every condition. That's the point of
the benchmark, so the grade is always reported next to what was kept.
"""

from __future__ import annotations

import re

from .text import LIST, sentences

SIGNOFF = re.compile(r"^\s*(sincerely|respectfully|regards|thank you|enclosures?|cc|dear|to|from|re|date|"
                     r"subject|attachment)\b.{0,40}$", re.I)
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def strip_markdown(text: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"[*_`|>]", " ", text)


def is_heading(line: str) -> bool:
    s = line.strip()
    if s.startswith("#"):
        return True
    # a short line with no sentence punctuation that isn't a list item: "What we need", "Time limit"
    return not LIST.match(line) and len(WORD.findall(s)) <= 6 and not re.search(r"[.!?:;,]$", s)


def units(text: str) -> list[str]:
    """The sentences that count: list items included, headings and sign-off lines left out."""
    t = strip_markdown(text)
    out = []
    for a, b in sentences(t):
        s = t[a:b]
        if is_heading(s) or SIGNOFF.match(s):
            continue
        s = re.sub(r"^\s*([-*•]|\d{1,2}[.)]|[a-z][.)])\s+", "", s)
        if WORD.search(s):
            out.append(s)
    return out


def measure(text: str) -> dict:
    """{grade, words, sentences, words_per_sentence, syllables_per_word}; grade is None
    under 30 words, where the formula means little."""
    us = units(text)
    words = [w for u in us for w in WORD.findall(u)]
    n_w, n_s = len(words), len(us)
    if not n_w or not n_s:
        return {"grade": None, "words": n_w, "sentences": n_s, "words_per_sentence": None, "syllables_per_word": None}
    wps, spw = n_w / n_s, sum(map(syllables, words)) / n_w
    return {"grade": round(0.39 * wps + 11.8 * spw - 15.59, 1) if n_w >= 30 else None, "words": n_w,
            "sentences": n_s, "words_per_sentence": round(wps, 1), "syllables_per_word": round(spw, 2)}


def grade(text: str) -> float | None:
    return measure(text)["grade"]
