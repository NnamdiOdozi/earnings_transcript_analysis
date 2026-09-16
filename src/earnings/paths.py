"""Where every artifact of one run lives on disk.

This module is the ONLY place the run-directory layout is expressed. Everything else
asks `RunPaths` for a path instead of joining `run_dir` with a filename constant.

The split of responsibility with `config` is deliberate:

- `config` owns the *names* (``claims.json``, ``review``, ...). Those are the stable
  public identifiers an operator or an agent skill refers to.
- `RunPaths` owns the *arrangement* -- which directory each name sits in.

Two arrangements exist:

``LAYOUT_FLAT`` (1)
    Every artifact at the run root, with ``_validation_history``,
    ``_outlook_validation_history`` and ``_review_history`` beside them. What every run
    written before the stage folders landed looks like.

``LAYOUT_STAGED`` (2)
    The run root narrates the pipeline: shared source pack at the top, then ``claims/``,
    ``outlook/`` and ``review/``, each holding its own artifacts and its own
    ``history/``. ``audit-record.json`` stays at the root because it summarises the run
    as a whole.

Existing runs are never migrated. A run declares its own layout in its manifest, so a
frozen run keeps working under new code and the audit records inside it keep describing
the structure that actually existed when they were written.

A note for whoever changes the arrangement again: `validation.json`'s ``input_hashes``
keys (e.g. ``"evidence/web-evidence.jsonl"``) are a serialization format, not paths.
They are compared against previously written validation files, so renaming a key breaks
staleness detection on older runs. Keep the keys stable even when the file moves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import config

LAYOUT_FLAT = 1
LAYOUT_STAGED = 2
CURRENT_LAYOUT = LAYOUT_STAGED


def detect_layout(run_dir: Path) -> int:
    """Read the layout a run declares in its manifest.

    Falls back to ``LAYOUT_FLAT`` when there is no manifest yet or it does not name a
    layout -- the second case is exactly a run written before the field existed.

    Deliberately NOT inferred from whether a stage directory exists: a freshly prepared
    layout-2 run has no ``claims/`` content until ``analyze`` runs, so existence-based
    detection would classify it as legacy and scatter its later artifacts across both
    arrangements.
    """
    manifest_path = Path(run_dir) / config.MANIFEST_FILENAME
    if not manifest_path.is_file():
        return LAYOUT_FLAT
    try:
        declared = json.loads(manifest_path.read_text(encoding="utf-8")).get("layout_version")
    except (json.JSONDecodeError, OSError, AttributeError):
        return LAYOUT_FLAT
    return declared if isinstance(declared, int) and declared in (LAYOUT_FLAT, LAYOUT_STAGED) else LAYOUT_FLAT


# Which stage folder each artifact filename belongs to under LAYOUT_STAGED. Needed
# because several call sites iterate over a LIST of filenames (snapshotting a review
# round, copying an attempt's inputs) and so cannot name a property -- see RunPaths.resolve.
_STAGE_OF_FILENAME = {
    config.CLAIMS_FILENAME: config.CLAIMS_STAGE_SUBDIR,
    config.METRICS_FILENAME: config.CLAIMS_STAGE_SUBDIR,
    config.VALIDATION_FILENAME: config.CLAIMS_STAGE_SUBDIR,
    config.SIGNAL_CARD_FILENAME: config.CLAIMS_STAGE_SUBDIR,
    config.OUTLOOK_BRIEF_FILENAME: config.OUTLOOK_STAGE_SUBDIR,
    config.OUTLOOK_VALIDATION_FILENAME: config.OUTLOOK_STAGE_SUBDIR,
    config.REVIEW_REPORT_JSON_FILENAME: config.REVIEW_STAGE_SUBDIR,
    config.REVIEW_REPORT_MD_FILENAME: config.REVIEW_STAGE_SUBDIR,
    config.REVIEW_DIFF_FILENAME: config.REVIEW_STAGE_SUBDIR,
    config.REVIEW_DIFF_SHA256_FILENAME: config.REVIEW_STAGE_SUBDIR,
}


@dataclass(frozen=True)
class RunPaths:
    """Every path belonging to one ticker/event run, resolved from its root directory."""

    root: Path
    layout: int = LAYOUT_FLAT

    @classmethod
    def for_run(cls, ticker: str, event_id: str, layout: int | None = None) -> RunPaths:
        """Paths for `ticker`/`event_id` under the configured runs directory."""
        return cls.at(config.run_dir(ticker, event_id), layout)

    @classmethod
    def at(cls, run_dir: Path, layout: int | None = None) -> RunPaths:
        """Paths for a known run directory, reading its declared layout unless given.

        Pass `layout` explicitly only when the manifest is not yet on disk to be read --
        `prepare` does this while creating a run.
        """
        root = Path(run_dir)
        return cls(root, detect_layout(root) if layout is None else layout)

    def resolve(self, filename: str) -> Path:
        """Where a run artifact named `filename` lives under this run's layout.

        For call sites that iterate over a list of filenames and so cannot name a
        property. A filename with no stage (manifest.json, audit-record.json, an
        attempt receipt) resolves to the run root under both layouts.
        """
        stage = _STAGE_OF_FILENAME.get(filename)
        if stage is None or self.layout == LAYOUT_FLAT:
            return self.root / filename
        return self.root / stage / filename

    def _staged(self, stage: str, filename: str) -> Path:
        """Resolve `filename` into its stage folder, or the run root under layout 1."""
        if self.layout == LAYOUT_FLAT:
            return self.root / filename
        return self.root / stage / filename

    # --- source pack: shared evidence every later stage depends on. Identical in both
    # layouts -- claims, outlook and review all rest on it, so it belongs to none of them.

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
    def claims_dir(self) -> Path:
        return self.root if self.layout == LAYOUT_FLAT else self.root / config.CLAIMS_STAGE_SUBDIR

    @property
    def claims(self) -> Path:
        return self._staged(config.CLAIMS_STAGE_SUBDIR, config.CLAIMS_FILENAME)

    @property
    def metrics(self) -> Path:
        return self._staged(config.CLAIMS_STAGE_SUBDIR, config.METRICS_FILENAME)

    @property
    def validation(self) -> Path:
        return self._staged(config.CLAIMS_STAGE_SUBDIR, config.VALIDATION_FILENAME)

    @property
    def signal_card(self) -> Path:
        return self._staged(config.CLAIMS_STAGE_SUBDIR, config.SIGNAL_CARD_FILENAME)

    @property
    def validation_history(self) -> Path:
        if self.layout == LAYOUT_FLAT:
            return self.root / config.VALIDATION_HISTORY_SUBDIR
        return self.claims_dir / config.STAGE_HISTORY_SUBDIR

    # --- stage 2: outlook -----------------------------------------------------------

    @property
    def outlook_dir(self) -> Path:
        return self.root if self.layout == LAYOUT_FLAT else self.root / config.OUTLOOK_STAGE_SUBDIR

    @property
    def outlook_brief(self) -> Path:
        return self._staged(config.OUTLOOK_STAGE_SUBDIR, config.OUTLOOK_BRIEF_FILENAME)

    @property
    def outlook_validation(self) -> Path:
        return self._staged(config.OUTLOOK_STAGE_SUBDIR, config.OUTLOOK_VALIDATION_FILENAME)

    @property
    def outlook_validation_history(self) -> Path:
        if self.layout == LAYOUT_FLAT:
            return self.root / config.OUTLOOK_VALIDATION_HISTORY_SUBDIR
        return self.outlook_dir / config.STAGE_HISTORY_SUBDIR

    # --- stage 3: review ------------------------------------------------------------

    @property
    def review_dir(self) -> Path:
        return self.root if self.layout == LAYOUT_FLAT else self.root / config.REVIEW_STAGE_SUBDIR

    @property
    def review_report_json(self) -> Path:
        return self._staged(config.REVIEW_STAGE_SUBDIR, config.REVIEW_REPORT_JSON_FILENAME)

    @property
    def review_report_md(self) -> Path:
        return self._staged(config.REVIEW_STAGE_SUBDIR, config.REVIEW_REPORT_MD_FILENAME)

    @property
    def review_diff(self) -> Path:
        return self._staged(config.REVIEW_STAGE_SUBDIR, config.REVIEW_DIFF_FILENAME)

    @property
    def review_diff_sha256(self) -> Path:
        return self._staged(config.REVIEW_STAGE_SUBDIR, config.REVIEW_DIFF_SHA256_FILENAME)

    @property
    def review_history(self) -> Path:
        if self.layout == LAYOUT_FLAT:
            return self.root / config.REVIEW_HISTORY_SUBDIR
        return self.review_dir / config.STAGE_HISTORY_SUBDIR

    def review_round(self, number: int) -> Path:
        """Snapshot directory for one completed review round."""
        return self.review_history / f"round-{number}"

    # --- whole-run ------------------------------------------------------------------

    @property
    def audit_record(self) -> Path:
        """Summarises the whole run, so it sits at the root under both layouts."""
        return self.root / config.AUDIT_RECORD_FILENAME

    @property
    def archive(self) -> Path:
        return self.root / config.ARCHIVE_SUBDIR

    @property
    def stage_dirs(self) -> tuple[Path, ...]:
        """Stage folders to create up front, so a prepared run already shows its shape."""
        if self.layout == LAYOUT_FLAT:
            return ()
        return (self.claims_dir, self.outlook_dir, self.review_dir)
