"""The rewrite tool, with a fake model, so the wiring is tested without spending anything."""

import asyncio
import json

from plainbench import llm, pipeline

LETTER = ("Dear Ms. Reyes,\n\nSend your statement within 30 days. If you do not respond, we will reduce your payments. "
          "Call 1-800-827-1000 with questions. Your Social Security number is 123-45-6789. "
          "Your claim number: CL-55821 is on file. Mail it to 410 Main Street.")
ITEMS = {"items": [
    {"id": "1", "type": "deadline", "fact": "Send your statement within 30 days", "answer": "30 days", "quote": "within 30 days"},
    {"id": "2", "type": "consequence", "fact": "If you don't respond, payments are reduced", "answer": "", "quote": "we will reduce your payments"},
    {"id": "3", "type": "contact", "fact": "Call 1-800-827-1000", "answer": "1-800-827-1000", "quote": "Call 1-800-827-1000"},
    {"id": "4", "type": "action", "fact": "a made-up item", "answer": "", "quote": "this sentence isn't in the letter"},
]}


def fake(replies):
    sent = []

    async def call(prompt, system, model="sonnet", effort=None, timeout=300.0):
        sent.append((system, prompt))
        return llm.Reply(replies.pop(0), model, 0.01)
    return call, sent


def test_redact_and_restore_round_trip():
    red, mapping = pipeline.redact(LETTER)
    assert "123-45-6789" not in red and "CL-55821" not in red and "410 Main Street" not in red
    assert "[SSN-1]" in red and "1-800-827-1000" in red  # phone numbers are kept: the reader needs them
    assert pipeline.restore(red, mapping) == LETTER


def test_items_whose_quote_isnt_in_the_letter_are_set_aside(monkeypatch):
    call, _ = fake([json.dumps(ITEMS)])
    monkeypatch.setattr(llm, "call", call)
    items, dropped, _ = asyncio.run(pipeline.extract(LETTER, "sonnet"))
    assert [i.id for i in items] == ["1", "2", "3"] and dropped[0]["id"] == "4"


def test_a_lost_item_triggers_one_revision_and_is_reported(monkeypatch):
    first = "<letter>Send it within 30 days. Call us with questions.</letter>"  # lost 2, and 3's number
    located1 = json.dumps({"items": [
        {"id": "1", "result": "found", "where": "Send it within 30 days."},
        {"id": "2", "result": "not found", "where": ""},
        {"id": "3", "result": "found", "where": "Call us with questions."}]})  # model says found; code catches the missing number
    second = "<letter>Send it within 30 days. If you don't, we will lower your payments. Call 1-800-827-1000.</letter>"
    located2 = json.dumps({"items": [
        {"id": "1", "result": "found", "where": "Send it within 30 days."},
        {"id": "2", "result": "found", "where": "If you don't, we will lower your payments."},
        {"id": "3", "result": "found", "where": "Call 1-800-827-1000."}]})
    call, sent = fake([json.dumps(ITEMS), first, located1, second, located2])
    monkeypatch.setattr(llm, "call", call)
    res = asyncio.run(pipeline.run(LETTER))
    assert res.revised and res.lost == []
    revise_prompt = sent[3][1]
    assert "we will reduce your payments" in revise_prompt and "Call 1-800-827-1000" in revise_prompt
    assert "Send your statement within 30 days" not in revise_prompt.split("Items to put back:")[1].split("<rewrite>")[0]


def test_code_overrides_a_found_without_the_number(monkeypatch):
    call, _ = fake([json.dumps(ITEMS), json.dumps({"items": [
        {"id": "1", "result": "found", "where": "within a month"},
        {"id": "2", "result": "found", "where": "we will lower your payments"},
        {"id": "3", "result": "found", "where": "Call us."}]})])
    monkeypatch.setattr(llm, "call", call)
    res = asyncio.run(pipeline.check(LETTER, "Reply within a month or we will lower your payments. Call us."))
    status = {i.id: i.status for i in res.items}
    assert status == {"1": "changed", "2": "kept", "3": "changed"}
    report = pipeline.markdown(res)
    assert "2 items may be lost or changed" in report and "not that nothing was lost" in report


def test_redact_catches_directional_and_numbered_streets():
    for addr in ("123 N Harris St", "4100 SW Elm Ave", "88 21st Ave", "7 E. Main Street"):
        red, mapping = pipeline.redact(f"John Smith\n{addr}\nHarvard, TX 12345")
        assert addr not in red and list(mapping.values()) == [addr], addr


def test_clean_report_quotes_the_measured_catch_rate():
    from plainbench.facts import ROOT
    measured = json.loads((ROOT / "results" / "2026-11-10-gate" / "tool-checker.json").read_text())["test"]["ALL"]
    assert pipeline.CAUGHT == (measured["k"], measured["n"])
    res = pipeline.Result(rewrite="y", items=[], dropped=[], grade_before=8, grade_after=6, revised=False,
                          not_in_source=[], cost_usd=0.0)
    assert f"{measured['k']} of {measured['n']}" in pipeline.markdown(res)
