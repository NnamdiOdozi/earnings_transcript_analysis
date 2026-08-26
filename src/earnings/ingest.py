"""Load a transcript from a local file or a simple URL.

Local files: .txt, .md, .html/.htm. URLs: fetched via httpx, capped at
MAX_FETCH_BYTES. Network calls are isolated here so tests can monkeypatch
`fetch_url` and never touch the network.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import HTTP_TIMEOUT_SECONDS, MAX_FETCH_BYTES

_HTML_SUFFIXES = {".html", ".htm"}
_TEXT_SUFFIXES = {".txt", ".md"}


@dataclass
class LoadedTranscript:
    raw_text: str
    is_html: bool
    origin: str  # local path or URL, for the manifest
    content_type: str


def load_local_file(path: str | Path) -> LoadedTranscript:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Transcript file not found: {p}")
    suffix = p.suffix.lower()
    if suffix not in _HTML_SUFFIXES | _TEXT_SUFFIXES:
        raise ValueError(f"Unsupported transcript file type: {suffix} (expected txt/md/html)")
    raw_text = p.read_text(encoding="utf-8", errors="replace")
    is_html = suffix in _HTML_SUFFIXES
    content_type = "text/html" if is_html else "text/plain"
    return LoadedTranscript(raw_text=raw_text, is_html=is_html, origin=str(p), content_type=content_type)


def fetch_url(url: str) -> LoadedTranscript:
    """Fetch a transcript from a simple URL. Real network call -- not used in tests."""
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content[:MAX_FETCH_BYTES]
        content_type = resp.headers.get("content-type", "text/plain")
        is_html = "html" in content_type.lower()
        text = content.decode(resp.encoding or "utf-8", errors="replace")
    return LoadedTranscript(raw_text=text, is_html=is_html, origin=url, content_type=content_type)


def load_transcript(source: str) -> LoadedTranscript:
    """Dispatch to local file loading or URL fetching based on the source string."""
    if source.startswith("http://") or source.startswith("https://"):
        return fetch_url(source)
    return load_local_file(source)
