"""Statistics, standard library only, so each can be checked by hand.

`bootstrap_ci` and `cohen_kappa` come from judge-audit (kappa generalized from
pass/fail to any labels). Added: Wilson intervals for small counts, and a
paired bootstrap that compares two setups on the same notices, which is much
tighter than comparing two separate intervals.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a proportion k/n that stays sensible at small n and at 0 or n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(stat: Callable[[list[str]], float | None], items: Sequence[str],
                 n: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float] | None:
    """Percentile CI for `stat` by resampling items (a notice's facts stay together)."""
    rng = random.Random(seed)
    items = list(items)
    if not items:
        return None
    draws = []
    for _ in range(n):
        s = stat([rng.choice(items) for _ in items])
        if s is not None:
            draws.append(s)
    if len(draws) < n // 2:
        return None
    draws.sort()
    return draws[int(alpha / 2 * len(draws))], draws[int((1 - alpha / 2) * len(draws)) - 1]


def paired_diff(a: Mapping[str, float], b: Mapping[str, float], n: int = 2000, seed: int = 0) -> dict:
    """Mean of a - b over the notices both setups have, with a bootstrap CI over notices."""
    common = sorted(a.keys() & b.keys())
    if not common:
        return {"n": 0, "diff": None, "ci": None}
    d = {k: a[k] - b[k] for k in common}
    mean = lambda ks: sum(d[k] for k in ks) / len(ks)  # noqa: E731
    return {"n": len(common), "diff": mean(common), "ci": bootstrap_ci(mean, common, n=n, seed=seed)}


def cohen_kappa(a: Mapping[str, object], b: Mapping[str, object]) -> float | None:
    """Agreement between two raters' labels on the items both labelled, beyond chance."""
    pairs = [(a[i], b[i]) for i in a.keys() & b.keys() if a[i] is not None and b[i] is not None]
    if not pairs:
        return None
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in ca) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def false_loss_band(f: float, n: int) -> float:
    """Chance that a rewrite losing nothing still shows at least one loss, if each of its
    n facts is wrongly flagged with probability f."""
    return 1 - (1 - f) ** n
