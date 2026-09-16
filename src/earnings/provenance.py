from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import config
from .models import Manifest, PriceLookupDecision, ValidationIssue, ValidationResult
from .paths import RunPaths
from .process import sha256_hex
from .runio import _now_iso, _write_json


def _input_hashes(run_dir: Path) -> dict[str, str]:
    """SHA-256 of each validation input file that exists, keyed by filename. Binds a
    validation record to the exact bytes it was computed from so staleness is detectable
    downstream (see ValidationResult.input_hashes / _stale).

    Archived sources are deliberately NOT listed individually. manifest.json is the
    provenance index and already carries a sha256 per source; pinning the manifest's own
    hash here makes that a verifiable chain (see _validation_inputs_current, which walks
    it via _manifest_source_errors). Restating every source made this a second, redundant
    provenance index: on a 216-source run it was 96% of validation.json's bytes, copied
    again into every attempt receipt, and read by the reviewer subagent each round."""
    paths = RunPaths.at(run_dir)
    candidates = {
        config.CLAIMS_FILENAME: paths.claims,
        config.TRANSCRIPT_FILENAME: paths.transcript,
        config.FINANCIALS_FILENAME: paths.financials,
        config.METRICS_FILENAME: paths.metrics,
        config.MANIFEST_FILENAME: paths.manifest,
        config.PRICE_LOOKUP_LOG_FILENAME: paths.price_lookup_log,
        f"{config.EVIDENCE_SUBDIR}/{config.WEB_EVIDENCE_FILENAME}": (
            paths.web_evidence
        ),
    }
    return {name: sha256_hex(path.read_bytes()) for name, path in candidates.items() if path.exists()}


def _stale(recorded_hash: str | None, path: Path) -> bool:
    """True if `path`'s current bytes don't match `recorded_hash`. A missing recorded
    hash (older run written before hashes existed) or missing file is treated as NOT
    stale -- we only fail on a positive mismatch, never on absence of evidence."""
    if not recorded_hash or not path.exists():
        return False
    return sha256_hex(path.read_bytes()) != recorded_hash


def _load_validated_json(path: Path, model: type[BaseModel]) -> BaseModel | None:
    """Schema-validate a Python-owned gate file (ValidationResult/OutlookValidation)
    instead of trusting a raw dict via json.loads()+.get() -- a hand-written or
    malformed file now fails schema validation instead of silently passing whatever
    truthy 'ok' field it happens to have. Returns None if the file doesn't exist or
    fails schema validation; caller decides how to report that."""
    if not path.exists():
        return None
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError:
        return None


def _hash_gate_ok(recorded_hash: str | None, path: Path) -> bool:
    """Strict hash-match gate for stage-to-stage checks: the recorded hash must be
    PRESENT (unlike _stale's own permissive default, which answers the different
    question "did the file change since a hash WAS recorded") and must match the
    file's current bytes. A missing hash now fails the gate, not passes it -- this
    closes the hole where a hand-written validation.json with no input_hashes
    sailed through."""
    return bool(recorded_hash) and path.is_file() and not _stale(recorded_hash, path)


def _manifest_source_errors(run_dir: Path, manifest: Manifest) -> list[str]:
    """Verify that every provenance record still names the bytes it claims to."""
    errors: list[str] = []
    root = run_dir.resolve()
    for index, source in enumerate(manifest.sources):
        path = (run_dir / source.path).resolve()
        label = f"manifest source[{index}] {source.path!r}"
        if not source.path or not path.is_relative_to(root):
            errors.append(f"{label} is empty, absolute, or escapes the run directory")
            continue
        if not path.is_file():
            errors.append(f"{label} does not exist")
            continue
        content = path.read_bytes()
        if source.byte_length != len(content):
            errors.append(f"{label} byte_length does not match the file")
        if not re.fullmatch(r"[0-9a-f]{64}", source.sha256) or source.sha256 != sha256_hex(content):
            errors.append(f"{label} sha256 does not match the file")
    return errors


def _validation_inputs_current(run_dir: Path, validation: ValidationResult) -> bool:
    """Fail closed unless every hashed analyze input still exists and matches."""
    paths = RunPaths.at(run_dir)
    locations = {
        config.CLAIMS_FILENAME: paths.claims,
        config.TRANSCRIPT_FILENAME: paths.transcript,
        config.FINANCIALS_FILENAME: paths.financials,
        config.METRICS_FILENAME: paths.metrics,
        config.MANIFEST_FILENAME: paths.manifest,
        config.PRICE_LOOKUP_LOG_FILENAME: paths.price_lookup_log,
        f"{config.EVIDENCE_SUBDIR}/{config.WEB_EVIDENCE_FILENAME}": (
            paths.web_evidence
        ),
    }
    required = {config.CLAIMS_FILENAME, config.TRANSCRIPT_FILENAME, config.MANIFEST_FILENAME}
    manifest = _load_validated_json(paths.manifest, Manifest)
    if manifest is None:
        return False
    # Walk the provenance chain rather than re-listing it. validation.json pins
    # manifest.json's own hash (checked in the _hash_gate_ok sweep below) and the
    # manifest pins every archived source, so verifying the sources against the manifest
    # here gives validate-outlook and check-review the same tamper detection they had
    # when validation.json restated all N source hashes. Deleting the restatement WITHOUT
    # this call would silently stop those two gates from noticing an edited evidence file.
    if _manifest_source_errors(run_dir, manifest):
        return False
    for optional in (config.FINANCIALS_FILENAME, config.METRICS_FILENAME):
        if locations[optional].is_file():
            required.add(optional)
    web_index = f"{config.EVIDENCE_SUBDIR}/{config.WEB_EVIDENCE_FILENAME}"
    if locations[web_index].is_file():
        required.add(web_index)
    if validation.tool_decisions is None:
        return False
    if _price_decision_issues(
        run_dir, manifest.ticker, validation.tool_decisions.price_lookup
    ):
        return False
    if locations[config.PRICE_LOOKUP_LOG_FILENAME].is_file():
        required.add(config.PRICE_LOOKUP_LOG_FILENAME)
    if not required.issubset(validation.input_hashes):
        return False
    # `source:` keys are no longer written (see _input_hashes), but a validation.json
    # from before that change still carries them -- keep resolving the prefix so an
    # older run is checked exactly as strictly as it was when it was produced.
    return all(
        _hash_gate_ok(
            recorded_hash,
            locations.get(name, run_dir / name.removeprefix("source:")),
        )
        for name, recorded_hash in validation.input_hashes.items()
    )


def _price_decision_issues(
    run_dir: Path, ticker: str, decision: PriceLookupDecision
) -> list[ValidationIssue]:
    """Check the declared price-tool decision against its run-local receipts."""
    issues: list[ValidationIssue] = []
    if not decision.reason.strip():
        issues.append(
            ValidationIssue(
                claim_index=-1,
                check="price_decision",
                message="price lookup decision requires a non-empty reason",
            )
        )

    log_path = RunPaths.at(run_dir).price_lookup_log
    records: list[dict] = []
    if log_path.is_file():
        for line_number, line in enumerate(
            log_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                issues.append(
                    ValidationIssue(
                        claim_index=-1,
                        check="price_decision",
                        message=f"{config.PRICE_LOOKUP_LOG_FILENAME} line {line_number} is invalid JSON",
                    )
                )
                continue
            records.append(record)
            if record.get("ticker") != ticker.upper():
                issues.append(
                    ValidationIssue(
                        claim_index=-1,
                        check="price_decision",
                        message=f"price lookup line {line_number} belongs to a different ticker",
                    )
                )

    successful = any(record.get("status") == "ok" for record in records)
    if decision.decision == "used" and not successful:
        issues.append(
            ValidationIssue(
                claim_index=-1,
                check="price_decision",
                message="decision is 'used' but no successful run-local price lookup exists",
            )
        )
    elif decision.decision == "attempted_failed" and (not records or successful):
        issues.append(
            ValidationIssue(
                claim_index=-1,
                check="price_decision",
                message="decision is 'attempted_failed' but receipts are absent or include a success",
            )
        )
    elif decision.decision == "not_used" and records:
        issues.append(
            ValidationIssue(
                claim_index=-1,
                check="price_decision",
                message="decision is 'not_used' but run-local price lookup receipts exist",
            )
        )
    return issues


def _write_validation(run_dir: Path, result: ValidationResult) -> None:
    """Stamp result.validated_at with the real clock at write time (validate_claims()
    itself stays pure/timestamp-free, see ValidationResult.validated_at), bind it to the
    input bytes via input_hashes, and write validation.json. Single call site so every
    cmd_analyze exit path is stamped and hash-bound alike.
    """
    result.validated_at = _now_iso()
    result.input_hashes = _input_hashes(run_dir)
    _write_json(RunPaths.at(run_dir).validation, result.model_dump())
