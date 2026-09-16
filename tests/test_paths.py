"""RunPaths is the single place the run-directory layout is expressed.

These tests pin the current (flat) arrangement so the planned move to
claims/outlook/review stage folders is a deliberate, visible change rather than an
accidental one.
"""

import json

from earnings import config
from earnings.paths import (
    LAYOUT_FLAT,
    LAYOUT_STAGED,
    RunPaths,
    detect_layout,
)


def test_for_run_matches_config_run_dir():
    assert RunPaths.for_run("jpm", "2026-q2").root == config.run_dir("JPM", "2026-q2")


def test_every_artifact_resolves_under_the_run_root(tmp_path):
    paths = RunPaths.at(tmp_path)
    artifacts = [
        paths.manifest, paths.transcript, paths.financials, paths.web_evidence,
        paths.segmentation_report, paths.injection_scan, paths.price_lookup_log,
        paths.claims, paths.metrics, paths.validation, paths.signal_card,
        paths.outlook_brief, paths.outlook_validation,
        paths.review_report_json, paths.review_report_md,
        paths.review_diff, paths.review_diff_sha256,
        paths.audit_record,
        paths.raw, paths.normalized, paths.evidence, paths.web_evidence_dir,
        paths.validation_history, paths.outlook_validation_history,
        paths.review_history, paths.review_round(2), paths.archive,
    ]
    for artifact in artifacts:
        assert artifact.is_relative_to(tmp_path), artifact
    # no two artifacts may collide on the same path
    assert len(set(artifacts)) == len(artifacts)


def test_flat_layout_is_what_a_pre_existing_run_gets(tmp_path):
    """A run with no manifest, or a manifest predating layout_version, stays flat.

    Existing runs are never migrated, so this is the shape every already-committed run
    must keep resolving to under new code.
    """
    paths = RunPaths.at(tmp_path, LAYOUT_FLAT)
    assert paths.claims == tmp_path / "claims.json"
    assert paths.outlook_brief == tmp_path / "outlook-brief.md"
    assert paths.review_report_json == tmp_path / "review-report.json"
    assert paths.transcript == tmp_path / "normalized" / "transcript.jsonl"
    assert paths.financials == tmp_path / "evidence" / "financials.json"
    assert paths.review_round(1) == tmp_path / "_review_history" / "round-1"


def test_manifest_without_layout_version_detects_as_flat(tmp_path):
    (tmp_path / config.MANIFEST_FILENAME).write_text(
        json.dumps({"ticker": "ACME", "event_id": "2026-q2", "created_at": "x"})
    )
    assert detect_layout(tmp_path) == LAYOUT_FLAT
    assert RunPaths.at(tmp_path).claims == tmp_path / "claims.json"


def test_manifest_declaring_layout_2_detects_as_staged(tmp_path):
    (tmp_path / config.MANIFEST_FILENAME).write_text(json.dumps({"layout_version": 2}))
    assert detect_layout(tmp_path) == LAYOUT_STAGED
    paths = RunPaths.at(tmp_path)
    assert paths.claims == tmp_path / "claims" / "claims.json"
    assert paths.validation == tmp_path / "claims" / "validation.json"
    assert paths.signal_card == tmp_path / "claims" / "signal-card.md"
    assert paths.outlook_brief == tmp_path / "outlook" / "outlook-brief.md"
    assert paths.review_report_json == tmp_path / "review" / "review-report.json"
    # each stage's history sits beside the artifacts it is the history of
    assert paths.validation_history == tmp_path / "claims" / "history"
    assert paths.outlook_validation_history == tmp_path / "outlook" / "history"
    assert paths.review_round(1) == tmp_path / "review" / "history" / "round-1"
    # shared source pack and the whole-run summary do not move into a stage
    assert paths.manifest == tmp_path / "manifest.json"
    assert paths.audit_record == tmp_path / "audit-record.json"
    assert paths.transcript == tmp_path / "normalized" / "transcript.jsonl"


def test_unreadable_or_absurd_layout_falls_back_to_flat(tmp_path):
    """Fail to the arrangement that already exists on disk, never to a new one."""
    (tmp_path / config.MANIFEST_FILENAME).write_text("{not json")
    assert detect_layout(tmp_path) == LAYOUT_FLAT
    (tmp_path / config.MANIFEST_FILENAME).write_text(json.dumps({"layout_version": 99}))
    assert detect_layout(tmp_path) == LAYOUT_FLAT


def test_resolve_matches_the_named_properties(tmp_path):
    """resolve() is for filename-list loops; it must not drift from the properties."""
    paths = RunPaths.at(tmp_path, LAYOUT_STAGED)
    assert paths.resolve(config.CLAIMS_FILENAME) == paths.claims
    assert paths.resolve(config.OUTLOOK_BRIEF_FILENAME) == paths.outlook_brief
    assert paths.resolve(config.REVIEW_REPORT_JSON_FILENAME) == paths.review_report_json
    assert paths.resolve(config.MANIFEST_FILENAME) == paths.manifest
