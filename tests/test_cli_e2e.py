"""End-to-end CLI test: prepare -> write claims.json -> analyze, using tmp_path so
no real network call happens (no --sec-cik passed) and no files leak outside tmp_path.
"""
import json
from pathlib import Path

import pytest

from earnings import config, ingest, sources
from earnings.paths import RunPaths
from earnings.rendering import _escape_currency
from earnings.provenance import _price_decision_issues
from earnings.review import _review_bundle_matches_snapshot, _review_round_count
from earnings.cli import main as _cli_main
from earnings.models import PriceLookupDecision
from earnings.process import sha256_hex

FIXTURES = Path(__file__).parent / "fixtures"


def main(args: list[str]) -> int:
    """Run the CLI with the default no-price decision used by existing fixtures."""
    if args and args[0] == "analyze" and "--price-decision" not in args:
        args = [
            *args,
            "--price-decision",
            "not_used",
            "--price-reason",
            "Fixture does not require market-price evidence",
        ]
    return _cli_main(args)


def _validation_attempt_dirs(run_dir: Path) -> list[Path]:
    history_dir = RunPaths.at(run_dir).validation_history
    return sorted(path for path in history_dir.iterdir() if path.is_dir())


def _outlook_validation_attempt_dirs(run_dir: Path) -> list[Path]:
    history_dir = RunPaths.at(run_dir).outlook_validation_history
    return sorted(path for path in history_dir.iterdir() if path.is_dir())


@pytest.fixture
def isolated_runs_dir(tmp_path, monkeypatch):
    """Redirect config.RUNS_DIR to a tmp_path subdirectory for the duration of the
    test, and disable SEC/Tavily auto-lookups (both on by default) so `prepare`
    never touches the network in tests.
    """
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "EXTRACTOR_LESSONS_PATH", tmp_path / "extractor-lessons.md")
    monkeypatch.setattr(config, "RESEARCH_SEC_ENABLED", False)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", False)
    yield tmp_path / "runs"


def test_prepare_then_analyze_empty_transcript_yields_zero_segments_and_passes(isolated_runs_dir, tmp_path):
    # Edge case: empty/whitespace-only transcript should not crash prepare -- it
    # produces zero segments -- and analyzing zero claims against it should pass
    # cleanly (nothing to validate, not an error).
    blank_transcript = tmp_path / "blank.txt"
    blank_transcript.write_text("   \n\n\t\n   ", encoding="utf-8")

    rc = main(["prepare", "--ticker", "ACME", "--event-id", "2026-empty", "--transcript", str(blank_transcript)])
    assert rc == 0

    run_dir = isolated_runs_dir / "ACME" / "2026-empty"
    segment_lines = (RunPaths.at(run_dir).transcript).read_text().splitlines()
    assert segment_lines == []

    # Web search is disabled by this fixture -- queries must be an empty list, not
    # crash on an undefined variable (it's only assigned inside the enabled branch).
    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    assert manifest["queries"] == []

    (RunPaths.at(run_dir).claims).write_text("[]")
    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-empty"])
    assert rc == 0

    validation = json.loads((RunPaths.at(run_dir).validation).read_text())
    assert validation["ok"] is True
    assert validation["checked_claims"] == 0
    assert validation["validated_at"]  # real-clock stamp, not agent-authored
    assert validation["tool_decisions"] == {
        "price_lookup": {
            "decision": "not_used",
            "reason": "Fixture does not require market-price evidence",
        }
    }


@pytest.mark.parametrize(
    ("decision", "records", "expected_issue"),
    [
        ("not_used", [], False),
        ("used", [{"ticker": "ACME", "status": "ok"}], False),
        ("attempted_failed", [{"ticker": "ACME", "status": "error"}], False),
        ("not_used", [{"ticker": "ACME", "status": "ok"}], True),
        ("used", [], True),
        ("attempted_failed", [{"ticker": "ACME", "status": "ok"}], True),
    ],
)
def test_price_decision_matches_run_local_receipts(tmp_path, decision, records, expected_issue):
    for record in records:
        with (tmp_path / config.PRICE_LOOKUP_LOG_FILENAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    issues = _price_decision_issues(
        tmp_path,
        "ACME",
        PriceLookupDecision(decision=decision, reason="Test decision"),
    )

    assert bool(issues) is expected_issue


def test_analyze_requires_explicit_price_decision():
    with pytest.raises(SystemExit) as exc_info:
        _cli_main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"])

    assert exc_info.value.code == 2


def test_late_price_lookup_invalidates_not_used_decision(isolated_runs_dir, tmp_path):
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("Operator: Welcome to the call.", encoding="utf-8")
    assert main(
        ["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", str(transcript)]
    ) == 0

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    (RunPaths.at(run_dir).claims).write_text("[]", encoding="utf-8")
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    price_record = {"ticker": "ACME", "status": "ok"}
    (RunPaths.at(run_dir).price_lookup_log).write_text(
        json.dumps(price_record) + "\n", encoding="utf-8"
    )
    (RunPaths.at(run_dir).outlook_brief).write_text("No material outlook.", encoding="utf-8")

    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1


def test_prepare_archives_segmentation_omission_receipt(isolated_runs_dir):
    transcript = str(FIXTURES / "lloyds_pdf_transition.txt")
    assert main(["prepare", "--ticker", "LLOY", "--event-id", "2026-h1", "--transcript", transcript]) == 0

    run_dir = isolated_runs_dir / "LLOY" / "2026-h1"
    report = json.loads((RunPaths.at(run_dir).segmentation_report).read_text())
    assert report["created_at"]
    assert len(report["sanitized_input_sha256"]) == 64
    assert report["segment_count"] > 0
    assert report["omission_count"] == 1
    assert report["omissions"] == [
        {"text": "QUESTION AND ANSWER SESSION", "reason": "qa_heading"}
    ]

    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    assert any(config.SEGMENTATION_REPORT_FILENAME in note for note in manifest["notes"])


def test_prepare_records_event_date_cutoff_in_manifest(isolated_runs_dir):
    """The manifest must persist the --event-date every temporal_status was judged
    against; without it an auditor has to infer the run's own cutoff from the evidence."""
    transcript = str(FIXTURES / "normal_transcript.txt")
    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2",
                 "--transcript", transcript, "--event-date", "2026-07-14"]) == 0
    manifest = json.loads(
        (isolated_runs_dir / "ACME" / "2026-q2" / config.MANIFEST_FILENAME).read_text()
    )
    assert manifest["event_date"] == "2026-07-14"

    # No cutoff supplied is a real state, not an error: it is why statuses read "unchecked".
    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q3",
                 "--transcript", transcript]) == 0
    no_date = json.loads(
        (isolated_runs_dir / "ACME" / "2026-q3" / config.MANIFEST_FILENAME).read_text()
    )
    assert no_date["event_date"] is None


def test_analyze_preserves_each_failed_and_passing_claims_attempt(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript]) == 0
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"

    malformed_claims = b'[{"id": "claim-broken"'
    (RunPaths.at(run_dir).claims).write_bytes(malformed_claims)
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1

    (RunPaths.at(run_dir).claims).write_text("[]", encoding="utf-8")
    (RunPaths.at(run_dir).metrics).write_text("[]", encoding="utf-8")
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    attempts = _validation_attempt_dirs(run_dir)
    assert len(attempts) == 2
    assert attempts[0].name.startswith("attempt-0001_")
    assert attempts[1].name.startswith("attempt-0002_")

    assert (attempts[0] / config.CLAIMS_FILENAME).read_bytes() == malformed_claims
    failed_validation = json.loads((attempts[0] / config.VALIDATION_FILENAME).read_text())
    failed_receipt = json.loads((attempts[0] / config.VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text())
    assert failed_validation["ok"] is False
    assert failed_receipt["outcome"] == "failed"
    assert failed_receipt["exit_code"] == 1
    assert failed_receipt["issue_counts"] == {"schema": 1}
    assert config.MANIFEST_FILENAME in failed_receipt["input_hashes"]
    assert config.TRANSCRIPT_FILENAME in failed_receipt["input_hashes"]
    assert not (attempts[0] / config.MANIFEST_FILENAME).exists()

    assert (attempts[1] / config.CLAIMS_FILENAME).read_text() == "[]"
    assert (attempts[1] / config.METRICS_FILENAME).read_text() == "[]"
    passed_receipt = json.loads((attempts[1] / config.VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text())
    assert passed_receipt["attempt"] == 2
    assert passed_receipt["outcome"] == "passed"
    assert passed_receipt["exit_code"] == 0
    assert passed_receipt["issue_counts"] == {}


def test_analyze_records_blocked_attempt_when_claims_are_missing(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript]) == 0
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"

    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2

    attempts = _validation_attempt_dirs(run_dir)
    assert len(attempts) == 1
    receipt = json.loads((attempts[0] / config.VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text())
    assert receipt["outcome"] == "blocked"
    assert receipt["exit_code"] == 2
    assert not (attempts[0] / config.CLAIMS_FILENAME).exists()
    assert not (attempts[0] / config.VALIDATION_FILENAME).exists()


def test_prepare_appends_to_cross_run_processing_log(isolated_runs_dir, tmp_path):
    transcript = str(FIXTURES / "normal_transcript.txt")
    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q1", "--transcript", transcript]) == 0
    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript]) == 0

    log_path = tmp_path / "logs" / config.PROCESSING_LOG_FILENAME
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2  # one prepare -> one line; a rerun for the same event_id also appends, never overwrites

    first, second = (json.loads(line) for line in lines)
    assert first["event_id"] == "2026-q1"
    assert second["event_id"] == "2026-q2"
    for entry in (first, second):
        assert entry["ticker"] == "ACME"
        assert entry["source"] == transcript
        assert entry["source_type"] == "file"
        assert len(entry["sha256"]) == 64
        assert entry["timestamp"]


def test_prepare_then_analyze_valid_claims_produces_signal_card(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    rc = main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])
    assert rc == 0

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    assert (RunPaths.at(run_dir).manifest).exists()
    assert (RunPaths.at(run_dir).transcript).exists()

    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    assert manifest["ticker"] == "ACME"
    assert len(manifest["sources"]) == 1
    assert len(manifest["sources"][0]["sha256"]) == 64

    segment_lines = (RunPaths.at(run_dir).transcript).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue was $110 million, up 10% YoY.",
            "quote": "Revenue for the quarter was $110 million, up from $100 million a year ago.",
            "segment_id": revenue_segment["id"],
            "speaker": revenue_segment["speaker"],
            "status": "reported",
            "values": {
                "calculation": {
                    "name": "yoy_growth",
                    "inputs": {"current": 110, "prior": 100},
                    "result": 0.10,
                }
            },
            "confidence": 0.9,
        }
    ]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims, indent=2))

    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert rc == 0

    validation = json.loads((RunPaths.at(run_dir).validation).read_text())
    assert validation["ok"] is True

    card = (RunPaths.at(run_dir).signal_card).read_text()
    assert "ACME" in card
    assert "110 million" in card
    assert "_Generated:" in card
    # classification must render alongside status -- otherwise an analytical_inference
    # claim is indistinguishable from a direct quote/reported_fact in the card (found
    # live: a reviewer flagged an inference rendering as if it were the speaker's words).
    assert "[reported_fact]" in card


def test_analyze_blocks_signal_card_when_claim_has_paraphrased_quote(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (RunPaths.at(run_dir).transcript).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue rose sharply.",
            "quote": "Revenue climbed to $110 million this quarter.",  # paraphrased, not verbatim
            "segment_id": revenue_segment["id"],
            "status": "reported",
            "confidence": 0.7,
        }
    ]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims, indent=2))

    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert rc == 1  # non-zero exit blocks the pipeline

    validation = json.loads((RunPaths.at(run_dir).validation).read_text())
    assert validation["ok"] is False
    assert not (RunPaths.at(run_dir).signal_card).exists()


def test_analyze_handles_malformed_claims_json_without_traceback(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    (RunPaths.at(run_dir).claims).write_text("{not valid json")

    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert rc == 1

    validation = json.loads((RunPaths.at(run_dir).validation).read_text())
    assert validation["ok"] is False
    assert validation["issues"][0]["check"] == "schema"


def test_analyze_handles_malformed_metrics_json_without_traceback(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (RunPaths.at(run_dir).transcript).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue was $110 million.",
            "quote": "Revenue for the quarter was $110 million, up from $100 million a year ago.",
            "segment_id": revenue_segment["id"],
            "status": "reported",
            "values": {"revenue_millions": 110},
            "confidence": 0.9,
        }
    ]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    (RunPaths.at(run_dir).metrics).write_text("{not valid json")

    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert rc == 1

    validation = json.loads((RunPaths.at(run_dir).validation).read_text())
    assert validation["ok"] is False
    assert validation["issues"][0]["check"] == "schema"


def test_analyze_removes_stale_signal_card_after_later_failing_run(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (RunPaths.at(run_dir).transcript).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    passing_claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue was $110 million.",
            "quote": "Revenue for the quarter was $110 million, up from $100 million a year ago.",
            "segment_id": revenue_segment["id"],
            "status": "reported",
            "values": {"revenue_millions": 110},
            "confidence": 0.9,
        }
    ]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(passing_claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    assert (RunPaths.at(run_dir).signal_card).exists()

    # Edit claims to something that now fails validation -- the stale card from the
    # prior passing run must not survive being mistaken for the current result.
    failing_claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue was $999 million.",
            "quote": "Revenue for the quarter was $110 million, up from $100 million a year ago.",
            "segment_id": revenue_segment["id"],
            "status": "reported",
            "values": {"revenue_millions": 999},
            "confidence": 0.9,
        }
    ]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(failing_claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1
    assert not (RunPaths.at(run_dir).signal_card).exists()


@pytest.mark.parametrize("provider", ["exa", "tavily"])
def test_prepare_calls_web_search_by_default_and_archives_hits(isolated_runs_dir, monkeypatch, provider):
    """Web search (Exa or Tavily, config.toml [research] provider) is on by default
    -- `prepare` must call it itself and archive every hit into the manifest, just
    like the transcript and SEC evidence. cli.py dispatches through the
    provider-agnostic sources.web_search/web_extract, so this test doesn't care
    which provider is active -- it monkeypatches those, not the provider internals.
    """
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_PROVIDER", provider)
    calls = []
    extract_calls = []

    def fake_web_search(query, provider, max_results, end_date=None):
        calls.append(query)
        assert end_date == "2026-07-15"  # server-side causality guard: passed through from --event-date
        return [{"url": f"https://example.com/{len(calls)}", "title": None, "score": 1.0 / len(calls), "published_date": None}]

    def fake_web_extract(url, provider):
        extract_calls.append(url)
        return f"# Full extracted content for {url}\n\nBody text."

    monkeypatch.setattr(sources, "web_search", fake_web_search)
    monkeypatch.setattr(sources, "web_extract", fake_web_extract)

    transcript = str(FIXTURES / "normal_transcript.txt")
    rc = main(
        [
            "prepare",
            "--ticker",
            "ACME",
            "--event-id",
            "2026-q2",
            "--transcript",
            transcript,
            "--company-name",
            "Acme Corp",
            "--event-date",
            "2026-07-15",
        ]
    )
    assert rc == 0
    assert len(calls) == 5  # one per config [research] consensus_queries template (no --peers)
    assert all("Acme Corp" in q and "ACME" in q for q in calls)
    assert any("2026-q2" in q for q in calls)  # event_id fills the period placeholder

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    archived = sorted((RunPaths.at(run_dir).raw / "web").glob("*.json"))
    assert len(archived) == 5  # one hit archived per query, per the fake
    # Fetch time embedded in the file itself, not just cross-referenced via manifest.
    assert all(json.loads(f.read_text())["_retrieved_at"] for f in archived)
    # Which provider produced this hit -- the archive directory is always literally
    # named "web" regardless of provider, so this was previously unrecorded per-hit.
    assert all(json.loads(f.read_text())["_provider"] == provider for f in archived)
    # Each hit also records the query CLASS it came from -- all "consensus" here (no --peers).
    assert all(json.loads(f.read_text())["_class"] == "consensus" for f in archived)
    # The exact query string that produced each hit is also embedded in the file.
    archived_queries = [json.loads(f.read_text())["_query"] for f in archived]
    assert all("Acme Corp" in q and "ACME" in q for q in archived_queries)

    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    assert any(f"Web search evidence ({provider}): ok" in note for note in manifest["notes"])
    assert any("Web evidence (extracted, citable): 5 source(s)" in note for note in manifest["notes"])
    # The full query set is also recorded once at the manifest level, in order --
    # "query-NN" in a hit's filename indexes into this list.
    assert manifest["queries"] == calls

    # 5 search hits (one per query, distinct URLs) all get extracted -- capped by
    # max_extracted_sources (15, default), so all 5 are selected here.
    assert len(extract_calls) == 5

    extracted_files = sorted((RunPaths.at(run_dir).web_evidence_dir).glob("*.md"))
    assert len(extracted_files) == 5
    assert "Full extracted content" in extracted_files[0].read_text()

    web_evidence_lines = (RunPaths.at(run_dir).web_evidence).read_text().strip().splitlines()
    assert len(web_evidence_lines) == 5

    # transcript source + 5 search-hit sources + 5 extracted web-evidence sources
    assert len(manifest["sources"]) == 11
    assert all(len(s["sha256"]) == 64 for s in manifest["sources"])


@pytest.mark.parametrize("provider", ["exa", "tavily"])
def test_prepare_peer_queries_run_and_are_class_tagged(isolated_runs_dir, monkeypatch, provider):
    """--peers turns each peer into peer-group web queries (one per config [research]
    peer_queries template), tagged _class="peer" in the raw archive, alongside the
    consensus queries. Peers are supplied per run (agent-discovered from the transcript),
    never hardcoded -- keeping the code industry-agnostic.
    """
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_PROVIDER", provider)
    calls = []

    def fake_web_search(query, provider, max_results, end_date=None):
        calls.append(query)
        return [{"url": f"https://example.com/{len(calls)}", "title": None, "score": None, "published_date": None}]

    monkeypatch.setattr(sources, "web_search", fake_web_search)
    monkeypatch.setattr(sources, "web_extract", lambda url, provider: f"# Content for {url}")

    transcript = str(FIXTURES / "normal_transcript.txt")
    rc = main(
        [
            "prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript,
            "--company-name", "Acme Corp", "--peers", "Amazon", "Google",
        ]
    )
    assert rc == 0
    # 5 consensus + (2 peers x 5 peer_queries templates) = 15 queries
    assert len(calls) == 15
    assert any("Amazon" in q for q in calls) and any("Google" in q for q in calls)

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    archived = [json.loads(f.read_text()) for f in sorted((RunPaths.at(run_dir).raw / "web").glob("*.json"))]
    classes = [a["_class"] for a in archived]
    assert classes.count("consensus") == 5
    assert classes.count("peer") == 10
    # every peer query names a peer -- provenance traceable per hit
    peer_queries = [a["_query"] for a in archived if a["_class"] == "peer"]
    assert all(("Amazon" in q or "Google" in q) for q in peer_queries)


def test_prepare_flags_prompt_injection_in_manifest_and_scan_file(isolated_runs_dir, monkeypatch):
    """The injection fixture embeds "IGNORE PREVIOUS INSTRUCTIONS ... developer mode".
    prepare flags it (advisory, non-blocking): a manifest note plus injection-scan.json.
    The run still completes normally -- the suspicious text is data, never a gate.
    """
    monkeypatch.setattr(config, "SANITISATION_INJECTION_SCAN_ENABLED", True)
    transcript = str(FIXTURES / "injection_transcript.txt")
    rc = main(["prepare", "--ticker", "WIDG", "--event-id", "2026-q1", "--transcript", transcript])
    assert rc == 0  # never blocks

    run_dir = isolated_runs_dir / "WIDG" / "2026-q1"
    scan = json.loads((RunPaths.at(run_dir).injection_scan).read_text())
    assert scan["finding_count"] >= 1
    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    assert any("Prompt-injection scan" in n and "flagged" in n for n in manifest["notes"])


def test_prepare_injection_scan_can_be_disabled(isolated_runs_dir, monkeypatch):
    """The scan is a config toggle -- off means no scan file and a 'disabled' note."""
    monkeypatch.setattr(config, "SANITISATION_INJECTION_SCAN_ENABLED", False)
    transcript = str(FIXTURES / "injection_transcript.txt")
    rc = main(["prepare", "--ticker", "WIDG", "--event-id", "2026-q1", "--transcript", transcript])
    assert rc == 0
    run_dir = isolated_runs_dir / "WIDG" / "2026-q1"
    assert not (RunPaths.at(run_dir).injection_scan).exists()
    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    assert any("Prompt-injection scan: disabled" in n for n in manifest["notes"])


def test_prepare_extraction_round_robins_so_consensus_never_starves_peers(isolated_runs_dir, monkeypatch):
    """The live bug: consensus queries (run first, more hits, higher scores) filled all
    10 extraction slots, so 0 peer results ever became citable. Extraction now interleaves
    by _class, so peer hits get extracted even when every consensus hit outscores them.
    """
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_PROVIDER", "exa")
    monkeypatch.setattr(config, "EXA_MAX_EXTRACTED_SOURCES", 10)

    seq = {"n": 0}

    def fake_web_search(query, provider, max_results, end_date=None):
        # Consensus queries name the company; peer queries name a peer. Give consensus
        # MANY high-score hits and peers FEW low-score ones -- under the old score-only
        # sort the peers would never be reached.
        is_peer = "Amazon" in query or "Google" in query
        count, score = (1, 0.1) if is_peer else (6, 0.9)
        hits = []
        for _ in range(count):
            seq["n"] += 1
            hits.append({"url": f"https://ex.com/{seq['n']}", "title": None, "score": score, "published_date": None})
        return hits

    monkeypatch.setattr(sources, "web_search", fake_web_search)
    extracted = []
    monkeypatch.setattr(sources, "web_extract", lambda url, provider: extracted.append(url) or f"# {url}")

    transcript = str(FIXTURES / "normal_transcript.txt")
    rc = main(
        [
            "prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript,
            "--company-name", "Acme Corp", "--peers", "Amazon", "Google",
        ]
    )
    assert rc == 0
    # 5 consensus x6 = 30 consensus hits; 10 peer queries x1 = 10 peer hits (5 Amazon,
    # 5 Google). Round-robin into the monkeypatched 10 slots -> both classes
    # represented (old code: 10 consensus, 0 peer) AND both peers represented (the
    # sub-class-by-peer fix): 3 buckets drawn in turn until the cap is hit mid-round.
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    archived = {a["url"]: a for f in (RunPaths.at(run_dir).raw / "web").glob("*.json")
                for a in [json.loads(f.read_text())]}
    extracted_classes = [archived[url]["_class"] for url in extracted]
    extracted_keys = [archived[url]["_select_key"] for url in extracted]
    assert len(extracted) == 10
    assert extracted_classes.count("peer") == 6  # both peers survive well past the old 2-hit exhaustion point
    assert extracted_classes.count("consensus") == 4
    # neither peer starved: each of the two peers contributes to citable evidence
    assert extracted_keys.count("peer:Amazon") == 3
    assert extracted_keys.count("peer:Google") == 3


@pytest.mark.parametrize("provider", ["exa", "tavily"])
def test_discover_peers_searches_and_archives_candidates(isolated_runs_dir, monkeypatch, provider):
    """`discover-peers` runs the peer-group queries, archives each hit (class-tagged
    peer_group, hashed) and extracts candidate pages to runs/<TICKER>/peer-discovery/
    for the agent to read and pick ~4 peers -- the SEARCH is deterministic/auditable,
    the SELECTION is the agent's, made afterward.
    """
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_PROVIDER", provider)
    calls = []

    def fake_web_search(query, provider, max_results, end_date=None):
        calls.append(query)
        assert end_date is None  # peer group is not event-relative -- no causality cutoff
        return [{"url": f"https://example.com/{len(calls)}", "title": "Peers", "score": None, "published_date": None}]

    monkeypatch.setattr(sources, "web_search", fake_web_search)
    monkeypatch.setattr(sources, "web_extract", lambda url, provider: f"# Comparable companies\n\nPeers listed for {url}.")

    rc = main(["discover-peers", "--ticker", "MSFT", "--company-name", "Microsoft"])
    assert rc == 0
    assert len(calls) == 3  # one per config [research] peer_group_queries template
    assert all("Microsoft" in q and "MSFT" in q for q in calls)

    disc_dir = isolated_runs_dir / "MSFT" / "peer-discovery"
    archived = [json.loads(f.read_text()) for f in sorted((disc_dir / "raw").glob("*.json"))]
    assert archived and all(a["_class"] == "peer_group" for a in archived)
    candidates = sorted(disc_dir.glob("candidate-*.md"))
    assert candidates and "Comparable companies" in candidates[0].read_text()

    manifest = json.loads((disc_dir / config.MANIFEST_FILENAME).read_text())
    assert manifest["event_id"] == "peer-discovery"
    assert all(len(s["sha256"]) == 64 for s in manifest["sources"])


def test_discover_peers_applies_optional_event_date_cutoff(isolated_runs_dir, monkeypatch):
    """--event-date on discover-peers is an optional safety net: a dated hit published
    after it is dropped from extraction (undated ones still pass through), same guard as
    prepare. Without --event-date, no cutoff applies (covered by the test above).
    """
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_PROVIDER", "exa")
    end_dates = []

    def fake_web_search(query, provider, max_results, end_date=None):
        end_dates.append(end_date)
        return [
            {"url": "https://ex.com/before", "title": None, "score": 0.9, "published_date": "2026-07-10"},
            {"url": "https://ex.com/after", "title": None, "score": 0.8, "published_date": "2026-08-20"},
            {"url": "https://ex.com/undated", "title": None, "score": 0.7, "published_date": None},
        ]

    extracted = []
    monkeypatch.setattr(sources, "web_search", fake_web_search)
    monkeypatch.setattr(sources, "web_extract", lambda url, provider: extracted.append(url) or f"# {url}")

    rc = main(["discover-peers", "--ticker", "MSFT", "--company-name", "Microsoft", "--event-date", "2026-07-30"])
    assert rc == 0
    assert all(d == "2026-07-30" for d in end_dates)  # cutoff forwarded to provider too
    # "after" (2026-08-20) dropped; "before" and undated kept.
    assert "https://ex.com/after" not in extracted
    assert "https://ex.com/before" in extracted and "https://ex.com/undated" in extracted

    disc_dir = isolated_runs_dir / "MSFT" / "peer-discovery"
    manifest = json.loads((disc_dir / config.MANIFEST_FILENAME).read_text())
    assert any("causality guard" in note for note in manifest["notes"])
    raw_hits = [json.loads(path.read_text()) for path in (disc_dir / "raw").glob("*.json")]
    statuses_by_url = {hit["url"]: hit["_temporal_status"] for hit in raw_hits}
    assert statuses_by_url == {
        "https://ex.com/before": "pre_event",
        "https://ex.com/after": "post_event",
        "https://ex.com/undated": "undated",
    }


@pytest.mark.parametrize("provider", ["exa", "tavily"])
def test_prepare_excludes_web_evidence_published_after_event_date(isolated_runs_dir, monkeypatch, provider):
    """Causality guard: a hit published after the earnings event date must not
    become citable WebEvidence, regardless of provider. Still archived under
    raw/web/ (audit trail), just excluded from extraction.
    """
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_PROVIDER", provider)
    extract_calls = []

    def fake_web_search(query, provider, max_results, end_date=None):
        # Fake deliberately still returns the "after" hit despite end_date, to prove
        # the client-side post-filter (the real guard, per this session's live
        # testing) catches it regardless of the server-side end_date param.
        return [
            {"url": "https://example.com/before", "title": None, "score": 0.9, "published_date": "2026-07-10"},
            {"url": "https://example.com/after", "title": None, "score": 0.8, "published_date": "2026-07-20"},
        ]

    def fake_web_extract(url, provider):
        extract_calls.append(url)
        return f"# Content for {url}"

    monkeypatch.setattr(sources, "web_search", fake_web_search)
    monkeypatch.setattr(sources, "web_extract", fake_web_extract)

    transcript = str(FIXTURES / "normal_transcript.txt")
    rc = main(
        [
            "prepare",
            "--ticker",
            "ACME",
            "--event-id",
            "2026-q2",
            "--transcript",
            transcript,
            "--event-date",
            "2026-07-15",  # cutoff: "after" hit (2026-07-20) is post-event
        ]
    )
    assert rc == 0
    assert extract_calls == ["https://example.com/before"]

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    assert any("causality guard" in note for note in manifest["notes"])

    web_evidence_lines = (RunPaths.at(run_dir).web_evidence).read_text().strip().splitlines()
    assert len(web_evidence_lines) == 1
    web_evidence = json.loads(web_evidence_lines[0])
    assert "before" in web_evidence["url"]
    assert web_evidence["temporal_status"] == "pre_event"

    # still archived under raw/web/ for audit (both hits, all 5 consensus queries -> 10
    # files), just never extracted as citable evidence.
    assert len(list((RunPaths.at(run_dir).raw / "web").glob("*.json"))) == 10


def test_prepare_extraction_selection_preserves_order_when_score_is_none(isolated_runs_dir, monkeypatch):
    # Regression: when score is None for every hit (e.g. Exa "auto" mode, which never
    # returns one), extraction selection must not crash on the None/float comparison,
    # and must preserve the provider's own result order rather than picking arbitrarily.
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_PROVIDER", "exa")

    def fake_web_search(query, provider, max_results, end_date=None):
        # Every query returns the same 2 hits, in this fixed order, all score=None.
        return [
            {"url": "https://example.com/first", "title": None, "score": None, "published_date": None},
            {"url": "https://example.com/second", "title": None, "score": None, "published_date": None},
        ]

    def fake_web_extract(url, provider):
        return f"# Content for {url}"

    monkeypatch.setattr(sources, "web_search", fake_web_search)
    monkeypatch.setattr(sources, "web_extract", fake_web_extract)

    transcript = str(FIXTURES / "normal_transcript.txt")
    rc = main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])
    assert rc == 0

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    web_evidence_lines = (RunPaths.at(run_dir).web_evidence).read_text().strip().splitlines()
    first_two_evidence = [json.loads(line) for line in web_evidence_lines[:2]]
    first_two = [evidence["url"] for evidence in first_two_evidence]
    assert first_two == ["https://example.com/first", "https://example.com/second"]
    assert all(evidence["temporal_status"] == "unchecked" for evidence in first_two_evidence)


def test_normalize_hits_maps_both_provider_shapes_to_one_canonical_shape():
    tavily_hit = {"url": "https://x.com", "title": "T", "score": 0.5, "published_date": "2026-07-10"}
    exa_hit = {"url": "https://y.com", "title": "Y", "score": 0.7, "publishedDate": "2026-07-11"}
    assert sources._normalize_hits([tavily_hit], "tavily") == [
        {"url": "https://x.com", "title": "T", "score": 0.5, "published_date": "2026-07-10"}
    ]
    assert sources._normalize_hits([exa_hit], "exa") == [
        {"url": "https://y.com", "title": "Y", "score": 0.7, "published_date": "2026-07-11"}
    ]


def test_normalize_hits_score_is_none_not_a_fake_zero_when_absent():
    # Regression: Exa's "auto" type (config.toml [exa] type default) never returns a
    # "score" field at all -- live-confirmed 2026-08-26. A silent 0 default made every
    # such hit tie, turning cmd_prepare's "extract the best-scoring hits" selection
    # into a no-op. score must be None (distinguishable from a real score of 0.0), not 0.
    scoreless_hit = {"url": "https://y.com", "title": "Y", "publishedDate": "2026-07-11"}
    assert sources._normalize_hits([scoreless_hit], "exa")[0]["score"] is None


def test_prepare_archives_prior_run_instead_of_overwriting(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"

    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript]) == 0
    first_manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())

    # Rerun for the same ticker/event -- must not silently clobber the first run.
    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript]) == 0
    second_manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())

    archive_dir = RunPaths.at(run_dir).archive
    assert archive_dir.is_dir()
    archived_runs = list(archive_dir.iterdir())
    assert len(archived_runs) == 1
    archived_manifest = json.loads((archived_runs[0] / config.MANIFEST_FILENAME).read_text())
    assert archived_manifest == first_manifest
    assert second_manifest["created_at"] >= first_manifest["created_at"]


def test_validate_outlook_fails_on_unknown_claim_id(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (RunPaths.at(run_dir).transcript).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue was $110 million.",
            "quote": "Revenue for the quarter was $110 million, up from $100 million a year ago.",
            "segment_id": revenue_segment["id"],
            "status": "reported",
            "values": {"revenue_millions": 110},
            "confidence": 0.9,
        }
    ]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\nRevenue growth looks strong [claim-999].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1

    outlook_validation = json.loads((RunPaths.at(run_dir).outlook_validation).read_text())
    assert outlook_validation["ok"] is False
    assert outlook_validation["validated_at"]
    assert outlook_validation["errors"]


def test_validate_outlook_passes_with_real_citation(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (RunPaths.at(run_dir).transcript).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue was $110 million.",
            "quote": "Revenue for the quarter was $110 million, up from $100 million a year ago.",
            "segment_id": revenue_segment["id"],
            "status": "reported",
            "values": {"revenue_millions": 110},
            "confidence": 0.9,
        }
    ]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\nRevenue growth looks strong [claim-001].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    outlook_validation = json.loads((RunPaths.at(run_dir).outlook_validation).read_text())
    assert outlook_validation["ok"] is True
    assert outlook_validation["validated_at"]
    assert outlook_validation["errors"] == []


def test_validate_outlook_history_records_failed_then_passed_attempts(isolated_runs_dir):
    """Preserve each submitted brief and its own result when the top-level result changes."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    claims_bytes = (RunPaths.at(run_dir).claims).read_bytes()

    bad_brief = b"# Outlook\n\nUnsupported [claim-999].\n"
    (RunPaths.at(run_dir).outlook_brief).write_bytes(bad_brief)
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1

    good_brief = b"# Outlook\n\nSupported [claim-001].\n"
    (RunPaths.at(run_dir).outlook_brief).write_bytes(good_brief)
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    attempts = _outlook_validation_attempt_dirs(run_dir)
    assert len(attempts) == 2
    for number, attempt_dir in enumerate(attempts, start=1):
        assert attempt_dir.name.startswith(f"attempt-{number:04d}_")
        assert (attempt_dir / config.CLAIMS_FILENAME).read_bytes() == claims_bytes

    first_result = json.loads((attempts[0] / config.OUTLOOK_VALIDATION_FILENAME).read_text())
    second_result = json.loads((attempts[1] / config.OUTLOOK_VALIDATION_FILENAME).read_text())
    first_receipt = json.loads(
        (attempts[0] / config.OUTLOOK_VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text()
    )
    second_receipt = json.loads(
        (attempts[1] / config.OUTLOOK_VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text()
    )

    assert (attempts[0] / config.OUTLOOK_BRIEF_FILENAME).read_bytes() == bad_brief
    assert (attempts[1] / config.OUTLOOK_BRIEF_FILENAME).read_bytes() == good_brief
    assert first_result["ok"] is False
    assert second_result["ok"] is True
    assert first_receipt["outcome"] == "failed"
    assert first_receipt["exit_code"] == 1
    assert first_receipt["error_count"] > 0
    assert second_receipt["outcome"] == "passed"
    assert second_receipt["exit_code"] == 0
    assert second_receipt["error_count"] == 0
    for receipt in (first_receipt, second_receipt):
        assert receipt["started_at"]
        assert receipt["finished_at"]
    assert first_receipt["claims_sha256"] == sha256_hex(claims_bytes)
    assert first_receipt["outlook_brief_sha256"] == sha256_hex(bad_brief)
    assert second_receipt["outlook_brief_sha256"] == sha256_hex(good_brief)
    assert json.loads((RunPaths.at(run_dir).outlook_validation).read_text()) == second_result


def test_validate_outlook_history_records_blocked_attempt(isolated_runs_dir):
    """Record an invocation even when the brief is absent and validation cannot run."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2

    attempts = _outlook_validation_attempt_dirs(run_dir)
    assert len(attempts) == 1
    attempt_dir = attempts[0]
    receipt = json.loads(
        (attempt_dir / config.OUTLOOK_VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text()
    )
    assert receipt["outcome"] == "blocked"
    assert receipt["exit_code"] == 2
    assert receipt["error_count"] == 0
    assert receipt["claims_sha256"] == sha256_hex(
        (attempt_dir / config.CLAIMS_FILENAME).read_bytes()
    )
    assert receipt["outlook_brief_sha256"] is None
    assert not (attempt_dir / config.OUTLOOK_BRIEF_FILENAME).exists()
    assert not (attempt_dir / config.OUTLOOK_VALIDATION_FILENAME).exists()


def test_validate_outlook_fails_on_unescaped_dollar_signs(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (RunPaths.at(run_dir).transcript).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    claims = [
        {
            "id": "claim-001",
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue was $110 million.",
            "quote": "Revenue for the quarter was $110 million, up from $100 million a year ago.",
            "segment_id": revenue_segment["id"],
            "status": "reported",
            "values": {"revenue_millions": 110},
            "confidence": 0.9,
        }
    ]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    # Two unescaped '$' -- exactly the shape that corrupts under KaTeX/MathJax preview
    # rendering -- must fail the gate even though claim-001's citation resolves fine.
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\nRevenue was $110 million, ahead of the prior $100 million [claim-001].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1

    outlook_validation = json.loads((RunPaths.at(run_dir).outlook_validation).read_text())
    assert outlook_validation["ok"] is False
    assert "unescaped" in outlook_validation["errors"][0]


def test_escape_currency_is_idempotent():
    # Regression: a naive .replace("$", "\\$") would turn an already-escaped '\$'
    # (the outlook-brief template now tells agents to write this by hand) into '\\$',
    # which renders as a literal backslash followed by a bare, re-exposed '$'.
    once = _escape_currency("Revenue was $81.3B.")
    twice = _escape_currency(once)
    assert once == twice == "Revenue was \\$81.3B."


# --- P0 correctness: input-hash binding + gate chain (validate-outlook / check-review) ---

def _seed_validated_run(isolated_runs_dir, ticker="ACME", event="2026-q2"):
    """prepare + a single valid claim + passing analyze. Returns the run dir."""
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", ticker, "--event-id", event, "--transcript", transcript])
    run_dir = isolated_runs_dir / ticker / event
    segments = [json.loads(l) for l in (RunPaths.at(run_dir).transcript).read_text().splitlines()]
    rev = next(s for s in segments if "110 million" in s["text"])
    claims = [{
        "id": "claim-001", "category": "reported_financial_performance", "classification": "reported_fact",
        "claim_text": "Revenue was $110 million.",
        "quote": "Revenue for the quarter was $110 million, up from $100 million a year ago.",
        "segment_id": rev["id"], "status": "reported", "values": {"revenue_millions": 110}, "confidence": 0.9,
    }]
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", ticker, "--event-id", event]) == 0
    return run_dir


def test_validation_json_records_input_hashes(isolated_runs_dir):
    """analyze binds validation.json to the exact bytes it validated, so staleness is
    later detectable (claims.json + transcript.jsonl at minimum)."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    v = json.loads((RunPaths.at(run_dir).validation).read_text())
    assert config.CLAIMS_FILENAME in v["input_hashes"]
    assert config.TRANSCRIPT_FILENAME in v["input_hashes"]
    assert all(len(h) == 64 for h in v["input_hashes"].values())


def test_analyze_warns_when_no_coverage_receipt_exists(isolated_runs_dir):
    """Absence is advisory, not fatal: runs predating the receipt must stay analysable."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    v = json.loads(RunPaths.at(run_dir).validation.read_text())
    assert v["ok"] is True
    assert any("completeness is unverifiable" in w for w in v["warnings"])


def test_analyze_checks_a_present_coverage_receipt_without_metrics_json(isolated_runs_dir):
    """A receipt that exists is checked hard -- and metrics.json is optional.

    Regression: claim_ids was computed inside the metrics block, so a run with a
    receipt and no metrics.json crashed with UnboundLocalError instead of validating.
    Every test fixture happened to have no receipt, so nothing caught it; the real JPM
    run did, immediately.
    """
    run_dir = _seed_validated_run(isolated_runs_dir)
    paths = RunPaths.at(run_dir)
    assert not paths.metrics.exists()
    segment_ids = [json.loads(l)["id"] for l in paths.transcript.read_text().splitlines()]
    claim_id = json.loads(paths.claims.read_text())[0]["id"]
    paths.coverage_receipt.write_text(json.dumps({
        "segments": [
            {"segment_id": s, "outcome": "claims_extracted", "claim_ids": [claim_id]} if i == 0
            else {"segment_id": s, "outcome": "deliberately_immaterial", "claim_ids": [], "reason": "operator"}
            for i, s in enumerate(segment_ids)
        ],
        "web_evidence": [],
    }))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2",
                 "--price-decision", "not_used", "--price-reason", "n/a"]) == 0

    # and an incomplete one fails rather than passing quietly
    paths.coverage_receipt.write_text(json.dumps({"segments": [], "web_evidence": []}))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2",
                 "--price-decision", "not_used", "--price-reason", "n/a"]) == 1
    v = json.loads(paths.validation.read_text())
    assert any(i["check"] == "coverage_receipt" for i in v["issues"])


def test_validation_json_pins_manifest_not_every_source(isolated_runs_dir):
    """manifest.json is the provenance index. validation.json pins its hash and stops
    there, rather than restating a hash per archived source -- on a real run that
    restatement was 96% of the file's bytes and was copied into every attempt receipt."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    v = json.loads((RunPaths.at(run_dir).validation).read_text())
    assert config.MANIFEST_FILENAME in v["input_hashes"]
    assert [k for k in v["input_hashes"] if k.startswith("source:")] == []
    receipt_dirs = sorted((RunPaths.at(run_dir).validation_history).glob("attempt-*"))
    receipt = json.loads((receipt_dirs[-1] / config.VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text())
    assert [k for k in receipt["input_hashes"] if k.startswith("source:")] == []


def test_later_gates_still_detect_an_edited_archived_source(isolated_runs_dir, capsys):
    """The teeth removed from validation.json must still bite via the manifest chain.

    Dropping the per-source hashes without relocating this check would leave
    validate-outlook and check-review unable to notice an evidence file edited after
    analyze passed -- silently, with no test failing. This is that regression test.
    """
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    archived = run_dir / manifest["sources"][0]["path"]
    archived.write_bytes(archived.read_bytes() + b"\ntampered after analyze\n")

    capsys.readouterr()
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1
    assert "an analyze input changed" in capsys.readouterr().out
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2
    assert "an analyze input changed" in capsys.readouterr().out


def test_validate_outlook_blocks_when_claims_changed_since_analyze(isolated_runs_dir):
    """If claims.json is edited after analyze, its recorded hash no longer matches, so the
    'ok' is stale -- validate-outlook must refuse rather than validate against unvalidated claims."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    # edit claims.json bytes WITHOUT re-running analyze (claim-001 still present -> not a citation failure)
    claims = json.loads((RunPaths.at(run_dir).claims).read_text())
    claims[0]["confidence"] = 0.8
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1


def test_check_review_requires_passing_outlook_validation(isolated_runs_dir):
    """The review gate must require validate-outlook to have actually passed. Previously it
    only checked outlook-brief.md existed, so the stage could be skipped entirely."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    # deliberately do NOT run validate-outlook -> no outlook-validation.json
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_check_review_blocks_when_outlook_edited_after_validation(isolated_runs_dir):
    """Even after a passing validate-outlook, editing the brief must invalidate the review
    gate -- the reviewed bytes must be the validated bytes."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    # tamper with the brief after it passed
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001]. Edited afterwards.\n")
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


@pytest.mark.parametrize("provider", ["exa", "tavily"])
def test_discover_peers_archives_prior_output_on_rerun(isolated_runs_dir, monkeypatch, provider):
    """A rerun must not leave stale candidate-*.md from a previous discovery on disk (the
    agent globs candidate-*.md). The prior discovery is archived under _archive/ first."""
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "RESEARCH_WEB_SEARCH_PROVIDER", provider)
    calls = {"n": 0}

    def fake_web_search(query, provider, max_results, end_date=None):
        calls["n"] += 1
        return [{"url": f"https://ex.com/{calls['n']}", "title": "Peers", "score": None, "published_date": None}]

    monkeypatch.setattr(sources, "web_search", fake_web_search)
    monkeypatch.setattr(sources, "web_extract", lambda url, provider: f"# Comparable companies for {url}")

    assert main(["discover-peers", "--ticker", "MSFT", "--company-name", "Microsoft"]) == 0
    assert main(["discover-peers", "--ticker", "MSFT", "--company-name", "Microsoft"]) == 0  # rerun

    disc_dir = isolated_runs_dir / "MSFT" / "peer-discovery"
    archive_root = disc_dir / config.ARCHIVE_SUBDIR
    assert archive_root.exists(), "prior peer-discovery should have been archived on rerun"
    archived_manifests = list(archive_root.glob("*/manifest.json"))
    assert archived_manifests, "the archived prior discovery should include its manifest.json"


def test_prepare_pdf_with_unrecognised_layout_fails_loudly(isolated_runs_dir, tmp_path, monkeypatch):
    """A PDF whose extracted text has no recognisable speaker lines at all (no
    'Name — Title:' headers, no FactSet dotted-separator markers) must raise rather
    than silently produce a run with one giant unattributed segment."""
    plain_prose = (
        "This is just plain prose extracted from a PDF with an unknown vendor layout. "
        "There are no speaker headers here at all, just paragraphs of text running on "
        "with no structural markers the segmenter can recognise.\n"
    )
    monkeypatch.setattr(ingest, "_extract_pdf_text", lambda data: plain_prose)

    pdf_path = tmp_path / "unrecognised.pdf"
    pdf_path.write_bytes(b"%PDF-fake-bytes")

    with pytest.raises(ValueError, match="zero recognised speaker turns"):
        main(["prepare", "--ticker", "ACME", "--event-id", "2026-pdf", "--transcript", str(pdf_path)])


# --- Diff-based re-review (round 2+) ---

def _write_review_report(run_dir, report, review_mode="full"):
    """Add the exact artifact receipt required of a semantic reviewer."""
    report["review_mode"] = review_mode
    report["claims_sha256"] = sha256_hex((RunPaths.at(run_dir).claims).read_bytes())
    report["outlook_brief_sha256"] = sha256_hex((RunPaths.at(run_dir).outlook_brief).read_bytes())
    diff_path = RunPaths.at(run_dir).review_diff
    report["review_diff_sha256"] = sha256_hex(diff_path.read_bytes()) if diff_path.exists() else None
    if not report.get("source_checks"):
        report["source_checks"] = [_finding("info", "manifest.json")]
    if not report.get("process_findings"):
        report["process_findings"] = [_finding("info", "validation.json")]
    (RunPaths.at(run_dir).review_report_json).write_text(json.dumps(report))


def _seed_reviewed_run(isolated_runs_dir, ticker="ACME", event="2026-q2", verdict="pass", escalate=False):
    """_seed_validated_run + a passing validate-outlook + a fake round-1
    review-report.json + a successful check-review, so _review_history/round-1/
    exists and diff-review tests have a completed round to diff against."""
    run_dir = _seed_validated_run(isolated_runs_dir, ticker=ticker, event=event)
    # claim-001 is cited only in a non-conclusion section (## 2) so a plain text-only
    # edit to claim-001 does not, by itself, trip the conclusion-section escalation
    # rule -- the conclusion-section test below adds its own citation in ## 5.
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\n## 1. Outlook in brief\n\nStrong quarter.\n\n"
        "## 2. Q&A highlights\n\nRevenue grew steadily [claim-001].\n\n"
        "## 5. Base case\n\nContinued momentum expected.\n"
    )
    assert main(["validate-outlook", "--ticker", ticker, "--event-id", event]) == 0
    review_report = {
        "verdict": verdict,
        "reviewed_at": "2026-08-27T00:00:00Z",
        "model": "opus",
        "source_checks": [],
        "claim_findings": [],
        "outlook_findings": [],
        "process_findings": [],
        "unverified_items": [],
        "summary": "Looks fine.",
        "escalate_full_review": escalate,
    }
    _write_review_report(run_dir, review_report)
    exit_code = main(["check-review", "--ticker", ticker, "--event-id", event])
    assert exit_code == (3 if escalate else 0)
    return run_dir


def test_snapshot_review_round_copies_complete_review_bundle(isolated_runs_dir):
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    round_dir = RunPaths.at(run_dir).review_round(1)
    assert round_dir.exists()
    for filename in (
        config.CLAIMS_FILENAME,
        config.OUTLOOK_BRIEF_FILENAME,
        config.OUTLOOK_VALIDATION_FILENAME,
        config.REVIEW_REPORT_JSON_FILENAME,
    ):
        assert (round_dir / filename).exists()
        # A snapshot holds its files flat inside itself, whatever layout the run uses.
        assert (round_dir / filename).read_bytes() == RunPaths.at(run_dir).resolve(filename).read_bytes()


def test_snapshot_review_round_writes_severity_count_receipt(isolated_runs_dir):
    """receipt.json mirrors _validation_history's per-attempt receipt for Stage 1: a
    human (or the next agent) should be able to see how a round went -- verdict and
    finding counts by severity -- without opening the full review-report.json or
    waiting for audit-record.json, which is only written once the whole run passes."""
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    receipt = json.loads((RunPaths.at(run_dir).review_round(1) / config.REVIEW_ROUND_RECEIPT_FILENAME).read_text())
    assert receipt["round"] == 1
    assert receipt["verdict"] == "pass"
    assert receipt["escalate_full_review"] is False
    # _write_review_report auto-fills one info-severity placeholder each into
    # source_checks/process_findings when the caller leaves them empty (they're
    # required non-empty by validate_review_report), hence info: 2 here.
    assert receipt["finding_counts"] == {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 2}


def test_review_diff_with_zero_completed_rounds_errors(isolated_runs_dir):
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_review_diff_unchanged_claims_produces_empty_diff(isolated_runs_dir):
    _seed_reviewed_run(isolated_runs_dir)
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    diff = json.loads(RunPaths.at(run_dir).review_diff.read_text())
    assert diff["claims_changed"] == []
    assert diff["auto_escalated"] is False
    assert diff["round_number"] == 2
    assert diff["since_round"] == 1


def test_review_diff_writes_readable_sha256_sidecar(isolated_runs_dir):
    # The reviewer subagent has no execution tool (Read/Grep/Glob/Write only), so it
    # cannot hash review-diff.json itself the way it can for claims_sha256/
    # outlook_brief_sha256 (copied from outlook-validation.json) -- this sidecar is
    # the equivalent free ride for review_diff_sha256, required from round 2 on.
    _seed_reviewed_run(isolated_runs_dir)
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    recorded = (RunPaths.at(run_dir).review_diff_sha256).read_text(encoding="utf-8")
    actual = sha256_hex((RunPaths.at(run_dir).review_diff).read_bytes())
    assert recorded == actual


def test_review_diff_text_only_change_under_threshold_not_escalated(isolated_runs_dir):
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    claims = json.loads((RunPaths.at(run_dir).claims).read_text())
    claims[0]["claim_text"] = "Revenue came in at $110 million."
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    diff = json.loads(RunPaths.at(run_dir).review_diff.read_text())
    assert diff["auto_escalated"] is False
    assert len(diff["claims_changed"]) == 1
    assert diff["claims_changed"][0]["claim_id"] == "claim-001"
    assert diff["claims_changed"][0]["change"] == "changed"


def test_review_diff_escalates_when_too_many_claims_changed(isolated_runs_dir, monkeypatch):
    monkeypatch.setattr(config, "REVIEW_DIFF_MAX_CLAIMS_CHANGED", 1)
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    claims = json.loads((RunPaths.at(run_dir).claims).read_text())
    claims[0]["claim_text"] = "Revenue came in at $110 million."
    claims.append(dict(claims[0], id="claim-002", claim_text="Second claim added."))
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 3
    diff = json.loads(RunPaths.at(run_dir).review_diff.read_text())
    assert diff["auto_escalated"] is True


def test_review_diff_escalates_when_period_changes(isolated_runs_dir):
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    claims = json.loads((RunPaths.at(run_dir).claims).read_text())
    claims[0]["period"] = "3 months to 30 Jun 2026"
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 3
    diff = json.loads(RunPaths.at(run_dir).review_diff.read_text())
    assert diff["auto_escalated"] is True


def test_review_diff_escalates_when_conclusion_section_cites_changed_claim(isolated_runs_dir):
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    # Now also cite claim-001 from the ## 5 Base case (conclusion-bearing) section.
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\n## 1. Outlook in brief\n\nStrong quarter.\n\n"
        "## 2. Q&A highlights\n\nRevenue grew steadily [claim-001].\n\n"
        "## 5. Base case\n\nContinued momentum expected [claim-001].\n"
    )
    claims = json.loads((RunPaths.at(run_dir).claims).read_text())
    claims[0]["claim_text"] = "Revenue came in at $110 million, a touch higher."
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 3
    diff = json.loads(RunPaths.at(run_dir).review_diff.read_text())
    assert 5 in diff["affected_brief_sections"]
    assert diff["auto_escalated"] is True


def test_review_diff_blocked_when_round_cap_reached(isolated_runs_dir, monkeypatch):
    monkeypatch.setattr(config, "REVIEW_MAX_ROUNDS", 1)
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    diff_path = RunPaths.at(run_dir).review_diff
    assert not diff_path.exists()
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 4
    assert not diff_path.exists()


def test_check_review_escalate_full_review_returns_3_regardless_of_verdict(isolated_runs_dir):
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    review_report = {
        "verdict": "pass",
        "reviewed_at": "2026-08-27T00:00:00Z",
        "model": "opus",
        "source_checks": [],
        "claim_findings": [],
        "outlook_findings": [],
        "process_findings": [],
        "unverified_items": [],
        "summary": "Diff was ambiguous, escalating.",
        "escalate_full_review": True,
    }
    _write_review_report(run_dir, review_report)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 3
    assert (RunPaths.at(run_dir).review_report_md).exists()


def test_check_review_persists_proposed_lessons_deduplicated(isolated_runs_dir):
    """proposed_lessons on an accepted review-report.json land in the repo-root
    extractor-lessons memory file, appended once and deduplicated across runs."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    review_report = {
        "verdict": "pass",
        "reviewed_at": "2026-08-27T00:00:00Z",
        "model": "opus",
        "source_checks": [],
        "claim_findings": [],
        "outlook_findings": [],
        "process_findings": [],
        "unverified_items": [],
        "summary": "Clean run.",
        "escalate_full_review": False,
        "proposed_lessons": ["Verify quarterly vs YTD periods before creating financial claims."],
    }
    _write_review_report(run_dir, review_report)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    lessons_path = config.EXTRACTOR_LESSONS_PATH
    assert lessons_path.is_file()
    first_contents = lessons_path.read_text(encoding="utf-8")
    assert "Verify quarterly vs YTD periods before creating financial claims." in first_contents

    # A second run proposing the same lesson (plus a new one) must not duplicate the first.
    run_dir_2 = _seed_validated_run(isolated_runs_dir, ticker="MSFT")
    RunPaths.at(run_dir_2).outlook_brief.write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "MSFT", "--event-id", "2026-q2"]) == 0
    review_report_2 = dict(review_report)
    review_report_2["proposed_lessons"] = [
        "Verify quarterly vs YTD periods before creating financial claims.",
        "Do not treat analyst questions as management statements.",
    ]
    _write_review_report(run_dir_2, review_report_2)
    assert main(["check-review", "--ticker", "MSFT", "--event-id", "2026-q2"]) == 0

    final_contents = lessons_path.read_text(encoding="utf-8")
    assert final_contents.count("Verify quarterly vs YTD periods before creating financial claims.") == 1
    assert "Do not treat analyst questions as management statements." in final_contents


def test_analyze_blocked_by_unclosed_review_report(isolated_runs_dir):
    """Reproduces a real sequencing bug found live: correcting claims.json after a
    reviewer dispatch but BEFORE running check-review corrupts the next round's diff
    baseline (the round-N snapshot ends up holding post-correction files against the
    pre-correction verdict). analyze must refuse to run until check-review closes the
    outstanding round."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    review_report = {
        "verdict": "fail", "reviewed_at": "2026-08-27T00:00:00Z", "model": "opus",
        "source_checks": [], "claim_findings": [_finding("high")], "outlook_findings": [], "process_findings": [],
        "unverified_items": [], "summary": "Needs a fix.", "escalate_full_review": False,
    }
    _write_review_report(run_dir, review_report)
    # Dispatch happened, review-report.json exists -- but check-review was never run.
    # Correcting now, before closing the round, must be blocked.
    claims_path = RunPaths.at(run_dir).claims
    original_claims_bytes = claims_path.read_bytes()
    claims = json.loads(original_claims_bytes)
    claims[0]["claim_text"] = "Revenue was $110 million, corrected."
    claims_path.write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2

    # Since claims.json was premized (edited before the round closed), the correction
    # must also be reverted before check-review will close the round: check-review now
    # also gates on claims_sha256 (Fix 1b(a)), so a stale claims.json blocks closing too,
    # not just analyze/validate-outlook. Revert to the bytes validate-outlook actually
    # validated, then close the round.
    claims_path.write_bytes(original_claims_bytes)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2  # fail verdict

    # Now that the round is closed, the correction can be made safely.
    claims_path.write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0


# --- Review-gating fixes: brief-prose diff, hash-gate strictness, round cap, verdict/severity ---

def test_review_diff_escalates_on_brief_prose_change_alone(isolated_runs_dir):
    """A narrative-only correction (same claims, same citations, different conclusion
    drawn) must still auto-escalate -- review-diff previously only diffed claims.json,
    so this produced an empty claims_changed diff and auto_escalated stayed False."""
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    # claims.json is untouched (byte-identical to round 1); only the brief's prose changes.
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\n## 1. Outlook in brief\n\nActually a weak quarter, revise down.\n\n"
        "## 2. Q&A highlights\n\nRevenue grew steadily [claim-001].\n\n"
        "## 5. Base case\n\nContinued momentum expected.\n"
    )
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 3
    diff = json.loads(RunPaths.at(run_dir).review_diff.read_text())
    assert diff["claims_changed"] == []
    assert diff["auto_escalated"] is True


def test_check_review_requires_diff_and_current_bundle_receipt_after_round_one(isolated_runs_dir):
    """A changed brief cannot inherit round 1's verdict by skipping review-diff."""
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\n## 1. Outlook in brief\n\nWeak quarter.\n\n"
        "## 2. Q&A highlights\n\nRevenue grew [claim-001].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    copied_verdict = {
        "verdict": "pass", "reviewed_at": "2026-08-27T00:00:00Z", "model": "opus",
        "source_checks": [], "claim_findings": [], "outlook_findings": [], "process_findings": [],
        "unverified_items": [], "summary": "Copied old verdict.", "escalate_full_review": False,
    }
    _write_review_report(run_dir, copied_verdict, review_mode="full")
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2
    assert not (RunPaths.at(run_dir).review_round(2)).exists()

    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 3
    _write_review_report(run_dir, copied_verdict, review_mode="full")
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    assert (RunPaths.at(run_dir).review_round(2)).exists()


def test_validate_outlook_blocks_when_an_archived_source_changed_after_analyze(isolated_runs_dir):
    run_dir = _seed_validated_run(isolated_runs_dir)
    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    source_path = run_dir / manifest["sources"][0]["path"]
    source_path.write_bytes(source_path.read_bytes() + b"\nchanged after validation")
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1


def test_repeated_check_review_rechecks_sources_before_returning_accepted_verdict(isolated_runs_dir):
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    source_path = run_dir / manifest["sources"][0]["path"]
    source_path.write_bytes(source_path.read_bytes() + b"\nchanged after accepted review")
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_check_review_fails_cleanly_when_hashed_claims_file_is_missing(isolated_runs_dir):
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    (RunPaths.at(run_dir).claims).unlink()
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_check_review_blocks_when_claims_edited_after_validate_outlook(isolated_runs_dir):
    """claims_sha256 is recorded in outlook-validation.json at validate-outlook time but
    was never checked by check-review -- claims.json could be edited afterwards, leaving
    the brief untouched, and this gate previously missed it entirely."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    # Edit claims.json in place (leave outlook-brief.md untouched).
    claims = json.loads((RunPaths.at(run_dir).claims).read_text())
    claims[0]["confidence"] = 0.5
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_validate_outlook_rejects_hand_written_validation_json_without_hashes(isolated_runs_dir):
    """A hand-written validation.json with only {"ok": true} is missing required
    ValidationResult fields (checked_claims), so _load_validated_json's schema
    validation rejects it outright -- it never reaches the hash gate at all.
    Previously json.loads()+.get() let this sail straight through."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    (RunPaths.at(run_dir).validation).write_text(json.dumps({"ok": True}))
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) != 0


def test_validate_outlook_rejects_schema_valid_validation_json_missing_claims_hash(isolated_runs_dir):
    """The actual _hash_gate_ok path (distinct from the schema-rejection test above):
    a SCHEMA-VALID validation.json whose input_hashes simply omits claims.json's entry
    -- e.g. hand-constructed, or from a tool that didn't know to include it. Must be
    rejected: a missing recorded hash fails this gate, it doesn't pass by default."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    validation = json.loads((RunPaths.at(run_dir).validation).read_text())
    assert config.CLAIMS_FILENAME in validation["input_hashes"]  # sanity: it's really there normally
    del validation["input_hashes"][config.CLAIMS_FILENAME]
    (RunPaths.at(run_dir).validation).write_text(json.dumps(validation))
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1


def test_check_review_enforces_round_cap_even_when_review_diff_skipped(isolated_runs_dir, monkeypatch):
    """The round cap was previously enforced only in review-diff. If a round is closed
    via check-review without going through review-diff first, check-review must still
    refuse rather than accept and snapshot an unbounded number of rounds."""
    monkeypatch.setattr(config, "REVIEW_MAX_ROUNDS", 1)
    run_dir = _seed_reviewed_run(isolated_runs_dir)  # round 1 already closed
    review_report = {
        "verdict": "pass",
        "reviewed_at": "2026-08-27T00:00:00Z",
        "model": "opus",
        "source_checks": [],
        "claim_findings": [],
        "outlook_findings": [],
        "process_findings": [],
        "unverified_items": [],
        "summary": "Second round, bypassing review-diff.",
        "escalate_full_review": False,
    }
    _write_review_report(run_dir, review_report)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 4
    assert not (RunPaths.at(run_dir).review_round(2)).exists()


def test_check_review_cap_refusal_does_not_write_report_md_or_deadlock(isolated_runs_dir, monkeypatch):
    """Reproduces a real bug found live (2026-08-29): the cap check used to run AFTER
    rendering/writing review-report.md, so a refused round still overwrote the file
    with a verdict that was never accepted, and because it was never snapshotted, the
    unclosed-review-report gate stayed permanently tripped -- analyze, validate-outlook,
    check-review and review-diff all refused, with no CLI path to recover."""
    monkeypatch.setattr(config, "REVIEW_MAX_ROUNDS", 1)
    run_dir = _seed_reviewed_run(isolated_runs_dir)  # round 1 already closed
    original_md = (RunPaths.at(run_dir).review_report_md).read_text()
    review_report = {
        "verdict": "pass", "reviewed_at": "2026-08-27T00:00:00Z", "model": "opus",
        "source_checks": [], "claim_findings": [], "outlook_findings": [], "process_findings": [],
        "unverified_items": [], "summary": "round 2 attempt", "escalate_full_review": False,
    }
    _write_review_report(run_dir, review_report)

    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 4
    # review-report.md must NOT have been overwritten with the refused round's content.
    assert (RunPaths.at(run_dir).review_report_md).read_text() == original_md
    assert not (RunPaths.at(run_dir).review_round(2)).exists()

    # The cap is a terminal policy state, but it must not lock unrelated commands.
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    # Raising the cap permits a new round, but the normal diff receipt remains
    # mandatory. A cap change must not become a review-diff bypass.
    monkeypatch.setattr(config, "REVIEW_MAX_ROUNDS", 2)
    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    _write_review_report(run_dir, review_report, review_mode="diff")
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) not in (2, 4)
    assert (RunPaths.at(run_dir).review_round(2)).exists()


def test_check_review_rejects_round_two_without_review_diff_when_cap_not_reached(isolated_runs_dir):
    """The round cap and the review-diff requirement are two independent gates. A
    round-2 report submitted without ever running review-diff must be rejected for
    THAT reason (exit 2) even when the cap has plenty of headroom left (default 3) --
    previously only exercised with the cap already at its limit, which meant this
    rejection branch (cli.py's 'run `earnings review-diff` before round N') had no
    dedicated test of its own."""
    run_dir = _seed_reviewed_run(isolated_runs_dir)  # round 1 already closed, cap default 3
    review_report = {
        "verdict": "pass",
        "reviewed_at": "2026-08-27T00:00:00Z",
        "model": "opus",
        "source_checks": [], "claim_findings": [], "outlook_findings": [], "process_findings": [],
        "unverified_items": [], "summary": "Second round, no review-diff run first.",
        "escalate_full_review": False,
    }
    _write_review_report(run_dir, review_report)  # review_diff_sha256 -> None, no review-diff.json exists
    exit_code = main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert exit_code == 2  # NOT 4 -- this is a missing-diff rejection, not a cap rejection
    assert not (RunPaths.at(run_dir).review_round(2)).exists()


def test_check_review_refuses_mutated_bundle_after_cap_exhausted(isolated_runs_dir, monkeypatch):
    """Once the cap is exhausted, `analyze`/`validate-outlook` are allowed to proceed
    on a corrected bundle (see the deadlock-fix test above), but that must never give
    the corrected bundle a route to an accepted verdict -- there is no cap left to
    consume. Mutating claims.json post-cap and resubmitting must still be refused,
    not silently treated as the already-accepted round."""
    monkeypatch.setattr(config, "REVIEW_MAX_ROUNDS", 1)
    run_dir = _seed_reviewed_run(isolated_runs_dir)  # round 1 already closed, cap exhausted

    claims = json.loads((RunPaths.at(run_dir).claims).read_text())
    claims[0]["confidence"] = 0.5
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    review_report = {
        "verdict": "pass",
        "reviewed_at": "2026-08-27T00:00:00Z",
        "model": "opus",
        "source_checks": [], "claim_findings": [], "outlook_findings": [], "process_findings": [],
        "unverified_items": [], "summary": "Mutated bundle, cap already spent.",
        "escalate_full_review": False,
    }
    _write_review_report(run_dir, review_report)
    exit_code = main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert exit_code == 4  # refused -- the mutated bundle is NOT treated as the accepted round-1 repeat
    assert not (RunPaths.at(run_dir).review_round(2)).exists()


def test_analyze_clears_stale_review_report_md_after_cap_exhausted_bundle_edit(isolated_runs_dir, monkeypatch):
    """Once the cap is exhausted, `analyze` is allowed to run on a corrected bundle
    (see the deadlock-fix test above) -- but the top-level review-report.md from the
    now-inapplicable round-1 verdict must not linger looking final next to files it no
    longer describes. The accepted verdict itself stays intact under
    _review_history/round-1/."""
    monkeypatch.setattr(config, "REVIEW_MAX_ROUNDS", 1)
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    assert (RunPaths.at(run_dir).review_report_md).exists()

    claims = json.loads((RunPaths.at(run_dir).claims).read_text())
    claims[0]["confidence"] = 0.5
    (RunPaths.at(run_dir).claims).write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    assert not (RunPaths.at(run_dir).review_report_md).exists()
    assert (RunPaths.at(run_dir).review_round(1) / config.REVIEW_REPORT_JSON_FILENAME).exists()


def test_analyze_clears_stale_audit_record_when_bundle_changes_after_acceptance(isolated_runs_dir):
    """A stale audit-record.json is worse than none: it is the one file a human
    approver reads on its own, and it states a verdict for a bundle that has moved on.

    Confirmed live (JPM/2026-q2, 2026-09-16): accepted at round 1, three claims then
    corrected and re-validated, review-diff escalated to a round 2 that was never
    dispatched -- and audit-record.json still read "accepted" against claims.json it no
    longer matched.
    """
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    paths = RunPaths.at(run_dir)
    assert paths.audit_record.exists()          # written on the round-1 acceptance

    # correct a claim and re-validate, exactly as a correction round does
    claims = json.loads(paths.claims.read_text())
    claims[0]["confidence"] = 0.8
    paths.claims.write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2",
                 "--price-decision", "not_used", "--price-reason", "n/a"]) == 0

    assert not paths.audit_record.exists(), "stale audit record survived a bundle change"
    assert not paths.review_report_md.exists()
    # the accepted verdict itself is preserved in history, not destroyed
    assert (paths.review_round(1) / config.REVIEW_REPORT_JSON_FILENAME).exists()


def test_validate_outlook_clears_stale_review_report_md_after_brief_edit(isolated_runs_dir):
    """Same cleanup, exercised through validate-outlook's call site and a brief edit
    instead of a claims edit, and without the cap being exhausted -- this is also the
    ordinary round-2 workflow, not just the post-cap edge case."""
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    assert (RunPaths.at(run_dir).review_report_md).exists()

    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\n## 1. Outlook in brief\n\nRevised after round 1 findings.\n\n"
        "## 2. Q&A highlights\n\nRevenue grew steadily [claim-001].\n\n"
        "## 5. Base case\n\nContinued momentum expected.\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    assert not (RunPaths.at(run_dir).review_report_md).exists()
    assert (RunPaths.at(run_dir).review_round(1) / config.REVIEW_REPORT_JSON_FILENAME).exists()


def test_analyze_preserves_review_report_md_when_bundle_unchanged(isolated_runs_dir):
    """The cleanup must not fire on a no-op re-run: the round-1 bundle still matches
    its snapshot, so the rendered review-report.md is still an accurate receipt."""
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    assert (RunPaths.at(run_dir).review_report_md).exists()
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    assert (RunPaths.at(run_dir).review_report_md).exists()


def _finding(severity, artifact="claims.json#claim-001"):
    return {
        "severity": severity,
        "artifact": artifact,
        "passage": "Revenue was $110 million.",
        "evidence": "Matches quote.",
        "recommendation": "None.",
    }


def test_check_review_blocks_pass_verdict_with_medium_severity_finding(isolated_runs_dir):
    """verdict: 'pass' must be internally consistent with the reviewer's own assigned
    severities -- 'pass' requires nothing above 'low'."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    review_report = {
        "verdict": "pass",
        "reviewed_at": "2026-08-27T00:00:00Z",
        "model": "opus",
        "source_checks": [],
        "claim_findings": [_finding("medium")],
        "outlook_findings": [],
        "process_findings": [],
        "unverified_items": [],
        "summary": "Minor issue but marked pass.",
        "escalate_full_review": False,
    }
    _write_review_report(run_dir, review_report)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_check_review_blocks_pass_with_warnings_verdict_with_critical_severity_finding(isolated_runs_dir):
    """verdict: 'pass_with_warnings' must not co-exist with a 'critical' finding -- that
    combination should have been verdict: 'fail'."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text("# Outlook\n\nStrong [claim-001].\n")
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    review_report = {
        "verdict": "pass_with_warnings",
        "reviewed_at": "2026-08-27T00:00:00Z",
        "model": "opus",
        "source_checks": [],
        "claim_findings": [_finding("critical")],
        "outlook_findings": [],
        "process_findings": [],
        "unverified_items": [],
        "summary": "Serious issue but marked pass_with_warnings.",
        "escalate_full_review": False,
    }
    _write_review_report(run_dir, review_report)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_analyze_requires_manifest_json(isolated_runs_dir):
    """analyze previously never checked manifest.json existed at all -- claims could
    validate against a run with no source-provenance record."""
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    (RunPaths.at(run_dir).claims).write_text("[]")
    (RunPaths.at(run_dir).manifest).unlink()
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_analyze_rejects_manifest_source_hash_mismatch(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    (RunPaths.at(run_dir).claims).write_text("[]")
    manifest = json.loads((RunPaths.at(run_dir).manifest).read_text())
    manifest["sources"][0]["sha256"] = "0" * 64
    (RunPaths.at(run_dir).manifest).write_text(json.dumps(manifest))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2


def test_snapshot_review_round_is_idempotent_on_unchanged_report(isolated_runs_dir):
    """Calling check-review twice on an unchanged review-report.json must not create
    a redundant round-2 snapshot -- that would inflate the round count and eat into
    max_review_rounds for nothing new having happened."""
    run_dir = _seed_reviewed_run(isolated_runs_dir)  # round-1 already snapshotted
    assert _review_round_count(run_dir) == 1
    # Re-run check-review against the SAME, unchanged review-report.json (as if it
    # were accidentally invoked twice with no new dispatch in between).
    main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert _review_round_count(run_dir) == 1
    assert not (RunPaths.at(run_dir).review_round(2)).exists()


def test_review_snapshot_identity_includes_outlook_validation(isolated_runs_dir):
    """Ignore a new timestamp but detect a meaningful change to the outlook gate."""
    run_dir = _seed_reviewed_run(isolated_runs_dir)
    assert _review_bundle_matches_snapshot(run_dir, 1) is True
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    assert _review_bundle_matches_snapshot(run_dir, 1) is True
    result_path = RunPaths.at(run_dir).outlook_validation
    result = json.loads(result_path.read_text())
    result["claims_sha256"] = "0" * 64
    result_path.write_text(json.dumps(result))
    assert _review_bundle_matches_snapshot(run_dir, 1) is False


# --- audit-record.json: one-time final summary, written only on a terminal verdict ---

def test_check_review_writes_audit_record_on_pass(isolated_runs_dir):
    run_dir = _seed_reviewed_run(isolated_runs_dir, verdict="pass")
    audit_path = RunPaths.at(run_dir).audit_record
    assert audit_path.exists()
    record = json.loads(audit_path.read_text())
    assert record["run_id"] == "ACME:2026-q2"
    assert record["status"] == "accepted"
    assert record["final_review_round"] == 1
    assert record["decision"]["verdict"] == "pass"
    assert record["review_history_summary"]["review_rounds"] == 1
    assert record["review_history_summary"]["failed_review_rounds"] == 0
    assert record["workflow_trace"][0]["stage"] == "claim_validation"
    assert record["workflow_trace"][0]["attempts"] >= 1
    assert record["workflow_trace"][1] == {
        "stage": "outlook_validation",
        "attempts": 1,
        "status": "passed",
    }
    assert record["guardrail_summary"]["outlook_validation_retries"] == 0
    assert record["guardrail_summary"]["outlook_validation_rejections"] == 0
    assert record["guardrail_summary"]["review_rejections"] == 0
    assert record["guardrail_summary"]["escalations"] == 0
    assert record["hashes"]["manifest_sha256"]
    assert record["hashes"]["claims_sha256"]
    assert record["hashes"]["outlook_brief_sha256"]
    assert record["hashes"]["review_report_sha256"]
    assert record["reviewer_model"] == "opus"
    assert record["tool_decisions"] == {
        "price_lookup": {
            "decision": "not_used",
            "reason": "Fixture does not require market-price evidence",
        }
    }


def test_audit_record_counts_outlook_validation_corrections(isolated_runs_dir):
    """Expose a failed brief submission followed by a passing correction in the audit."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook\n\nUnsupported [claim-999].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook\n\nSupported [claim-001].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    _write_review_report(
        run_dir,
        {
            "verdict": "pass",
            "reviewed_at": "2026-08-27T00:00:00Z",
            "model": "opus",
            "source_checks": [],
            "claim_findings": [],
            "outlook_findings": [],
            "process_findings": [],
            "unverified_items": [],
            "summary": "Looks fine.",
            "escalate_full_review": False,
        },
    )
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    record = json.loads((RunPaths.at(run_dir).audit_record).read_text())
    assert record["workflow_trace"][1]["attempts"] == 2
    assert record["workflow_trace"][1]["status"] == "passed"
    assert record["guardrail_summary"]["outlook_validation_retries"] == 1
    assert record["guardrail_summary"]["outlook_validation_rejections"] == 1
    assert "2 outlook-validation attempt(s)" in record["trace_summary"]


def test_check_review_does_not_write_audit_record_on_fail(isolated_runs_dir):
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook\n\nStrong [claim-001].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    review_report = {
        "verdict": "fail", "reviewed_at": "2026-08-27T00:00:00Z", "model": "opus",
        "source_checks": [], "claim_findings": [_finding("high")], "outlook_findings": [],
        "process_findings": [], "unverified_items": [], "summary": "Needs a fix.",
        "escalate_full_review": False,
    }
    _write_review_report(run_dir, review_report)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2
    assert not (RunPaths.at(run_dir).audit_record).exists()


def test_check_review_audit_record_aggregates_across_rounds(isolated_runs_dir):
    """A round-1 fail followed by a round-2 pass_with_warnings must still produce
    exactly one audit-record.json, reflecting round 2 as final but counting the
    round-1 failure and its finding severities in the cumulative guardrail summary."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\n## 1. Outlook in brief\n\nStrong quarter.\n\n"
        "## 2. Q&A highlights\n\nRevenue grew steadily [claim-001].\n\n"
        "## 5. Base case\n\nContinued momentum expected.\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    round1_report = {
        "verdict": "fail", "reviewed_at": "2026-08-27T00:00:00Z", "model": "opus",
        "source_checks": [_finding("info")], "claim_findings": [_finding("high")],
        "outlook_findings": [], "process_findings": [_finding("info")],
        "unverified_items": [], "summary": "One high finding.", "escalate_full_review": False,
    }
    _write_review_report(run_dir, round1_report)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2
    assert not (RunPaths.at(run_dir).audit_record).exists()

    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) in (0, 3)
    round2_report = {
        "verdict": "pass_with_warnings", "reviewed_at": "2026-08-28T00:00:00Z", "model": "opus",
        "source_checks": [_finding("info")], "claim_findings": [_finding("medium"), _finding("medium"), _finding("medium")],
        "outlook_findings": [], "process_findings": [_finding("info")],
        "unverified_items": [], "summary": "Fixed; three medium warnings remain.",
        "escalate_full_review": False, "review_mode": "diff",
    }
    _write_review_report(run_dir, round2_report, review_mode="diff")
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1

    record = json.loads((RunPaths.at(run_dir).audit_record).read_text())
    assert record["final_review_round"] == 2
    assert record["decision"]["verdict"] == "pass_with_warnings"
    assert record["decision"]["finding_counts"]["medium"] == 3
    assert record["review_history_summary"]["review_rounds"] == 2
    assert record["review_history_summary"]["failed_review_rounds"] == 1
    assert record["review_history_summary"]["historical_findings"]["high"] == 1
    assert record["review_history_summary"]["historical_findings"]["medium"] == 3
    assert record["guardrail_summary"]["review_rejections"] == 1
    assert record["guardrail_summary"]["escalations"] == 0
    assert [t["status"] for t in record["workflow_trace"] if t["stage"] == "review"] == ["fail", "pass_with_warnings"]
    assert "2 round" in record["trace_summary"]
    assert "round 1 fail" in record["trace_summary"]
    assert "round 2 pass_with_warnings" in record["trace_summary"]


def test_check_review_audit_record_counts_historical_escalation(isolated_runs_dir):
    """A round that escalates (forces a full re-review) is snapshotted into
    _review_history like any other round but never gets its own audit-record.json
    (escalation isn't terminal). Once a later round passes cleanly, the final
    audit record's guardrail_summary must still show that escalation happened."""
    run_dir = _seed_validated_run(isolated_runs_dir)
    (RunPaths.at(run_dir).outlook_brief).write_text(
        "# Outlook Brief\n\n## 1. Outlook in brief\n\nStrong quarter.\n\n"
        "## 2. Q&A highlights\n\nRevenue grew steadily [claim-001].\n\n"
        "## 5. Base case\n\nContinued momentum expected.\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    round1_report = {
        "verdict": "fail", "reviewed_at": "2026-08-27T00:00:00Z", "model": "opus",
        "source_checks": [], "claim_findings": [_finding("high")], "outlook_findings": [],
        "process_findings": [], "unverified_items": [], "summary": "One high finding.",
        "escalate_full_review": False,
    }
    _write_review_report(run_dir, round1_report)
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 2

    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) in (0, 3)
    round2_report = {
        "verdict": "pass_with_warnings", "reviewed_at": "2026-08-28T00:00:00Z", "model": "opus",
        "source_checks": [], "claim_findings": [_finding("low")], "outlook_findings": [], "process_findings": [],
        "unverified_items": [], "summary": "Diff too thin to judge; escalating.",
        "escalate_full_review": True, "review_mode": "diff",
    }
    _write_review_report(run_dir, round2_report, review_mode="diff")
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 3
    assert not (RunPaths.at(run_dir).audit_record).exists()

    assert main(["review-diff", "--ticker", "ACME", "--event-id", "2026-q2"]) in (0, 3)
    round3_report = {
        "verdict": "pass", "reviewed_at": "2026-08-29T00:00:00Z", "model": "opus",
        "source_checks": [], "claim_findings": [], "outlook_findings": [], "process_findings": [],
        "unverified_items": [], "summary": "Clean on full re-review.", "escalate_full_review": False,
    }
    _write_review_report(run_dir, round3_report, review_mode="full")
    assert main(["check-review", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    record = json.loads((RunPaths.at(run_dir).audit_record).read_text())
    assert record["final_review_round"] == 3
    assert record["review_history_summary"]["review_rounds"] == 3
    assert record["guardrail_summary"]["escalations"] == 1
    assert record["guardrail_summary"]["review_rejections"] == 1
