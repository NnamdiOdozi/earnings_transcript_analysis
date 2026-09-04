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
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment

from .config import (
    QA_STANDALONE_HEADINGS,
    QA_TRANSITION_PHRASES,
    SEGMENT_ID_PREFIX,
    SEGMENT_ID_WIDTH,
    SPEAKER_DENYLIST_PATTERNS,
    SPEAKER_NAME_PARTICLES,
    ZERO_WIDTH_CHARS,
)
from .models import Segment

# Speaker label heuristics: "Name — Title:", "Name:", or "Name, Company:".
# Deliberately conservative -- only fires on short, name-shaped leading tokens
# followed by a colon, to avoid mis-detecting ordinary prose sentences.
#
# The regex alone cannot enforce "starts with an uppercase letter" for arbitrary
# scripts -- stdlib `re` has no \p{Lu}, and even restricting to Latin-1 Supplement
# (an earlier version of this fix) still missed Latin Extended-A capitals used in
# Czech/Polish/etc. names, because that block alternates upper/lower per codepoint
# with no contiguous range to express in a character class (confirmed live, regex
# audit 2026-09-04). So the regex below matches any run of Unicode-letter words,
# permissively -- _is_valid_speaker_name() does the actual "is this name-shaped"
# judgment afterward, in Python, via str.isupper() (script-agnostic and correct,
# unlike hand-enumerated Unicode ranges).
_NAME_WORD_PATTERN = r"[^\W\d_](?:[^\W\d_]|['’.\-])*"
# Word-repeat count raised 3->9 (confirmed live, follow-up regex audit
# 2026-09-04): a 6-word plain name with no affiliation ("Jan Willem van der Berg
# Junior") previously couldn't even match the regex, even though the separate
# length guard in _detect_speaker already allowed up to 10 words -- the two
# limits must agree, or the guard's headroom is fiction.
_SPEAKER_NAME_PATTERN = (
    rf"{_NAME_WORD_PATTERN}(?:\s+{_NAME_WORD_PATTERN}){{0,9}}"
    r"(?:\s+\d{1,2})?"  # optional trailing placeholder index, e.g. "Speaker 1"
)
# The dash-title portion is now a named group (`dash_title`), not thrown away,
# so _detect_speaker can reject it when it looks like a metric rather than a
# role/title -- confirmed live (follow-up regex audit, 2026-09-04):
# "Group Sales — 3.6%:" previously matched as speaker "Group Sales" because
# nothing checked the text between the dash and the colon.
_SPEAKER_LINE_RE = re.compile(
    rf"^(?P<speaker>{_SPEAKER_NAME_PATTERN})"
    r"(?:\s*[—–-]\s*(?P<dash_title>[^:]{0,80}))?:\s*(?P<rest>.*)$"
)
# Named "name"/"affiliation" groups, not one combined "speaker" group, so the name
# portion can be validated on its own -- _detect_speaker still joins them back into
# one speaker string ("Manjari Dhar, RBC"), preserving prior behaviour. Affiliation
# allows internal commas ("Name, Title, Company:") -- confirmed live (regex audit):
# the old `[^,:]` class rejected a second comma outright.
_SPEAKER_WITH_AFFILIATION_RE = re.compile(
    rf"^(?P<name>{_SPEAKER_NAME_PATTERN}),\s*(?P<affiliation>[^:]{{1,100}}):\s*(?P<rest>.*)$"
)
_SPEAKER_DENYLIST_RE = (
    re.compile("^(?:" + "|".join(SPEAKER_DENYLIST_PATTERNS) + ")$", re.IGNORECASE)
    if SPEAKER_DENYLIST_PATTERNS
    else None
)


def _is_valid_speaker_name(name: str) -> bool:
    """True if `name` is name-shaped: the first word starts with an uppercase
    letter (any script), and every later word either starts uppercase, is a
    configured lowercase particle (SPEAKER_NAME_PARTICLES, e.g. "van"/"von"), or is
    a short digit token (a placeholder index like "Speaker 1"). The regex that
    captured `name` only bounds its shape/length; this is the real "looks like a
    name" check, done here because stdlib `re` cannot express "uppercase letter"
    for arbitrary scripts.
    """
    words = name.split()
    if not words or not words[0][0].isupper():
        return False
    for word in words[1:]:
        if word[0].isupper() or word.isdigit():
            continue
        if word.lower() in SPEAKER_NAME_PARTICLES:
            continue
        return False
    return True


def _is_denylisted_speaker(name: str) -> bool:
    """True if `name` matches a configured non-name document/section header
    (e.g. "Forward Looking Statements") -- confirmed live (regex audit
    2026-09-04): such a line would otherwise be accepted as a fabricated speaker,
    silently absorbing real content under a name nobody actually said.
    """
    return bool(_SPEAKER_DENYLIST_RE and _SPEAKER_DENYLIST_RE.match(name))


_METRIC_CHAR_RE = re.compile(r"[\d%$£€¥]")


def _looks_like_metric_not_title(dash_title: str) -> bool:
    """True if a "Name — X:" line's X portion contains a digit or currency/percent
    symbol -- a real role or job title never does, but a financial-metric line
    happens to have the same "Word — stuff:" shape. Confirmed live (follow-up
    regex audit 2026-09-04): "Group Sales — 3.6%:" was accepted as speaker
    "Group Sales" because nothing checked what came after the dash.
    """
    return bool(_METRIC_CHAR_RE.search(dash_title))


_NEAR_MISS_MAX_WORDS = 15


def _looks_speaker_shaped(candidate: str) -> bool:
    """Loose heuristic for the near-miss signal ONLY -- never gates real speaker
    detection, and deliberately looser than _is_valid_speaker_name. True if
    `candidate` (the text before a trailing colon) has 1-15 words and at least
    half start with an uppercase letter. Exists so a line that looks speaker-ish
    but didn't parse is recorded as an advisory near-miss (see
    segment_transcript_with_report), instead of silently vanishing into whichever
    segment happens to be open -- confirmed as the umbrella issue behind every
    speaker-detection bug found so far (regex audit 2026-09-04).
    """
    words = candidate.split()
    if not words or len(words) > _NEAR_MISS_MAX_WORDS:
        return False
    capitalized = sum(1 for w in words if w[:1].isupper())
    return capitalized >= max(1, len(words) // 2)


@dataclass(frozen=True)
class SegmentationResult:
    """Hold transcript segments, deliberate structural omissions, and near-miss
    speaker lines.

    Attributes
    ----------
    segments : list of Segment
        Normalized transcript segments in source order.
    omissions : list of dict
        Non-empty source lines deliberately removed as structural headings.
    near_miss_speakers : list of dict
        Lines that look speaker-shaped (see _looks_speaker_shaped) but did not
        parse as one -- advisory only, never gates the run. See
        segment_transcript_with_report.
    """

    segments: list[Segment]
    omissions: list[dict[str, str]]
    near_miss_speakers: list[dict[str, str]] = field(default_factory=list)

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


_INJECTION_FINDINGS_CAP = 500


def scan_for_injection(text: str, patterns: list[str]) -> list[dict]:
    """Best-effort prompt-injection FLAG: match each regex in `patterns` (case-
    insensitive) against `text` and return one record per hit -- NOT a classifier, NOT
    a gate. Callers record the result as an advisory note; they never block the run or
    remove the text (suspicious content stays quotable data). Each record carries the
    pattern that fired, the exact matched substring, and a short surrounding context
    window so a reviewer can judge it. Run this AFTER sanitize() so invisible-character
    evasions (e.g. a zero-width space inside "ig<zwsp>nore") are already normalised away.

    Capped at _INJECTION_FINDINGS_CAP total findings (confirmed as a latent gap,
    regex audit 2026-09-04): a pathologically repetitive document could otherwise
    produce an unbounded findings list. Still advisory-only -- capping the receipt,
    not the scan, so a run is never blocked by this.
    """
    findings: list[dict] = []
    for pattern in patterns:
        if len(findings) >= _INJECTION_FINDINGS_CAP:
            break
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue  # a malformed config pattern must never crash a run
        for m in regex.finditer(text):
            if len(findings) >= _INJECTION_FINDINGS_CAP:
                break
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
    match = _SPEAKER_WITH_AFFILIATION_RE.match(stripped)
    if match:
        name = match.group("name").strip()
        speaker = f"{name}, {match.group('affiliation').strip()}"
    else:
        match = _SPEAKER_LINE_RE.match(stripped)
        if not match:
            return None, line
        dash_title = match.group("dash_title")
        if dash_title and _looks_like_metric_not_title(dash_title):
            return None, line
        name = match.group("speaker").strip()
        speaker = name
    rest = match.group("rest").strip()
    # Reject speaker candidates that are implausibly long (likely a normal sentence
    # with a colon in it, e.g. "Note: revenue grew"). Raised 5->10 words / 60->100
    # chars (confirmed live, SBRY/q1-2627, 2026-09-04): a 3-word name + 3-word
    # affiliation alone ("Xavier Le Mené, Bank of America") already hits 6 words, and
    # a name + multi-word title + multi-word firm ("head of equity research") could
    # plausibly reach 9 -- 10 leaves headroom without admitting an ordinary sentence.
    if len(speaker.split()) > 10 or len(speaker) > 100:
        return None, line
    if not _is_valid_speaker_name(name) or _is_denylisted_speaker(name):
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
        Ordered segments, the receipt of deliberately omitted headings, and any
        near-miss speaker-shaped lines that failed to parse (advisory only).
    """
    lines = [ln for ln in sanitized_text.split("\n")]
    section = "prepared"
    segments: list[Segment] = []
    current_speaker: str | None = None
    current_lines: list[str] = []
    omissions: list[dict[str, str]] = []
    near_misses: list[dict[str, str]] = []
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
            stripped = line.strip()
            if stripped.endswith(":") and _looks_speaker_shaped(stripped[:-1].strip()):
                near_misses.append({"text": stripped, "reason": "unparsed_speaker_shaped_line"})
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
    return SegmentationResult(segments=segments, omissions=omissions, near_miss_speakers=near_misses)


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
