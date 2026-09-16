from __future__ import annotations

import json
from pathlib import Path

from . import config
from .models import OutlookValidation, ReviewReport, ValidationResult
from .paths import RunPaths
from .process import sha256_hex
from .provenance import _load_validated_json
from .runio import _now_iso


def _build_audit_record(
    ticker: str, event_id: str, run_dir: Path, round_number: int, report: ReviewReport
) -> dict:
    """Compile the single, final audit-record.json for a run, once check-review
    accepts a non-fail verdict -- a deterministic summary package built entirely
    from artefacts that already exist (manifest.json, outlook-validation.json,
    _validation_history/, _review_history/). Never agent-authored: the agent
    doesn't read or write this file at all.

    Not a live log and not a history file -- those already exist separately
    (_validation_history/, _review_history/); this is the one-file answer to
    "what happened on this run, and was it approved."

    `trace_summary` is deterministic templated prose, not a second LLM call --
    plain and formulaic by design, not meant to read as polished narrative.
    `workflow_trace` is a coarse stage/round list built from the same
    attempt-dir and round-dir counts, not a claim of full execution tracing.
    `review_history_summary` aggregates findings across every round in
    _review_history (not just the final one), so it reflects how much scrutiny
    the run went through even where a later round fixed what was flagged --
    this is a review-outcome rollup, not a guardrail-intervention log.
    `guardrail_summary.validation_retries` is `attempts - 1` when there's more
    than one attempt: it counts *resubmissions*, not confirmed retry-after-
    rejection causation -- in practice every extra attempt in this pipeline is
    a correction resubmission, but the field doesn't itself prove causality.
    `escalations` counts historical rounds where the reviewer set
    `escalate_full_review` (models.ReviewReport) -- forced a full re-review
    because a diff-only review couldn't be judged responsibly.
    """
    paths = RunPaths.at(run_dir)
    manifest_path = paths.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest.get("sources", [])
    transcript_candidates = [s for s in sources if s.get("path", "").startswith("raw/transcript")]
    transcript_source = next(
        (s for s in transcript_candidates if not s["path"].endswith(".converted.md")),
        transcript_candidates[0] if transcript_candidates else None,
    )

    outlook_validation = _load_validated_json(paths.outlook_validation, OutlookValidation)
    validation = _load_validated_json(paths.validation, ValidationResult)
    report_path = paths.review_report_json

    attempt_dirs = sorted((paths.validation_history).glob("attempt-*"))
    attempts_with_issues = 0
    last_attempt_outcome = None
    for attempt_dir in attempt_dirs:
        receipt = json.loads((attempt_dir / config.VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text(encoding="utf-8"))
        last_attempt_outcome = receipt.get("outcome")
        if receipt.get("outcome") != "passed":
            attempts_with_issues += 1

    outlook_attempt_dirs = sorted(
        (paths.outlook_validation_history).glob("attempt-*")
    )
    outlook_attempts_with_issues = 0
    last_outlook_attempt_outcome = None
    for attempt_dir in outlook_attempt_dirs:
        receipt = json.loads(
            (attempt_dir / config.OUTLOOK_VALIDATION_ATTEMPT_RECEIPT_FILENAME).read_text(
                encoding="utf-8"
            )
        )
        last_outlook_attempt_outcome = receipt.get("outcome")
        if receipt.get("outcome") != "passed":
            outlook_attempts_with_issues += 1

    round_dirs = sorted(
        (paths.review_history).glob("round-*"),
        key=lambda p: int(p.name.split("-")[1]),
    )
    severities = ("critical", "high", "medium", "low", "info")
    finding_list_keys = ("source_checks", "claim_findings", "outlook_findings", "process_findings")

    failed_rounds = 0
    escalations = 0
    historical_findings = {sev: 0 for sev in severities}
    round_traces: list[dict] = []
    round_descriptions: list[str] = []
    for round_dir_path in round_dirs:
        round_report = json.loads((round_dir_path / config.REVIEW_REPORT_JSON_FILENAME).read_text(encoding="utf-8"))
        round_num = int(round_dir_path.name.split("-")[1])
        round_verdict = round_report.get("verdict")
        if round_verdict == "fail":
            failed_rounds += 1
        if round_report.get("escalate_full_review"):
            escalations += 1
        round_severity_counts = {sev: 0 for sev in severities}
        for key in finding_list_keys:
            for finding in round_report.get(key, []):
                sev = finding.get("severity")
                if sev in historical_findings:
                    historical_findings[sev] += 1
                    round_severity_counts[sev] += 1
        round_traces.append({"stage": "review", "round": round_num, "status": round_verdict})
        finding_phrase = ", ".join(
            f"{count} {sev}" for sev, count in round_severity_counts.items() if count
        )
        round_descriptions.append(
            f"round {round_num} {round_verdict}" + (f" with {finding_phrase} finding(s)" if finding_phrase else "")
        )

    final_lists = [getattr(report, key) for key in finding_list_keys]
    final_finding_counts = {
        sev: sum(1 for lst in final_lists for f in lst if f.severity == sev) for sev in severities
    }

    claim_validation_status = "passed" if last_attempt_outcome == "passed" else "unknown"
    outlook_validation_status = last_outlook_attempt_outcome or (
        "passed" if outlook_validation and outlook_validation.ok else "unknown"
    )
    workflow_trace = [
        {"stage": "claim_validation", "attempts": len(attempt_dirs), "status": claim_validation_status},
        {
            "stage": "outlook_validation",
            "attempts": len(outlook_attempt_dirs),
            "status": outlook_validation_status,
        },
        *round_traces,
    ]

    validation_retries = max(len(attempt_dirs) - 1, 0)
    outlook_validation_retries = max(len(outlook_attempt_dirs) - 1, 0)

    trace_summary = (
        f"Analysis drew on {len(sources)} recorded source(s) (transcript, SEC/web evidence). "
        f"{len(attempt_dirs)} claim-validation attempt(s) were made"
        + (f", {attempts_with_issues} with issues," if attempts_with_issues else "")
        + " before passing."
        + (
            (
                f" {len(outlook_attempt_dirs)} outlook-validation attempt(s) were made"
                + (
                    f", {outlook_attempts_with_issues} with issues or blocked,"
                    if outlook_attempts_with_issues
                    else ""
                )
                + " before passing."
            )
            if outlook_attempt_dirs
            else ""
        )
        + (f" Review ran {len(round_dirs)} round(s): " + "; ".join(round_descriptions) + "."
           if round_descriptions else "")
    )

    return {
        "run_id": f"{ticker}:{event_id}",
        "ticker": ticker,
        "event_id": event_id,
        "status": "accepted",
        "final_review_round": round_number,
        "generated_at": _now_iso(),
        "decision": {
            "verdict": report.verdict,
            "summary": report.summary,
            "finding_counts": final_finding_counts,
        },
        "trace_summary": trace_summary,
        "workflow_trace": workflow_trace,
        "review_history_summary": {
            "review_rounds": len(round_dirs),
            "failed_review_rounds": failed_rounds,
            "historical_findings": historical_findings,
        },
        "guardrail_summary": {
            "validation_retries": validation_retries,
            "validation_rejections": attempts_with_issues,
            "outlook_validation_retries": outlook_validation_retries,
            "outlook_validation_rejections": outlook_attempts_with_issues,
            "review_rejections": failed_rounds,
            "escalations": escalations,
        },
        "tool_decisions": (
            validation.tool_decisions.model_dump()
            if validation and validation.tool_decisions
            else None
        ),
        "hashes": {
            "transcript_sha256": transcript_source["sha256"] if transcript_source else None,
            "manifest_sha256": sha256_hex(manifest_path.read_bytes()),
            "claims_sha256": outlook_validation.claims_sha256 if outlook_validation else None,
            "outlook_brief_sha256": outlook_validation.outlook_brief_sha256 if outlook_validation else None,
            "review_report_sha256": sha256_hex(report_path.read_bytes()),
        },
        "evidence_summary": {"source_count": len(sources)},
        "reviewer_model": report.model,
    }
