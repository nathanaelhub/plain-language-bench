"""A resumable JSONL log of model calls, with a spending cap.

Every call is one line. A call is identified by a key built from what makes it
what it is (stage, setup, notice, sample, and the hash of the prompt it was
sent), so changing a prompt runs it again instead of mixing old and new
answers. Calls that errored are retried on the next run. `run` stops starting
new calls once the logged cost plus what's in flight reaches `max_usd`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path


def phash(*parts: str) -> str:
    return hashlib.sha256("\n\x1f\n".join(parts).encode()).hexdigest()[:12]


def key(**parts) -> str:
    return "|".join(f"{k}={parts[k]}" for k in sorted(parts))


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def done(rows: list[dict]) -> dict[str, dict]:
    """The latest successful row for each key."""
    out = {}
    for r in rows:
        if not r.get("error"):
            out[r["key"]] = r
    return out


def spent(rows: list[dict]) -> float:
    return round(sum(r.get("cost_usd") or 0 for r in rows), 4)


@dataclass
class Task:
    key: str
    run: Callable[[], Awaitable[dict]]  # returns the row's fields; must include cost_usd and error


async def run(tasks: list[Task], path: Path, concurrency: int = 4, max_usd: float | None = None,
              est_usd: float = 0.05, progress: Callable[[str], None] = print) -> dict:
    """Run the tasks whose keys aren't already done. Returns counts and cost."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = read(path)
    finished_keys = done(rows)
    todo = [t for t in tasks if t.key not in finished_keys]
    budget = {"spent": spent(rows), "in_flight": 0.0}
    progress(f"{len(todo)} calls to make, {len(tasks) - len(todo)} already done; "
             f"${budget['spent']:.2f} spent so far in {path.name}")
    sem, lock = asyncio.Semaphore(concurrency), asyncio.Lock()
    stats = {"made": 0, "errors": 0, "skipped_budget": 0}

    async def one(t: Task) -> None:
        async with sem:
            async with lock:
                if max_usd is not None and budget["spent"] + budget["in_flight"] + est_usd > max_usd:
                    stats["skipped_budget"] += 1
                    return
                budget["in_flight"] += est_usd
            t0 = time.monotonic()
            try:
                row = await t.run()
            except Exception as exc:  # a bug in one task shouldn't lose the others' results
                row = {"cost_usd": 0.0, "error": f"{type(exc).__name__}: {exc}"[:300]}
            row = {"key": t.key, **row, "seconds": round(time.monotonic() - t0, 1)}
        async with lock:
            budget["in_flight"] -= est_usd
            budget["spent"] += row.get("cost_usd") or 0
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            stats["made"] += 1
            stats["errors"] += bool(row.get("error"))
            if row.get("error") or stats["made"] % 20 == 0 or stats["made"] == len(todo):
                progress(f"  {stats['made']}/{len(todo)}  ${budget['spent']:.2f}"
                         + (f"  error on {t.key}: {row['error']}" if row.get("error") else ""))

    await asyncio.gather(*(one(t) for t in todo))
    if stats["skipped_budget"]:
        progress(f"stopped at the ${max_usd:.2f} cap: {stats['skipped_budget']} calls not started")
    return {**stats, "spent": round(budget["spent"], 4)}
