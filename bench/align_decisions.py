"""My alignment decisions (Claude, in session, November 10, 2026), written as sentence
indices or exact substrings of each base rewrite, then saved as labels/align/*.json.
Nothing here comes from the judge. Status notes give the reason for each non-"kept"."""

from __future__ import annotations

import json

from bench.align import ALIGN, path, rewrite_text
from plainbench.text import sentences


def build(nid: str, decisions: dict, setup: str = "sonnet-g6", sample: int = 0) -> None:
    rw = rewrite_text(nid, setup, sample)
    sp = sentences(rw)

    def S(i, j=None):  # sentences i..j as one contiguous span
        return rw[sp[i][0]:sp[j if j is not None else i][1]]

    out = {}
    for fid, d in decisions.items():
        status, spans, note = d[0], d[1], (d[2] if len(d) > 2 else "")
        resolved = []
        for s in spans:
            resolved.append(S(*s) if isinstance(s, tuple) else (S(s) if isinstance(s, int) else s))
        out[fid] = {"status": status, "spans": resolved, **({"note": note} if note else {})}
    ALIGN.mkdir(parents=True, exist_ok=True)
    path(nid, setup, sample).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


K, C, M = "kept", "changed", "missing"

DECISIONS = {
    "va-claim-info": {
        "F1": (K, [1]), "F2": (K, ["We asked you for a certified copy of your marriage license."]), "F3": (K, [3]),
        "F4": (K, [4]), "F5": (K, [5]), "F6": (K, ["You can still send us the paper."]),
        "F7": (K, ["You can send it at any time."]), "F8": (K, [(7, 8)]), "F9": (K, [(9, 10)]),
        "F10": (K, ["and you qualify for benefits"]), "F11": (K, [(11, 12)]),
        "F12": (K, ["please read the form we included with this letter. It is called VA Form 1-4107, *Notice of Procedural and Appellate Rights*."]),
        "F13": (C, ["you may have a right to appeal"], "'you may have a right' weakens 'you have the right to appeal'"),
    },
    "irs-cp21b": {
        "F1": (K, [0]), "F2": (K, [6]), "F3": (K, ["**Date of notice:** January 30, 2019"]),
        # F4's second span was added after the first gate run showed my alignment had missed it.
        "F4": (K, ["**Phone:** 1-800-829-1040", "Call us at 1-800-829-1040."]), "F5": (K, [4, 11]), "F6": (K, [(5, 6)]), "F7": (K, [(5, 6)]),
        "F8": (K, [8]), "F9": (K, [9]), "F10": (K, [10]), "F11": (K, [(13, 14)]),
        "F12": (K, ["if you have not already gotten it"]), "F13": (K, [14]), "F14": (K, [15]),
        "F15": (K, [16]), "F16": (K, [(16, 17)]), "F17": (K, [18]), "F18": (K, [19]), "F19": (K, [19]),
        "F20": (K, [21]), "F21": (K, ["go to www.irs.gov/formspubs"]), "F22": (K, [22]),
        "F23": (K, ["You can write to us at the address at the top of this letter."]), "F24": (K, [(23, 26)]),
        "F25": (K, [27]), "F26": (K, [28]), "F27": (K, [29]), "F28": (K, [30]),
    },
    "cms-nomnc": {
        "F1": (K, [0]), "F2": (K, [1, 3]), "F3": (K, [3]), "F4": (K, [4]), "F5": (K, [(3, 4)]), "F6": (K, [5]),
        "F7": (K, [6]), "F8": (K, [10]), "F9": (K, [11]), "F10": (K, ["The reviewer will want to hear what you think."]),
        "F11": (K, ["You do not have to write anything down. You can if you want to."]), "F12": (K, [13]),
        "F13": (K, [14]), "F14": (K, [15]), "F15": (K, [15]), "F16": (K, [16]), "F17": (K, [16]), "F18": (K, [18]),
        "F19": (K, [19]), "F20": (K, ["To ask, call the Quality Improvement Organization."]),
        "F21": (K, ["The QIO is a group that Medicare trusts to review these decisions."]),
        "F22": (K, ["If you miss the deadline, you may still be able to appeal."]),
        "F23": (K, ["If you miss the deadline, you may still be able to appeal."]), "F24": (K, [21, 26]),
        "F25": (K, [24]), "F26": (K, [25]), "F27": (K, [25]), "F28": (K, [(27, 28)]), "F29": (K, [35]),
        "F30": (K, [36]),
        "F31": (C, [36], "'treated unfairly' is broader than 'discriminated against', a specific legal protection"),
        "F32": (K, [38]), "F33": (K, [39]), "F34": (K, [40]),
    },
    "irs-cp12": {
        "F1": (K, [3]), "F2": (K, [4, 8]), "F3": (K, [5]), "F4": (K, [6]), "F5": (K, [(10, 11)]), "F6": (K, [(12, 14)]),
        "F7": (K, [14]), "F8": (K, [15]), "F9": (K, [16]), "F10": (K, [17]), "F11": (K, ["Or write to us."]),
        "F12": (K, ['Fill out the "Contact information" section of this letter, tear it off, and mail it to us. Include any papers that support your side.']),
        "F13": (C, [19], "drops 'in writing': a phone call wouldn't get the change reversed"),
        "F14": (C, [19], "drops 'in writing'"),
        "F15": (K, ["if you can't show us new facts to support your view, and we still think undoing the change is wrong"]),
        "F16": (K, ["we will send your case to our audit team"]),
        "F17": (K, ["This gives you the right to appeal. You can even go to court before you have to pay any extra tax."]),
        "F18": (K, ["The audit team will contact you in 5 to 6 weeks to explain how an audit works and what your rights are."]),
        "F19": (K, ["If you wait longer than 60 days"]), "F20": (K, ["you lose the right to appeal before you pay"]),
        "F21": (K, ["We will not undo the change"]), "F22": (K, ["you will have to pay the extra tax"]),
        "F23": (K, ['After you pay, you can still ask for money back by filing a "claim for refund."']),
        "F24": (K, ["You must file the claim within 3 years of the day you filed your tax return, or within 2 years of the day you made your last payment for this tax."]),
        "F25": (K, [22]), "F26": (K, [22]), "F27": (K, [23]), "F28": (K, [23]), "F29": (K, [(25, 27)]),
        "F30": (K, [29]), "F31": (K, [30]),
    },
    "cms-im": {
        "F1": (K, [0]), "F2": (K, [0]), "F3": (C, [3], "'hospital patient' for 'hospital inpatient', a status that matters for Medicare"),
        "F4": (K, ["**Medicare helps pay for your care.**"]), "F5": (K, ["This includes hospital care that you need for your health."]),
        "F6": (K, ["You have the right to know what Medicare covers."]),
        "F7": (K, ["The hospital will work with you to make sure it is safe for you to leave. They can also help set up any care you may need after you go home."]),
        "F8": (K, ["If you are worried about anything, talk to your doctor or the hospital staff."]),
        "F9": (K, ["If you are not happy with the quality of your care, call this group: Midsouth Quality Review at 1-888-555-0142."]),
        "F10": (K, ["call this group: Midsouth Quality Review at 1-888-555-0142", 10]),
        "F11": (K, ["This group is not part of Medicare. It is separate."]), "F12": (K, [9]), "F13": (K, [9]), "F14": (K, [10]),
        "F15": (K, ["Call as soon as you can. Be sure to call **before you leave the hospital**."]),
        "F16": (K, ["If you appeal before you leave, Medicare will keep paying for your stay while you wait to hear the answer."]),
        "F17": (K, ["If you appeal before you leave, Medicare will keep paying for your stay while you wait to hear the answer."]),
        "F18": (K, [12]), "F19": (K, [13]), "F20": (K, [14]), "F21": (K, [14]), "F22": (K, [15]), "F23": (K, [15]),
        "F24": (K, ["You will get another letter called the **Detailed Notice of Discharge**."]),
        "F25": (C, ["It tells you why the group thinks you no longer need to stay in the hospital."],
                "attributes the reasons to the review group; the notice gives the hospital's (or plan's) reasons"),
        "F26": (K, [18]), "F27": (K, [18]), "F28": (K, [19]), "F29": (K, [19]), "F30": (K, [19]), "F31": (K, [21]),
        "F32": (K, [25]), "F33": (K, [26]),
        "F34": (C, [26], "'treated you unfairly' is broader than 'discriminated against'"),
        "F35": (K, ["go to Medicare.gov/about-us/accessibility-nondiscrimination-notice"]),
        "F36": (K, ["You can also call 1-800-MEDICARE (1-800-633-4227)."]), "F37": (K, [28]),
    },
    "va-enrollment": {
        "F1": (K, [(1, 2)]), "F2": (K, [3]), "F3": (K, [5]), "F4": (K, [7]), "F5": (K, [8]), "F6": (K, [9]),
        "F7": (K, [11]), "F8": (K, [12]), "F9": (K, [13]), "F10": (K, [13]), "F11": (K, [(14, 15)]), "F12": (K, [17]),
        "F13": (K, [19]), "F14": (K, [20]), "F15": (K, ["If you already owe us money"]),
        "F16": (K, ["you will still have to pay it back"]), "F17": (K, ["But you will not owe more than that."]),
        "F18": (K, [22]), "F19": (K, [23]), "F20": (K, [24]), "F21": (K, [25]), "F22": (K, [26]), "F23": (K, [27]),
        "F24": (K, [28]), "F25": (K, [29]), "F26": (K, [29]), "F27": (K, [31]), "F28": (K, [(32, 33)]),
        "F29": (K, ["VA Form 21-4138"]),
    },
}

if __name__ == "__main__":
    for nid, d in DECISIONS.items():
        build(nid, d)
    from bench.align import check
    print("\n".join(check()) or "all alignments check out")
