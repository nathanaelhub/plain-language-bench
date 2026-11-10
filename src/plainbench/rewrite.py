"""The rewriting setups the benchmark compares.

The prompts are what someone at a nonprofit would plausibly type, not
engineered: the point is to measure what ordinary use loses. Every setup asks
for the letter between <letter> tags, and gets one retry if they're missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import llm

SYSTEM = "You are a helpful assistant."
EFFORT = "medium"  # fixed so results don't drift with a CLI default


@dataclass(frozen=True)
class Setup:
    name: str
    model: str
    grade: int
    keep: bool = False  # the "keep everything" instruction

    def prompt(self, letter: str) -> str:
        ask = (f"Rewrite this letter in plain language so that someone who reads at a {self.grade}th-grade level "
               f"can understand it.")
        if self.keep:
            ask += (" Keep every deadline, date, amount of money, condition, right and way to contact the "
                    "agency: the reader needs all of them.")
        return f"{ask} Put the rewritten letter between <letter> and </letter>.\n\n{letter}"


SETUPS = {s.name: s for s in [
    Setup("haiku-g6", "haiku", 6),
    Setup("sonnet-g6", "sonnet", 6),
    Setup("opus-g6", "opus", 6),
    Setup("sonnet-g4", "sonnet", 4),
    Setup("sonnet-g8", "sonnet", 8),
    Setup("sonnet-g6-keep", "sonnet", 6, keep=True),
]}


async def rewrite(setup: Setup, letter: str) -> dict:
    """{"text", "model", "cost_usd", "error", "attempts"}."""
    cost, model, last = 0.0, None, ""
    for attempt in (1, 2):
        ask = setup.prompt(letter) if attempt == 1 else (
            setup.prompt(letter) + "\n\nRemember to put the whole rewritten letter between <letter> and </letter>.")
        r = await llm.call(ask, SYSTEM, model=setup.model, effort=EFFORT)
        cost += r.cost_usd
        model = r.model or model
        if r.error:
            last = r.error
            continue
        text = llm.tagged(r.text, "letter")
        if text:
            return {"text": text, "model": model, "cost_usd": cost, "error": None, "attempts": attempt}
        last = "no <letter> tags in the reply"
    return {"text": None, "model": model, "cost_usd": cost, "error": last, "attempts": 2}
