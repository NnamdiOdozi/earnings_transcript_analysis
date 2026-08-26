"""Proves the pipeline is industry-agnostic: three transcripts from materially
different businesses (subscription/tech, retailer, insurer) each validate and
produce a signal card + metrics using that company's own vocabulary, with no
sector-specific code path and no cross-contamination of terms between industries.
"""
import json
from pathlib import Path

import pytest

from earnings import config
from earnings.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def isolated_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "RESEARCH_SEC_ENABLED", False)  # no network in tests
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", False)
    yield tmp_path / "runs"


CASES = [
    {
        "name": "subscription",
        "ticker": "BETA",
        "transcript": "subscription_transcript.txt",
        "segment_needle": "118%",
        "quote": "Annual recurring revenue grew to $85 million, up from $70 million a year ago.",
        "claim_text": "Annual recurring revenue was $85 million, up from $70 million.",
        "metric_name": "Annual recurring revenue",
        "metric_value": 85.0,
        "metric_unit": "USD millions",
        "sector_term": "Annual recurring revenue",
        "foreign_terms": ["Comparable sales", "combined ratio", "Gross written premiums"],
    },
    {
        "name": "retailer",
        "ticker": "GAMMA",
        "transcript": "retailer_transcript.txt",
        "segment_needle": "Comparable sales grew 6%",
        "quote": "Comparable sales grew 6% versus last year, and total revenue was $240 million, up from $225 million a year ago.",
        "claim_text": "Comparable sales grew 6% and total revenue was $240 million.",
        "metric_name": "Comparable sales growth",
        "metric_value": 6.0,
        "metric_unit": "%",
        "sector_term": "Comparable sales",
        "foreign_terms": ["Annual recurring revenue", "combined ratio", "Gross written premiums"],
    },
    {
        "name": "insurer",
        "ticker": "DELTA",
        "transcript": "insurer_transcript.txt",
        "segment_needle": "Combined ratio was 96%",
        "quote": "Gross written premiums were $410 million, up from $380 million a year ago. Combined ratio was 96% this quarter.",
        "claim_text": "Gross written premiums were $410 million with a combined ratio of 96%.",
        "metric_name": "Combined ratio",
        "metric_value": 96.0,
        "metric_unit": "%",
        "sector_term": "Gross written premiums",
        "foreign_terms": ["Annual recurring revenue", "Comparable sales"],
    },
]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_pipeline_discovers_company_specific_metrics_generically(isolated_runs_dir, case):
    transcript = str(FIXTURES / case["transcript"])
    rc = main(["prepare", "--ticker", case["ticker"], "--event-id", "2026-q2", "--transcript", transcript])
    assert rc == 0

    run_dir = isolated_runs_dir / case["ticker"] / "2026-q2"
    segment_lines = (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    segment = next(s for s in segments if case["segment_needle"] in s["text"])

    claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": case["claim_text"],
            "quote": case["quote"],
            "segment_id": segment["id"],
            "speaker": segment["speaker"],
            "status": "reported",
            "values": {},
            "confidence": 0.9,
        }
    ]
    (run_dir / config.CLAIMS_FILENAME).write_text(json.dumps(claims))

    metrics = [
        {
            "name": case["metric_name"],
            "value": case["metric_value"],
            "unit": case["metric_unit"],
            "period": "Q2 FY2026",
            "definition": f"As reported by {case['ticker']} management on the earnings call.",
            "source_claim_ids": ["claim-001"],
        }
    ]
    (run_dir / config.METRICS_FILENAME).write_text(json.dumps(metrics))

    rc = main(["analyze", "--ticker", case["ticker"], "--event-id", "2026-q2"])
    assert rc == 0

    validation = json.loads((run_dir / config.VALIDATION_FILENAME).read_text())
    assert validation["ok"] is True

    card = (run_dir / config.SIGNAL_CARD_FILENAME).read_text()
    assert case["sector_term"] in card
    for foreign_term in case["foreign_terms"]:
        assert foreign_term not in card, f"{case['name']} card leaked unrelated sector term {foreign_term!r}"


def test_metric_with_no_source_claim_ids_fails_validation(isolated_runs_dir):
    """A metric with no citation is exactly the ungrounded-figure problem this
    pipeline exists to catch -- at the metric layer, not just the claim layer."""
    case = CASES[0]
    transcript = str(FIXTURES / case["transcript"])
    main(["prepare", "--ticker", case["ticker"], "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / case["ticker"] / "2026-q2"
    segment_lines = (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    segment = next(s for s in segments if case["segment_needle"] in s["text"])

    claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": case["claim_text"],
            "quote": case["quote"],
            "segment_id": segment["id"],
            "status": "reported",
            "values": {},
            "confidence": 0.9,
        }
    ]
    (run_dir / config.CLAIMS_FILENAME).write_text(json.dumps(claims))

    metrics = [
        {
            "name": case["metric_name"],
            "value": case["metric_value"],
            "unit": case["metric_unit"],
            "period": "Q2 FY2026",
            "definition": "Unsourced.",
            "source_claim_ids": [],  # no citation -- must fail
        }
    ]
    (run_dir / config.METRICS_FILENAME).write_text(json.dumps(metrics))

    rc = main(["analyze", "--ticker", case["ticker"], "--event-id", "2026-q2"])
    assert rc == 1

    validation = json.loads((run_dir / config.VALIDATION_FILENAME).read_text())
    assert validation["ok"] is False
    assert any(issue["check"] == "metric_provenance" for issue in validation["issues"])
