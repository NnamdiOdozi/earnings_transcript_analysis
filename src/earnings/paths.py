"""Where every artifact of one run lives on disk.

This module is the ONLY place the run-directory layout is expressed. Everything else
asks `RunPaths` for a path instead of joining `run_dir` with a filename constant, so
changing the arrangement of a run directory is a change here and nowhere else.

The split of responsibility with `config` is deliberate:

- `config` owns the *names* (``claims.json``, ``_review_history``, ...). Those are the
  stable public identifiers an operator or an agent skill refers to.
- `RunPaths` owns the *arrangement* -- which directory each name sits in.

A note for whoever changes the arrangement: `validation.json`'s ``input_hashes`` keys
(e.g. ``"evidence/web-evidence.jsonl"``) are a serialization format, not paths. They are
compared against previously written validation files, so renaming a key breaks staleness
detection on runs produced before the change. Keep the keys stable, or handle the old
spelling explicitly, even if the underlying file moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass(frozen=True)
class RunPaths:
    """Every path belonging to one ticker/event run, resolved from its root directory."""

    root: Path

    @classmethod
    def for_run(cls, ticker: str, event_id: str) -> RunPaths:
        """Paths for `ticker`/`event_id` under the configured runs directory."""
        return cls(config.run_dir(ticker, event_id))

    @classmethod
    def at(cls, run_dir: Path) -> RunPaths:
        """Paths for an already-known run directory (an archived or snapshotted one)."""
        return cls(Path(run_dir))

    # --- source pack: shared evidence every later stage depends on -------------------

    @property
    def raw(self) -> Path:
        return self.root / config.RAW_SUBDIR

    @property
    def normalized(self) -> Path:
        return self.root / config.NORMALIZED_SUBDIR

    @property
    def evidence(self) -> Path:
        return self.root / config.EVIDENCE_SUBDIR

    @property
    def web_evidence_dir(self) -> Path:
        return self.evidence / config.WEB_SUBDIR

    @property
    def manifest(self) -> Path:
        return self.root / config.MANIFEST_FILENAME

    @property
    def transcript(self) -> Path:
        return self.normalized / config.TRANSCRIPT_FILENAME

    @property
    def financials(self) -> Path:
        return self.evidence / config.FINANCIALS_FILENAME

    @property
    def web_evidence(self) -> Path:
        return self.evidence / config.WEB_EVIDENCE_FILENAME

    @property
    def segmentation_report(self) -> Path:
        return self.root / config.SEGMENTATION_REPORT_FILENAME

    @property
    def injection_scan(self) -> Path:
        return self.root / config.INJECTION_SCAN_FILENAME

    @property
    def price_lookup_log(self) -> Path:
        return self.root / config.PRICE_LOOKUP_LOG_FILENAME

    # --- stage 1: claims ------------------------------------------------------------

    @property
    def claims(self) -> Path:
        return self.root / config.CLAIMS_FILENAME

    @property
    def metrics(self) -> Path:
        return self.root / config.METRICS_FILENAME

    @property
    def validation(self) -> Path:
        return self.root / config.VALIDATION_FILENAME

    @property
    def signal_card(self) -> Path:
        return self.root / config.SIGNAL_CARD_FILENAME

    @property
    def validation_history(self) -> Path:
        return self.root / config.VALIDATION_HISTORY_SUBDIR

    # --- stage 2: outlook -----------------------------------------------------------

    @property
    def outlook_brief(self) -> Path:
        return self.root / config.OUTLOOK_BRIEF_FILENAME

    @property
    def outlook_validation(self) -> Path:
        return self.root / config.OUTLOOK_VALIDATION_FILENAME

    @property
    def outlook_validation_history(self) -> Path:
        return self.root / config.OUTLOOK_VALIDATION_HISTORY_SUBDIR

    # --- stage 3: review ------------------------------------------------------------

    @property
    def review_report_json(self) -> Path:
        return self.root / config.REVIEW_REPORT_JSON_FILENAME

    @property
    def review_report_md(self) -> Path:
        return self.root / config.REVIEW_REPORT_MD_FILENAME

    @property
    def review_diff(self) -> Path:
        return self.root / config.REVIEW_DIFF_FILENAME

    @property
    def review_diff_sha256(self) -> Path:
        return self.root / config.REVIEW_DIFF_SHA256_FILENAME

    @property
    def review_history(self) -> Path:
        return self.root / config.REVIEW_HISTORY_SUBDIR

    def review_round(self, number: int) -> Path:
        """Snapshot directory for one completed review round."""
        return self.review_history / f"round-{number}"

    # --- whole-run ------------------------------------------------------------------

    @property
    def audit_record(self) -> Path:
        return self.root / config.AUDIT_RECORD_FILENAME

    @property
    def archive(self) -> Path:
        return self.root / config.ARCHIVE_SUBDIR
