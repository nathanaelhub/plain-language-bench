"""plainbench rewrite LETTER [--grade 6] [--model sonnet] [--redact] [--out REPORT.md]
plainbench check LETTER REWRITE [--model sonnet] [--redact] [--out REPORT.md]

Rewrites a letter in plain language and checks that every deadline, amount,
right, condition and contact the reader needs is still there, or checks a
rewrite someone already wrote. The letter is sent to Claude through the
`claude` CLI: don't use it on letters with personal details unless you're
allowed to share them, and use --redact to replace Social Security, claim and
case numbers and street addresses with placeholders before sending.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import pipeline


def main(argv=None):
    ap = argparse.ArgumentParser(prog="plainbench", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rewrite", help="rewrite a letter and check nothing was lost")
    r.add_argument("letter", type=Path)
    r.add_argument("--grade", type=int, default=6)
    c = sub.add_parser("check", help="check a rewrite someone already wrote")
    c.add_argument("letter", type=Path)
    c.add_argument("rewrite", type=Path)
    for p in (r, c):
        p.add_argument("--model", default="sonnet")
        p.add_argument("--redact", action="store_true", help="replace SSNs, claim/case numbers and street addresses before sending")
        p.add_argument("--out", type=Path, help="write the report here (markdown); default: print it")
    a = ap.parse_args(argv)
    letter = a.letter.read_text(encoding="utf-8")
    if not a.redact:
        print("Note: the letter is sent to Claude. Use --redact to replace SSNs, claim/case numbers and addresses first.",
              file=sys.stderr)
    if a.cmd == "rewrite":
        res = asyncio.run(pipeline.run(letter, model=a.model, grade=a.grade, use_redact=a.redact))
    else:
        res = asyncio.run(pipeline.check(letter, a.rewrite.read_text(encoding="utf-8"), model=a.model, use_redact=a.redact))
    report = pipeline.markdown(res)
    if a.out:
        a.out.write_text(report, encoding="utf-8")
        print(f"wrote {a.out}  ({len(res.lost)} possible losses, ${res.cost_usd:.3f})", file=sys.stderr)
    else:
        print(report)
    return 1 if res.error else 0


if __name__ == "__main__":
    sys.exit(main())
