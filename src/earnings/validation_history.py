"""Preserve each deterministic claims-validation attempt in append-only history."""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from . import config
from .models import ValidationResult

ValidationAttemptOutcome = Literal["passed", "failed", "blocked"]

_ATTEMPT_NUMBER_RE = re.compile(r"^attempt-(\d+)_")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _directory_timestamp(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "")


class ValidationAttempt:
    """Capture the mutable inputs and outcome of one ``earnings analyze`` call.

    The history is append-only. Source-pack files are not copied because their
    hashes bind the attempt to the exact prepared evidence without duplicating it.

    Parameters
    ----------
    number : int
        Monotonically increasing attempt number within one run.
    path : pathlib.Path
        Newly created directory for this attempt.
    started_at : str
        UTC timestamp recorded before claims parsing begins.
    input_hashes : dict[str, str]
        Hashes of all validation inputs present when the attempt started.
    """

    def __init__(self, number: int, path: Path, started_at: str, input_hashes: dict[str, str]) -> None:
        self.number = number
        self.path = path
        self.started_at = started_at
        self.input_hashes = input_hashes

    @classmethod
    def start(cls, run_dir: Path, input_hashes: dict[str, str]) -> ValidationAttempt:
        """Start an attempt and snapshot its mutable agent-authored inputs.

        Parameters
        ----------
        run_dir : pathlib.Path
            Ticker/event directory containing the current claims and evidence.
        input_hashes : dict[str, str]
            Hashes computed from the current validation inputs.

        Returns
        -------
        ValidationAttempt
            Open attempt that must be finished for an expected command outcome.
        """
        history_dir = run_dir / config.VALIDATION_HISTORY_SUBDIR
        history_dir.mkdir(parents=True, exist_ok=True)
        numbers = [
            int(match.group(1))
            for entry in history_dir.iterdir()
            if entry.is_dir() and (match := _ATTEMPT_NUMBER_RE.match(entry.name))
        ]
        number = max(numbers, default=0) + 1
        started_at = _now_iso()
        attempt_dir = history_dir / f"attempt-{number:04d}_{_directory_timestamp(started_at)}"
        attempt_dir.mkdir(exist_ok=False)

        for filename in (config.CLAIMS_FILENAME, config.METRICS_FILENAME):
            source = run_dir / filename
            if source.is_file():
                shutil.copyfile(source, attempt_dir / filename)

        return cls(number, attempt_dir, started_at, dict(input_hashes))

    def finish(
        self,
        outcome: ValidationAttemptOutcome,
        exit_code: int,
        result: ValidationResult | None = None,
        *,
        validation_path: Path | None = None,
    ) -> None:
        """Close an attempt with a receipt and its newly written validation result.

        Parameters
        ----------
        outcome : {"passed", "failed", "blocked"}
            Expected command outcome. Unexpected interpreter failures remain crashes.
        exit_code : int
            Exit code returned by ``earnings analyze``.
        result : ValidationResult, optional
            Validation result produced by this invocation, when validation ran.
        validation_path : pathlib.Path, optional
            Newly written top-level validation file to preserve. Callers omit this
            for blocked attempts so stale validation output is never copied.

        Returns
        -------
        None
        """
        if validation_path is not None and validation_path.is_file():
            shutil.copyfile(validation_path, self.path / config.VALIDATION_FILENAME)

        issue_counts = Counter(issue.check for issue in result.issues) if result else Counter()
        receipt = {
            "attempt": self.number,
            "started_at": self.started_at,
            "finished_at": _now_iso(),
            "outcome": outcome,
            "exit_code": exit_code,
            "checked_claims": result.checked_claims if result else 0,
            "issue_counts": dict(sorted(issue_counts.items())),
            "input_hashes": self.input_hashes,
        }
        (self.path / config.VALIDATION_ATTEMPT_RECEIPT_FILENAME).write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )
