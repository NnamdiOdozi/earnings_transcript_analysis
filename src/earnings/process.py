"""Sanitisation, segmentation, hashing and archiving.

Fetched/loaded text is treated as untrusted DATA, never as instructions. We do not
classify or STRIP "prompt injection" content -- we only remove structural HTML noise,
control characters and invisible Unicode so the text is clean to read and quote.
Anything else (e.g. "IGNORE PREVIOUS INSTRUCTIONS...") is left intact as plain text and
only ever flows into segment .text, never executed or treated specially.

We do, optionally, FLAG it: `scan_for_injection` runs a config-driven list of regex
patterns over the sanitised transcript and records any hit (in manifest.json and a
per-run injection-scan.json) as an awareness signal for the reviewer. This is a
best-effort flag, NOT a classifier and NOT a gate -- it never blocks the run or removes
text. See `reference/sanitisation-notes.md`.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment

from .config import (
    QA_STANDALONE_HEADINGS,
    QA_TRANSITION_PHRASES,
    SEGMENT_ID_PREFIX,
    SEGMENT_ID_WIDTH,
    ZERO_WIDTH_CHARS,
)
from .models import Segment

# Speaker label heuristics: "Name — Title:", "Name:", or "Name, Company:".
# Deliberately conservative -- only fires on short, title-cased leading tokens
# followed by a colon, to avoid mis-detecting ordinary prose sentences.
_SPEAKER_NAME_PATTERN = r"[A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,4}"
_SPEAKER_LINE_RE = re.compile(
    rf"^(?P<speaker>{_SPEAKER_NAME_PATTERN})"
    r"(?:\s*[—–-]\s*[^:]{0,80})?:\s*(?P<rest>.*)$"
)
_SPEAKER_WITH_AFFILIATION_RE = re.compile(
    rf"^(?P<speaker>{_SPEAKER_NAME_PATTERN},\s*[^,:]{{1,80}}):\s*(?P<rest>.*)$"
)


@dataclass(frozen=True)
class SegmentationResult:
    """Hold transcript segments and deliberate structural omissions.

    Attributes
    ----------
    segments : list of Segment
        Normalized transcript segments in source order.
    omissions : list of dict
        Non-empty source lines deliberately removed as structural headings.
    """

    segments: list[Segment]
    omissions: list[dict[str, str]]

# Control characters except \n (0x0A) and \t (0x09).
_CONTROL_CHAR_RE = re.compile(
    "[" + "".join(chr(c) for c in range(0x20) if c not in (0x09, 0x0A)) + chr(0x7F) + "]"
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


def scan_for_injection(text: str, patterns: list[str]) -> list[dict]:
    """Best-effort prompt-injection FLAG: match each regex in `patterns` (case-
    insensitive) against `text` and return one record per hit -- NOT a classifier, NOT
    a gate. Callers record the result as an advisory note; they never block the run or
    remove the text (suspicious content stays quotable data). Each record carries the
    pattern that fired, the exact matched substring, and a short surrounding context
    window so a reviewer can judge it. Run this AFTER sanitize() so invisible-character
    evasions (e.g. a zero-width space inside "ig<zwsp>nore") are already normalised away.
    """
    findings: list[dict] = []
    for pattern in patterns:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue  # a malformed config pattern must never crash a run
        for m in regex.finditer(text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            findings.append(
                {
                    "pattern": pattern,
                    "match": m.group(0),
                    "context": normalize_whitespace(text[start:end]),
                }
            )
    return findings


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _detect_speaker(line: str) -> tuple[str | None, str]:
    stripped = line.strip()
    match = _SPEAKER_WITH_AFFILIATION_RE.match(stripped) or _SPEAKER_LINE_RE.match(stripped)
    if not match:
        return None, line
    speaker = match.group("speaker").strip()
    rest = match.group("rest").strip()
    # Reject speaker candidates that are implausibly long (likely a normal sentence
    # with a colon in it, e.g. "Note: revenue grew").
    if len(speaker.split()) > 5 or len(speaker) > 60:
        return None, line
    return speaker, rest


def _qa_match_text(line: str) -> str:
    """Canonical text for configured Q&A rules, including curly apostrophes."""
    return normalize_whitespace(line).casefold().replace("’", "'")


def _is_qa_heading(line: str) -> bool:
    candidate = _qa_match_text(line).removesuffix(":").strip()
    return candidate in QA_STANDALONE_HEADINGS


def _has_qa_transition(line: str) -> bool:
    candidate = _qa_match_text(line)
    return any(phrase in candidate for phrase in QA_TRANSITION_PHRASES)


def segment_transcript_with_report(sanitized_text: str) -> SegmentationResult:
    """Split sanitized transcript text into prepared-remarks vs Q&A segments.

    The first configured transition moves the state from prepared to Q&A. Meaningful
    transition sentences remain in the prepared segment under their speaker. Only an
    exact standalone Q&A heading is omitted, and every such omission is returned in
    the report. After the transition, later Q&A wording cannot alter segmentation.

    Every non-empty line is therefore represented as segment text, captured speaker
    metadata, or an explicit structural omission.

    Parameters
    ----------
    sanitized_text : str
        Visible transcript text after HTML and control-character sanitisation.

    Returns
    -------
    SegmentationResult
        Ordered segments and the receipt of deliberately omitted headings.
    """
    lines = [ln for ln in sanitized_text.split("\n")]
    section = "prepared"
    segments: list[Segment] = []
    current_speaker: str | None = None
    current_lines: list[str] = []
    omissions: list[dict[str, str]] = []
    counter = 0

    def flush():
        nonlocal counter
        text = normalize_whitespace(" ".join(current_lines))
        if not text:
            return
        counter += 1
        seg_id = f"{SEGMENT_ID_PREFIX}-{counter:0{SEGMENT_ID_WIDTH}d}"
        segments.append(Segment(id=seg_id, section=section, speaker=current_speaker, text=text))

    def append_content(line: str) -> None:
        nonlocal current_lines, current_speaker
        speaker, rest = _detect_speaker(line)
        if speaker is not None:
            flush()
            current_lines = [rest] if rest else []
            current_speaker = speaker
        else:
            current_lines.append(line)

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if _is_qa_heading(line):
            omissions.append({"text": line, "reason": "qa_heading"})
            if section == "qa":
                continue
            flush()
            current_lines = []
            section = "qa"
            current_speaker = None
            continue
        if section == "prepared" and _has_qa_transition(line):
            # Preserve the hand-off under the current speaker, then change state.
            append_content(line)
            flush()
            current_lines = []
            current_speaker = None
            section = "qa"
            continue
        append_content(line)
    flush()
    return SegmentationResult(segments=segments, omissions=omissions)


def segment_transcript(sanitized_text: str) -> list[Segment]:
    """Return transcript segments without the structural-omission receipt.

    Parameters
    ----------
    sanitized_text : str
        Visible transcript text after HTML and control-character sanitisation.

    Returns
    -------
    list of Segment
        Ordered prepared-remarks and questions-and-answers segments.
    """
    return segment_transcript_with_report(sanitized_text).segments
