"""Every notice's fact list passes the rules in corpus/RULES.md."""

import pytest

from plainbench.facts import Fact, ids, load, problems

NOTICES = ids()


@pytest.mark.parametrize("nid", NOTICES)
def test_fact_list_passes_the_checks(nid):
    n = load(nid)
    errs, _ = problems(n)
    assert errs == []
    assert n.meta.get("license", "").startswith("US government work")
    assert len(n.critical) >= 3


@pytest.mark.parametrize("nid", NOTICES)
def test_notice_is_reviewed_and_in_the_word_range(nid):
    n = load(nid)
    import json
    data = json.loads((n.path / "facts.json").read_text())
    assert data["reviewed"] is True
    assert 150 <= len(n.text.split()) <= 900


def test_a_condition_needs_the_fact_it_limits():
    n = load(NOTICES[0])
    n.facts = n.facts + [Fact("FX", "condition", "s", "q", "a", n.facts[0].quote, True, [])]
    assert any("depends_on" in e for e in problems(n)[0])


def test_a_quote_not_in_the_notice_is_an_error():
    n = load(NOTICES[0])
    n.facts[0].quote = "a sentence this notice never says"
    assert any("quote not found" in e for e in problems(n)[0])


def test_amount_values_match_across_money_and_bare_numbers():
    f = Fact("F1", "amount", "s", "q", "$963.00", "Decrease in penalty: – 963.00", True)
    assert f.needed_values() == {("number", "963")}


def test_frozen_fact_lists_havent_changed():
    """The freeze: a fact list that changes after it must be corrected through
    corpus/facts_errata.json, never edited in place."""
    import json
    from pathlib import Path

    from plainbench.facts import ROOT, corpus_hash
    frozen = json.loads((ROOT / "results" / "FROZEN.json").read_text())
    now = corpus_hash()
    assert set(now) == set(frozen["notices"])
    changed = [nid for nid, h in now.items() if h != frozen["notices"][nid]["hash"]]
    assert changed == [], f"changed after the freeze: {changed}"
