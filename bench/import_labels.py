"""Import the human labels from the review page's download, refusing a mismatched or partial file.

    uv run python -m bench.import_labels ~/Downloads/labels-<hash>.json
"""

from __future__ import annotations

import json
import shutil
import sys

from plainbench.facts import ROOT

STATUSES = {"kept", "changed", "missing", "unsure"}


def main(path: str) -> None:
    sample = json.loads((ROOT / "labels" / "sample.json").read_text())
    got = json.loads(open(path, encoding="utf-8").read())
    if got.get("sample") != sample["hash"]:
        sys.exit(f"this file is for sample {got.get('sample')}, the current sample is {sample['hash']}")
    labels = got.get("labels", {})
    missing = [it["n"] for it in sample["items"] if str(it["n"]) not in labels or labels[str(it["n"])].get("status") not in STATUSES]
    if missing:
        sys.exit(f"{len(missing)} item(s) have no answer yet: {missing}")
    dest = ROOT / "labels" / f"human-{sample['hash']}.json"
    shutil.copy(path, dest)
    print(f"imported {len(labels)} labels to {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1])
