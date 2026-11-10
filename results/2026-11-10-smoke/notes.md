# Smoke run, November 10, 2026

Three notices (va-claim-info, irs-cp21b, cms-nomnc) x six rewriting setups, plus each original,
judged by Sonnet. These three are now the **dev** notices: the judge prompt was tuned on them, so
they're excluded from the gate and labelled dev in every result.

## Cost and reliability per call type

See `costs.txt`. All 18 rewrites came back in `<letter>` tags on the first try; all 42 judge calls
(two rounds) parsed. Per call: Haiku rewrite $0.0008, Sonnet $0.011-0.012, Opus $0.027; Sonnet
judge $0.03-0.06 per rewrite including the confirmation call. Projected full run (24 notices):
about $31-34 including what's already spent ($3.6), within the $40 cap.

## What the smoke run found

1. **Instrument bug, fixed:** a URL in markdown bold (`**www.irs.gov/cp21**.`) was read with its
   asterisks, so code overrode a correct "kept". Values are now read from text with emphasis
   removed (`values.unmark`), with a test.
2. **The judge was too strict on paraphrase.** First prompt: 26 critical facts flagged across 18
   rewrites, many of them plain rewordings ("you will not have to pay for it" for "you'll avoid
   financial liability"). The prompt now gives examples of both kept paraphrase and changed
   qualifiers; 21 flagged. Originals: 0 false losses before and after (60 critical facts).
3. **Still contested after tuning** (my reading in brackets; the human labels decide):
   - va-claim-info/sonnet-g6 F8: "please try to send it by June 3, 2025" + consequence [kept]
   - irs-cp21b/opus-g6 F16: "Call us at 1-800-829-1040" without "to review your account" [kept]
   - irs-cp21b/opus-g6 F14: "if you owe other taxes ... we may have to use this money" [kept]
   - cms-nomnc/sonnet-g6 F25: "usually within two days after March 14" [kept; the prompt's own example]
   - cms-nomnc/opus-g6 F8: "a reviewer who does not work for us ... right away", "medical" dropped [unsure]
   Not tuned further on five examples; the gate (planted errors in real rewrites) and the
   question-answering judge comparison in M7 decide the judge.
4. **Requested grade isn't reached grade:** asking for grade 8 produced grade 4.7-6.8 text, so
   results are plotted against the grade each rewrite actually reached.
