"""The measuring instruments: if these are wrong, every number in the benchmark is."""

import asyncio
import json

import pytest

from plainbench import llm, log, metrics
from plainbench.readability import measure, syllables, units
from plainbench.text import find, flat, sentences
from plainbench.values import extract, missing_from, not_in_source, values

LETTER = """Dear Veteran:

Send us your statement within thirty (30) days, by **March 14, 2025**. If you do not respond, we will
reduce your payments on September 1, 1996. You owe $1,287.40.

- Call 1-800-827-1000 if you have questions.
- Our TDD number is (800) 829-4833.

Sincerely,"""


# ---- text ----

def test_find_returns_the_span_in_the_original_through_formatting():
    a, b = find("within 30 days", LETTER.replace("thirty (30)", "30")) or (None, None)
    assert a is not None
    a, b = find("by March 14, 2025.", LETTER)
    assert LETTER[a:b] == "by **March 14, 2025**."
    assert find("we will reduce your payments", LETTER)  # across a line break
    assert find("we will increase your payments", LETTER) is None


def test_flat_straightens_quotes_dashes_and_case():
    assert flat("We’ll “call” — soon") == flat('we\'ll "call" - soon')


def test_sentences_keep_list_items_apart_and_skip_abbreviations():
    t = "See Dr. Smith on Jan. 5. Then call.\n- One item\n- Two items\nU.S. law applies. It ends."
    got = [t[a:b] for a, b in sentences(t)]
    assert got == ["See Dr. Smith on Jan. 5.", "Then call.", "- One item", "- Two items", "U.S. law applies.", "It ends."]


# ---- values ----

def test_values_are_normalized_across_spellings():
    v = values(LETTER)
    assert ("duration", "30 day") in v and ("date", "2025-03-14") in v and ("date", "1996-09-01") in v
    assert ("money", "1287.4") in v and ("phone", "8008271000") in v and ("phone", "8008294833") in v
    assert values("$6 million") == values("$6,000,000.00")
    assert values("one year") == values("1 year") and values("sixty days") == values("60 days")
    assert values("3/14/2025") == values("March 14, 2025") == values("14 March 2025")


@pytest.mark.parametrize("edit", [
    ("thirty (30) days", "sixty (60) days"), ("March 14, 2025", "March 21, 2025"),
    ("$1,287.40", "$1,931.10"), ("1-800-827-1000", "1-800-827-1001"), ("September 1, 1996", "October 1, 1996"),
])
def test_a_planted_value_change_changes_the_check(edit):
    needed = values(LETTER) - {(k, v) for k, v in values(LETTER) if k == "number"}
    changed = LETTER.replace(*edit)
    assert missing_from(LETTER, needed) == []
    assert missing_from(changed, needed), f"changing {edit} went unnoticed"
    assert not_in_source(changed, LETTER), f"the new value in {edit} wasn't reported as not in the source"


def test_a_date_without_its_year_still_matches():
    assert missing_from("Reply by March 14.", {("date", "2025-03-14")}) == []


def test_step_numbers_are_not_reported_as_not_in_source():
    assert not_in_source("1. Read this.\n2. Call us at 1-800-827-1000.", LETTER) == []


def test_values_dont_overlap():
    vs = extract(LETTER)
    for x, y in zip(vs, vs[1:]):
        assert x.end <= y.start


# ---- readability ----

def test_syllables():
    assert [syllables(w) for w in ("table", "agree", "make", "the", "cat", "evidence")] == [2, 2, 1, 1, 1, 3]


def test_headings_and_signoffs_dont_count_but_list_items_do():
    us = units("# What we need\n\nSend the form.\n\n- One copy\n- Your ID\n\nSincerely,\nJane Doe")
    assert us == ["Send the form.", "One copy", "Your ID"]


def test_short_text_has_no_grade_and_hard_text_scores_higher():
    assert measure("Call us.")["grade"] is None
    easy = " ".join(["We got your form. You do not owe us money. Call us if you have a question."] * 4)
    hard = " ".join(["The determination regarding your eligibility necessitates supplementary documentation "
                     "substantiating the circumstances previously enumerated in correspondence."] * 4)
    assert measure(easy)["grade"] < 4 < 14 < measure(hard)["grade"]


def test_grades_rank_texts_like_textstat():
    textstat = pytest.importorskip("textstat")
    texts = [
        "The cat sat on the mat. The dog ran to the park. We had fun in the sun all day long with friends.",
        "Send us the form by the date on this letter. If we do not get it, we will stop your payments. Call us with questions.",
        "Your request for reconsideration must be received within sixty days. Additional documentation may be submitted at any time.",
        "This letter concerns your recent claim for benefits. Before final action could be taken, we needed additional evidence from you.",
        "Notwithstanding the foregoing provisions, the beneficiary's entitlement shall be determined in accordance with applicable regulations.",
        "Eligibility determinations incorporate comprehensive evaluations of documentation substantiating extraordinary circumstances affecting beneficiaries.",
    ]
    ours = [measure(t * 3)["grade"] for t in texts]
    theirs = [textstat.flesch_kincaid_grade(t * 3) for t in texts]
    rank = lambda xs: [sorted(xs).index(x) for x in xs]  # noqa: E731
    d = sum((a - b) ** 2 for a, b in zip(rank(ours), rank(theirs)))
    n = len(texts)
    spearman = 1 - 6 * d / (n * (n * n - 1))
    assert spearman >= 0.9, (ours, theirs)


# ---- metrics ----

def test_wilson_matches_a_hand_value_and_handles_edges():
    lo, hi = metrics.wilson(13, 14)
    assert abs(lo - 0.685) < 0.01 and abs(hi - 0.987) < 0.01
    assert metrics.wilson(0, 0) == (0.0, 1.0) and metrics.wilson(0, 10)[0] == 0.0


def test_paired_diff_uses_only_shared_notices():
    r = metrics.paired_diff({"a": 0.9, "b": 0.8, "c": 1.0}, {"a": 0.7, "b": 0.8, "d": 0.0})
    assert r["n"] == 2 and abs(r["diff"] - 0.1) < 1e-9


def test_kappa_on_three_labels():
    a = {"1": "kept", "2": "missing", "3": "changed", "4": "kept"}
    assert metrics.cohen_kappa(a, a) == 1.0
    assert metrics.cohen_kappa(a, {"1": "kept", "2": "kept", "3": "kept", "4": "kept"}) == 0.0


def test_false_loss_band():
    assert abs(metrics.false_loss_band(0.03, 15) - 0.3667) < 1e-3


# ---- llm + log ----

def test_llm_parses_the_cli_json_and_errors():
    out = json.dumps({"result": "hi <letter>Dear you</letter>", "total_cost_usd": 0.012,
                      "modelUsage": {"claude-sonnet-5-5": {}}}).encode()
    r = llm.parse(out, b"", 0)
    assert (r.text, r.model, r.cost_usd, r.error) == ("hi <letter>Dear you</letter>", "claude-sonnet-5-5", 0.012, None)
    assert llm.tagged(r.text, "letter") == "Dear you"
    assert llm.parse(b"not json", b"boom", 1).error.startswith("exit 1")
    assert llm.json_block('Sure:\n```json\n{"a": [1]}\n```') == {"a": [1]}


def test_login_mode_drops_the_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("PLAINBENCH_USE_LOGIN", "1")
    assert "ANTHROPIC_API_KEY" not in llm.env()


def test_log_resumes_retries_errors_and_respects_the_cap(tmp_path):
    path = tmp_path / "calls.jsonl"
    calls = []

    def task(k, cost=0.01, fail=False):
        async def run():
            calls.append(k)
            return {"cost_usd": cost, "error": "boom" if fail else None}
        return log.Task(k, run)

    asyncio.run(log.run([task("a"), task("b", fail=True)], path, progress=lambda m: None))
    calls.clear()
    asyncio.run(log.run([task("a"), task("b")], path, progress=lambda m: None))
    assert calls == ["b"]  # a was done; b had errored, so it runs again
    calls.clear()
    res = asyncio.run(log.run([task(str(i), cost=0.5) for i in range(10)], path, max_usd=1.0, est_usd=0.5,
                              concurrency=1, progress=lambda m: None))
    assert res["skipped_budget"] >= 8 and log.spent(log.read(path)) <= 1.03


def test_a_blank_line_ends_a_paragraph():
    t = "Amount due: $5.00\n\nOur records show a balance."
    assert [t[a:b] for a, b in sentences(t)] == ["Amount due: $5.00", "Our records show a balance."]


def test_zip_codes_and_signed_amounts():
    assert values("Columbia, TN 38401") == {("zip", "38401")}
    assert values("Decrease in tax: $-1,076.63") == {("money", "1076.63")}


def test_markdown_around_a_value_doesnt_hide_it():
    assert missing_from("Go to **www.irs.gov/cp21**. Call **1-800-829-1040**.",
                        {("url", "irs.gov/cp21"), ("phone", "8008291040")}) == []


def test_judge_prompt_is_the_frozen_one():
    """Results were gated with this exact prompt; changing it means re-running the gate."""
    import json
    from plainbench import judge as J
    from plainbench.facts import ROOT
    frozen = json.loads((ROOT / "results" / "JUDGE_FROZEN.json").read_text())
    assert log.phash(J.SYSTEM, J.CONFIRM, J.EFFORT) == frozen["prompt_hash"]


def test_an_amount_the_letter_gives_without_a_dollar_sign_is_not_new():
    src = "Billing Summary\n- Payments and credits: -3,328.00\n- Failure-to-pay penalty: 633.30"
    assert not_in_source("| Payments | -$3,328.00 |\n| Penalty | $633.30 |", src) == []
    assert [v.value for v in not_in_source("Penalty: $633.31", src)] == ["633.31"]


def test_hyphenated_words_are_not_form_numbers():
    got = lambda s: [(v.kind, v.value) for v in extract(s)]  # noqa: E731
    for s in ("your co-pay", "the TEAR-OFF stub", "a ONE-YEAR period", "Failure-to-file penalty"):
        assert not [k for k, _ in got(s) if k == "code"], s
    assert ("code", "CMS-R-131") in got("Form CMS-R-131") and ("code", "SSA-561-U2") in got("see SSA-561-U2")
    assert got("go to www.irs.gov/payments: pay") == [("url", "irs.gov/payments")]
