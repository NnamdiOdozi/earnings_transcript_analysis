"""Load a transcript from a local file or a simple URL.

Local files: .txt, .md, .html/.htm, .pdf. URLs: fetched via httpx and REJECTED if
larger than MAX_FETCH_BYTES -- never silently truncated, because a truncated
transcript analysed as if whole is worse than a clean failure for an auditable
pipeline. PDF sources (local or URL) are converted to plain text via pypdf; the
original PDF bytes are preserved on the LoadedTranscript for provenance archiving
in cli.cmd_prepare. Network calls are isolated here so tests can monkeypatch
`fetch_url` and never touch the network.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import httpx
from pypdf import PdfReader

from .config import HTTP_TIMEOUT_SECONDS, MAX_FETCH_BYTES

_HTML_SUFFIXES = {".html", ".htm"}
_TEXT_SUFFIXES = {".txt", ".md"}
_PDF_SUFFIXES = {".pdf"}


@dataclass
class LoadedTranscript:
    raw_text: str
    is_html: bool
    origin: str  # local path or URL, for the manifest
    content_type: str
    raw_bytes: bytes | None = None  # original PDF bytes; set ONLY for PDF sources
    raw_suffix: str | None = None  # e.g. ".pdf"; set ONLY for PDF sources


def _extract_pdf_text(data: bytes) -> str:
    """Extract plain text from PDF bytes via pypdf, one blank-line-joined block per page."""
    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def load_local_file(path: str | Path) -> LoadedTranscript:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Transcript file not found: {p}")
    suffix = p.suffix.lower()
    if suffix not in _HTML_SUFFIXES | _TEXT_SUFFIXES | _PDF_SUFFIXES:
        raise ValueError(f"Unsupported transcript file type: {suffix} (expected txt/md/html/pdf)")
    if suffix in _PDF_SUFFIXES:
        data = p.read_bytes()
        text = _extract_pdf_text(data)
        return LoadedTranscript(
            raw_text=text,
            is_html=False,
            origin=str(p),
            content_type="text/markdown",
            raw_bytes=data,
            raw_suffix=".pdf",
        )
    raw_text = p.read_text(encoding="utf-8", errors="replace")
    is_html = suffix in _HTML_SUFFIXES
    content_type = "text/html" if is_html else "text/plain"
    return LoadedTranscript(raw_text=raw_text, is_html=is_html, origin=str(p), content_type=content_type)


def fetch_url(url: str) -> LoadedTranscript:
    """Fetch a transcript from a simple URL. Real network call -- not used in tests."""
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content
        if len(content) > MAX_FETCH_BYTES:
            # Fail loudly rather than truncate: an incomplete transcript treated as
            # whole would silently corrupt every downstream claim/quote check.
            raise ValueError(
                f"Transcript at {url} is {len(content)} bytes, over the {MAX_FETCH_BYTES}-byte "
                f"cap (config.toml [http] max_fetch_mb). Refusing to analyse a truncated transcript."
            )
        content_type = resp.headers.get("content-type", "text/plain")
        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            text = _extract_pdf_text(content)
            return LoadedTranscript(
                raw_text=text,
                is_html=False,
                origin=url,
                content_type="text/markdown",
                raw_bytes=content,
                raw_suffix=".pdf",
            )
        is_html = "html" in content_type.lower()
        text = content.decode(resp.encoding or "utf-8", errors="replace")
    return LoadedTranscript(raw_text=text, is_html=is_html, origin=url, content_type=content_type)


def load_transcript(source: str) -> LoadedTranscript:
    """Dispatch to local file loading or URL fetching based on the source string."""
    if source.startswith("http://") or source.startswith("https://"):
        return fetch_url(source)
    return load_local_file(source)
