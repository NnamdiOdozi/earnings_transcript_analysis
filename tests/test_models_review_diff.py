"""Round-trip serialization for the diff-based re-review models (ReviewDiff,
ClaimDiffEntry), plus ReviewReport.escalate_full_review's default."""
from earnings.models import ClaimDiffEntry, ReviewDiff, ReviewReport


def test_claim_diff_entry_round_trips():
    entry = ClaimDiffEntry(
        claim_id="claim-001",
        change="changed",
        old={"claim_text": "Revenue was $100 million."},
        new={"claim_text": "Revenue was $110 million."},
    )
    dumped = entry.model_dump()
    restored = ClaimDiffEntry.model_validate(dumped)
    assert restored == entry


def test_claim_diff_entry_added_has_no_old():
    entry = ClaimDiffEntry(claim_id="claim-002", change="added", new={"claim_text": "New claim."})
    assert entry.old is None
    assert ClaimDiffEntry.model_validate(entry.model_dump()) == entry


def test_review_diff_round_trips():
    diff = ReviewDiff(
        generated_at="2026-08-27T00:00:00Z",
        round_number=2,
        since_round=1,
        previous_verdict="pass",
        previous_summary="Looks fine.",
        previous_finding_count=0,
        claims_changed=[
            ClaimDiffEntry(claim_id="claim-001", change="changed", old={"a": 1}, new={"a": 2}),
        ],
        affected_brief_sections=[5],
        auto_escalated=True,
        auto_escalation_reason="conclusion-bearing section(s) [5] cite a changed claim",
    )
    restored = ReviewDiff.model_validate_json(diff.model_dump_json())
    assert restored == diff


def test_review_diff_defaults():
    diff = ReviewDiff(
        generated_at="2026-08-27T00:00:00Z",
        round_number=2,
        since_round=1,
        previous_verdict="pass",
        previous_summary="",
        previous_finding_count=0,
    )
    assert diff.claims_changed == []
    assert diff.affected_brief_sections == []
    assert diff.auto_escalated is False
    assert diff.auto_escalation_reason is None


def test_review_report_escalate_full_review_defaults_false():
    report = ReviewReport(
        verdict="pass",
        reviewed_at="2026-08-27T00:00:00Z",
        summary="ok",
    )
    assert report.escalate_full_review is False
    restored = ReviewReport.model_validate_json(report.model_dump_json())
    assert restored.escalate_full_review is False
