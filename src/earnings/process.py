"""Sanitisation, segmentation, hashing and archiving.

Fetched/loaded text is treated as untrusted DATA, never as instructions. We do not
attempt to classify or strip "prompt injection" content -- we only remove structural
HTML noise, control characters and invisible Unicode so the text is clean to read and
quote. Anything else (e.g. "IGNORE PREVIOUS INSTRUCTIONS...") is left intact as plain
text and only ever flows into segment .text, never executed or treated specially.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from bs4 import BeautifulSoup, Comment

from .config import QA_BOUNDARY_MARKERS, SEGMENT_ID_PREFIX, SEGMENT_ID_WIDTH, ZERO_WIDTH_CHARS
from .models import Segment

# Speaker label heuristics: "Name — Title:" or "Name:" at line start.
# Deliberately conservative -- only fires on short, title-cased leading tokens
# followed by a colon, to avoid mis-detecting ordinary prose sentences.
_SPEAKER_LINE_RE = re.compile(
    r"^(?P<speaker>[A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,4})"
    r"(?:\s*[—–-]\s*[^:]{0,80})?:\s*(?P<rest>.*)$"
)

# Control characters except \n (0x0A) and \t (0x09).
_CONTROL_CHAR_RE = re.compile(
    "[" + "".join(chr(c) for c in range(0x00, 0x20) if c not in (0x09, 0x0A)) + chr(0x7F) + "]"
)


def html_to_text(raw_html: str) -> str:
    """Strip <script>/<style>/comments and extract visible text via BeautifulSoup."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    return soup.get_text(separator="\n")


def strip_invisible_and_control_chars(text: str) -> str:
    for ch in ZERO_WIDTH_CHARS:
        text = text.replace(ch, "")
    # Catch any other Unicode "format" (Cf) category chars (zero-width, BOM, marks)
    # not already covered by the explicit list above.
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = _CONTROL_CHAR_RE.sub("", text)
    return text


def normalize_whitespace(text: str) -> str:
    """Canonical normalization: collapse whitespace runs to a single space, strip.

    This is applied identically to segment text and to quotes before the exact-quote
    substring check in validate.py, so quotes copied verbatim from a segment's stored
    text will always match. Newlines are treated as ordinary whitespace here because
    segments are stored as a single normalized text field, not multi-line.
    """
    return re.sub(r"\s+", " ", text).strip()


def sanitize(raw_text: str, is_html: bool) -> str:
    """Full sanitisation pipeline: HTML strip (if needed) -> invisible/control chars.

    Whitespace normalization is NOT applied here; it is applied per-line during
    segmentation and per-segment when building final segment text, so line-based
    heuristics (speaker labels, Q&A markers) still see original line breaks.
    """
    text = html_to_text(raw_text) if is_html else raw_text
    return strip_invisible_and_control_chars(text)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _detect_speaker(line: str) -> tuple[str | None, str]:
    match = _SPEAKER_LINE_RE.match(line.strip())
    if not match:
        return None, line
    speaker = match.group("speaker").strip()
    rest = match.group("rest").strip()
    # Reject speaker candidates that are implausibly long (likely a normal sentence
    # with a colon in it, e.g. "Note: revenue grew").
    if len(speaker.split()) > 5 or len(speaker) > 60:
        return None, line
    return speaker, rest


def _is_qa_boundary(line: str) -> bool:
    lowered = line.strip().lower()
    return any(marker in lowered for marker in QA_BOUNDARY_MARKERS)


def segment_transcript(sanitized_text: str) -> list[Segment]:
    """Split sanitized transcript text into prepared-remarks vs Q&A segments.

    Heuristic: scan lines in order; once a Q&A boundary marker line is seen, every
    subsequent line belongs to the "qa" section (including the boundary line itself,
    which is dropped as pure noise). Each contiguous run of lines attributed to the
    same speaker (or to no speaker) becomes one segment. Speaker labels are detected
    per-line via _detect_speaker; once a speaker line is seen, following unlabelled
    lines are attributed to that same speaker until a new speaker line appears.
    """
    lines = [ln for ln in sanitized_text.split("\n")]
    section = "prepared"
    segments: list[Segment] = []
    current_speaker: str | None = None
    current_lines: list[str] = []
    counter = 0

    def flush():
        nonlocal counter
        text = normalize_whitespace(" ".join(current_lines))
        if not text:
            return
        counter += 1
        seg_id = f"{SEGMENT_ID_PREFIX}-{counter:0{SEGMENT_ID_WIDTH}d}"
        segments.append(Segment(id=seg_id, section=section, speaker=current_speaker, text=text))

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if _is_qa_boundary(line):
            flush()
            current_lines = []
            section = "qa"
            current_speaker = None
            continue
        speaker, rest = _detect_speaker(line)
        if speaker is not None:
            flush()
            current_lines = [rest] if rest else []
            current_speaker = speaker
        else:
            current_lines.append(line)
    flush()
    return segments
