"""Planted-error labels are decided by construction; these pin down the rules."""

import json

import pytest

from bench import plants
from bench.align import ALIGN, rewrite_text
from plainbench.facts import load

BASES = sorted(p.stem for p in ALIGN.glob("*.json"))


def base(stem):
    nid, setup, sample = stem.split("__")
    return load(nid), rewrite_text(nid, setup, int(sample)), json.loads((ALIGN / f"{stem}.json").read_text())


@pytest.mark.parametrize("stem", BASES)
def test_an_edit_nothing_overlaps_keeps_every_label(stem):
    n, rw, al = base(stem)
    labels = plants.label_plant(n, rw, al, None, None, [], removal=False)
    assert labels == {f: al[f]["status"] for f in al}


@pytest.mark.parametrize("stem", BASES)
def test_deleting_everything_makes_every_stated_fact_missing(stem):
    n, rw, al = base(stem)
    labels = plants.label_plant(n, rw, al, None, None, [(0, len(rw))], removal=True)
    for f in n.facts:
        assert labels[f.id] == ("missing" if al[f.id]["spans"] else al[f.id]["status"])


@pytest.mark.parametrize("stem", BASES)
def test_labels_dont_depend_on_fact_order(stem):
    n, rw, al = base(stem)
    t = next(f.id for f in n.facts if al[f.id]["status"] == "kept" and al[f.id]["spans"])
    ranges = plants.units_covering(rw, plants.spans_of(rw, al, t))
    a = plants.label_plant(n, rw, al, t, "missing", ranges, removal=True)
    n.facts = list(reversed(n.facts))
    assert plants.label_plant(n, rw, al, t, "missing", ranges, removal=True) == a


def test_every_variant_labels_its_target_and_only_excludes_what_it_must():
    vs = plants.build()
    for v in vs:
        if v.target:
            assert v.labels[v.target] in ("missing", "changed")
            n = load(v.base)
            linked = set(n.fact(v.target).depends_on) | {f.id for f in n.facts if v.target in f.depends_on}
            for fid in linked:
                assert v.labels[fid] == plants.EXCLUDED
        assert v.text != rewrite_text(v.base) or v.kind == "BASE"


def test_null_edits_change_text_but_no_label():
    for v in plants.build():
        if v.kind == "NULL":
            al = json.loads((ALIGN / f"{v.base}__sonnet-g6__0.json").read_text())
            assert v.labels == {f: al[f]["status"] for f in al}
