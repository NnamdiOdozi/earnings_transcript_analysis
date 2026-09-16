"""RunPaths is the single place the run-directory layout is expressed.

These tests pin the current (flat) arrangement so the planned move to
claims/outlook/review stage folders is a deliberate, visible change rather than an
accidental one.
"""

from earnings import config
from earnings.paths import RunPaths


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


def test_current_flat_layout(tmp_path):
    """Change these deliberately when the stage-folder layout lands, not by accident."""
    paths = RunPaths.at(tmp_path)
    assert paths.claims == tmp_path / "claims.json"
    assert paths.outlook_brief == tmp_path / "outlook-brief.md"
    assert paths.review_report_json == tmp_path / "review-report.json"
    assert paths.transcript == tmp_path / "normalized" / "transcript.jsonl"
    assert paths.financials == tmp_path / "evidence" / "financials.json"
    assert paths.review_round(1) == tmp_path / "_review_history" / "round-1"
