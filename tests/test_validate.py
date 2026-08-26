import json
from pathlib import Path

import pytest

from pydantic import ValidationError

from earnings.models import Claim, ReviewFinding, ReviewReport, Segment
from earnings.process import normalize_whitespace
from earnings.validate import (
    check_calculation_inputs,
    check_calculations,
    check_claim_text_numbers,
    check_evidence_reference,
    check_exact_quote,
    check_numeric,
    check_outlook_brief_citations,
    validate_claims,
    validate_review_report,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def revenue_segment() -> Segment:
    text = normalize_whitespace(
        "Revenue for the quarter was $110 million, up from $100 million a year ago. "
        "Net income was $20 million."
    )
    return Segment(id="seg-0001", section="prepared", speaker="Jane Smith", text=text)


@pytest.fixture
def financials() -> dict:
    """Flattened evidence/financials.json shape, as produced by
    sources.extract_financials_from_company_facts (see test_sources_extract below).
    """
    from earnings.sources import extract_financials_from_company_facts

    company_facts = json.loads((FIXTURES / "sec_company_facts.json").read_text(encoding="utf-8"))
    return extract_financials_from_company_facts(company_facts, concepts=["Revenues", "NetIncomeLoss"])


def test_exact_quote_passes_for_verbatim_substring(revenue_segment):
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue grew year over year.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    assert check_exact_quote(claim, revenue_segment.text, revenue_segment.id) is None


def test_exact_quote_fails_for_paraphrase(revenue_segment):
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue grew year over year.",
        quote="Revenue increased to $110 million from $100 million last year.",  # paraphrased, not verbatim
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    error = check_exact_quote(claim, revenue_segment.text, revenue_segment.id)
    assert error is not None
    assert "does not occur exactly" in error


def test_exact_quote_tolerant_of_whitespace_differences(revenue_segment):
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue grew year over year.",
        quote="Revenue  for the quarter   was $110 million,\nup from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    assert check_exact_quote(claim, revenue_segment.text, revenue_segment.id) is None


def test_numeric_check_passes_when_number_in_segment(revenue_segment, financials):
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue was $110 million.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={"revenue_millions": 110},
        confidence=0.9,
    )
    assert check_numeric(claim, revenue_segment.text, revenue_segment.id, financials) is None


def test_numeric_check_fails_for_fabricated_number(revenue_segment, financials):
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue was $999 million.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={"revenue_millions": 999},  # not present anywhere
        confidence=0.9,
    )
    error = check_numeric(claim, revenue_segment.text, revenue_segment.id, financials)
    assert error is not None
    assert "not found" in error


def test_numeric_check_is_unit_blind_cross_unit_false_accept(revenue_segment, financials):
    # Documents a known limitation (not a new bug): grounding is presence-only, so a
    # claim of value=12 (intended as e.g. $12M) is "grounded" by an unrelated "12%" in
    # the segment. check_numeric can't tell units/scale apart -- semantic correctness
    # is the outlook-reviewer's remit, not deterministic Python's.
    segment = Segment(
        id="seg-0002",
        section="prepared",
        speaker="Jane Smith",
        text=normalize_whitespace("Gross margin rose 12% in the quarter."),
    )
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue was $12 million.",
        quote="Gross margin rose 12% in the quarter.",
        segment_id="seg-0002",
        status="reported",
        values={"revenue_millions": 12},  # unrelated to the 12% margin figure
        confidence=0.9,
    )
    assert check_numeric(claim, segment.text, segment.id, financials) is None


def test_numeric_check_passes_using_financials_evidence(revenue_segment, financials):
    # 110000000 (full-dollar revenue) appears only in SEC financials evidence, not
    # in this segment's text (which says "$110 million", i.e. the number 110, not
    # 110000000) -- proving the numeric check falls back to financials evidence.
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue per SEC filing was $110,000,000.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={"revenue_exact": 110000000},
        confidence=0.9,
    )
    assert check_numeric(claim, revenue_segment.text, revenue_segment.id, financials) is None


def test_calculation_check_passes_for_correct_recomputation():
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue grew 10% YoY.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={"calculation": {"name": "yoy_growth", "inputs": {"current": 110, "prior": 100}, "result": 0.10}},
        confidence=0.9,
    )
    assert check_calculations(claim) is None


def test_calculation_check_fails_for_wrong_derived_value():
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue grew 50% YoY.",  # wrong: actual is 10%
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={"calculation": {"name": "yoy_growth", "inputs": {"current": 110, "prior": 100}, "result": 0.50}},
        confidence=0.9,
    )
    error = check_calculations(claim)
    assert error is not None
    assert "mismatch" in error


def test_calculation_inputs_pass_when_grounded_in_segment(revenue_segment, financials):
    # inputs 110 and 100 both appear in the cited segment text.
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue grew 10% YoY.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={"calculation": {"name": "yoy_growth", "inputs": {"current": 110, "prior": 100}, "result": 0.10}},
        confidence=0.9,
    )
    assert check_calculation_inputs(claim, revenue_segment.text, revenue_segment.id, financials) is None


def test_calculation_inputs_fail_when_fabricated(revenue_segment, financials):
    # Formula is arithmetically correct (770/700 -> 0.10) but 770/700 appear nowhere
    # in the segment or SEC evidence: a hallucinated base fed to a correct formula.
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue grew 10% YoY.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={"calculation": {"name": "yoy_growth", "inputs": {"current": 770, "prior": 700}, "result": 0.10}},
        confidence=0.9,
    )
    # The result recomputation still passes -- the grounding check is what catches it.
    assert check_calculations(claim) is None
    error = check_calculation_inputs(claim, revenue_segment.text, revenue_segment.id, financials)
    assert error is not None
    assert "not found" in error


def test_claim_text_numbers_ignores_fiscal_year_and_quarter_tokens(revenue_segment, financials):
    # "fiscal 2027" / "Q2 2026" are calendar tokens, not financial figures -- neither
    # appears in the evidence, but they must not be forced to ground (regression for
    # the false-reject bug where extract_numbers treated years/quarters as figures).
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue for fiscal 2027 and Q2 2026 was $110 million, matching the quote.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    assert check_claim_text_numbers(claim, revenue_segment.text, revenue_segment.id, financials) is None


def test_claim_text_numbers_percent_leniency_only_applies_to_percent_written_numbers(
    revenue_segment, financials
):
    # The value/100 leniency exists so prose "10%" matches a stored fraction 0.10. It must
    # NOT apply to a plain magnitude: "$2000 million" divided by 100 is 20, which the
    # fixture's "$20 million" would otherwise ground -- letting an invented figure pass.
    # Regression for the percent-form false-accept hole (only "%"-written numbers get /100).
    fabricated = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue was $2000 million.",  # 2000/100 == 20 == fixture net income, but no "%"
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    error = check_claim_text_numbers(fabricated, revenue_segment.text, revenue_segment.id, financials)
    assert error is not None and "not found" in error

    # A genuinely percent-written number whose fraction IS grounded still passes.
    legit_percent = Claim(
        category="costs_margins_efficiency",
        classification="reported_fact",
        claim_text="Net margin was 20%.",  # 20/100 == 0.20; 20 itself is grounded ($20m), also fine
        quote="Net income was $20 million.",
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    assert check_claim_text_numbers(legit_percent, revenue_segment.text, revenue_segment.id, financials) is None


def test_claim_text_numbers_still_fails_for_fabricated_magnitude_despite_period_stripping(
    revenue_segment, financials
):
    # Period-token stripping must not accidentally swallow a genuinely fabricated number.
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Fiscal 2027 revenue was $999 million.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    error = check_claim_text_numbers(claim, revenue_segment.text, revenue_segment.id, financials)
    assert error is not None
    assert "not found" in error


def test_claim_text_numbers_still_grounds_round_thousand_magnitude_with_money_cue(
    revenue_segment, financials
):
    # Hardening regression: a round-thousand figure that LOOKS like a year but carries a
    # money cue ($ prefix or a magnitude unit) must NOT be swallowed by period-stripping,
    # so a fabricated "$2000 million" / "2000 bps" still fails grounding. Without the
    # hardening the bare-year regex ate these and the fabrication slipped through.
    # NB: pick magnitudes whose /100 percent-form is also ungrounded (avoid 2000->20,
    # which the fixture's "$20 million" would coincidentally ground via the percent path).
    for fabricated_text in ("Revenue was $2500 million.", "Margin widened 2600 bps."):
        claim = Claim(
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text=fabricated_text,
            quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
            segment_id="seg-0001",
            status="reported",
            confidence=0.9,
        )
        error = check_claim_text_numbers(claim, revenue_segment.text, revenue_segment.id, financials)
        assert error is not None, f"expected {fabricated_text!r} to fail grounding"
        assert "not found" in error


def test_claim_text_numbers_fails_for_fabricated_prose_number(revenue_segment, financials):
    # values is empty and quote is genuine -- only claim_text carries the fabrication.
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue was $999 million.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    error = check_claim_text_numbers(claim, revenue_segment.text, revenue_segment.id, financials)
    assert error is not None
    assert "not found" in error


def test_claim_text_numbers_accepts_percent_form_of_calculation_result(revenue_segment, financials):
    # calc result is stored as a fraction (0.10); prose naturally says "10%".
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue was $110 million, up 10% YoY.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={"calculation": {"name": "yoy_growth", "inputs": {"current": 110, "prior": 100}, "result": 0.10}},
        confidence=0.9,
    )
    assert check_claim_text_numbers(claim, revenue_segment.text, revenue_segment.id, financials) is None


def test_validate_claims_end_to_end_mixed_pass_fail(revenue_segment, financials):
    segments_by_id = {"seg-0001": revenue_segment}
    claims = [
        Claim(  # 0: valid
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Revenue was $110 million, up 10% YoY.",
            quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
            segment_id="seg-0001",
            status="reported",
            values={"calculation": {"name": "yoy_growth", "inputs": {"current": 110, "prior": 100}, "result": 0.10}},
            confidence=0.9,
        ),
        Claim(  # 1: paraphrased quote -> fails
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Revenue rose.",
            quote="Revenue climbed to $110 million this quarter.",
            segment_id="seg-0001",
            status="reported",
            confidence=0.8,
        ),
        Claim(  # 2: fabricated number -> fails
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Revenue was $999 million.",
            quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
            segment_id="seg-0001",
            status="reported",
            values={"revenue_millions": 999},
            confidence=0.5,
        ),
        Claim(  # 3: no source segment -> fails
            category="risk",
            classification="reported_fact",
            claim_text="Some risk.",
            quote="anything",
            segment_id="seg-9999",
            status="reported",
            confidence=0.5,
        ),
    ]
    result = validate_claims(claims, segments_by_id, financials)
    assert result.ok is False
    assert result.checked_claims == 4
    failed_indices = {issue.claim_index for issue in result.issues}
    assert failed_indices == {1, 2, 3}


def test_validate_claims_all_pass_is_ok(revenue_segment, financials):
    segments_by_id = {"seg-0001": revenue_segment}
    claims = [
        Claim(
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Revenue was $110 million.",
            quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
            segment_id="seg-0001",
            status="reported",
            values={"revenue_millions": 110},
            confidence=0.9,
        ),
    ]
    result = validate_claims(claims, segments_by_id, financials)
    assert result.ok is True
    assert result.issues == []


def test_inference_claim_fails_without_citation(revenue_segment, financials):
    segments_by_id = {"seg-0001": revenue_segment}
    claims = [
        Claim(
            id="claim-001",
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Revenue was $110 million.",
            quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
            segment_id="seg-0001",
            status="reported",
            values={"revenue_millions": 110},
            confidence=0.9,
        ),
        Claim(
            id="claim-002",
            category="management_explanation",
            classification="analytical_inference",  # no inferred_from -- must fail
            claim_text="Momentum appears to be building.",
            quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
            segment_id="seg-0001",
            status="reported",
            confidence=0.6,
        ),
    ]
    result = validate_claims(claims, segments_by_id, financials)
    assert result.ok is False
    issue = next(i for i in result.issues if i.claim_index == 1)
    assert issue.check == "inference_citation"


def test_inference_claim_passes_with_valid_citation(revenue_segment, financials):
    segments_by_id = {"seg-0001": revenue_segment}
    claims = [
        Claim(
            id="claim-001",
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Revenue was $110 million.",
            quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
            segment_id="seg-0001",
            status="reported",
            values={"revenue_millions": 110},
            confidence=0.9,
        ),
        Claim(
            id="claim-002",
            category="management_explanation",
            classification="analytical_inference",
            claim_text="Momentum appears to be building.",
            quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
            segment_id="seg-0001",
            status="reported",
            confidence=0.6,
            inferred_from=["claim-001"],
        ),
    ]
    result = validate_claims(claims, segments_by_id, financials)
    assert result.ok is True


def test_evidence_reference_fails_when_neither_set():
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue was $110 million.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        status="reported",
        confidence=0.9,
    )
    error = check_evidence_reference(claim)
    assert error is not None
    assert "neither" in error


def test_evidence_reference_fails_when_both_set():
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue was $110 million.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        web_evidence_id="web-001",
        status="reported",
        confidence=0.9,
    )
    error = check_evidence_reference(claim)
    assert error is not None
    assert "both" in error


def test_evidence_reference_passes_for_web_evidence_only():
    claim = Claim(
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Analysts noted strong demand.",
        quote="Analysts noted strong demand for the quarter.",
        web_evidence_id="web-001",
        status="reported",
        confidence=0.9,
    )
    assert check_evidence_reference(claim) is None


def test_validate_claims_grounds_web_evidence_citation():
    # A claim citing web_evidence_id instead of a transcript segment_id is checked
    # against web_evidence_texts the same way a segment-citing claim is checked
    # against segments_by_id -- proving Tavily-extracted content is now real,
    # quote-checkable evidence, not just archival.
    claims = [
        Claim(
            category="demand_activity",
            classification="reported_fact",
            claim_text="Analysts noted strong demand for the new product line.",
            quote="Analysts noted strong demand for the new product line this quarter.",
            web_evidence_id="web-001",
            status="reported",
            confidence=0.8,
        ),
    ]
    web_evidence_texts = {"web-001": "Analysts noted strong demand for the new product line this quarter."}
    result = validate_claims(claims, segments_by_id={}, financials={}, web_evidence_texts=web_evidence_texts)
    assert result.ok is True


def test_validate_claims_fails_for_unknown_web_evidence_id():
    claims = [
        Claim(
            category="demand_activity",
            classification="reported_fact",
            claim_text="Analysts noted strong demand.",
            quote="Analysts noted strong demand.",
            web_evidence_id="web-999",  # never extracted
            status="reported",
            confidence=0.8,
        ),
    ]
    result = validate_claims(claims, segments_by_id={}, financials={}, web_evidence_texts={})
    assert result.ok is False
    assert "No web evidence found" in result.issues[0].message


def test_sources_extract_financials_from_company_facts_flattens_latest_value():
    from earnings.sources import extract_financials_from_company_facts

    company_facts = json.loads((FIXTURES / "sec_company_facts.json").read_text(encoding="utf-8"))
    out = extract_financials_from_company_facts(company_facts, concepts=["Revenues", "NetIncomeLoss"])
    assert out["Revenues"]["value"] == 110000000  # latest by "end" date, not first in list
    assert out["Revenues"]["end"] == "2026-06-30"
    assert out["Revenues"]["unit"] == "USD"
    assert out["NetIncomeLoss"]["value"] == 20000000


def test_sources_extract_financials_pins_to_explicit_period_end():
    from earnings.sources import extract_financials_from_company_facts

    company_facts = json.loads((FIXTURES / "sec_company_facts.json").read_text(encoding="utf-8"))
    # An earlier period than the latest-by-end fact -- proves period_end overrides
    # the "just take the latest" default that could otherwise pick a later quarter,
    # an annual figure, or a restatement instead of the fact matching the event.
    out = extract_financials_from_company_facts(
        company_facts, concepts=["Revenues"], period_end="2025-06-30"
    )
    assert out["Revenues"]["end"] == "2025-06-30"
    assert out["Revenues"]["value"] == 100000000


def test_sources_extract_financials_drops_concept_absent_at_pinned_period():
    from earnings.sources import extract_financials_from_company_facts

    company_facts = json.loads((FIXTURES / "sec_company_facts.json").read_text(encoding="utf-8"))
    out = extract_financials_from_company_facts(
        company_facts, concepts=["Revenues"], period_end="1999-01-01"
    )
    assert "Revenues" not in out


def _finding(artifact: str, passage: str = "n/a") -> ReviewFinding:
    return ReviewFinding(
        severity="info", artifact=artifact, passage=passage, evidence="e", recommendation="r"
    )


def test_validate_review_report_passes_with_real_claim_citations():
    report = ReviewReport(
        verdict="pass",
        reviewed_at="2026-08-25T12:00:00Z",
        claim_findings=[_finding("claims.json#claim-001")],
        summary="Clean.",
    )
    issues = validate_review_report(report, claim_ids={"claim-001", "claim-002"})
    assert issues == []


def test_validate_review_report_fails_for_fabricated_claim_citation():
    report = ReviewReport(
        verdict="fail",
        reviewed_at="2026-08-25T12:00:00Z",
        claim_findings=[_finding("claims.json#claim-999", "claim-999 does not exist")],
        summary="Fabricated citation.",
    )
    issues = validate_review_report(report, claim_ids={"claim-001"})
    assert len(issues) == 1
    assert issues[0].check == "review_citation"
    assert "claim-999" in issues[0].message


def test_review_report_rejects_invalid_verdict():
    with pytest.raises(ValidationError):
        ReviewReport(verdict="maybe", reviewed_at="2026-08-25T12:00:00Z", summary="Bad verdict.")


@pytest.mark.parametrize(
    "text",
    [
        "a claim-based, bottom-up outlook citing claim-007 for support",
        "our claim-by-claim, claim-level review found claim-007 sound",
    ],
)
def test_outlook_brief_citations_ignores_hyphenated_prose_but_catches_real_id(text):
    # Regression for the false-reject bug: "claim-based"/"claim-level"/"claim-by-claim"
    # must not be parsed as claim ids, but a real claim-NNN id is still checked.
    errors = check_outlook_brief_citations(text, claim_ids={"claim-007"})
    assert errors == []


def test_outlook_brief_citations_still_catches_fabricated_id():
    errors = check_outlook_brief_citations("a claim-based outlook citing claim-999", claim_ids={"claim-007"})
    assert len(errors) == 1
    assert "claim-999" in errors[0]


def test_validate_review_report_ignores_hyphenated_prose_in_finding_text():
    report = ReviewReport(
        verdict="pass",
        reviewed_at="2026-08-25T12:00:00Z",
        claim_findings=[_finding("claims.json#claim-001", "a claim-based, claim-level assessment")],
        summary="Clean.",
    )
    issues = validate_review_report(report, claim_ids={"claim-001"})
    assert issues == []
