from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from pydantic import ValidationError

from . import config
from .audit import _build_audit_record
from .models import OutlookValidation, ReviewDiff, ReviewReport, ValidationResult
from .paths import RunPaths
from .process import sha256_hex
from .provenance import _hash_gate_ok, _load_validated_json, _validation_inputs_current
from .rendering import _render_review_report
from .runio import _now_iso, _write_json
from .validate import validate_review_report


def _review_round_count(run_dir: Path) -> int:
    """How many review rounds have completed (each a snapshot in the run's review history)."""
    history_dir = RunPaths.at(run_dir).review_history
    if not history_dir.exists():
        return 0
    return len([d for d in history_dir.iterdir() if d.is_dir() and d.name.startswith("round-")])


def _review_bundle_matches_snapshot(run_dir: Path, round_number: int) -> bool:
    """Whether the validated review bundle still equals one accepted round exactly."""
    prior_dir = RunPaths.at(run_dir).review_round(round_number)
    filenames = (
        config.CLAIMS_FILENAME,
        config.OUTLOOK_BRIEF_FILENAME,
        config.REVIEW_REPORT_JSON_FILENAME,
    )
    if not all(
        (prior_dir / filename).is_file()
        and RunPaths.at(run_dir).resolve(filename).is_file()
        and (prior_dir / filename).read_bytes() == RunPaths.at(run_dir).resolve(filename).read_bytes()
        for filename in filenames
    ):
        return False

    gate_filename = config.OUTLOOK_VALIDATION_FILENAME
    if not (prior_dir / gate_filename).is_file() or not RunPaths.at(run_dir).resolve(gate_filename).is_file():
        return False
    prior_gate = json.loads((prior_dir / gate_filename).read_text(encoding="utf-8"))
    current_gate = json.loads(RunPaths.at(run_dir).resolve(gate_filename).read_text(encoding="utf-8"))
    prior_gate.pop("validated_at", None)
    current_gate.pop("validated_at", None)
    return prior_gate == current_gate


def _snapshot_review_round(run_dir: Path, round_number: int) -> None:
    """After a structurally-valid review-report.json is accepted (any verdict, or an
    escalation), snapshot the claims, brief, outlook gate result, and report under
    the run's review history so the NEXT round's `review-diff` can diff against a
    known-good prior state. Called once per completed round, from cmd_check_review.

    Idempotent only when the complete reviewed bundle is byte-identical to the
    latest snapshot. Comparing the report alone allowed changed claims or brief
    bytes to inherit an old verdict and suppress the next snapshot.
    """
    if round_number > 1 and _review_bundle_matches_snapshot(run_dir, round_number - 1):
        return
    dest = RunPaths.at(run_dir).review_round(round_number)
    dest.mkdir(parents=True, exist_ok=True)
    for filename in (
        config.CLAIMS_FILENAME,
        config.OUTLOOK_BRIEF_FILENAME,
        config.OUTLOOK_VALIDATION_FILENAME,
        config.REVIEW_REPORT_JSON_FILENAME,
    ):
        src = RunPaths.at(run_dir).resolve(filename)
        if src.exists():
            shutil.copy2(src, dest / filename)
    _write_review_round_receipt(dest)


def _write_review_round_receipt(round_dir: Path) -> None:
    """Write a small receipt.json alongside this round's snapshotted review-report.json:
    verdict and finding counts by severity only, no finding text -- so a human (or the
    next agent) can see how a round went at a glance, without opening the full report or
    waiting for audit-record.json, which is only written once the whole run is accepted.
    Mirrors the Stage 1 attempt receipt's role in the claims history.
    """
    report_path = round_dir / config.REVIEW_REPORT_JSON_FILENAME
    if not report_path.is_file():
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    severities = ("critical", "high", "medium", "low", "info")
    finding_counts = {sev: 0 for sev in severities}
    for key in ("source_checks", "claim_findings", "outlook_findings", "process_findings"):
        for finding in report.get(key, []):
            sev = finding.get("severity")
            if sev in finding_counts:
                finding_counts[sev] += 1
    receipt = {
        "round": int(round_dir.name.split("-")[1]),
        "verdict": report.get("verdict"),
        "reviewed_at": report.get("reviewed_at"),
        "review_mode": report.get("review_mode"),
        "escalate_full_review": report.get("escalate_full_review", False),
        "finding_counts": finding_counts,
    }
    _write_json(round_dir / config.REVIEW_ROUND_RECEIPT_FILENAME, receipt)


def _unclosed_review_report(run_dir: Path) -> bool:
    """True if review-report.json exists on disk but was never closed via
    `check-review` -- i.e. it doesn't byte-match the most recently completed round's
    snapshot. Editing claims.json/outlook-brief.md now, before closing that round,
    silently corrupts the diff-review baseline for every future round on this run:
    the next round's snapshot would capture the NEW correction under the OLD round
    number, so review-diff sees no change even though real edits happened. Discovered
    live (2026-08-28): an agent hand-following the skill's prose instructions made
    this exact mistake twice in one session, including once immediately after writing
    the "no exceptions" warning into the skill itself -- prose alone doesn't hold
    under the pull of "fix the findings now". This is the mechanical backstop.
    """
    paths = RunPaths.at(run_dir)
    report_path = paths.review_report_json
    if not report_path.exists():
        return False
    completed = _review_round_count(run_dir)
    # Once the configured cap is exhausted, a stray new report cannot be accepted.
    # It must not lock unrelated inspection/correction commands forever either.
    if completed >= config.REVIEW_MAX_ROUNDS:
        return False
    if completed == 0:
        return True  # a report exists but round 1 was never closed
    latest_snapshot = paths.review_round(completed) / config.REVIEW_REPORT_JSON_FILENAME
    if not latest_snapshot.exists():
        return True
    return report_path.read_bytes() != latest_snapshot.read_bytes()


def _clear_stale_review_report_md(run_dir: Path) -> None:
    """Delete the top-level review-report.md if it no longer describes the current
    bundle. Once the round cap is exhausted, `_unclosed_review_report` deliberately
    stops blocking analyze/validate-outlook (see its docstring) so a corrected bundle
    can still be produced -- but that leaves a seemingly-final review-report.md sitting
    next to files it no longer applies to. The accepted verdict is preserved unchanged
    inside the review history; only this top-level rendering is cleared. Safe to
    call any time: a no-op when there's no completed round or the bundle still matches
    the latest one.
    """
    completed = _review_round_count(run_dir)
    if not completed:
        return
    md_path = RunPaths.at(run_dir).review_report_md
    if md_path.exists() and not _review_bundle_matches_snapshot(run_dir, completed):
        md_path.unlink()


def _block_if_unclosed_review_report(run_dir: Path) -> int | None:
    """Shared guard for cmd_analyze/cmd_validate_outlook: returns an exit code to
    return immediately if blocked, or None to proceed. See _unclosed_review_report."""
    if _unclosed_review_report(run_dir):
        print(
            f"error: {config.REVIEW_REPORT_JSON_FILENAME} exists but was never closed via "
            f"`earnings check-review`. Run check-review FIRST to snapshot that round -- "
            f"editing claims.json/outlook-brief.md now would corrupt the diff-review "
            f"baseline for future rounds. See .agents/skills/review-earnings-run/SKILL.md.",
            file=sys.stderr,
        )
        return 2
    return None


def cmd_review_diff(args: argparse.Namespace) -> int:
    """Build review-diff.json for a round-2+ re-review: what changed in claims.json
    and outlook-brief.md since the last completed review round, plus an
    auto-escalation check. Never touches claims.json/outlook-brief.md -- read-only.
    """
    run_dir = config.run_dir(args.ticker, args.event_id)
    paths = RunPaths.at(run_dir)

    completed_rounds = _review_round_count(run_dir)
    round_number = completed_rounds + 1

    if completed_rounds == 0:
        print("error: no completed review round to diff against. Round 1 must be a full review.", file=sys.stderr)
        return 2
    if round_number > config.REVIEW_MAX_ROUNDS:
        print(
            f"Review round cap reached ({config.REVIEW_MAX_ROUNDS} max, see config.toml [review] "
            f"max_review_rounds). Not attempting round {round_number}. Surface the last "
            f"accepted {paths.review_round(completed_rounds).relative_to(run_dir)}/"
            f"{config.REVIEW_REPORT_JSON_FILENAME} "
            "findings to the user -- do not loop further."
        )
        return 4  # distinct from 2 (schema/fail) -- "stop, don't correct" not "go fix it"

    since_round = completed_rounds
    prior_dir = paths.review_round(since_round)
    prior_claims = json.loads((prior_dir / config.CLAIMS_FILENAME).read_text(encoding="utf-8"))
    prior_report = json.loads((prior_dir / config.REVIEW_REPORT_JSON_FILENAME).read_text(encoding="utf-8"))
    current_claims = json.loads((paths.claims).read_text(encoding="utf-8"))
    current_brief = (paths.outlook_brief).read_text(encoding="utf-8")
    prior_brief_path = prior_dir / config.OUTLOOK_BRIEF_FILENAME
    prior_brief = prior_brief_path.read_text(encoding="utf-8") if prior_brief_path.exists() else None

    prior_by_id = {c["id"]: c for c in prior_claims if c.get("id")}
    current_by_id = {c["id"]: c for c in current_claims if c.get("id")}

    diff_entries: list[dict] = []
    for cid, claim in current_by_id.items():
        if cid not in prior_by_id:
            diff_entries.append({"claim_id": cid, "change": "added", "old": None, "new": claim})
        elif claim != prior_by_id[cid]:
            diff_entries.append({"claim_id": cid, "change": "changed", "old": prior_by_id[cid], "new": claim})
    for cid, claim in prior_by_id.items():
        if cid not in current_by_id:
            diff_entries.append({"claim_id": cid, "change": "removed", "old": claim, "new": None})

    changed_ids = {e["claim_id"] for e in diff_entries}

    # Which brief sections (## N. Title) cite a changed claim id -- ALL sections,
    # informational regardless of escalation.
    affected_sections: set[int] = set()
    section_pattern = re.compile(r"^## (\d+)\.", re.MULTILINE)
    section_starts = [(int(m.group(1)), m.start()) for m in section_pattern.finditer(current_brief)]
    for i, (num, start) in enumerate(section_starts):
        end = section_starts[i + 1][1] if i + 1 < len(section_starts) else len(current_brief)
        body = current_brief[start:end]
        if any(f"[{cid}]" in body for cid in changed_ids):
            affected_sections.add(num)

    # NOTE: input_hash_changes was deliberately dropped from this function and from
    # ReviewDiff. Only claims.json/outlook-brief.md/review-report.json are snapshotted
    # per round (not validation.json), so there is no prior validation.json to diff
    # against. The claims_changed diff above already captures everything meaningful --
    # any transcript/financials/metrics.json change not reflected in claims.json would
    # mean `analyze` was rerun, a much bigger event that should trigger a full
    # `prepare`/`_archive_existing_run` cycle, not a diff-review.

    auto_escalated = False
    reasons: list[str] = []
    if len(diff_entries) > config.REVIEW_DIFF_MAX_CLAIMS_CHANGED:
        auto_escalated = True
        reasons.append(f"{len(diff_entries)} claims changed, over the {config.REVIEW_DIFF_MAX_CLAIMS_CHANGED} threshold")
    for entry in diff_entries:
        if entry["change"] == "changed":
            old, new = entry["old"], entry["new"]
            if old.get("period") != new.get("period") or old.get("values") != new.get("values"):
                auto_escalated = True
                reasons.append(f"{entry['claim_id']}: period or values changed")
    if affected_sections & set(config.REVIEW_DIFF_CONCLUSION_SECTIONS):
        auto_escalated = True
        hit = affected_sections & set(config.REVIEW_DIFF_CONCLUSION_SECTIONS)
        reasons.append(f"conclusion-bearing section(s) {sorted(hit)} cite a changed claim")
    if prior_brief is not None and prior_brief != current_brief:
        auto_escalated = True
        reasons.append(
            "outlook-brief.md text changed since the last round -- review-diff only diffs "
            "claims.json, not brief prose, so a narrative-only correction cannot be safely "
            "assessed from the diff alone"
        )

    review_diff = ReviewDiff(
        generated_at=_now_iso(),
        round_number=round_number,
        since_round=since_round,
        previous_verdict=prior_report.get("verdict", "unknown"),
        previous_summary=prior_report.get("summary", ""),
        previous_finding_count=sum(
            len(prior_report.get(k, []))
            for k in ("source_checks", "claim_findings", "outlook_findings", "process_findings")
        ),
        claims_sha256=sha256_hex((paths.claims).read_bytes()),
        outlook_brief_sha256=sha256_hex((paths.outlook_brief).read_bytes()),
        claims_changed=diff_entries,
        affected_brief_sections=sorted(affected_sections),
        auto_escalated=auto_escalated,
        auto_escalation_reason="; ".join(reasons) if reasons else None,
    )
    diff_path = paths.review_diff
    _write_json(diff_path, review_diff.model_dump())
    # The reviewer has no execution tool, so it cannot hash this file itself (unlike
    # claims_sha256/outlook_brief_sha256, which it already copies from
    # outlook-validation.json) -- write the digest as a sidecar it can just Read.
    (paths.review_diff_sha256).write_text(sha256_hex(diff_path.read_bytes()), encoding="utf-8")

    if auto_escalated:
        print(f"Auto-escalated to full review: {'; '.join(reasons)}")
        return 3
    print(f"Wrote {config.REVIEW_DIFF_FILENAME} for round {round_number} ({len(diff_entries)} claim(s) changed).")
    return 0


def _persist_extractor_lessons(proposed_lessons: list[str]) -> None:
    """Append new, deduplicated one-line lessons to config.EXTRACTOR_LESSONS_PATH.

    Append-only: existing lines are never rewritten or reordered. Dedup is exact-string
    match against lines already in the file, so re-accepting an already-snapshotted
    review round (or two rounds proposing the same lesson) does not create duplicates.
    """
    if not proposed_lessons:
        return
    path = config.EXTRACTOR_LESSONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.is_file():
        existing = {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    new_lines = [f"- {lesson.strip()}" for lesson in proposed_lessons if f"- {lesson.strip()}" not in existing]
    if not new_lines:
        return
    with path.open("a", encoding="utf-8") as f:
        if not existing:
            f.write("# Extractor lessons\n\n")
            f.write(
                "Process guidance only, proposed by the outlook-reviewer and persisted by "
                "`earnings check-review`. Never facts, quotes, or numbers -- see "
                "produce-earnings-signal-card/SKILL.md.\n\n"
            )
        f.write("\n".join(new_lines) + "\n")


def cmd_check_review(args: argparse.Namespace) -> int:
    """Gate the Outlook_Reviewer subagent's review-report.json: it must exist
    (written by the subagent, never by this command -- semantic judgment isn't
    deterministic Python's job, same principle as outlook-brief.md), its own claim-id
    citations must resolve, and the underlying evidence must have already passed
    `analyze`. On success, renders review-report.md deterministically from the
    validated JSON (never trusts agent-authored markdown to match its own JSON).
    """
    run_dir = config.run_dir(args.ticker, args.event_id)
    paths = RunPaths.at(run_dir)

    completed_rounds = _review_round_count(run_dir)
    repeated_accepted_bundle = bool(
        completed_rounds and _review_bundle_matches_snapshot(run_dir, completed_rounds)
    )

    # Round cap FIRST, before any other check, any parsing, or any write. It depends
    # on nothing but _review_round_count(run_dir), so there's no reason to let a
    # capped round get as far as writing review-report.md with a verdict that's
    # about to be refused -- that happened in practice (found live, 2026-08-29):
    # the render+write below used to run before this check, so a refused round
    # still overwrote review-report.md, and because it was never snapshotted, the
    # earlier _unclosed_review_report gate stayed permanently tripped with no
    # command able to clear it (analyze/validate-outlook/check-review/review-diff
    # all refuse). Checking the cap before any write closes both holes at once.
    round_number = completed_rounds if repeated_accepted_bundle else completed_rounds + 1
    if not repeated_accepted_bundle and round_number > config.REVIEW_MAX_ROUNDS:
        print(
            f"error: review round cap reached ({config.REVIEW_MAX_ROUNDS} max, see config.toml "
            f"[review] max_review_rounds). Refusing to accept round {round_number}. Surface the "
            f"last accepted {paths.review_round(completed_rounds).relative_to(run_dir)}/"
            f"{config.REVIEW_REPORT_JSON_FILENAME} "
            "findings to the user -- do not loop further.",
            file=sys.stderr,
        )
        return 4

    validation_path = paths.validation
    outlook_path = paths.outlook_brief
    claims_path = paths.claims
    report_path = paths.review_report_json

    validation = _load_validated_json(validation_path, ValidationResult)
    if validation is None:
        print(f"error: {validation_path} not found or invalid. Run `earnings analyze` first.", file=sys.stderr)
        return 2
    if not validation.ok:
        print("Review blocked: underlying claims have not passed validation.")
        return 2
    if not _validation_inputs_current(run_dir, validation):
        print("Review blocked: an analyze input changed or disappeared. Re-run `earnings analyze`.")
        return 2

    if not outlook_path.exists():
        print(f"error: {outlook_path} not found. Run `earnings validate-outlook` first.", file=sys.stderr)
        return 2

    # Gate on validate-outlook having actually passed for the CURRENT brief. Previously
    # this command only checked that outlook-brief.md existed, so the whole
    # validate-outlook stage could be skipped (or its brief edited afterwards) and review
    # would still proceed. Require a passing outlook-validation.json bound to these bytes.
    outlook_validation_path = paths.outlook_validation
    if not outlook_validation_path.exists():
        print(f"error: {outlook_validation_path} not found. Run `earnings validate-outlook` first.", file=sys.stderr)
        return 2
    outlook_validation = _load_validated_json(outlook_validation_path, OutlookValidation)
    if outlook_validation is None:
        print(f"error: {outlook_validation_path} not found or invalid. Run `earnings validate-outlook` first.", file=sys.stderr)
        return 2
    if not outlook_validation.ok:
        print("Review blocked: outlook brief has not passed `earnings validate-outlook`.")
        return 2
    if not _hash_gate_ok(outlook_validation.outlook_brief_sha256, outlook_path):
        print(
            f"Review blocked: {config.OUTLOOK_BRIEF_FILENAME} changed since `validate-outlook` "
            "(or no hash was recorded for it). Re-run it."
        )
        return 2
    # NEW: claims.json's hash was recorded at validate-outlook time but never checked
    # here -- claims.json could be edited after validate-outlook passed, leaving the
    # brief untouched, and this gate would previously miss it entirely.
    if not _hash_gate_ok(outlook_validation.claims_sha256, claims_path):
        print(
            f"Review blocked: {config.CLAIMS_FILENAME} changed since `validate-outlook` "
            "(or no hash was recorded for it). Re-run `earnings validate-outlook`."
        )
        return 2

    if not report_path.exists():
        print(
            f"error: {report_path} not found. Dispatch the outlook-reviewer subagent first "
            "(see .agents/skills/review-earnings-run).",
            file=sys.stderr,
        )
        return 2

    try:
        report = ReviewReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        print(f"Review validation FAILED: could not parse {config.REVIEW_REPORT_JSON_FILENAME}: {exc}")
        return 2

    # Bind the verdict to the exact claims and brief bytes that were reviewed.
    if not _hash_gate_ok(report.claims_sha256, claims_path):
        print(f"Review blocked: report is not bound to the current {config.CLAIMS_FILENAME}.")
        return 2
    if not _hash_gate_ok(report.outlook_brief_sha256, outlook_path):
        print(f"Review blocked: report is not bound to the current {config.OUTLOOK_BRIEF_FILENAME}.")
        return 2

    if round_number == 1:
        if report.review_mode != "full" or report.review_diff_sha256 is not None:
            print("Review blocked: round 1 requires review_mode='full' and no review_diff_sha256.")
            return 2
    else:
        # Every later round must pass through the deterministic diff command, even
        # when that command decides the semantic work must be a full review.
        diff_path = paths.review_diff
        review_diff = _load_validated_json(diff_path, ReviewDiff)
        if review_diff is None:
            print(f"Review blocked: run `earnings review-diff` before round {round_number}.")
            return 2
        if review_diff.round_number != round_number or review_diff.since_round != round_number - 1:
            print(f"Review blocked: {config.REVIEW_DIFF_FILENAME} belongs to a different review round.")
            return 2
        if not _hash_gate_ok(review_diff.claims_sha256, claims_path) or not _hash_gate_ok(
            review_diff.outlook_brief_sha256, outlook_path
        ):
            print(f"Review blocked: {config.REVIEW_DIFF_FILENAME} is stale. Re-run `earnings review-diff`.")
            return 2
        if not _hash_gate_ok(report.review_diff_sha256, diff_path):
            print(f"Review blocked: report is not bound to the current {config.REVIEW_DIFF_FILENAME}.")
            return 2
        if review_diff.auto_escalated and report.review_mode != "full":
            print("Review blocked: review-diff auto-escalated this round to a full review.")
            return 2
        if report.escalate_full_review and report.review_mode != "diff":
            print("Review blocked: only a diff review may request escalation to a full review.")
            return 2

    raw_claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claim_ids = {c.get("id") for c in raw_claims if c.get("id")}
    issues = validate_review_report(report, claim_ids)
    if issues:
        print(f"Review validation FAILED: {len(issues)} issue(s).")
        for issue in issues:
            print(f"  {issue.check}: {issue.message}")
        return 2

    # Report is now structurally accepted (any verdict) -- persist any new proposed
    # lessons regardless of pass/fail, same as the checks above already ran regardless
    # of verdict. Dedup means re-accepting an already-snapshotted round is harmless.
    _persist_extractor_lessons(report.proposed_lessons)

    # audit-record.json is written once, only for a terminal (non-fail,
    # non-escalated) verdict -- a fail or an escalation means the run isn't done.
    # Re-writing on a repeated (already-accepted) confirmation is harmless: it's
    # a pure derivation from files that haven't changed, so the content is
    # identical -- see _build_audit_record.
    if repeated_accepted_bundle:
        print(f"Review round {completed_rounds} was already accepted; no new snapshot written.")
        if not report.escalate_full_review and report.verdict != "fail":
            _write_json(
                paths.audit_record,
                _build_audit_record(args.ticker, args.event_id, run_dir, round_number, report),
            )
        if report.escalate_full_review:
            return 3
        if report.verdict == "fail":
            return 2
        if report.verdict == "pass_with_warnings":
            return 1
        return 0

    md = _render_review_report(args.ticker, args.event_id, report)
    (paths.review_report_md).write_text(md, encoding="utf-8")
    print(f"Review verdict: {report.verdict}. Wrote {config.REVIEW_REPORT_MD_FILENAME}.")

    _snapshot_review_round(run_dir, round_number)

    if not report.escalate_full_review and report.verdict != "fail":
        _write_json(
            paths.audit_record,
            _build_audit_record(args.ticker, args.event_id, run_dir, round_number, report),
        )
        print(f"Wrote {config.AUDIT_RECORD_FILENAME} (run accepted).")

    if report.escalate_full_review:
        print(f"Reviewer escalated: full review required (round {round_number} diff was insufficient).")
        return 3

    if report.verdict == "fail":
        return 2
    if report.verdict == "pass_with_warnings":
        return 1
    return 0
