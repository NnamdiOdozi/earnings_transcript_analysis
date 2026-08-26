"""End-to-end CLI test: prepare -> write claims.json -> analyze, using tmp_path so
no real network call happens (no --sec-cik passed) and no files leak outside tmp_path.
"""
import json
from pathlib import Path

import pytest

from earnings import config, sources
from earnings.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def isolated_runs_dir(tmp_path, monkeypatch):
    """Redirect config.RUNS_DIR to a tmp_path subdirectory for the duration of the
    test, and disable SEC/Tavily auto-lookups (both on by default) so `prepare`
    never touches the network in tests.
    """
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
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
    segment_lines = (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).read_text().splitlines()
    assert segment_lines == []

    (run_dir / config.CLAIMS_FILENAME).write_text("[]")
    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-empty"])
    assert rc == 0

    validation = json.loads((run_dir / config.VALIDATION_FILENAME).read_text())
    assert validation["ok"] is True
    assert validation["checked_claims"] == 0


def test_prepare_then_analyze_valid_claims_produces_signal_card(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    rc = main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])
    assert rc == 0

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    assert (run_dir / config.MANIFEST_FILENAME).exists()
    assert (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).exists()

    manifest = json.loads((run_dir / config.MANIFEST_FILENAME).read_text())
    assert manifest["ticker"] == "ACME"
    assert len(manifest["sources"]) == 1
    assert len(manifest["sources"][0]["sha256"]) == 64

    segment_lines = (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    claims = [
        {
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
    (run_dir / config.CLAIMS_FILENAME).write_text(json.dumps(claims, indent=2))

    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert rc == 0

    validation = json.loads((run_dir / config.VALIDATION_FILENAME).read_text())
    assert validation["ok"] is True

    card = (run_dir / config.SIGNAL_CARD_FILENAME).read_text()
    assert "ACME" in card
    assert "110 million" in card


def test_analyze_blocks_signal_card_when_claim_has_paraphrased_quote(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    claims = [
        {
            "category": "reported_financial_performance",
            "classification": "reported_fact",
            "claim_text": "Revenue rose sharply.",
            "quote": "Revenue climbed to $110 million this quarter.",  # paraphrased, not verbatim
            "segment_id": revenue_segment["id"],
            "status": "reported",
            "confidence": 0.7,
        }
    ]
    (run_dir / config.CLAIMS_FILENAME).write_text(json.dumps(claims, indent=2))

    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert rc == 1  # non-zero exit blocks the pipeline

    validation = json.loads((run_dir / config.VALIDATION_FILENAME).read_text())
    assert validation["ok"] is False
    assert not (run_dir / config.SIGNAL_CARD_FILENAME).exists()


def test_analyze_handles_malformed_claims_json_without_traceback(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    (run_dir / config.CLAIMS_FILENAME).write_text("{not valid json")

    rc = main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"])
    assert rc == 1

    validation = json.loads((run_dir / config.VALIDATION_FILENAME).read_text())
    assert validation["ok"] is False
    assert validation["issues"][0]["check"] == "schema"


def test_analyze_removes_stale_signal_card_after_later_failing_run(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).read_text().splitlines()
    segments = [json.loads(line) for line in segment_lines]
    revenue_segment = next(s for s in segments if "110 million" in s["text"])

    passing_claims = [
        {
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
    (run_dir / config.CLAIMS_FILENAME).write_text(json.dumps(passing_claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
    assert (run_dir / config.SIGNAL_CARD_FILENAME).exists()

    # Edit claims to something that now fails validation -- the stale card from the
    # prior passing run must not survive being mistaken for the current result.
    failing_claims = [
        {
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
    (run_dir / config.CLAIMS_FILENAME).write_text(json.dumps(failing_claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1
    assert not (run_dir / config.SIGNAL_CARD_FILENAME).exists()


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
    assert len(calls) == 7  # one per _OFFICIAL_DOC_TYPES entry
    assert all("Acme Corp" in q and "ACME" in q and "2026-07-15" in q for q in calls)

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    archived = sorted((run_dir / config.RAW_SUBDIR / "web").glob("*.json"))
    assert len(archived) == 7  # one hit archived per query, per the fake

    manifest = json.loads((run_dir / config.MANIFEST_FILENAME).read_text())
    assert any(f"Web search evidence ({provider}): ok" in note for note in manifest["notes"])
    assert any("Web evidence (extracted, citable): 7 source(s)" in note for note in manifest["notes"])

    # 7 search hits (one per query, distinct URLs) all get extracted -- capped by
    # max_extracted_sources (10, default), so all 7 are selected here.
    assert len(extract_calls) == 7

    extracted_files = sorted((run_dir / config.EVIDENCE_SUBDIR / config.WEB_SUBDIR).glob("*.md"))
    assert len(extracted_files) == 7
    assert "Full extracted content" in extracted_files[0].read_text()

    web_evidence_lines = (run_dir / config.EVIDENCE_SUBDIR / config.WEB_EVIDENCE_FILENAME).read_text().strip().splitlines()
    assert len(web_evidence_lines) == 7

    # transcript source + 7 search-hit sources + 7 extracted web-evidence sources
    assert len(manifest["sources"]) == 15
    assert all(len(s["sha256"]) == 64 for s in manifest["sources"])


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
    manifest = json.loads((run_dir / config.MANIFEST_FILENAME).read_text())
    assert any("causality guard" in note for note in manifest["notes"])

    web_evidence_lines = (run_dir / config.EVIDENCE_SUBDIR / config.WEB_EVIDENCE_FILENAME).read_text().strip().splitlines()
    assert len(web_evidence_lines) == 1
    assert "before" in web_evidence_lines[0]

    # still archived under raw/web/ for audit (both hits, all 7 queries -> 14 files),
    # just never extracted as citable evidence.
    assert len(list((run_dir / config.RAW_SUBDIR / "web").glob("*.json"))) == 14


def test_normalize_hits_maps_both_provider_shapes_to_one_canonical_shape():
    tavily_hit = {"url": "https://x.com", "title": "T", "score": 0.5, "published_date": "2026-07-10"}
    exa_hit = {"url": "https://y.com", "title": "Y", "score": 0.7, "publishedDate": "2026-07-11"}
    assert sources._normalize_hits([tavily_hit], "tavily") == [
        {"url": "https://x.com", "title": "T", "score": 0.5, "published_date": "2026-07-10"}
    ]
    assert sources._normalize_hits([exa_hit], "exa") == [
        {"url": "https://y.com", "title": "Y", "score": 0.7, "published_date": "2026-07-11"}
    ]


def test_prepare_archives_prior_run_instead_of_overwriting(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    run_dir = isolated_runs_dir / "ACME" / "2026-q2"

    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript]) == 0
    first_manifest = json.loads((run_dir / config.MANIFEST_FILENAME).read_text())

    # Rerun for the same ticker/event -- must not silently clobber the first run.
    assert main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript]) == 0
    second_manifest = json.loads((run_dir / config.MANIFEST_FILENAME).read_text())

    archive_dir = run_dir / config.ARCHIVE_SUBDIR
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
    segment_lines = (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).read_text().splitlines()
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
    (run_dir / config.CLAIMS_FILENAME).write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    (run_dir / config.OUTLOOK_BRIEF_FILENAME).write_text(
        "# Outlook Brief\n\nRevenue growth looks strong [claim-999].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 1


def test_validate_outlook_passes_with_real_citation(isolated_runs_dir):
    transcript = str(FIXTURES / "normal_transcript.txt")
    main(["prepare", "--ticker", "ACME", "--event-id", "2026-q2", "--transcript", transcript])

    run_dir = isolated_runs_dir / "ACME" / "2026-q2"
    segment_lines = (run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME).read_text().splitlines()
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
    (run_dir / config.CLAIMS_FILENAME).write_text(json.dumps(claims))
    assert main(["analyze", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0

    (run_dir / config.OUTLOOK_BRIEF_FILENAME).write_text(
        "# Outlook Brief\n\nRevenue growth looks strong [claim-001].\n"
    )
    assert main(["validate-outlook", "--ticker", "ACME", "--event-id", "2026-q2"]) == 0
