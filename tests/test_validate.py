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
    check_outlook_brief_dollar_escaping,
    extract_numbers,
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


@pytest.mark.parametrize(
    "text,expected",
    [
        # A hyphen directly between two numbers is a RANGE separator, not a minus sign
        # -- regression for the bug where "37%-38%" parsed as {37.0, -38.0}.
        ("guidance of 37%-38% for next quarter", {37.0, 38.0}),
        ("revenue of $80.65-81.75 billion", {80.65, 81.75}),
        ("revenue of $80.65-$81.75 billion", {80.65, 81.75}),
        ("growth of 10-15% is expected", {10.0, 15.0}),
        # A genuine negative figure must keep its sign, not silently become positive
        # -- this was a real latent bug (a net loss would ground against a positive).
        ("a net loss of -$50 million this quarter", {-50.0}),
        ("revenue declined -5% year over year", {-5.0}),
        # No hyphen at all involved -- must not regress under a left-context guard.
        ("growth of 15% to %17", {15.0, 17.0}),
        ("commercial bookings increased 230% and 228% in constant currency", {230.0, 228.0}),
    ],
)
def test_extract_numbers_distinguishes_range_hyphen_from_minus_sign(text, expected):
    assert extract_numbers(text) == expected


def test_claim_text_numbers_accepts_hyphenated_range_grounded_in_evidence(financials):
    # The exact scenario hit while extracting real MSFT claims: prose phrases a range
    # with a hyphen, and both bounds are genuinely grounded in the cited segment.
    segment_text = normalize_whitespace(
        "In Azure, we expect Q3 revenue growth to be between 37% and 38% in constant currency."
    )
    claim = Claim(
        id="claim-test-100",
        category="current_guidance",
        classification="management_guidance",
        claim_text="Azure guidance of 37%-38% for Q3.",
        quote="In Azure, we expect Q3 revenue growth to be between 37% and 38% in constant currency.",
        segment_id="seg-0004",
        status="forward_looking",
        values={"low_pct": 37, "high_pct": 38},
        confidence=0.9,
    )
    assert check_claim_text_numbers(claim, segment_text, "seg-0004", financials) is None


def test_claim_text_numbers_still_catches_fabricated_range_bound(financials):
    # Confirms the range fix didn't blunt fabrication detection: only 80 is grounded,
    # 90 is invented and must still fail.
    segment_text = normalize_whitespace("We expect revenue of approximately $80 billion.")
    claim = Claim(
        id="claim-test-101",
        category="current_guidance",
        classification="management_guidance",
        claim_text="Guidance of $80-90 billion.",
        quote="We expect revenue of approximately $80 billion.",
        segment_id="seg-0004",
        status="forward_looking",
        values={},
        confidence=0.9,
    )
    error = check_claim_text_numbers(claim, segment_text, "seg-0004", financials)
    assert error is not None
    assert "90" in error


def test_exact_quote_passes_for_verbatim_substring(revenue_segment):
    claim = Claim(
        id="claim-test-102",
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
        id="claim-test-103",
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
        id="claim-test-104",
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
        id="claim-test-105",
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
        id="claim-test-106",
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
        id="claim-test-107",
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
        id="claim-test-108",
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
        id="claim-test-109",
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
        id="claim-test-110",
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
        id="claim-test-111",
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
        id="claim-test-112",
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
        id="claim-test-113",
        category="reported_financial_performance",
        classification="reported_fact",
        claim_text="Revenue for fiscal 2027 and Q2 2026 was $110 million, matching the quote.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        confidence=0.9,
    )
    assert check_claim_text_numbers(claim, revenue_segment.text, revenue_segment.id, financials) is None


def test_claim_text_numbers_ignores_claim_id_citations_in_reasoning_prose(revenue_segment, financials):
    # Regression: an analytical_inference's claim_text legitimately cites other claim
    # ids in its reasoning prose (e.g. "per claim-011"). The digits inside "claim-011"
    # must not be misread as the number -11 or 11 and demanded to ground -- they're an
    # id, not a financial figure.
    claim = Claim(
        id="claim-test-114",
        category="management_explanation",
        classification="analytical_inference",
        claim_text="Revenue was $110 million, consistent with the demand signal noted in claim-011 and claim-015.",
        quote="Revenue for the quarter was $110 million, up from $100 million a year ago.",
        segment_id="seg-0001",
        status="reported",
        values={},
        confidence=0.7,
        inferred_from=["claim-011", "claim-015"],
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
        id="claim-test-115",
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
        id="claim-test-116",
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
        id="claim-test-117",
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
            id="claim-test-118",
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
        id="claim-test-119",
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
        id="claim-test-120",
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
            id="claim-test-001",
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
            id="claim-test-002",
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Revenue rose.",
            quote="Revenue climbed to $110 million this quarter.",
            segment_id="seg-0001",
            status="reported",
            confidence=0.8,
        ),
        Claim(  # 2: fabricated number -> fails
            id="claim-test-003",
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
            id="claim-test-004",
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
            id="claim-test-005",
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


def test_inference_claim_fails_when_citing_itself(revenue_segment, financials):
    # Self-reference guard (#13): an analytical_inference claim naming its own id in
    # inferred_from must fail -- it can't be evidence for itself.
    segments_by_id = {"seg-0001": revenue_segment}
    claims = [
        Claim(
            id="claim-001",
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
    assert result.ok is False
    issue = next(i for i in result.issues if i.claim_index == 0)
    assert issue.check == "inference_citation"
    assert "cites itself" in issue.message


def test_validate_claims_fails_for_duplicate_ids(revenue_segment, financials):
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
            id="claim-001",  # duplicate of the claim above
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Net income was $20 million.",
            quote="Net income was $20 million.",
            segment_id="seg-0001",
            status="reported",
            values={"net_income_millions": 20},
            confidence=0.9,
        ),
    ]
    result = validate_claims(claims, segments_by_id, financials)
    assert result.ok is False
    issue = next(i for i in result.issues if i.claim_index == 1)
    assert issue.check == "claim_id"
    assert "Duplicate" in issue.message


def test_validate_claims_passes_with_unique_ids(revenue_segment, financials):
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
            category="reported_financial_performance",
            classification="reported_fact",
            claim_text="Net income was $20 million.",
            quote="Net income was $20 million.",
            segment_id="seg-0001",
            status="reported",
            values={"net_income_millions": 20},
            confidence=0.9,
        ),
    ]
    result = validate_claims(claims, segments_by_id, financials)
    assert result.ok is True
    assert result.issues == []


def test_evidence_reference_fails_when_neither_set():
    claim = Claim(
        id="claim-test-121",
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
        id="claim-test-122",
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
        id="claim-test-123",
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
            id="claim-test-006",
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
    result = validate_claims(
        claims,
        segments_by_id={},
        financials={},
        web_evidence_texts=web_evidence_texts,
        web_evidence_statuses={"web-001": "undated"},
    )
    assert result.ok is True
    # Web evidence WAS consumed (a claim cites web-001), so no "unconsumed" advisory.
    assert result.warnings == []


def test_validate_claims_rejects_post_event_web_evidence():
    claims = [
        Claim(
            id="claim-test-007",
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
    result = validate_claims(
        claims,
        segments_by_id={},
        financials={},
        web_evidence_texts=web_evidence_texts,
        web_evidence_statuses={"web-001": "post_event"},
    )
    assert result.ok is False
    assert result.issues[0].check == "temporal_eligibility"


def test_warns_when_web_evidence_fetched_but_uncited(revenue_segment, financials):
    # The "downloaded but unconsumed" guard: web evidence exists for the run but every
    # claim anchors to a transcript segment, so the web search added nothing to the
    # claims. Non-failing -- ok stays True (the card is valid), the advisory is surfaced.
    segments_by_id = {"seg-0001": revenue_segment}
    claims = [
        Claim(
            id="claim-test-007",
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
    web_evidence_texts = {"web-001": "Analyst consensus was $105 million ahead of the print."}
    result = validate_claims(claims, segments_by_id, financials, web_evidence_texts=web_evidence_texts)
    assert result.ok is True
    assert result.issues == []
    assert result.warnings and "no claim cites any" in result.warnings[0]
    assert result.warnings[0].startswith("1 web evidence source(s)")


def test_validate_claims_fails_for_unknown_web_evidence_id():
    claims = [
        Claim(
            id="claim-test-008",
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


def test_sources_extract_financials_prefers_original_filing_over_restatement():
    from earnings.sources import extract_financials_from_company_facts

    # Two facts share the same period "end" (same quarter) but differ in "filed" date
    # and "val" -- the earlier-filed one is the original 10-Q, the later-filed one is
    # a restatement (10-Q/A) for the same period. Only the original was knowable at
    # the earnings event, so it must be the one selected, never the restatement.
    company_facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "end": "2026-06-30",
                                "start": "2026-04-01",
                                "val": 110000000,
                                "filed": "2026-07-25",
                                "form": "10-Q",
                                "fy": 2026,
                                "accn": "0000000000-26-000001",
                            },
                            {
                                "end": "2026-06-30",
                                "start": "2026-04-01",
                                "val": 999000000,
                                "filed": "2026-09-15",
                                "form": "10-Q/A",
                                "fy": 2026,
                                "accn": "0000000000-26-000002",
                            },
                        ]
                    }
                }
            }
        }
    }
    out = extract_financials_from_company_facts(company_facts, concepts=["Revenues"])
    assert out["Revenues"]["value"] == 110000000
    assert out["Revenues"]["filed"] == "2026-07-25"
    assert out["Revenues"]["form"] == "10-Q"


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


def test_sources_extract_financials_derives_period_type_and_duration():
    from earnings.sources import extract_financials_from_company_facts

    company_facts = json.loads((FIXTURES / "sec_company_facts.json").read_text(encoding="utf-8"))
    out = extract_financials_from_company_facts(company_facts, concepts=["Revenues"])
    assert out["Revenues"]["start"] == "2026-04-01"
    assert out["Revenues"]["period_type"] == "quarter"
    assert out["Revenues"]["duration_days"] == 90


def test_sources_extract_financials_period_type_resolves_end_date_ambiguity():
    # Regression for the real MSFT bug: three facts share end=2026-06-30 (quarter,
    # half-year YTD, full-year) -- period_end alone can't tell them apart, but
    # period_type (derived from each fact's own start/end) can.
    from earnings.sources import extract_financials_from_company_facts

    company_facts = json.loads((FIXTURES / "sec_company_facts.json").read_text(encoding="utf-8"))
    concept = "RevenueFromContractWithCustomerExcludingAssessedTax"

    quarterly = extract_financials_from_company_facts(
        company_facts, concepts=[concept], period_end="2026-06-30", period_type="quarter"
    )
    assert quarterly[concept]["value"] == 30000000
    assert quarterly[concept]["start"] == "2026-04-01"

    half_year = extract_financials_from_company_facts(
        company_facts, concepts=[concept], period_end="2026-06-30", period_type="half_year"
    )
    assert half_year[concept]["value"] == 55000000

    full_year = extract_financials_from_company_facts(
        company_facts, concepts=[concept], period_end="2026-06-30", period_type="full_year"
    )
    assert full_year[concept]["value"] == 115000000

    # Without period_type, the ambiguity is real: "latest by end" ties on end date and
    # falls back to whichever fact happens to be max()'d first among ties -- exactly
    # the silent-wrong-duration risk period_type exists to close.
    ambiguous = extract_financials_from_company_facts(
        company_facts, concepts=[concept], period_end="2026-06-30"
    )
    assert ambiguous[concept]["end"] == "2026-06-30"  # end alone doesn't disambiguate value


def test_sources_extract_financials_drops_concept_when_period_type_unmatched_and_required():
    from earnings.sources import extract_financials_from_company_facts

    company_facts = json.loads((FIXTURES / "sec_company_facts.json").read_text(encoding="utf-8"))
    # No 9-month fact exists for this concept -- fail closed (drop it), don't silently
    # substitute a different-duration fact, matching the existing period_end convention.
    out = extract_financials_from_company_facts(
        company_facts,
        concepts=["RevenueFromContractWithCustomerExcludingAssessedTax"],
        period_end="2026-06-30",
        period_type="nine_months",
        require_period_type_match=True,
    )
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" not in out


def test_sources_extract_financials_falls_back_when_period_type_match_not_required():
    from earnings.sources import extract_financials_from_company_facts

    company_facts = json.loads((FIXTURES / "sec_company_facts.json").read_text(encoding="utf-8"))
    out = extract_financials_from_company_facts(
        company_facts,
        concepts=["RevenueFromContractWithCustomerExcludingAssessedTax"],
        period_end="2026-06-30",
        period_type="nine_months",
        require_period_type_match=False,
    )
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in out


def test_sources_extract_financials_instant_fact_has_no_period_type():
    # A balance-sheet/instant concept (no "start" at all) must not crash or be
    # misclassified -- period_type/duration_days are simply None.
    from earnings.sources import extract_financials_from_company_facts

    company_facts = {
        "facts": {
            "us-gaap": {
                "Assets": {"units": {"USD": [{"end": "2026-06-30", "val": 500000000, "form": "10-Q", "fy": 2026}]}}
            }
        }
    }
    out = extract_financials_from_company_facts(company_facts, concepts=["Assets"])
    assert out["Assets"]["start"] is None
    assert out["Assets"]["period_type"] is None
    assert out["Assets"]["duration_days"] is None


def _finding(artifact: str, passage: str = "n/a") -> ReviewFinding:
    return ReviewFinding(
        severity="info", artifact=artifact, passage=passage, evidence="e", recommendation="r"
    )


def _review_report(**overrides) -> ReviewReport:
    values = {
        "verdict": "pass",
        "review_mode": "full",
        "reviewed_at": "2026-08-25T12:00:00Z",
        "claims_sha256": "a" * 64,
        "outlook_brief_sha256": "b" * 64,
        "source_checks": [_finding("manifest.json")],
        "process_findings": [_finding("validation.json")],
        "summary": "Clean.",
    }
    values.update(overrides)
    return ReviewReport(**values)


def test_validate_review_report_passes_with_real_claim_citations():
    report = _review_report(
        claim_findings=[_finding("claims.json#claim-001")],
    )
    issues = validate_review_report(report, claim_ids={"claim-001", "claim-002"})
    assert issues == []


def test_validate_review_report_fails_for_fabricated_claim_citation():
    report = _review_report(
        verdict="fail",
        claim_findings=[ReviewFinding(
            severity="high", artifact="claims.json#claim-999", passage="claim-999 does not exist",
            evidence="e", recommendation="r",
        )],
        summary="Fabricated citation.",
    )
    issues = validate_review_report(report, claim_ids={"claim-001"})
    assert len(issues) == 1
    assert issues[0].check == "review_citation"
    assert "claim-999" in issues[0].message


def test_validate_review_report_rejects_empty_review_receipts():
    report = _review_report(source_checks=[], process_findings=[])
    issues = validate_review_report(report, claim_ids={"claim-001"})
    assert [issue.check for issue in issues].count("review_receipt") == 2


def test_validate_review_report_rejects_fail_without_high_severity():
    report = _review_report(verdict="fail", claim_findings=[_finding("claims.json#claim-001")])
    issues = validate_review_report(report, claim_ids={"claim-001"})
    assert any(issue.check == "verdict_severity" and "no finding" in issue.message for issue in issues)


def test_review_report_rejects_invalid_verdict():
    with pytest.raises(ValidationError):
        _review_report(verdict="maybe", summary="Bad verdict.")


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


def test_outlook_brief_citations_fails_when_no_ids_cited_at_all():
    # (#14) A brief that cites zero claim ids is ungrounded outright -- every
    # conclusion must trace to a validated claim, even if no id is wrong/unknown.
    errors = check_outlook_brief_citations("a purely narrative outlook with no citations", claim_ids={"claim-007"})
    assert len(errors) == 1
    assert "cites no claim ids" in errors[0]


def test_dollar_escaping_passes_when_all_escaped():
    text = "Revenue was \\$81.3B and Microsoft Cloud was \\$51.5B [claim-001][claim-003]."
    assert check_outlook_brief_dollar_escaping(text) == []


def test_dollar_escaping_fails_on_two_unescaped_dollars():
    # Two unescaped '$' is an EVEN count -- the common, corrupting case (citing two
    # currency amounts) -- so this must fail, not pass under an odd-count heuristic.
    text = "Revenue was $81.3B and Microsoft Cloud was $51.5B."
    errors = check_outlook_brief_dollar_escaping(text)
    assert len(errors) == 1
    assert "2 unescaped" in errors[0]


def test_dollar_escaping_fails_on_single_unescaped_dollar():
    errors = check_outlook_brief_dollar_escaping("Revenue was $81.3B.")
    assert len(errors) == 1
    assert "1 unescaped" in errors[0]


def test_dollar_escaping_reports_line_numbers():
    text = "line one is fine\nline two has $81.3B\nline three is fine\nline four has $51.5B"
    errors = check_outlook_brief_dollar_escaping(text)
    assert "[2, 4]" in errors[0]


def test_validate_review_report_ignores_hyphenated_prose_in_finding_text():
    report = _review_report(
        claim_findings=[_finding("claims.json#claim-001", "a claim-based, claim-level assessment")],
    )
    issues = validate_review_report(report, claim_ids={"claim-001"})
    assert issues == []


def test_validate_review_report_catches_fabricated_id_in_evidence_and_recommendation():
    # (#15) The citation scan must cover all four ReviewFinding text fields, not just
    # artifact/passage -- a fabricated claim id hidden in evidence or recommendation
    # must still be caught.
    report = _review_report(
        claim_findings=[
            ReviewFinding(
                severity="info",
                artifact="claims.json#claim-001",
                passage="n/a",
                evidence="corroborated by claim-999",  # fabricated, only in evidence
                recommendation="cross-check against claim-998",  # fabricated, only in recommendation
            )
        ],
        summary="Clean.",
    )
    issues = validate_review_report(report, claim_ids={"claim-001"})
    assert len(issues) == 1
    assert "claim-999" in issues[0].message
    assert "claim-998" in issues[0].message
