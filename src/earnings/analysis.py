from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from . import config
from .models import (
    Claim,
    Manifest,
    Metric,
    PriceLookupDecision,
    TemporalStatus,
    ToolDecisions,
    ValidationIssue,
    ValidationResult,
    WebEvidence,
)
from .paths import RunPaths
from .provenance import (
    _input_hashes,
    _load_validated_json,
    _manifest_source_errors,
    _price_decision_issues,
    _write_validation,
)
from .rendering import _render_signal_card
from .review import _block_if_unclosed_review_report, _clear_stale_review_report_md
from .validate import validate_claims, validate_metrics
from .validation_history import ValidationAttempt


def cmd_analyze(args: argparse.Namespace) -> int:
    run_dir = config.run_dir(args.ticker, args.event_id)
    paths = RunPaths.at(run_dir)
    tool_decisions = ToolDecisions(
        price_lookup=PriceLookupDecision(decision=args.price_decision, reason=args.price_reason)
    )
    price_decision_issues = _price_decision_issues(
        run_dir, args.ticker, tool_decisions.price_lookup
    )
    attempt = ValidationAttempt.start(run_dir, _input_hashes(run_dir))
    blocked = _block_if_unclosed_review_report(run_dir)
    if blocked is not None:
        attempt.finish("blocked", blocked)
        return blocked
    _clear_stale_review_report_md(run_dir)
    claims_path = paths.claims
    transcript_path = paths.transcript
    financials_path = paths.financials

    card_path = paths.signal_card
    card_path.unlink(missing_ok=True)  # clear any stale card from a prior passing run before (re)validating

    if not claims_path.exists():
        print(f"error: {claims_path} not found. Write claims.json first (see skill).", file=sys.stderr)
        attempt.finish("blocked", 2)
        return 2

    manifest_path = paths.manifest
    # manifest.json is prepare's own provenance record (source hashes, retrieval
    # timestamps) -- analyze was never checking it existed at all, so claims could
    # validate against a run with no source manifest. Schema-validated, not just
    # existence-checked: a content-free {} would pass a bare .exists() test but
    # carries no sources, defeating the point of requiring it.
    manifest = _load_validated_json(manifest_path, Manifest)
    if manifest is None:
        print(f"error: {manifest_path} not found or invalid. Run `earnings prepare` first.", file=sys.stderr)
        attempt.finish("blocked", 2)
        return 2
    if not manifest.sources:
        print(f"error: {manifest_path} has no sources recorded. Run `earnings prepare` first.", file=sys.stderr)
        attempt.finish("blocked", 2)
        return 2
    if manifest.ticker != args.ticker.upper() or manifest.event_id != args.event_id:
        print(f"error: {manifest_path} belongs to a different ticker or event.", file=sys.stderr)
        attempt.finish("blocked", 2)
        return 2
    manifest_errors = _manifest_source_errors(run_dir, manifest)
    if manifest_errors:
        print(f"error: {manifest_path} failed provenance checks:", file=sys.stderr)
        for error in manifest_errors:
            print(f"  {error}", file=sys.stderr)
        attempt.finish("blocked", 2)
        return 2

    from .models import Segment

    segments_by_id: dict[str, Segment] = {}
    with transcript_path.open(encoding="utf-8") as fh:
        for line in fh:
            seg = Segment.model_validate_json(line)
            segments_by_id[seg.id] = seg

    financials = json.loads(financials_path.read_text(encoding="utf-8")) if financials_path.exists() else {}

    web_evidence_path = paths.web_evidence
    web_evidence_texts: dict[str, str] = {}
    web_evidence_statuses: dict[str, TemporalStatus] = {}
    if web_evidence_path.exists():
        with web_evidence_path.open(encoding="utf-8") as fh:
            for line in fh:
                we = WebEvidence.model_validate_json(line)
                web_evidence_texts[we.id] = (run_dir / we.content_path).read_text(encoding="utf-8")
                web_evidence_statuses[we.id] = we.temporal_status

    try:
        raw_claims = json.loads(claims_path.read_text(encoding="utf-8"))
        claims = [Claim.model_validate(c) for c in raw_claims]
    except (json.JSONDecodeError, ValidationError) as exc:
        result = ValidationResult(
            ok=False,
            checked_claims=0,
            issues=[ValidationIssue(claim_index=-1, check="schema", message=f"Could not parse {config.CLAIMS_FILENAME}: {exc}")]
            + price_decision_issues,
            tool_decisions=tool_decisions,
        )
        _write_validation(run_dir, result)
        attempt.finish("failed", 1, result, validation_path=paths.validation)
        print(f"Validation FAILED: could not parse {config.CLAIMS_FILENAME}: {exc}")
        return 1

    result = validate_claims(claims, segments_by_id, financials, web_evidence_texts, web_evidence_statuses)
    result.tool_decisions = tool_decisions
    result.issues.extend(price_decision_issues)
    result.ok = not result.issues

    metrics_path = paths.metrics
    if metrics_path.exists():
        claim_ids = {c.id for c in claims if c.id}
        try:
            raw_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics = [Metric.model_validate(m) for m in raw_metrics]
        except (json.JSONDecodeError, ValidationError) as exc:
            result = ValidationResult(
                ok=False,
                checked_claims=0,
                issues=[ValidationIssue(claim_index=-1, check="schema", message=f"Could not parse {config.METRICS_FILENAME}: {exc}")],
            )
            _write_validation(run_dir, result)
            attempt.finish("failed", 1, result, validation_path=paths.validation)
            print(f"Validation FAILED: could not parse {config.METRICS_FILENAME}: {exc}")
            return 1
        metric_issues = validate_metrics(metrics, claim_ids)
        if metric_issues:
            result = ValidationResult(
                ok=False,
                checked_claims=result.checked_claims,
                issues=result.issues + metric_issues,
                warnings=result.warnings,
                tool_decisions=tool_decisions,
            )

    _write_validation(run_dir, result)

    # Advisories print regardless of pass/fail -- they never block the card, but the
    # human should see them (e.g. web evidence fetched but no claim used it).
    for warning in result.warnings:
        print(f"  WARNING: {warning}")

    if not result.ok:
        attempt.finish("failed", 1, result, validation_path=paths.validation)
        print(f"Validation FAILED: {len(result.issues)} issue(s). See {config.VALIDATION_FILENAME}.")
        for issue in result.issues:
            print(f"  claim[{issue.claim_index}] {issue.check}: {issue.message}")
        return 1

    card = _render_signal_card(args.ticker, args.event_id, claims, segments_by_id)
    (paths.signal_card).write_text(card, encoding="utf-8")
    attempt.finish("passed", 0, result, validation_path=paths.validation)
    print(f"Validation passed ({result.checked_claims} claims). Wrote {config.SIGNAL_CARD_FILENAME}.")
    return 0
