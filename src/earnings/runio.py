from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from . import config
from .process import sha256_hex


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
