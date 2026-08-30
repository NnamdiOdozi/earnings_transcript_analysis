"""argparse CLI: `earnings prepare` and `earnings analyze`.

`prepare` builds a source pack (raw archive, normalized transcript, manifest,
financials evidence, web-search official-source evidence) for one ticker/event.
`analyze` reads an existing claims.json from that pack, validates it, and -- only
if validation passes -- writes signal-card.md. SEC and web-search lookups are both
**on by default** (config.toml [research] sec_enabled/web_search_enabled) -- set
either to false to disable it. Web search provider is config.toml [research]
provider ("exa" default, or "tavily"). Tests monkeypatch these flags to false so
they never touch the network.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from . import config
from .ingest import load_transcript
from .models import (
    Claim,
    Manifest,
    Metric,
    OutlookValidation,
    ReviewDiff,
    ReviewReport,
    SourceRecord,
    TemporalStatus,
    ValidationIssue,
    ValidationResult,
    WebEvidence,
)
from .process import sanitize, scan_for_injection, segment_transcript, sha256_hex
from .validate import (
    check_outlook_brief_citations,
    check_outlook_brief_dollar_escaping,
    validate_claims,
    validate_metrics,
    validate_review_report,
)
from .validation_history import ValidationAttempt


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _append_processing_log(ticker: str, event_id: str, loaded, raw_bytes: bytes, run_dir: Path) -> None:
    """Append one line to logs/processing_log.jsonl -- a cross-run audit trail of
    every transcript source (URL or local path) `prepare` has ever ingested and
    when, independent of any single run's manifest.json (which only covers that one
    run and gets moved under _archive/ on a rerun, whereas this log accumulates).
    """
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now_iso(),
        "ticker": ticker.upper(),
        "event_id": event_id,
        "source": loaded.origin,
        "source_type": "url" if loaded.origin.startswith(("http://", "https://")) else "file",
        "sha256": sha256_hex(raw_bytes),
        "byte_length": len(raw_bytes),
        "run_dir": str(run_dir),
    }
    with (config.LOGS_DIR / config.PROCESSING_LOG_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _input_hashes(run_dir: Path) -> dict[str, str]:
    """SHA-256 of each validation input file that exists, keyed by filename. Binds a
    validation record to the exact bytes it was computed from so staleness is detectable
    downstream (see ValidationResult.input_hashes / _stale)."""
    candidates = {
        config.CLAIMS_FILENAME: run_dir / config.CLAIMS_FILENAME,
        config.TRANSCRIPT_FILENAME: run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME,
        config.FINANCIALS_FILENAME: run_dir / config.EVIDENCE_SUBDIR / config.FINANCIALS_FILENAME,
        config.METRICS_FILENAME: run_dir / config.METRICS_FILENAME,
        config.MANIFEST_FILENAME: run_dir / config.MANIFEST_FILENAME,
        f"{config.EVIDENCE_SUBDIR}/{config.WEB_EVIDENCE_FILENAME}": (
            run_dir / config.EVIDENCE_SUBDIR / config.WEB_EVIDENCE_FILENAME
        ),
    }
    manifest_path = run_dir / config.MANIFEST_FILENAME
    if manifest_path.is_file():
        try:
            manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            root = run_dir.resolve()
            for source in manifest.sources:
                source_path = (run_dir / source.path).resolve()
                if source.path and source_path.is_relative_to(root):
                    candidates[f"source:{source.path}"] = source_path
        except ValidationError:
            pass
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
    locations = {
        config.CLAIMS_FILENAME: run_dir / config.CLAIMS_FILENAME,
        config.TRANSCRIPT_FILENAME: run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME,
        config.FINANCIALS_FILENAME: run_dir / config.EVIDENCE_SUBDIR / config.FINANCIALS_FILENAME,
        config.METRICS_FILENAME: run_dir / config.METRICS_FILENAME,
        config.MANIFEST_FILENAME: run_dir / config.MANIFEST_FILENAME,
        f"{config.EVIDENCE_SUBDIR}/{config.WEB_EVIDENCE_FILENAME}": (
            run_dir / config.EVIDENCE_SUBDIR / config.WEB_EVIDENCE_FILENAME
        ),
    }
    required = {config.CLAIMS_FILENAME, config.TRANSCRIPT_FILENAME, config.MANIFEST_FILENAME}
    manifest = _load_validated_json(run_dir / config.MANIFEST_FILENAME, Manifest)
    if manifest is None:
        return False
    required.update(f"source:{source.path}" for source in manifest.sources)
    for optional in (config.FINANCIALS_FILENAME, config.METRICS_FILENAME):
        if locations[optional].is_file():
            required.add(optional)
    web_index = f"{config.EVIDENCE_SUBDIR}/{config.WEB_EVIDENCE_FILENAME}"
    if locations[web_index].is_file():
        required.add(web_index)
    if not required.issubset(validation.input_hashes):
        return False
    return all(
        _hash_gate_ok(
            recorded_hash,
            locations.get(name, run_dir / name.removeprefix("source:")),
        )
        for name, recorded_hash in validation.input_hashes.items()
    )


def _write_validation(run_dir: Path, result: ValidationResult) -> None:
    """Stamp result.validated_at with the real clock at write time (validate_claims()
    itself stays pure/timestamp-free, see ValidationResult.validated_at), bind it to the
    input bytes via input_hashes, and write validation.json. Single call site so every
    cmd_analyze exit path is stamped and hash-bound alike.
    """
    result.validated_at = _now_iso()
    result.input_hashes = _input_hashes(run_dir)
    _write_json(run_dir / config.VALIDATION_FILENAME, result.model_dump())


def _archive_existing_run(run_dir: Path) -> None:
    """If run_dir already holds a manifest.json (a prior `prepare` ran here), move its
    entire contents under run_dir/_archive/<timestamp>/ before writing fresh output --
    a rerun for the same ticker/event must never silently overwrite prior evidence.
    """
    if not (run_dir / config.MANIFEST_FILENAME).exists():
        return
    stamp = _now_iso().replace(":", "").rstrip("Z")
    dest = run_dir / config.ARCHIVE_SUBDIR / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for item in run_dir.iterdir():
        if item.name == config.ARCHIVE_SUBDIR:
            continue
        shutil.move(str(item), str(dest / item.name))


def _review_round_count(run_dir: Path) -> int:
    """How many review rounds have completed (each a snapshot under _review_history/round-N/)."""
    history_dir = run_dir / config.REVIEW_HISTORY_SUBDIR
    if not history_dir.exists():
        return 0
    return len([d for d in history_dir.iterdir() if d.is_dir() and d.name.startswith("round-")])


def _review_bundle_matches_snapshot(run_dir: Path, round_number: int) -> bool:
    """Whether claims, brief, and report still equal one accepted round exactly."""
    prior_dir = run_dir / config.REVIEW_HISTORY_SUBDIR / f"round-{round_number}"
    filenames = (config.CLAIMS_FILENAME, config.OUTLOOK_BRIEF_FILENAME, config.REVIEW_REPORT_JSON_FILENAME)
    return all(
        (prior_dir / filename).is_file()
        and (run_dir / filename).is_file()
        and (prior_dir / filename).read_bytes() == (run_dir / filename).read_bytes()
        for filename in filenames
    )


def _snapshot_review_round(run_dir: Path, round_number: int) -> None:
    """After a structurally-valid review-report.json is accepted (any verdict, or an
    escalation), snapshot claims.json/outlook-brief.md/review-report.json under
    _review_history/round-<N>/ so the NEXT round's `review-diff` can diff against a
    known-good prior state. Called once per completed round, from cmd_check_review.

    Idempotent only when the complete reviewed bundle is byte-identical to the
    latest snapshot. Comparing the report alone allowed changed claims or brief
    bytes to inherit an old verdict and suppress the next snapshot.
    """
    if round_number > 1 and _review_bundle_matches_snapshot(run_dir, round_number - 1):
        return
    dest = run_dir / config.REVIEW_HISTORY_SUBDIR / f"round-{round_number}"
    dest.mkdir(parents=True, exist_ok=True)
    for filename in (config.CLAIMS_FILENAME, config.OUTLOOK_BRIEF_FILENAME, config.REVIEW_REPORT_JSON_FILENAME):
        src = run_dir / filename
        if src.exists():
            shutil.copy2(src, dest / filename)


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
    report_path = run_dir / config.REVIEW_REPORT_JSON_FILENAME
    if not report_path.exists():
        return False
    completed = _review_round_count(run_dir)
    # Once the configured cap is exhausted, a stray new report cannot be accepted.
    # It must not lock unrelated inspection/correction commands forever either.
    if completed >= config.REVIEW_MAX_ROUNDS:
        return False
    if completed == 0:
        return True  # a report exists but round 1 was never closed
    latest_snapshot = run_dir / config.REVIEW_HISTORY_SUBDIR / f"round-{completed}" / config.REVIEW_REPORT_JSON_FILENAME
    if not latest_snapshot.exists():
        return True
    return report_path.read_bytes() != latest_snapshot.read_bytes()


def _clear_stale_review_report_md(run_dir: Path) -> None:
    """Delete the top-level review-report.md if it no longer describes the current
    bundle. Once the round cap is exhausted, `_unclosed_review_report` deliberately
    stops blocking analyze/validate-outlook (see its docstring) so a corrected bundle
    can still be produced -- but that leaves a seemingly-final review-report.md sitting
    next to files it no longer applies to. The accepted verdict is preserved unchanged
    under _review_history/round-N/; only this top-level rendering is cleared. Safe to
    call any time: a no-op when there's no completed round or the bundle still matches
    the latest one.
    """
    completed = _review_round_count(run_dir)
    if not completed:
        return
    md_path = run_dir / config.REVIEW_REPORT_MD_FILENAME
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

    completed_rounds = _review_round_count(run_dir)
    round_number = completed_rounds + 1

    if completed_rounds == 0:
        print("error: no completed review round to diff against. Round 1 must be a full review.", file=sys.stderr)
        return 2
    if round_number > config.REVIEW_MAX_ROUNDS:
        print(
            f"Review round cap reached ({config.REVIEW_MAX_ROUNDS} max, see config.toml [review] "
            f"max_review_rounds). Not attempting round {round_number}. Surface the last "
            f"accepted _review_history/round-{completed_rounds}/{config.REVIEW_REPORT_JSON_FILENAME} "
            "findings to the user -- do not loop further."
        )
        return 4  # distinct from 2 (schema/fail) -- "stop, don't correct" not "go fix it"

    since_round = completed_rounds
    prior_dir = run_dir / config.REVIEW_HISTORY_SUBDIR / f"round-{since_round}"
    prior_claims = json.loads((prior_dir / config.CLAIMS_FILENAME).read_text(encoding="utf-8"))
    prior_report = json.loads((prior_dir / config.REVIEW_REPORT_JSON_FILENAME).read_text(encoding="utf-8"))
    current_claims = json.loads((run_dir / config.CLAIMS_FILENAME).read_text(encoding="utf-8"))
    current_brief = (run_dir / config.OUTLOOK_BRIEF_FILENAME).read_text(encoding="utf-8")
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
        claims_sha256=sha256_hex((run_dir / config.CLAIMS_FILENAME).read_bytes()),
        outlook_brief_sha256=sha256_hex((run_dir / config.OUTLOOK_BRIEF_FILENAME).read_bytes()),
        claims_changed=diff_entries,
        affected_brief_sections=sorted(affected_sections),
        auto_escalated=auto_escalated,
        auto_escalation_reason="; ".join(reasons) if reasons else None,
    )
    _write_json(run_dir / config.REVIEW_DIFF_FILENAME, review_diff.model_dump())

    if auto_escalated:
        print(f"Auto-escalated to full review: {'; '.join(reasons)}")
        return 3
    print(f"Wrote {config.REVIEW_DIFF_FILENAME} for round {round_number} ({len(diff_entries)} claim(s) changed).")
    return 0


def _parse_event_cutoff(event_date: str | None):
    """Parse a --event-date string into a datetime.date, or None if it isn't a real
    calendar date (event_id like "2026-q2" is the common non-date default). Shared by
    prepare and discover-peers so both apply the causality guard identically."""
    if not event_date:
        return None
    try:
        return date.fromisoformat(event_date[:10])
    except (ValueError, TypeError):
        return None


def _filter_post_event(hits: list[dict], event_cutoff) -> tuple[list[dict], int]:
    """Drop hits whose published_date is AFTER event_cutoff -- a source that appeared
    after the call could not have informed it, so it must never become citable evidence.
    Hits with no parseable published_date are KEPT, not dropped (undated post-event
    slippage is a consciously-accepted residual risk -- see README known limitations).
    Returns (kept_hits, excluded_count). With no cutoff, keeps everything."""
    kept: list[dict] = []
    excluded = 0
    for hit in hits:
        temporal_status = _classify_temporal_status(hit.get("published_date"), event_cutoff)
        hit["_temporal_status"] = temporal_status
        if temporal_status == "post_event":
            excluded += 1
            continue
        kept.append(hit)
    return kept, excluded


def _classify_temporal_status(published_date: str | None, event_cutoff) -> TemporalStatus:
    """Classify provider publication metadata without interpreting page content."""
    if not event_cutoff:
        return "unchecked"
    if not published_date:
        return "undated"
    try:
        parsed_date = date.fromisoformat(published_date[:10])
    except (ValueError, TypeError):
        return "undated"
    return "post_event" if parsed_date > event_cutoff else "pre_event"


def _select_round_robin(hits: list[dict], max_extracted: int) -> list[dict]:
    """Pick up to max_extracted unique-URL hits, INTERLEAVED across their bucket so no
    single bucket fills every extraction slot. This fixes the live bug where consensus
    queries (run first, more hits) crowded out every peer result -- 0 of 10 extracted
    pages were peer-related -- AND the narrower one where one peer crowded out the other
    three. The bucket is `_select_key` (consensus is one bucket; each peer is its own,
    peer:<name>), falling back to the coarse `_class` when no finer key is set (e.g.
    discover-peers, where everything is one class). Within a bucket the provider's own
    relevance order is kept (score desc; unscored providers like Exa "auto" fall back to
    result order via a stable sort). URLs are deduped globally across buckets."""
    ordered = sorted(
        hits, key=lambda h: h.get("score") if h.get("score") is not None else -1, reverse=True
    )
    by_class: dict[str, list[dict]] = {}
    for hit in ordered:
        by_class.setdefault(hit.get("_select_key") or hit.get("_class", ""), []).append(hit)

    queues = list(by_class.values())
    idxs = [0] * len(queues)
    seen_urls: set[str] = set()
    selected: list[dict] = []
    while len(selected) < max_extracted:
        progressed = False
        for i, queue in enumerate(queues):
            if idxs[i] >= len(queue):
                continue
            hit = queue[idxs[i]]
            idxs[i] += 1
            progressed = True
            url = hit.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            selected.append(hit)
            if len(selected) >= max_extracted:
                break
        if not progressed:  # every class queue exhausted
            break
    return selected


def cmd_discover_peers(args: argparse.Namespace) -> int:
    """Discover the company's analyst-recognised peer group by web search, so the agent
    can pick ~4 comparables to pass to `prepare --peers`. The SEARCH is deterministic
    and archived (hashed) here; the SELECTION of which 4 are the agreed peers is the
    agent's judgment, made by reading the extracted candidate pages. Output lives under
    runs/<TICKER>/peer-discovery/ -- company-level, not per-event (a company's peers
    don't change between quarters), so `prepare`'s per-event archiving never touches it.
    """
    if not config.RESEARCH_WEB_SEARCH_ENABLED:
        print("Web search is disabled (config.toml [research] web_search_enabled); cannot discover peers.")
        return 1
    from .sources import build_peer_group_queries, web_extract, web_search

    provider = config.RESEARCH_WEB_SEARCH_PROVIDER
    company_name = args.company_name or args.ticker
    out_dir = config.RUNS_DIR / args.ticker.upper() / "peer-discovery"
    # Archive any prior discovery FIRST. Without this a shorter rerun (fewer candidates)
    # leaves stale candidate-NN.md from the old run on disk, and the agent globs
    # candidate-*.md -- so it could read a superseded candidate as a current one.
    _archive_existing_run(out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    max_results = config.EXA_NUM_RESULTS if provider == "exa" else config.TAVILY_MAX_RESULTS
    max_extracted = config.EXA_MAX_EXTRACTED_SOURCES if provider == "exa" else config.TAVILY_MAX_EXTRACTED_SOURCES

    # Peer-group membership is not event-relative, but the user still wants an optional
    # cutoff as a safety net (a peer list published after the event can't have informed
    # the call). --event-date is optional here; when given, dated post-event hits are
    # dropped from extraction and undated ones pass through, same as prepare.
    event_cutoff = _parse_event_cutoff(getattr(args, "event_date", None))
    provider_end_date = event_cutoff.isoformat() if event_cutoff else None

    queries = build_peer_group_queries(company_name, args.ticker, config.RESEARCH_PEER_GROUP_QUERIES)
    sources: list[SourceRecord] = []
    all_hits: list[dict] = []
    for qi, query in enumerate(queries, start=1):
        hits = web_search(query, provider=provider, max_results=max_results, end_date=provider_end_date)
        for hit in hits:
            hit["_class"] = "peer_group"  # tag for the shared selection helper below
            hit["_temporal_status"] = _classify_temporal_status(hit.get("published_date"), event_cutoff)
        all_hits.extend(hits)
        for hi, hit in enumerate(hits, start=1):
            retrieved_at = _now_iso()
            hit_bytes = json.dumps(
                {**hit, "_provider": provider, "_query": query, "_class": "peer_group", "_retrieved_at": retrieved_at},
                indent=2,
            ).encode("utf-8")
            hit_path = raw_dir / f"query-{qi:02d}-hit-{hi:02d}.json"
            hit_path.write_bytes(hit_bytes)
            sources.append(
                SourceRecord(
                    path=str(hit_path.relative_to(out_dir)),
                    origin=hit.get("url", query),
                    retrieved_at=retrieved_at,
                    content_type="application/json",
                    sha256=sha256_hex(hit_bytes),
                    byte_length=len(hit_bytes),
                )
            )

    # Apply the causality guard (drops dated post-event hits, keeps undated) then extract
    # the top few unique pages so the agent reads the actual peer lists, not snippets.
    causal_hits, excluded_future = _filter_post_event(all_hits, event_cutoff)
    selected = _select_round_robin(causal_hits, max_extracted)

    candidate_paths: list[str] = []
    for ci, hit in enumerate(selected, start=1):
        url = hit["url"]
        try:
            content = web_extract(url, provider=provider)
        except Exception:  # noqa: BLE001 -- skip a failed page, never fabricate content
            content = None
        if not content:
            continue
        content_bytes = content.encode("utf-8")
        cand_path = out_dir / f"candidate-{ci:02d}.md"
        cand_path.write_text(content, encoding="utf-8")
        candidate_paths.append(str(cand_path))
        sources.append(
            SourceRecord(
                path=str(cand_path.relative_to(out_dir)),
                origin=url,
                retrieved_at=_now_iso(),
                content_type="text/markdown",
                sha256=sha256_hex(content_bytes),
                byte_length=len(content_bytes),
            )
        )

    manifest = Manifest(
        ticker=args.ticker.upper(),
        event_id="peer-discovery",
        created_at=_now_iso(),
        sources=sources,
        queries=queries,
        notes=[
            f"Peer-group discovery via {provider}: {len(all_hits)} hit(s) from {len(queries)} queries.",
            f"Extracted {len(candidate_paths)} candidate page(s) for the agent to read and pick ~4 peers.",
        ]
        + (
            [
                f"Excluded {excluded_future} {provider} hit(s) published after the event "
                f"date ({args.event_date}) from extraction (causality guard)."
            ]
            if excluded_future
            else []
        ),
    )
    _write_json(out_dir / config.MANIFEST_FILENAME, manifest.model_dump())

    print(f"Peer-group discovery for {args.ticker.upper()} -> {out_dir}")
    print(f"  {len(queries)} queries, {len(all_hits)} hits, {len(candidate_paths)} extracted page(s).")
    if candidate_paths:
        print("  Read these, pick ~4 analyst-agreed comparables, then run `prepare --peers ...`:")
        for path in candidate_paths:
            print(f"    - {path}")
    else:
        print("  No pages extracted -- widen config [research] peer_group_queries or check the provider.")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    run_dir = config.run_dir(args.ticker, args.event_id)
    _archive_existing_run(run_dir)
    raw_dir = run_dir / config.RAW_SUBDIR
    normalized_dir = run_dir / config.NORMALIZED_SUBDIR
    evidence_dir = run_dir / config.EVIDENCE_SUBDIR
    for d in (raw_dir, normalized_dir, evidence_dir):
        d.mkdir(parents=True, exist_ok=True)

    loaded = load_transcript(args.transcript)

    pdf_source_record = None
    pdf_reformat_note = None
    if loaded.raw_bytes is not None:
        from .reformat import looks_like_factset_format, reformat_factset_transcript

        pdf_raw_path = raw_dir / f"transcript{loaded.raw_suffix}"
        pdf_raw_path.write_bytes(loaded.raw_bytes)
        pdf_source_record = SourceRecord(
            path=str(pdf_raw_path.relative_to(run_dir)),
            origin=loaded.origin,
            retrieved_at=_now_iso(),
            content_type="application/pdf",
            sha256=sha256_hex(loaded.raw_bytes),
            byte_length=len(loaded.raw_bytes),
        )
        if config.PDF_FACTSET_REFORMAT_ENABLED and looks_like_factset_format(
            loaded.raw_text, config.PDF_FACTSET_SEPARATOR_PATTERN
        ):
            loaded.raw_text = reformat_factset_transcript(
                loaded.raw_text, config.PDF_FACTSET_SEPARATOR_PATTERN, config.PDF_FACTSET_BANNER_PATTERNS
            )
            pdf_reformat_note = "PDF source: FactSet-style layout detected and reformatted."
        else:
            pdf_reformat_note = "PDF source: no known vendor layout auto-detected; segmented as-is."

    raw_bytes = loaded.raw_text.encode("utf-8")
    if loaded.is_html:
        raw_filename = "transcript.html"
    elif loaded.raw_bytes is not None:
        raw_filename = "transcript.converted.md"
    else:
        raw_filename = "transcript.txt"
    raw_path = raw_dir / raw_filename
    raw_path.write_text(loaded.raw_text, encoding="utf-8")  # archive raw, verbatim, before sanitisation
    _append_processing_log(args.ticker, args.event_id, loaded, raw_bytes, run_dir)

    sanitized = sanitize(loaded.raw_text, is_html=loaded.is_html)
    segments = segment_transcript(sanitized)
    if loaded.raw_bytes is not None and not any(seg.speaker for seg in segments):
        raise ValueError(
            "PDF ingestion produced zero recognised speaker turns after segmentation -- "
            "refusing to proceed with an unattributed transcript. This PDF's vendor "
            "layout is not one we've handled before; if it is FactSet-style, check "
            "config.toml [pdf_ingestion] patterns; otherwise this vendor needs its own "
            "reformatter. See docs/AUDITABILITY.md 'Known limitations'."
        )
    transcript_path = normalized_dir / config.TRANSCRIPT_FILENAME
    with transcript_path.open("w", encoding="utf-8") as fh:
        for seg in segments:
            fh.write(seg.model_dump_json() + "\n")

    # Best-effort prompt-injection FLAG over the sanitised transcript (config-gated).
    # Advisory only -- it records matches, never blocks the run or removes text. Runs
    # AFTER sanitize so invisible-char evasions are already normalised away. Transcript
    # only, not Exa/Tavily results (those providers run their own defences).
    injection_findings: list[dict] = []
    if config.SANITISATION_INJECTION_SCAN_ENABLED:
        injection_findings = scan_for_injection(sanitized, config.SANITISATION_INJECTION_PATTERNS)
        _write_json(
            run_dir / config.INJECTION_SCAN_FILENAME,
            {
                "scanned_at": _now_iso(),
                "pattern_count": len(config.SANITISATION_INJECTION_PATTERNS),
                "finding_count": len(injection_findings),
                "findings": injection_findings,
            },
        )
    if not config.SANITISATION_INJECTION_SCAN_ENABLED:
        injection_note = "Prompt-injection scan: disabled (config.toml [sanitisation])."
    elif injection_findings:
        injection_note = (
            f"Prompt-injection scan: {len(injection_findings)} suspicious phrase(s) flagged in "
            f"transcript -- advisory only, run not blocked. See injection-scan.json."
        )
    else:
        injection_note = "Prompt-injection scan: clean (no configured patterns matched)."

    financials: dict = {}
    sec_status = "disabled"
    cik = args.sec_cik
    if config.RESEARCH_SEC_ENABLED:
        if not cik and config.SEC_RESOLVE_CIK_FROM_TICKER:
            from .sources import resolve_cik

            cik = resolve_cik(args.ticker)
        if cik:
            from .sources import extract_financials_from_company_facts, get_company_facts

            facts = get_company_facts(int(cik))
            financials = extract_financials_from_company_facts(
                facts,
                concepts=config.SEC_CONCEPTS,
                period_end=args.sec_period_end,
                period_type=args.sec_period_type,
                require_period_type_match=config.SEC_REQUIRE_PERIOD_MATCH,
            )
            sec_status = "ok"
        else:
            # Not every registrant is discoverable by ticker (e.g. non-SEC-registered
            # foreign private issuers); this is a normal, expected outcome, not an
            # error -- the pipeline continues with whatever other evidence exists.
            sec_status = "not_applicable"
    financials_path = evidence_dir / config.FINANCIALS_FILENAME
    _write_json(financials_path, financials)

    provider = config.RESEARCH_WEB_SEARCH_PROVIDER  # "exa" (default) | "tavily"
    web_search_sources: list[SourceRecord] = []
    web_search_status = "disabled"
    web_evidence: list[WebEvidence] = []
    web_evidence_sources: list[SourceRecord] = []
    web_evidence_notes: list[str] = []
    queries: list[str] = []
    if config.RESEARCH_WEB_SEARCH_ENABLED:
        from .sources import build_consensus_queries, build_peer_queries, web_extract, web_search

        max_results = config.EXA_NUM_RESULTS if provider == "exa" else config.TAVILY_MAX_RESULTS
        max_extracted = config.EXA_MAX_EXTRACTED_SOURCES if provider == "exa" else config.TAVILY_MAX_EXTRACTED_SOURCES

        web_search_raw_dir = raw_dir / "web"
        web_search_raw_dir.mkdir(parents=True, exist_ok=True)
        company_name = args.company_name or args.ticker
        event_date = args.event_date or args.event_id
        # Repurposed queries: consensus/expectations + peer-group results (info NOT in
        # the transcript), replacing the old official-document queries that restated the
        # call. Each query is tagged with its class so the raw archive records what a hit
        # was looking for. Peers come from --peers (agent-supplied from the transcript);
        # with none, only the consensus queries run.
        # Each tuple is (archive_class, query, select_key). archive_class is the coarse
        # "consensus"/"peer" label stamped into the raw hit for provenance. select_key is
        # the FINER bucket the extraction round-robin interleaves on: consensus is one
        # bucket, but each peer is its own (peer:<name>) so one high-scoring peer can't
        # fill every peer slot and starve the other three -- the peer group's whole point
        # is 4-way competitive breadth.
        classified_queries = [
            ("consensus", q, "consensus")
            for q in build_consensus_queries(company_name, args.ticker, args.event_id, config.RESEARCH_CONSENSUS_QUERIES)
        ]
        for peer in args.peers:
            classified_queries += [
                ("peer", q, f"peer:{peer}")
                for q in build_peer_queries(
                    company_name, args.ticker, args.event_id, [peer], config.RESEARCH_PEER_QUERIES
                )
            ]
        queries = [q for _, q, _ in classified_queries]

        # Causality guard, attempted server-side: pass event_date to the active
        # provider's own publish-date filter. DOCUMENTED LIMITATION, confirmed by
        # live testing on 2026-08-26 for both Tavily and Exa: not reliably enforced
        # in practice -- see sources.web_search's callees' docstrings. Sent anyway
        # (harmless); the real guard is the client-side filter below. Only set when
        # --event-date parses as a real calendar date (it defaults to event_id,
        # e.g. "2026-q2", which isn't one).
        event_cutoff = _parse_event_cutoff(event_date)
        provider_end_date = event_cutoff.isoformat() if event_cutoff else None

        all_hits: list[dict] = []  # every normalized hit seen, for the extract-selection step below
        for qi, (qclass, query, select_key) in enumerate(classified_queries, start=1):
            hits = web_search(query, provider=provider, max_results=max_results, end_date=provider_end_date)
            for hit in hits:
                hit["_class"] = qclass  # coarse label written to the raw archive (provenance)
                hit["_select_key"] = select_key  # finer bucket the round-robin interleaves on
                hit["_temporal_status"] = _classify_temporal_status(hit.get("published_date"), event_cutoff)
            all_hits.extend(hits)
            # archive_all_sources controls how many hits per query we keep -- the
            # config default (true) matches "narrow queries, but don't discard what
            # the provider returns for them" rather than us silently dropping evidence.
            kept = hits if config.RESEARCH_ARCHIVE_ALL_SOURCES else hits[:1]
            for hi, hit in enumerate(kept, start=1):
                # Stamped into the archived file itself (not just manifest.json's
                # per-source retrieved_at) so the fetch time is visible without
                # cross-referencing the manifest.
                hit_retrieved_at = _now_iso()
                # "_query" records the exact search string that produced this hit --
                # previously only recoverable by re-reading the query builder in
                # sources.py and assuming its fixed template never changed. "_provider" records
                # which search API (exa/tavily) produced it -- previously not recorded
                # ANYWHERE per-hit: the archive directory is always literally named
                # "web" regardless of provider (see web_search_raw_dir above), not
                # "exa"/"tavily", so only manifest.json's free-text notes said which
                # provider ran, and only once for the whole run, not per file.
                hit_bytes = json.dumps(
                    {
                        **hit,
                        "_provider": provider,
                        "_query": query,
                        "_class": qclass,  # "consensus" | "peer" -- what this query was looking for
                        "_retrieved_at": hit_retrieved_at,
                    },
                    indent=2,
                ).encode("utf-8")
                hit_filename = f"query-{qi:02d}-hit-{hi:02d}.json"
                (web_search_raw_dir / hit_filename).write_bytes(hit_bytes)
                web_search_sources.append(
                    SourceRecord(
                        path=str((web_search_raw_dir / hit_filename).relative_to(run_dir)),
                        origin=hit.get("url", query),
                        retrieved_at=hit_retrieved_at,
                        content_type="application/json",
                        sha256=sha256_hex(hit_bytes),
                        byte_length=len(hit_bytes),
                    )
                )
        web_search_status = (
            f"ok ({len(web_search_sources)} hit(s) from {len(queries)} queries)" if web_search_sources else "no_results"
        )

        # Search hits are short snippets, not quote-checkable evidence -- a claim
        # can't cite one. Extract full content for the best few so they become real,
        # citable WebEvidence (see models.WebEvidence, validate.check_evidence_reference).
        if all_hits:
            web_dir = evidence_dir / config.WEB_SUBDIR
            web_dir.mkdir(parents=True, exist_ok=True)

            # Causality guard, actual enforcement: provider_end_date above is not
            # reliably honored (confirmed by live testing on both providers), so this
            # client-side check on published_date is the real guard, not a backstop.
            # It only catches hits that carry a published_date at all -- confirmed by
            # the same testing that most hits do not, so this guard's real-world
            # coverage is narrower than it looks. Undated hits are kept, not dropped.
            causal_hits, excluded_future = _filter_post_event(all_hits, event_cutoff)
            if excluded_future:
                web_evidence_notes.append(
                    f"Excluded {excluded_future} {provider} hit(s) published after the event "
                    f"date ({event_date}) from citable evidence (causality guard)."
                )

            # Round-robin across query classes so consensus (run first, more hits) can't
            # fill every extraction slot and starve peer results -- the live bug this
            # fixes. Within a class, provider relevance order is preserved (see helper).
            selected = _select_round_robin(causal_hits, max_extracted)
            for wi, hit in enumerate(selected, start=1):
                url = hit["url"]
                try:
                    raw_content = web_extract(url, provider=provider)
                except Exception as exc:  # noqa: BLE001 -- record and continue, never fabricate content
                    raw_content = None
                    web_evidence_notes.append(f"web evidence extraction failed for {url}: {exc}")
                    continue
                if not raw_content:
                    web_evidence_notes.append(f"web evidence extraction returned no content for {url}")
                    continue
                web_id = f"web-{wi:03d}"
                content_bytes = raw_content.encode("utf-8")
                content_filename = f"{web_id}.md"
                content_path = web_dir / content_filename
                content_path.write_text(raw_content, encoding="utf-8")
                web_evidence.append(
                    WebEvidence(
                        id=web_id,
                        url=url,
                        title=hit.get("title"),
                        publisher=None,
                        published_at=hit.get("published_date"),
                        temporal_status=hit.get("_temporal_status", "unchecked"),
                        retrieved_at=_now_iso(),
                        content_path=str(content_path.relative_to(run_dir)),
                        content_sha256=sha256_hex(content_bytes),
                    )
                )
                web_evidence_sources.append(
                    SourceRecord(
                        path=str(content_path.relative_to(run_dir)),
                        origin=url,
                        retrieved_at=_now_iso(),
                        content_type="text/markdown",
                        sha256=sha256_hex(content_bytes),
                        byte_length=len(content_bytes),
                    )
                )
            if web_evidence:
                web_evidence_path = evidence_dir / config.WEB_EVIDENCE_FILENAME
                with web_evidence_path.open("w", encoding="utf-8") as fh:
                    for we in web_evidence:
                        fh.write(we.model_dump_json() + "\n")

    manifest = Manifest(
        ticker=args.ticker.upper(),
        event_id=args.event_id,
        created_at=_now_iso(),
        sources=(
            ([pdf_source_record] if pdf_source_record else [])
            + [
                SourceRecord(
                    path=str(raw_path.relative_to(run_dir)),
                    origin=loaded.origin,
                    retrieved_at=_now_iso(),
                    content_type=loaded.content_type,
                    sha256=sha256_hex(raw_bytes),
                    byte_length=len(raw_bytes),
                )
            ]
            + web_search_sources
            + web_evidence_sources
        ),
        queries=queries,
        notes=[
            "Raw source archived verbatim before sanitisation.",
            injection_note,
            f"SEC evidence: {sec_status}" + (f" (CIK {cik})" if sec_status == "ok" else ""),
            f"Web search evidence ({provider}): {web_search_status}",
            f"Web evidence (extracted, citable): {len(web_evidence)} source(s)",
        ]
        + ([pdf_reformat_note] if pdf_reformat_note else [])
        + web_evidence_notes,
    )
    _write_json(run_dir / config.MANIFEST_FILENAME, manifest.model_dump())

    print(f"Prepared source pack at {run_dir} ({len(segments)} segments).")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    run_dir = config.run_dir(args.ticker, args.event_id)
    attempt = ValidationAttempt.start(run_dir, _input_hashes(run_dir))
    blocked = _block_if_unclosed_review_report(run_dir)
    if blocked is not None:
        attempt.finish("blocked", blocked)
        return blocked
    _clear_stale_review_report_md(run_dir)
    claims_path = run_dir / config.CLAIMS_FILENAME
    transcript_path = run_dir / config.NORMALIZED_SUBDIR / config.TRANSCRIPT_FILENAME
    financials_path = run_dir / config.EVIDENCE_SUBDIR / config.FINANCIALS_FILENAME

    card_path = run_dir / config.SIGNAL_CARD_FILENAME
    card_path.unlink(missing_ok=True)  # clear any stale card from a prior passing run before (re)validating

    if not claims_path.exists():
        print(f"error: {claims_path} not found. Write claims.json first (see skill).", file=sys.stderr)
        attempt.finish("blocked", 2)
        return 2

    manifest_path = run_dir / config.MANIFEST_FILENAME
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

    web_evidence_path = run_dir / config.EVIDENCE_SUBDIR / config.WEB_EVIDENCE_FILENAME
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
            issues=[ValidationIssue(claim_index=-1, check="schema", message=f"Could not parse {config.CLAIMS_FILENAME}: {exc}")],
        )
        _write_validation(run_dir, result)
        attempt.finish("failed", 1, result, validation_path=run_dir / config.VALIDATION_FILENAME)
        print(f"Validation FAILED: could not parse {config.CLAIMS_FILENAME}: {exc}")
        return 1

    result = validate_claims(claims, segments_by_id, financials, web_evidence_texts, web_evidence_statuses)

    metrics_path = run_dir / config.METRICS_FILENAME
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
            attempt.finish("failed", 1, result, validation_path=run_dir / config.VALIDATION_FILENAME)
            print(f"Validation FAILED: could not parse {config.METRICS_FILENAME}: {exc}")
            return 1
        metric_issues = validate_metrics(metrics, claim_ids)
        if metric_issues:
            result = ValidationResult(
                ok=False,
                checked_claims=result.checked_claims,
                issues=result.issues + metric_issues,
                warnings=result.warnings,
            )

    _write_validation(run_dir, result)

    # Advisories print regardless of pass/fail -- they never block the card, but the
    # human should see them (e.g. web evidence fetched but no claim used it).
    for warning in result.warnings:
        print(f"  WARNING: {warning}")

    if not result.ok:
        attempt.finish("failed", 1, result, validation_path=run_dir / config.VALIDATION_FILENAME)
        print(f"Validation FAILED: {len(result.issues)} issue(s). See {config.VALIDATION_FILENAME}.")
        for issue in result.issues:
            print(f"  claim[{issue.claim_index}] {issue.check}: {issue.message}")
        return 1

    card = _render_signal_card(args.ticker, args.event_id, claims, segments_by_id)
    (run_dir / config.SIGNAL_CARD_FILENAME).write_text(card, encoding="utf-8")
    attempt.finish("passed", 0, result, validation_path=run_dir / config.VALIDATION_FILENAME)
    print(f"Validation passed ({result.checked_claims} claims). Wrote {config.SIGNAL_CARD_FILENAME}.")
    return 0


def cmd_validate_outlook(args: argparse.Namespace) -> int:
    """Gate outlook-brief.md (agent-authored Stage 2 synthesis, not Python-generated --
    scenarios/base-case judgment aren't deterministic) on two things: the underlying
    claims already passed `analyze`, and every claim id the brief cites is real.
    """
    run_dir = config.run_dir(args.ticker, args.event_id)
    blocked = _block_if_unclosed_review_report(run_dir)
    if blocked is not None:
        return blocked
    _clear_stale_review_report_md(run_dir)
    validation_path = run_dir / config.VALIDATION_FILENAME
    outlook_path = run_dir / config.OUTLOOK_BRIEF_FILENAME
    claims_path = run_dir / config.CLAIMS_FILENAME

    validation = _load_validated_json(validation_path, ValidationResult)
    if validation is None:
        print(f"error: {validation_path} not found or invalid. Run `earnings analyze` first.", file=sys.stderr)
        return 2
    if not validation.ok:
        print("Outlook brief blocked: underlying claims have not passed validation.")
        return 1

    # Recheck every input that analyze bound into validation.json. A later edit to
    # transcript, manifest, archived source, financials, metrics, or claims cannot
    # inherit the prior passing result.
    if not _validation_inputs_current(run_dir, validation):
        print(
            "Outlook brief blocked: an analyze input changed, disappeared, or lacks a required hash. "
            "Re-run `earnings analyze`."
        )
        return 1

    if not outlook_path.exists():
        print(f"error: {outlook_path} not found. Write {config.OUTLOOK_BRIEF_FILENAME} first (see skill).", file=sys.stderr)
        return 2

    raw_claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claim_ids = {c.get("id") for c in raw_claims if c.get("id")}
    outlook_text = outlook_path.read_text(encoding="utf-8")
    errors = check_outlook_brief_citations(outlook_text, claim_ids)
    errors += check_outlook_brief_dollar_escaping(outlook_text)
    # Bind this record to the exact brief + claims bytes so `check-review` can prove the
    # brief it reviews is still the one that passed here.
    outlook_validation = OutlookValidation(
        ok=not errors,
        validated_at=_now_iso(),
        errors=errors,
        outlook_brief_sha256=sha256_hex(outlook_path.read_bytes()),
        claims_sha256=sha256_hex(claims_path.read_bytes()),
    )
    _write_json(run_dir / config.OUTLOOK_VALIDATION_FILENAME, outlook_validation.model_dump())
    if errors:
        print(f"Outlook brief validation FAILED: {len(errors)} issue(s).")
        for error in errors:
            print(f"  {error}")
        return 1

    print(f"Outlook brief validated: all cited claim ids resolve. ({config.OUTLOOK_BRIEF_FILENAME})")
    return 0


def cmd_check_review(args: argparse.Namespace) -> int:
    """Gate the Outlook_Reviewer subagent's review-report.json: it must exist
    (written by the subagent, never by this command -- semantic judgment isn't
    deterministic Python's job, same principle as outlook-brief.md), its own claim-id
    citations must resolve, and the underlying evidence must have already passed
    `analyze`. On success, renders review-report.md deterministically from the
    validated JSON (never trusts agent-authored markdown to match its own JSON).
    """
    run_dir = config.run_dir(args.ticker, args.event_id)

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
            f"last accepted _review_history/round-{completed_rounds}/{config.REVIEW_REPORT_JSON_FILENAME} "
            "findings to the user -- do not loop further.",
            file=sys.stderr,
        )
        return 4

    validation_path = run_dir / config.VALIDATION_FILENAME
    outlook_path = run_dir / config.OUTLOOK_BRIEF_FILENAME
    claims_path = run_dir / config.CLAIMS_FILENAME
    report_path = run_dir / config.REVIEW_REPORT_JSON_FILENAME

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
    outlook_validation_path = run_dir / config.OUTLOOK_VALIDATION_FILENAME
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
        diff_path = run_dir / config.REVIEW_DIFF_FILENAME
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

    if repeated_accepted_bundle:
        print(f"Review round {completed_rounds} was already accepted; no new snapshot written.")
        if report.escalate_full_review:
            return 3
        if report.verdict == "fail":
            return 2
        if report.verdict == "pass_with_warnings":
            return 1
        return 0

    md = _render_review_report(args.ticker, args.event_id, report)
    (run_dir / config.REVIEW_REPORT_MD_FILENAME).write_text(md, encoding="utf-8")
    print(f"Review verdict: {report.verdict}. Wrote {config.REVIEW_REPORT_MD_FILENAME}.")

    _snapshot_review_round(run_dir, round_number)

    if report.escalate_full_review:
        print(f"Reviewer escalated: full review required (round {round_number} diff was insufficient).")
        return 3

    if report.verdict == "fail":
        return 2
    if report.verdict == "pass_with_warnings":
        return 1
    return 0


_BARE_DOLLAR_RE = re.compile(r"(?<!\\)\$")


def _escape_currency(text: str) -> str:
    """Escape bare '$' so Markdown renderers with LaTeX math support (KaTeX/MathJax --
    common in IDE previews) don't pair up two unrelated dollar amounts as one inline
    math span, mangling everything between them. Render-time only: never applied to
    claim.quote's underlying value used for exact-quote validation, only to the copy
    written into the .md file.

    Idempotent by construction (only matches a '$' NOT already preceded by '\\') --
    matters because outlook-brief.md's authoring template now tells the agent to
    write '\\$' directly; if agent-authored text carrying an existing '\\$' were ever
    escaped again with a naive .replace("$", "\\$"), it would become '\\\\$', which
    renders as a literal backslash followed by an unescaped '$' -- reopening the exact
    math-mode hazard this function exists to close.
    """
    return _BARE_DOLLAR_RE.sub(r"\\$", text)


def _render_review_report(ticker: str, event_id: str, report: ReviewReport) -> str:
    # report.reviewed_at is agent-self-reported (the subagent has no real clock) --
    # shown alongside, never in place of, checked_at (Python's actual clock at the
    # moment `check-review` validated this report), so a fabricated/rounded
    # agent timestamp is visibly distinguishable rather than silently trusted.
    lines = [
        f"# Review Report: {ticker.upper()} — {event_id}",
        "",
        f"**Verdict:** {report.verdict}",
        f"**Review mode:** {report.review_mode}",
        f"**Reviewed at (agent-reported):** {report.reviewed_at} (model: {report.model})",
        f"**Checked at (system clock):** {_now_iso()}",
        f"**Claims SHA-256:** `{report.claims_sha256}`",
        f"**Outlook brief SHA-256:** `{report.outlook_brief_sha256}`",
        f"**Review diff SHA-256:** `{report.review_diff_sha256 or 'n/a'}`",
        "",
        "## Summary",
        _escape_currency(report.summary),
        "",
    ]
    sections = [
        ("Source checks", report.source_checks),
        ("Claim findings", report.claim_findings),
        ("Outlook findings", report.outlook_findings),
        ("Process findings", report.process_findings),
    ]
    for title, findings in sections:
        lines.append(f"## {title}")
        if not findings:
            lines.append("_None._")
        for f in findings:
            lines.append(f"- **[{f.severity}]** {f.artifact}: {_escape_currency(f.passage)!r}")
            lines.append(f"  - Evidence: {_escape_currency(f.evidence)}")
            lines.append(f"  - Recommendation: {_escape_currency(f.recommendation)}")
        lines.append("")
    lines.append("## Unverified items")
    if report.unverified_items:
        for item in report.unverified_items:
            lines.append(f"- {item}")
    else:
        lines.append("_None._")
    return "\n".join(lines)


def _render_signal_card(ticker: str, event_id: str, claims: list[Claim], segments_by_id: dict) -> str:
    lines = [f"# Signal Card: {ticker.upper()} — {event_id}", "", f"_Generated: {_now_iso()}_", ""]
    by_category: dict[str, list[Claim]] = {}
    for claim in claims:
        by_category.setdefault(claim.category, []).append(claim)
    for category, group in by_category.items():
        lines.append(f"## {category.replace('_', ' ').title()}")
        for claim in group:
            speaker = f" ({claim.speaker})" if claim.speaker else ""
            # classification (e.g. "analytical_inference") must render alongside status --
            # without it, a reader cannot tell the pipeline's own inference apart from a
            # direct quote/fact, both of which render identically otherwise (found live,
            # 2026-08-28: a reviewer flagged an inference claim rendering indistinguishably
            # from a real quote, attributed to the speaker whose words it was derived from).
            lines.append(
                f"- **{claim.status}** [{claim.classification}]{speaker}: {_escape_currency(claim.claim_text)}"
            )
            location = claim.segment_id or claim.web_evidence_id
            lines.append(f'  > "{_escape_currency(claim.quote)}" — {location}')
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="earnings", description="Earnings transcript analysis POC")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser(
        "discover-peers",
        help="Search for the company's analyst peer group (run before prepare; agent picks ~4 --peers)",
    )
    discover.add_argument("--ticker", required=True)
    discover.add_argument(
        "--company-name",
        default=None,
        help="Full company name to sharpen peer-group queries, e.g. 'Microsoft' (defaults to --ticker)",
    )
    discover.add_argument(
        "--event-date",
        default=None,
        help="Optional calendar date, e.g. 2026-07-30. When given, applies the causality "
        "guard as a safety net: dated hits published after it are dropped from extraction; "
        "undated hits still pass through. Omit and no cutoff is applied.",
    )
    discover.set_defaults(func=cmd_discover_peers)

    prep = sub.add_parser("prepare", help="Build a source pack from a transcript")
    prep.add_argument("--ticker", required=True)
    prep.add_argument("--event-id", required=True)
    prep.add_argument("--transcript", required=True, help="Local file path or URL")
    prep.add_argument(
        "--sec-cik",
        default=None,
        help="Numeric SEC CIK, e.g. 320193 (optional -- if omitted, the CIK is "
        "auto-resolved from --ticker via SEC's ticker map unless config.toml disables it)",
    )
    prep.add_argument(
        "--sec-period-end",
        default=None,
        help="XBRL period end date to pin SEC facts to, e.g. 2026-06-30 "
        "(recommended with --sec-cik; without it, the latest-by-end fact is used)",
    )
    prep.add_argument(
        "--sec-period-type",
        default=None,
        choices=["quarter", "half_year", "nine_months", "full_year"],
        help="Duration bucket (derived from each XBRL fact's own start/end dates) to "
        "pin SEC facts to, e.g. 'quarter' -- resolves the case where a 10-Q's 3-month "
        "and 6-month (YTD) facts share the same --sec-period-end. Recommended "
        "alongside --sec-period-end for quarterly figures.",
    )
    prep.add_argument(
        "--company-name",
        default=None,
        help="Full company name for web-search queries, e.g. 'Microsoft' (defaults to --ticker if omitted)",
    )
    prep.add_argument(
        "--event-date",
        default=None,
        help="Calendar date of the earnings event, e.g. 2026-01-28, used to build web-search "
        "queries (defaults to --event-id if omitted, which is usually less precise)",
    )
    prep.add_argument(
        "--peers",
        nargs="*",
        default=[],
        help="The ~4 analyst-recognised peer companies to fetch results for, e.g. --peers "
        "'Amazon AWS' 'Alphabet'. Obtain these by running `earnings discover-peers` first and "
        "reading its candidate pages -- the transcript usually names no competitors. Kept out of "
        "config.toml on purpose: peers are per-company. With none given, only consensus queries run.",
    )
    prep.set_defaults(func=cmd_prepare)

    analyze = sub.add_parser("analyze", help="Validate claims.json and produce signal-card.md")
    analyze.add_argument("--ticker", required=True)
    analyze.add_argument("--event-id", required=True)
    analyze.set_defaults(func=cmd_analyze)

    validate_outlook = sub.add_parser(
        "validate-outlook", help="Check outlook-brief.md's claim-id citations against validated claims.json"
    )
    validate_outlook.add_argument("--ticker", required=True)
    validate_outlook.add_argument("--event-id", required=True)
    validate_outlook.set_defaults(func=cmd_validate_outlook)

    check_review = sub.add_parser(
        "check-review",
        help="Validate the outlook-reviewer subagent's review-report.json and render review-report.md",
    )
    check_review.add_argument("--ticker", required=True)
    check_review.add_argument("--event-id", required=True)
    check_review.set_defaults(func=cmd_check_review)

    review_diff = sub.add_parser(
        "review-diff",
        help="Build review-diff.json for a round-2+ diff-based re-review (see cmd_review_diff)",
    )
    review_diff.add_argument("--ticker", required=True)
    review_diff.add_argument("--event-id", required=True)
    review_diff.set_defaults(func=cmd_review_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
