from __future__ import annotations

import argparse
import json
import sys

from . import config
from .models import Claim, OutlookValidation, ValidationResult
from .paths import RunPaths
from .process import sha256_hex
from .provenance import _load_validated_json, _validation_inputs_current
from .review import _block_if_unclosed_review_report, _clear_stale_review_report_md
from .runio import _now_iso, _write_json
from .validate import (
    check_outlook_brief_citations,
    check_outlook_brief_dollar_escaping,
    check_outlook_brief_numbers,
)
from .validation_history import _OutlookValidationAttempt


def cmd_validate_outlook(args: argparse.Namespace) -> int:
    """Gate outlook-brief.md (agent-authored Stage 2 synthesis, not Python-generated --
    scenarios/base-case judgment aren't deterministic) on two things: the underlying
    claims already passed `analyze`, and every claim id the brief cites is real.
    """
    run_dir = config.run_dir(args.ticker, args.event_id)
    paths = RunPaths.at(run_dir)
    input_hashes = {}
    for filename in (config.CLAIMS_FILENAME, config.OUTLOOK_BRIEF_FILENAME):
        path = RunPaths.at(run_dir).resolve(filename)
        if path.is_file():
            input_hashes[filename] = sha256_hex(path.read_bytes())
    attempt = _OutlookValidationAttempt.start(run_dir, input_hashes)
    blocked = _block_if_unclosed_review_report(run_dir)
    if blocked is not None:
        attempt.finish("blocked", blocked)
        return blocked
    _clear_stale_review_report_md(run_dir)
    validation_path = paths.validation
    outlook_path = paths.outlook_brief
    claims_path = paths.claims

    validation = _load_validated_json(validation_path, ValidationResult)
    if validation is None:
        print(f"error: {validation_path} not found or invalid. Run `earnings analyze` first.", file=sys.stderr)
        attempt.finish("blocked", 2)
        return 2
    if not validation.ok:
        print("Outlook brief blocked: underlying claims have not passed validation.")
        attempt.finish("blocked", 1)
        return 1

    # Recheck every input that analyze bound into validation.json. A later edit to
    # transcript, manifest, archived source, financials, metrics, or claims cannot
    # inherit the prior passing result.
    if not _validation_inputs_current(run_dir, validation):
        print(
            "Outlook brief blocked: an analyze input changed, disappeared, or lacks a required hash. "
            "Re-run `earnings analyze`."
        )
        attempt.finish("blocked", 1)
        return 1

    if not outlook_path.exists():
        print(f"error: {outlook_path} not found. Write {config.OUTLOOK_BRIEF_FILENAME} first (see skill).", file=sys.stderr)
        attempt.finish("blocked", 2)
        return 2

    raw_claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claim_ids = {c.get("id") for c in raw_claims if c.get("id")}
    claims_by_id = {c["id"]: Claim.model_validate(c) for c in raw_claims if c.get("id")}
    outlook_text = outlook_path.read_text(encoding="utf-8")
    errors = check_outlook_brief_citations(outlook_text, claim_ids)
    errors += check_outlook_brief_dollar_escaping(outlook_text)
    errors += check_outlook_brief_numbers(outlook_text, claims_by_id)
    # Bind this record to the exact brief + claims bytes so `check-review` can prove the
    # brief it reviews is still the one that passed here.
    outlook_validation = OutlookValidation(
        ok=not errors,
        validated_at=_now_iso(),
        errors=errors,
        outlook_brief_sha256=sha256_hex(outlook_path.read_bytes()),
        claims_sha256=sha256_hex(claims_path.read_bytes()),
    )
    _write_json(paths.outlook_validation, outlook_validation.model_dump())
    if errors:
        attempt.finish(
            "failed", 1, outlook_validation, validation_path=paths.outlook_validation
        )
        print(f"Outlook brief validation FAILED: {len(errors)} issue(s).")
        for error in errors:
            print(f"  {error}")
        return 1

    attempt.finish(
        "passed", 0, outlook_validation, validation_path=paths.outlook_validation
    )
    print(f"Outlook brief validated: all cited claim ids resolve. ({config.OUTLOOK_BRIEF_FILENAME})")
    return 0
