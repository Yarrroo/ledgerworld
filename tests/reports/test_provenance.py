"""Every number in a report traces to a signed result (g2 `report_numbers_grounded`, T35).

The results are synthetic, signed in the test with a key drawn per run; their figures are the
LF-1 and LF-2 fixture numbers (system brief §6). The model is a ``ScriptedModel`` whose plan
answers the draft at round 0 and the redraft at round 1.
"""

from __future__ import annotations

import os

import pytest
from app.finance.schemas import Money
from app.reports.grounded import (
    GroundedReportAgent,
    UnverifiedResult,
    ground,
    sign_result,
    template_draft,
)
from app.testing.scripted_model import ScriptedPlan, UnexpectedModelCall
from app.utils.llm_client import LLMClient
from pydantic import ValidationError

SIGNING_KEY = os.urandom(32)
FEAS = "run:r-1:branch:integrated:feasibility"
KP = "run:r-1:lending:capacity"


def usd(minor: int) -> Money:
    return Money(minor=minor, currency="USD")


def results():
    return [
        sign_result(FEAS, "feasibility", {
            "breach_without_plan": usd(1_000_000),
            "advance_drawn": usd(1_000_000),
            "cash_after_payroll": usd(3_000_000),
        }, key=SIGNING_KEY),
        sign_result(KP, "lender_capacity", {
            "capacity_under_stress": usd(2_700_000),
            "rejected_draw": usd(3_000_000),
            "borrowers_reacting": 3,
        }, key=SIGNING_KEY),
    ]


def ph(evidence_id: str, figure: str) -> str:
    return "{{" + evidence_id + "#" + figure + "}}"


CLEAN = (
    f"Without a plan the floor is breached by {ph(FEAS, 'breach_without_plan')}. Drawing "
    f"{ph(FEAS, 'advance_drawn')} leaves {ph(FEAS, 'cash_after_payroll')} after payroll, while "
    f"the lender's capacity under stress is {ph(KP, 'capacity_under_stress')}."
)
INVENTED = "Without a plan the floor is breached by 12,345.00 and recovery is 87% likely."


def agent(*drafts: str):
    plan = ScriptedPlan([
        {"actor_id": "report", "round": n, "content": d} for n, d in enumerate(drafts)
    ])
    model = plan.model("report", lambda: len(model.calls))
    llm = LLMClient(api_key="unused", base_url="http://127.0.0.1:9", model="scripted")
    llm.client = model.openai_client()
    return GroundedReportAgent("g-1", "r-1", "LF-1 shock", key=SIGNING_KEY, llm_client=llm), model


def assert_every_number_links_to_evidence(report, given):
    assert report.unlinked() == []
    ids = {r.evidence_id for r in given}
    assert report.links
    for link in report.links:
        assert link.evidence_ids and set(link.evidence_ids) <= ids
        assert report.text[link.start:link.end] == link.text


@pytest.mark.parametrize("draft, number", [
    (INVENTED, "12,345.00"),
    ("Recovery is 87% likely.", "87"),
    ("The LF-1 treasury holds.", "1"),
    ("In round 4 the lender tightens.", "4"),
], ids=["amount-and-percent", "percent", "identifier", "round"])
def test_an_invented_number_is_rejected(draft, number):
    _, _, problems = ground(draft, results())
    assert f"the number {number} is in no signed result" in problems


def test_a_placeholder_naming_no_figure_is_rejected():
    _, _, problems = ground(f"Cash is {ph(FEAS, 'cash_tomorrow')}.", results())
    assert problems == [
        f"the placeholder {ph(FEAS, 'cash_tomorrow')} names no figure of a signed result"]
    _, _, problems = ground(f"Cash is {ph(FEAS, 'cash_after_payroll')[:-1]}.", results())
    assert any("malformed placeholder" in p for p in problems)


def test_a_literal_number_from_the_set_is_linked_to_its_evidence():
    _, links, problems = ground("The floor is breached by 10,000.00 and 3 borrowers react.",
                                   results())
    assert problems == []
    assert [(ln.text, ln.evidence_ids) for ln in links] == [("10,000.00", (FEAS,)), ("3", (KP,))]
    assert {r.figure for r in links[0].refs} == {"breach_without_plan", "advance_drawn"}


def test_a_grounded_draft_is_filled_from_the_signed_results():
    given = results()
    writer, model = agent(CLEAN)
    report = writer.write_section("Integrated plan", given)
    assert (report.path, report.rejected, len(model.calls)) == ("draft", (), 1)
    assert report.text == (
        "Without a plan the floor is breached by USD 10,000.00. Drawing USD 10,000.00 leaves "
        "USD 30,000.00 after payroll, while the lender's capacity under stress is USD 27,000.00."
    )
    assert [ln.text for ln in report.links] == [
        "USD 10,000.00", "USD 10,000.00", "USD 30,000.00", "USD 27,000.00"]
    assert_every_number_links_to_evidence(report, given)
    prompt = model.calls[0].messages[-1]["content"]
    assert ph(KP, "capacity_under_stress") in prompt and "USD 27,000.00" in prompt


def test_a_rejected_draft_gets_one_redraft():
    given = results()
    writer, model = agent(INVENTED, CLEAN)
    report = writer.write_section("Integrated plan", given)
    assert (report.path, len(model.calls)) == ("redraft", 2)
    assert report.rejected == (
        "draft: the number 12,345.00 is in no signed result",
        "draft: the number 87 is in no signed result",
    )
    assert "12,345" not in report.text and "87" not in report.text
    redraft_prompt = model.calls[1].messages[-1]["content"]
    assert "the number 12,345.00 is in no signed result" in redraft_prompt
    assert_every_number_links_to_evidence(report, given)


def test_a_rejected_redraft_falls_back_to_the_template():
    given = results()
    writer, model = agent(INVENTED, "Still 12,345.00 short.")
    report = writer.write_section("Integrated plan", given)
    assert (report.path, len(model.calls)) == ("template", 2)
    assert report.rejected[-1] == "redraft: the number 12,345.00 is in no signed result"
    assert report.text == (
        "Feasibility: breach without plan USD 10,000.00; advance drawn USD 10,000.00; "
        "cash after payroll USD 30,000.00.\n"
        "Lender capacity: capacity under stress USD 27,000.00; rejected draw USD 30,000.00; "
        "borrowers reacting 3."
    )
    assert_every_number_links_to_evidence(report, given)
    assert {(r.evidence_id, r.figure) for ln in report.links for r in ln.refs} == {
        (r.evidence_id, k) for r in given for k in r.figures}


def test_the_model_is_asked_at_most_twice():
    writer, _ = agent(INVENTED, INVENTED, CLEAN)
    assert writer.write_section("Integrated plan", results()).path == "template"


def test_a_tampered_result_is_refused_before_the_model_is_asked():
    given = results()
    forged = given[0].model_copy(
        update={"figures": {**given[0].figures, "advance_drawn": usd(5_000_000)}})
    writer, model = agent(CLEAN)
    with pytest.raises(UnverifiedResult):
        writer.write_section("Integrated plan", [forged, given[1]])
    other_key = sign_result(FEAS, "feasibility", dict(given[0].figures), key=os.urandom(32))
    with pytest.raises(UnverifiedResult):
        writer.write_section("Integrated plan", [other_key])
    assert model.calls == []


@pytest.mark.parametrize(
    "figure", [100.0, True, "10000", {"minor": 1.5, "currency": "USD"}],
    ids=["float", "bool", "string", "float-minor"])
def test_a_figure_is_money_or_a_count_never_a_float(figure):
    with pytest.raises(ValidationError):
        sign_result(FEAS, "feasibility", {"cash": figure}, key=SIGNING_KEY)


def test_a_section_never_reads_graph_memory():
    writer, _ = agent(CLEAN)
    with pytest.raises(RuntimeError, match="never graph memory"):
        writer.zep_tools.quick_search(graph_id="g-1", query="cash")


def test_the_template_alone_is_grounded():
    given = results()
    _, links, problems = ground(template_draft(given), given)
    assert problems == [] and len(links) == 6


def test_an_unplanned_model_call_is_not_swallowed():
    writer, _ = agent(INVENTED)
    with pytest.raises(UnexpectedModelCall):
        writer.write_section("Integrated plan", results())
