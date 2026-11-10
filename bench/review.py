"""Apply a hand review to drafted fact lists: change fields, with a note saying why.

Each edit is (notice, fact, field, new value, reason). The notes are kept in
facts.json under review_notes, so what the reviewer changed is visible.

    uv run python -m bench.review
"""

from __future__ import annotations

import json

from plainbench.facts import CORPUS, ids, load, problems

REVIEWER = "Claude (in session), November 10, 2026"
NOT_CRITICAL = "not critical under the clarified rule"

EDITS = [
    # irs-cp14
    ("irs-cp14", "F3", "critical", False, "the notice's own date; " + NOT_CRITICAL),
    ("irs-cp14", "F31", "critical", False, "advice about calling; " + NOT_CRITICAL),
    *[("irs-cp14", f, "critical", False, "a feature of paying electronically; " + NOT_CRITICAL)
      for f in ("F34", "F35", "F36", "F37", "F38", "F39")],
    ("irs-cp14", "F40", "critical", False, "a convenience (paying by card); " + NOT_CRITICAL),
    ("irs-cp14", "F41", "critical", False, "the fee for the card convenience; " + NOT_CRITICAL),
    ("irs-cp14", "F48", "critical", False, "how to pay an accepted offer; " + NOT_CRITICAL),
    ("irs-cp14", "F49", "critical", False, "condition on a non-critical fact"),
    ("irs-cp14", "F51", "critical", False, "where to check eligibility; " + NOT_CRITICAL),
    ("irs-cp14", "F52", "critical", False, "general information website; " + NOT_CRITICAL),
    ("irs-cp14", "F53", "critical", False, "general information website; " + NOT_CRITICAL),
    # irs-cp21b
    ("irs-cp21b", "F3", "type", "subject", "the notice's own date, not a deadline"),
    ("irs-cp21b", "F3", "critical", False, "the notice's own date; " + NOT_CRITICAL),
    ("irs-cp21b", "F17", "critical", False, "advice about calling; " + NOT_CRITICAL),
    ("irs-cp21b", "F25", "critical", False, "advice about keeping the letter; " + NOT_CRITICAL),
    # cms-abn
    ("cms-abn", "F10", "critical", False, "advice about reading the notice; " + NOT_CRITICAL),
    ("cms-abn", "F11", "critical", False, "advice to ask questions; " + NOT_CRITICAL),
    ("cms-abn", "F13", "critical", False, "restates F12 (choose one option)"),
    ("cms-abn", "F37", "critical", False, "signing to acknowledge receipt; " + NOT_CRITICAL),
    # cms-nomnc
    ("cms-nomnc", "F28", "critical", False, "signing to acknowledge receipt; " + NOT_CRITICAL),
    # va-enrollment
    ("va-enrollment", "F11", "critical", False, "points to an enclosure; " + NOT_CRITICAL),
    ("va-enrollment", "F28", "critical", False, "points to an enclosure; F27 (the right) stays critical"),
]
CHECKED = {  # notices read in full with no other change
    "va-claim-info": "read in full; no changes",
}


def main():
    by_notice: dict[str, list] = {}
    for nid, fid, fld, val, why in EDITS:
        by_notice.setdefault(nid, []).append((fid, fld, val, why))
    for nid in ids():
        path = CORPUS / nid / "facts.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        notes = []
        for fid, fld, val, why in by_notice.get(nid, []):
            f = next(x for x in data["facts"] if x["id"] == fid)
            if f.get(fld) != val:
                notes.append({"fact": fid, "field": fld, "from": f.get(fld), "to": val, "why": why})
                f[fld] = val
        if nid in CHECKED:
            notes.append({"note": CHECKED[nid]})
        data["reviewed"] = True
        data["reviewer"] = REVIEWER
        data["review_notes"] = data.get("review_notes", []) + notes
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        n = load(nid)
        errs, warns = problems(n)
        print(f"{nid}: {len(notes)} changes, {len(n.critical)}/{len(n.facts)} critical, {len(errs)} errors, {len(warns)} warnings")
        for e in errs:
            print("  ERROR", e)


if __name__ == "__main__":
    main()
