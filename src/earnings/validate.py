"""Deterministic validators: exact-quote, numerical, calculation, schema.

Design: every check is pure and takes plain data structures (segments-by-id, claims,
financials evidence) so it is trivially unit-testable without touching disk or network.
"""
from __future__ import annotations

import re
from typing import Any

from .calculations import recompute
from .config import NUMERIC_MATCH_TOLERANCE
from .models import Claim, Metric, ReviewReport, Segment, ValidationIssue, ValidationResult
from .process import normalize_whitespace

# How claim ids are cited in free text (claims.json ids, and inside outlook-brief.md's
# evidence appendix) -- matches the "claim-012" style used in the skill docs.
_CLAIM_ID_RE = re.compile(r"\bclaim-\d[a-zA-Z0-9_-]*\b")

# Matches numbers with optional $, thousands separators, decimals, % or unit suffix.
# The leading `-?` (before AND after the currency symbol) exists to preserve a genuine
# negative figure's sign ("-$50 million net loss" -> -50, not +50 with the sign
# silently dropped) -- this only works because _find_number_tokens() below first
# neutralizes any hyphen that is actually a RANGE separator (e.g. "37%-38%"), so any
# "-" still present when this regex runs is a real minus sign, never a range dash.
_NUMBER_RE = re.compile(r"-?[$€£]?\s*-?\d[\d,]*(?:\.\d+)?\s*%?")

# A hyphen directly between the tail of one number and the start of another is a range
# separator ("37%-38%", "$80.65-81.75 billion", "10-15%"), not a minus sign -- replaced
# with a space before _NUMBER_RE ever runs, so it can't be mistaken for a negative sign
# on the second number. Deliberately narrow: only fires when a number-tail character
# ($/%/digit) sits on both sides of the hyphen, so it never touches an isolated negative
# like "-$50 million" (nothing precedes that hyphen) or a hyphenated word.
_RANGE_HYPHEN_RE = re.compile(r"(?<=[\d%])-(?=[\d$€£])")


def _find_number_tokens(text: str) -> list[str]:
    """Range-hyphen-neutralized _NUMBER_RE.findall -- the single place both
    extract_numbers() and check_claim_text_numbers() get raw number tokens from, so a
    range vs. negative-sign fix only has to live in one spot.
    """
    return _NUMBER_RE.findall(_RANGE_HYPHEN_RE.sub(" ", text))

# Calendar/period tokens are not financial figures; strip them before grounding
# claim_text prose so "fiscal 2027" / "Q2 2026" don't demand grounding. HARDENED so a
# round-thousand MAGNITUDE that happens to look like a year (e.g. "$2000", "2000
# million") is NOT mistaken for a calendar token and stripped -- otherwise a fabricated
# round-thousand figure would silently escape the claim_text grounding check. A bare
# 4-digit year is only stripped when it carries no money cue: not preceded by a currency
# symbol, and not followed by a magnitude unit (%, million/billion/thousand, m/bn/k).
_MAGNITUDE_UNIT = r"%|million|billion|thousand|bps|units|m|bn|k"
_PERIOD_TOKEN_RE = re.compile(
    r"\bFY\s?20\d{2}\b"  # FY2027 / FY 2027
    r"|\bQ[1-4]\b"  # Q1..Q4
    rf"|(?<![$€£])\b(?:19|20)\d{{2}}\b(?!\s*(?:{_MAGNITUDE_UNIT})\b)",  # bare year, no money cue
    re.IGNORECASE,
)


def _clean_number_token(token: str) -> float | None:
    """Strip currency symbols/commas/%/sign and parse to float, or None if not numeric.

    A leading '-' may sit before the currency symbol ("-$50") or, rarely, after it
    ("$-50") -- both are checked and stripped explicitly, since a plain
    .lstrip("$...") first would silently discard a "-$50" sign along with the "$".
    """
    t = token.strip()
    negative = t.startswith("-")
    if negative:
        t = t[1:]
    t = t.lstrip("$€£")
    if t.startswith("-"):
        negative = True
        t = t[1:]
    t = t.replace(",", "").rstrip("%").strip()
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if negative else value


def extract_numbers(text: str) -> set[float]:
    """Extract all numeric values mentioned in free text, tolerant of $/%/commas/signs."""
    numbers = set()
    for match in _find_number_tokens(text):
        value = _clean_number_token(match)
        if value is not None:
            numbers.add(value)
    return numbers


def check_exact_quote(claim: Claim, text: str, location: str) -> str | None:
    """Return an error message if claim.quote is not an exact substring of the cited
    evidence's (already canonically normalized) text, else None.

    `text` is either a transcript segment's text or an extracted WebEvidence's
    content -- both sides re-normalized here defensively, since claim.quote comes
    from claims.json authored by the agent and could have stray whitespace.
    `location` is the segment_id or web_evidence_id, used only for the message.
    """
    quote_norm = normalize_whitespace(claim.quote)
    text_norm = normalize_whitespace(text)
    if not quote_norm:
        return "Quote is empty"
    if quote_norm not in text_norm:
        return f"Quote does not occur exactly in {location}"
    return None


def known_numbers(text: str, financials: dict[str, Any]) -> set[float]:
    """The set of numbers a claim is allowed to assert: everything mentioned in the
    cited evidence's text plus every deterministic SEC/XBRL value in the evidence file.
    Shared by check_numeric (scalar values) and check_calculation_inputs (calc inputs).
    """
    financial_numbers = {
        entry["value"]
        for entry in financials.values()
        if isinstance(entry, dict) and isinstance(entry.get("value"), (int, float))
    }
    return extract_numbers(text) | financial_numbers


def _is_grounded(value: float, known: set[float]) -> bool:
    return any(abs(value - k) < NUMERIC_MATCH_TOLERANCE for k in known)


def check_numeric(claim: Claim, text: str, location: str, financials: dict[str, Any]) -> str | None:
    """Every number in claim.values must appear in the cited evidence's text OR match
    a value present in evidence/financials.json (deterministic SEC/XBRL evidence).

    Only scalar int/float entries in claim.values are checked; nested calculation
    results are handled separately by check_calculations, and calculation *inputs*
    by check_calculation_inputs.

    Note: grounding here is presence-only -- it confirms the numeric value appears
    somewhere in the evidence/financials, not that its unit/scale matches (e.g. a
    claim of revenue=12 can be "grounded" by an unrelated "12%" in the text).
    Semantic unit correctness is out of scope for Python and is the
    outlook-reviewer's remit.
    """
    known = known_numbers(text, financials)
    for key, value in claim.values.items():
        if key == "calculation" or not isinstance(value, (int, float)):
            continue
        if not _is_grounded(value, known):
            return f"Value {value!r} for '{key}' not found in {location} or financials evidence"
    return None


def _claim_declared_numbers(claim: Claim) -> set[float]:
    """Numbers the claim itself declares in `values` (scalars plus any calculation
    block's inputs/result) -- these are allowed to appear in claim_text without also
    being quoted, since they are separately checked by check_numeric/check_calculations.
    """
    numbers: set[float] = set()
    for key, value in claim.values.items():
        if key == "calculation" and isinstance(value, dict):
            inputs = value.get("inputs")
            if isinstance(inputs, dict):
                numbers |= {v for v in inputs.values() if isinstance(v, (int, float))}
            result = value.get("result")
            if isinstance(result, (int, float)):
                numbers.add(result)
        elif isinstance(value, (int, float)):
            numbers.add(value)
    return numbers


def check_claim_text_numbers(claim: Claim, text: str, location: str, financials: dict[str, Any]) -> str | None:
    """Every number written in claim_text (free prose) must be grounded -- present in
    the cited evidence, in financials evidence, or declared in claim.values -- so a
    claim can't state a fabricated figure in prose while values/quote stay clean.
    """
    known = known_numbers(text, financials) | _claim_declared_numbers(claim)
    # Strip claim-id citations (e.g. "claim-011", legitimate in an analytical_inference's
    # reasoning prose -- see inferred_from) before period tokens, then before number
    # extraction: "claim-011" would otherwise be misread as the number -11 or 11 (the
    # id's own digits), demanding grounding for a figure that was never a financial claim.
    claim_text_no_periods = _PERIOD_TOKEN_RE.sub(" ", _CLAIM_ID_RE.sub(" ", claim.claim_text))
    # Iterate the raw regex matches (not the deduped float set) so each number keeps its
    # written form, letting us tell "10%" from "$10 million". Calculation results are
    # stored as fractions (0.10) while prose writes the percent form ("10%"), so the
    # value/100 leniency is applied ONLY to numbers actually written with a percent sign
    # -- otherwise it silently grounds a fabricated magnitude (e.g. "$2500 million"
    # "matches" a stored 25) and lets an invented figure through the check.
    for match in _find_number_tokens(claim_text_no_periods):
        value = _clean_number_token(match)
        if value is None:
            continue
        is_percent = "%" in match
        if not _is_grounded(value, known) and not (is_percent and _is_grounded(value / 100, known)):
            return (
                f"Number {value!r} in claim_text not found in {location}, "
                f"financials evidence, or claim.values"
            )
    return None


def check_calculation_inputs(claim: Claim, text: str, location: str, financials: dict[str, Any]) -> str | None:
    """Ground the *inputs* of a calculation block, not just its result.

    check_calculations proves the formula was applied correctly (result matches a
    Python recomputation), but a correct formula fed hallucinated base numbers would
    still pass that check. So every numeric input must itself trace back to the cited
    evidence or deterministic SEC evidence -- otherwise a claim could assert an
    ungrounded "10% growth" from invented current/prior figures. A claim with no
    calculation block trivially passes.
    """
    calc = claim.values.get("calculation")
    if calc is None or not isinstance(calc, dict):
        return None
    inputs = calc.get("inputs")
    if not isinstance(inputs, dict):
        return None
    known = known_numbers(text, financials)
    for name, value in inputs.items():
        if isinstance(value, (int, float)) and not _is_grounded(value, known):
            return (
                f"Calculation input {name}={value!r} not found in {location} "
                f"or financials evidence"
            )
    return None


def check_calculations(claim: Claim) -> str | None:
    """If claim.values contains a "calculation" block, recompute it in Python and
    compare against the claim's asserted result within tolerance.

    Expected shape: claim.values["calculation"] = {
        "name": "yoy_growth", "inputs": {"current": 110, "prior": 100}, "result": 0.10
    }
    A claim with no "calculation" block trivially passes this check (it asserts no
    derived metric, so there is nothing to recompute).
    """
    from .config import CALC_ABSOLUTE_TOLERANCE, CALC_RELATIVE_TOLERANCE

    calc = claim.values.get("calculation")
    if calc is None:
        return None
    try:
        name = calc["name"]
        inputs = calc["inputs"]
        asserted = calc["result"]
    except (KeyError, TypeError):
        return "Malformed 'calculation' block: requires name, inputs, result"

    try:
        recomputed = recompute(name, inputs)
    except (ValueError, TypeError) as exc:
        return f"Calculation '{name}' could not be recomputed: {exc}"

    tolerance = max(CALC_ABSOLUTE_TOLERANCE, CALC_RELATIVE_TOLERANCE * abs(recomputed))
    if abs(recomputed - asserted) > tolerance:
        return (
            f"Calculation '{name}' mismatch: claim asserts {asserted}, "
            f"Python recomputed {recomputed:.6f}"
        )
    return None


def check_evidence_reference(claim: Claim) -> str | None:
    """A claim cites exactly one evidence source: a transcript segment_id or a
    web_evidence_id (see models.WebEvidence) -- never both, never neither. Checked
    before attempting to resolve either one, so a malformed claim fails with a clear
    message instead of a confusing downstream lookup miss.
    """
    has_segment = bool(claim.segment_id)
    has_web = bool(claim.web_evidence_id)
    if has_segment and has_web:
        return "Claim cites both segment_id and web_evidence_id; exactly one is allowed"
    if not has_segment and not has_web:
        return "Claim cites neither segment_id nor web_evidence_id"
    return None


def check_inference_citations(claim: Claim, claim_ids: set[str]) -> str | None:
    """An `analytical_inference` claim must cite the claim id(s) it was derived from,
    and every cited id must be a real claim id present in this same claims.json --
    prevents an inference from being presented as evidence-backed when its cited
    sources are fabricated or missing.

    Claims of any other classification trivially pass (they cite a segment/quote
    directly instead, checked by check_exact_quote).
    """
    if claim.classification != "analytical_inference":
        return None
    if not claim.inferred_from:
        return "analytical_inference claim has no inferred_from claim ids"
    missing = [cid for cid in claim.inferred_from if cid not in claim_ids]
    if missing:
        return f"inferred_from cites unknown claim id(s): {missing!r}"
    return None


def validate_metrics(metrics: list[Metric], claim_ids: set[str]) -> list[ValidationIssue]:
    """Every discovered Metric must trace back to at least one real, cited claim id --
    a metric with no source_claim_ids (or a fabricated one) is exactly the kind of
    ungrounded figure this pipeline exists to catch, just at the metric layer instead
    of the claim layer.
    """
    issues: list[ValidationIssue] = []
    for idx, metric in enumerate(metrics):
        if not metric.source_claim_ids:
            issues.append(
                ValidationIssue(claim_index=idx, check="metric_provenance", message=f"Metric {metric.name!r} has no source_claim_ids")
            )
            continue
        missing = [cid for cid in metric.source_claim_ids if cid not in claim_ids]
        if missing:
            issues.append(
                ValidationIssue(
                    claim_index=idx,
                    check="metric_provenance",
                    message=f"Metric {metric.name!r} cites unknown claim id(s): {missing!r}",
                )
            )
    return issues


def check_outlook_brief_citations(outlook_text: str, claim_ids: set[str]) -> list[str]:
    """Every claim id cited anywhere in outlook-brief.md's prose/evidence appendix
    must be a real id from the validated claims.json -- the brief is agent-authored
    (interpretive synthesis is not deterministic Python's job), so this is the one
    check that gates it: cited evidence must actually exist and have passed
    validation. Returns a list of error messages (empty if all citations resolve).
    """
    cited = set(_CLAIM_ID_RE.findall(outlook_text))
    missing = sorted(cited - claim_ids)
    return [f"outlook-brief.md cites unknown claim id {cid!r}" for cid in missing]


# A '$' not already preceded by a backslash. Zero-tolerance (not odd-count): two
# unescaped '$' -- the common case of citing two currency amounts -- is an EVEN count
# and is exactly the shape that corrupts under KaTeX/MathJax preview rendering (the
# pair becomes one math span), so parity is the wrong heuristic; every '$' must be
# escaped, no exceptions.
_UNESCAPED_DOLLAR_RE = re.compile(r"(?<!\\)\$")


def check_outlook_brief_dollar_escaping(outlook_text: str) -> list[str]:
    """outlook-brief.md is agent-authored and never rewritten by Python (see
    check_outlook_brief_citations) -- so an unescaped '$' can only be caught, not
    silently fixed. A bare '$' pairs with the next one under KaTeX/MathJax-enabled
    Markdown previews and swallows everything between them (see
    reference/outlook-brief-template.md's escaping rule and its cited 2026-08-26
    incident). Detection-only: never mutates the file, just fails the gate with
    line numbers so the agent can fix it.
    """
    positions = [m.start() for m in _UNESCAPED_DOLLAR_RE.finditer(outlook_text)]
    if not positions:
        return []
    lines = sorted({outlook_text.count("\n", 0, p) + 1 for p in positions})
    return [
        f"outlook-brief.md has {len(positions)} unescaped '$' on line(s) {lines} -- "
        "write '\\$' for every currency amount (including inside quoted passages) so "
        "Markdown/KaTeX previews cannot mangle the text between two '$' signs."
    ]


def validate_claims(
    claims: list[Claim],
    segments_by_id: dict[str, Segment],
    financials: dict[str, Any],
    web_evidence_texts: dict[str, str] | None = None,
) -> ValidationResult:
    """Run all checks over every claim. A claim with no resolvable evidence
    reference (bad segment_id/web_evidence_id pairing, or a dangling id) fails
    immediately and is skipped for the other (evidence-text-dependent) checks.

    `web_evidence_texts` maps WebEvidence.id -> its extracted content text (see
    cli.cmd_analyze, which loads evidence/web-evidence.jsonl and each entry's
    content_path file). Absent/empty if no web evidence exists for this run.
    """
    issues: list[ValidationIssue] = []
    claim_ids = {claim.id for claim in claims if claim.id}
    web_evidence_texts = web_evidence_texts or {}

    for idx, claim in enumerate(claims):
        inference_error = check_inference_citations(claim, claim_ids)
        if inference_error:
            issues.append(ValidationIssue(claim_index=idx, check="inference_citation", message=inference_error))

        reference_error = check_evidence_reference(claim)
        if reference_error:
            issues.append(ValidationIssue(claim_index=idx, check="evidence_reference", message=reference_error))
            continue

        if claim.segment_id:
            segment = segments_by_id.get(claim.segment_id)
            if segment is None:
                issues.append(
                    ValidationIssue(
                        claim_index=idx,
                        check="schema",
                        message=f"No source segment found for segment_id {claim.segment_id!r}",
                    )
                )
                continue
            text, location = segment.text, segment.id
        else:
            text = web_evidence_texts.get(claim.web_evidence_id)
            if text is None:
                issues.append(
                    ValidationIssue(
                        claim_index=idx,
                        check="schema",
                        message=f"No web evidence found for web_evidence_id {claim.web_evidence_id!r}",
                    )
                )
                continue
            location = claim.web_evidence_id

        quote_error = check_exact_quote(claim, text, location)
        if quote_error:
            issues.append(ValidationIssue(claim_index=idx, check="exact_quote", message=quote_error))

        numeric_error = check_numeric(claim, text, location, financials)
        if numeric_error:
            issues.append(ValidationIssue(claim_index=idx, check="numeric", message=numeric_error))

        text_number_error = check_claim_text_numbers(claim, text, location, financials)
        if text_number_error:
            issues.append(ValidationIssue(claim_index=idx, check="claim_text_numeric", message=text_number_error))

        calc_error = check_calculations(claim)
        if calc_error:
            issues.append(ValidationIssue(claim_index=idx, check="calculation", message=calc_error))

        calc_input_error = check_calculation_inputs(claim, text, location, financials)
        if calc_input_error:
            issues.append(ValidationIssue(claim_index=idx, check="calculation_inputs", message=calc_input_error))

    return ValidationResult(ok=not issues, checked_claims=len(claims), issues=issues)


def validate_review_report(report: ReviewReport, claim_ids: set[str]) -> list[ValidationIssue]:
    """The one thing Python re-checks about Outlook_Reviewer's own output: every
    claim-### id it cites in a finding's artifact/passage text must be real. The
    reviewer's judgment (verdict, severities, recommendations) is not re-derived or
    graded here -- only citation integrity, same non-negotiable rule as everywhere
    else in this pipeline (check_outlook_brief_citations, check_inference_citations).
    """
    issues: list[ValidationIssue] = []
    all_findings = (
        report.source_checks + report.claim_findings + report.outlook_findings + report.process_findings
    )
    for idx, finding in enumerate(all_findings):
        cited = set(_CLAIM_ID_RE.findall(finding.artifact + " " + finding.passage))
        missing = sorted(cited - claim_ids)
        if missing:
            issues.append(
                ValidationIssue(
                    claim_index=idx,
                    check="review_citation",
                    message=f"review-report.json finding cites unknown claim id(s): {missing!r}",
                )
            )
    return issues
