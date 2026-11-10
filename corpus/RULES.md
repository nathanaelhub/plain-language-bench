# Corpus and fact rules

Written before any rewrite was generated (November 9–10, 2026). Changes after the freeze go in
`facts_errata.json`, never into the files silently.

## Which notices are in

A notice is included if all of these hold:

1. It's a US federal government notice, letter or required form that tells one person something
   about their own benefits, taxes, health coverage or a decision about them. Not a brochure,
   regulation or web page.
2. It's a public-domain US government work, published by the agency or in GSA's plainlanguage.gov
   archive, and its source can be downloaded without getting around a block (sites that refuse
   automated requests are logged and skipped).
3. Its text can be recovered in reading order (not an image), and the part used is 150 to 900 words.
4. It carries at least three reader-critical facts (below).

Every candidate looked at is logged in `candidates.csv` with the decision and the reason.

**Filling the blanks.** Templates have blanks ("(Date)", "{insert type}", "1-800-xxx-xxxx"). Each is
filled with a distinctive made-up value, recorded under `fills:` in the notice's frontmatter, so a
reader sees a real-looking letter and code can check dates and amounts exactly. Made-up phone numbers
use the reserved 555-01xx range; made-up organizations are labelled as such. Placeholders that are
redacted personal identifiers in the agency's own sample (`nnn-nn-nnnn`) are left as published.

**Cleaning.** Text is put in reading order and markdown headings and bullets mirror the layout.
Wording is never changed. Each repair (a dash lost in extraction, a repeated block) is noted under
`cleaning:`; a mistake in the agency's own text is kept and noted under `source_error:`.

## What a fact is

One thing the letter tells the reader, small enough to be kept or lost on its own:

| type | examples |
|---|---|
| `deadline` | "send your statement within 30 days", "by June 3, 2025" |
| `amount` | "$1,075.21 due", "refund of $2,128.66", "$202.00 per month" |
| `action` | something the reader must or can do: "pay online", "write your SSN on the check" |
| `consequence` | what happens to them: "we will reduce your payments", "you may have to pay" |
| `right` | something they're entitled to: appeal, a hearing, an accessible format, a copy |
| `condition` | an if / unless / except / only that limits another fact; linked with `depends_on` |
| `contact` | how to reach someone: a phone number, address, website |
| `subject` | what the letter is about: "your claim was disallowed", "coverage ends" |

Each fact has a `statement` (plain wording), a `question` and `answer` (what a reader who read only
the rewrite should be able to answer), and a `quote`: an exact passage of the notice that states it.

A fact that needs two separate passages to state is two facts. A condition is its own fact, linked to
the fact it limits with `depends_on`, so dropping "if entitlement is established" counts as losing a
condition even when the main statement survives.

## Which facts are critical

Decided when facts are drafted, before any rewrite exists, by this rule only:

> A fact is **critical** if it is something the reader must do, a date or deadline, money they owe
> or will receive, what will happen to them, a right they can use, a condition on any of those, or
> how to contact the agency about it.

Everything else (background, the agency's reasoning, statutory citations, form numbers that aren't
needed to act) is recorded but not critical.

Clarified on November 10, after reading the first six drafts and before any rewrite existed, because
the drafts marked nearly everything critical. These are **not** critical:

- the notice's own date and identifiers (only dates that apply to the reader's case are);
- features and conveniences of a way to pay or respond ("receive instant confirmation", "schedule
  payments in advance", the small fee for paying by card), as opposed to the way itself;
- advice about handling the letter ("read this notice", "ask any questions", "keep this notice",
  "have your account information ready when you call");
- signing to acknowledge receipt;
- where to read more (an enclosure, a general information website), unless the letter says that's
  how to act;
- details of an option that apply only after the agency accepts it (how to pay an accepted offer).

An option that lets the reader avoid harm (a payment plan, an offer in compromise, an appeal) is
critical, and so is the condition for using it. The benchmark's headline numbers count critical facts
only; the judge decides only whether a fact was kept, never how much a loss matters.

## Every sentence is accounted for

Each sentence of the notice (as split by `plainbench.text.sentences`) maps either to the facts it
carries or to `none` with a reason (greeting, sign-off, address block, signature line, repeated
heading). A sentence containing a marker (a number, date, money, phone number, or one of: must, may,
if, unless, except, only, within, before, after, right, appeal, hearing, deny, penalty, cannot,
will not, required, responsible) can't be `none` without an `override` saying why. A sentence with
more markers than facts is flagged for a second look.
