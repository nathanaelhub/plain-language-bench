# plain-language-bench

**What gets lost when a government letter is rewritten in plain language?** 18 real federal notices (IRS, Medicare,
VA) were rewritten 8 ways by Claude, and every deadline, amount, right, condition and contact the reader needs was
checked, one by one, by a judge that was itself tested against planted errors and a person's labels.

**Results site:** https://nathanaelhub.github.io/plain-language-bench/

Nonprofits rewrite letters like these for the people they serve, and reading-level scores reward cutting. Earlier work
in this portfolio found that AI judges catch a changed number but miss a dropped condition. This measures what plain
language costs, and ships a tool that checks a rewrite before it's sent.

## Findings

<!-- findings:start -->
Results for the 15 test notices; the 3 dev notices, used to tune the judge, are reported
separately in `results/`. "Critical facts" are the ones a reader needs to act or to know what happens to them
(see [corpus/RULES.md](corpus/RULES.md)); all figures count those.

| Setup | Critical facts kept | 95% range | Lost per letter | Letters with a loss | Reading grade |
|---|---|---|---|---|---|
| The original letter | 99.6% | 98.9%–100.0% | 0.1 | 7% | 8.7 |
| Haiku, grade 6 | 94.5% | 91.7%–97.1% | 1.5 | 60% | 6.0 |
| Sonnet, grade 6 | 96.2% | 93.5%–98.2% | 0.8 | 60% | 4.9 |
| Opus, grade 6 | 94.9% | 92.0%–97.2% | 1.2 | 73% | 4.4 |
| Sonnet, grade 4 | 90.2% | 86.6%–93.5% | 2.4 | 93% | 4.2 |
| Sonnet, grade 8 | 96.0% | 93.9%–97.9% | 1.1 | 60% | 5.4 |
| Sonnet, grade 6, 'keep everything' prompt | 97.8% | 95.8%–99.5% | 0.7 | 33% | 5.5 |
| Rewrite tool (Sonnet, grade 6) | 97.2% | 94.7%–99.2% | 0.8 | 40% | 5.7 |

**1. Plain enough costs little; plainer costs more.** At grade 6, Sonnet's rewrites kept 96.2% of
critical facts. Asking for grade 4 cost 6.0 points more (95% range 2.1 to
10.1), and 93% of grade-4 rewrites lost at least one critical fact.
Asking for grade 8 changed nothing: the rewrites landed at grade 5.4 anyway.

**2. Prompts, models and the tool: no difference bigger than noise.** The same setup run twice differed by
4.6 points per letter on average. The "keep everything" prompt (+1.6 points,
95% range -1.0 to +4.1) and the rewrite tool (+1.0, -2.5
to +4.6) both point the right way but can't be told apart from it; neither can Haiku, Sonnet and Opus.

**3. The judge catches planted losses, and misses some real ones.** On errors planted in hand-checked rewrites (labels known by
construction), the judge caught:

| Planted error | Caught (test) |
|---|---|
| Delete | 9 of 9 |
| Value | 5 of 5 |
| Condition | 5 of 6 |
| Alternative | 3 of 4 |
| Modal | 6 of 9 |
| Vague | 2 of 2 |

A "must" that became a "may" was the one type under the bar set in advance (0.70). False alarms: 3.4% of
critical facts that were kept. On unedited rewrites it agreed with only 1 of 5 subtle real changes found by hand
(for example, CP12's 60-day reversal right losing "in writing"), so the retention figures are best read as an **upper bound**.

**4. The Sonnet judge doesn't favour the tool.** The tool's own checker is Sonnet too, so Opus re-judged the tool's rewrites in
full: it found 5 losses where Sonnet found 14.
The tool's checker, scored on the same planted errors, caught 31 of 35.

**5. A person's check.** Pending: 40 blinded items are being labelled; this section will report agreement by group.

Total cost: $25.58 (nominal, on a Claude plan login).
<!-- findings:end -->

## The rewrite tool

```bash
uv run plainbench rewrite letter.txt --grade 6 --redact --out report.md
uv run plainbench check letter.txt someone-elses-rewrite.txt
```

It lists what the letter tells its reader (each item with an exact quote, checked by code), rewrites at the target
grade, finds each item in the rewrite (code checks the quote and that dates, amounts and phone numbers are really
there), revises once if anything was lost, and reports every item as kept, changed or missing. `--redact` replaces
Social Security, claim and case numbers and street addresses before anything is sent to Claude. The report never says
"nothing lost": its checks are measured above, and it says so.

## How it was built

| Step | What makes it trustworthy |
|---|---|
| Corpus | 18 public-domain federal notices; every candidate logged with a reason ([candidates.csv](corpus/candidates.csv)); template blanks filled with recorded made-up values; wording never changed |
| Facts | Drafted by Opus, every quote checked against the letter, every sentence accounted for, reviewed by hand, **frozen** before any rewrite (a test fails if one changes) |
| Critical | A written rule ([RULES.md](corpus/RULES.md)), decided per fact before rewriting; the judge never rates how much a loss matters |
| Rewrites | 7 setups x 18 notices, realistic prompts, fixed effort; one setup run twice to measure noise |
| Judge | Sonnet, one call per rewrite plus a confirmation call for flags; code checks every quote and value. Tuned on 3 dev notices only, then frozen |
| Gate | 73 planted losses and 12 meaning-preserving edits in 6 hand-aligned real rewrites; labels decided from character spans, never by a model; thresholds set in advance |
| People | 40 blinded items labelled by a person, in six groups chosen to test where the judge is weakest |

Facts and judge labels were reviewed by Claude, so they aren't independent of the models being tested; the planted
errors and the person's labels are the independent checks.

## Run

```bash
cd plain-language-bench
uv sync
uv run pytest -q                                          # offline: instruments, corpus, freeze, plants, tool
PLAINBENCH_USE_LOGIN=1 uv run python -m bench.run rewrites  # rewrites (resumable, --max-usd cap)
PLAINBENCH_USE_LOGIN=1 uv run python -m bench.run judge
PLAINBENCH_USE_LOGIN=1 uv run python -m bench.gate run --split test
uv run python -m bench.analyze && uv run python -m bench.site && uv run python -m bench.readme
```

`PLAINBENCH_USE_LOGIN=1` drops any `ANTHROPIC_API_KEY` so the `claude` CLI uses its plan login. Every call is in
`runs/*.jsonl` with its prompt hash and cost.

## Limits

- 18 notices, 11 from the IRS; other agencies' samples were images, refused automated requests, or duplicated these.
- The judge misses some subtle real changes (finding 3), so measured retention overstates what readers keep.
- Reading grade is Flesch-Kincaid: sentence and word length, not comprehension. No readers were tested.
- One rewrite per setup and notice (two for Sonnet grade 6); differences under the measured noise aren't claims.
- GSA's archive has only two full expert before-and-after letters, so expert rewrites are examples, not a measured group.
  One of them, the "Medicaid Eligibility" training example, folds a standalone eligibility path into nursing-home cases.
