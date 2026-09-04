"""FactSet-style transcript reformatting.

Some PDF-syndicated earnings transcripts (confirmed: FactSet CallStreet, from a
real JPMorgan Q2 2026 PDF) put a speaker's Name and Title on separate lines,
separated by a dotted rule between turns, rather than the "Name — Title:"
single-line header process.segment_transcript's _detect_speaker expects. This
module auto-detects that ONE confirmed layout and rewrites it into the expected
header form. Deliberately narrow: we do not know other vendors' PDF layouts and
do not guess at them here. An unrecognised layout is left untouched -- the
zero-speaker guard in cli.cmd_prepare is what catches that failure loudly.
"""
from __future__ import annotations

import re

# Reuse process.py's name-shape pattern and name validator rather than maintaining a
# second, independently-drifting ASCII-only regex here -- confirmed live (regex
# audit, 2026-09-04): this module's own _NAME_RE still had the exact ASCII-only bug
# just fixed in process.py, untouched, because nobody had run a FactSet-layout PDF
# with a non-ASCII name through the pipeline yet. A future one (this project has now
# separately confirmed both a real FactSet transcript and a real non-ASCII-name
# transcript) would have hit it.
from .process import _NAME_WORD_PATTERN, _is_valid_speaker_name

# {1,4} -> {0,4} (confirmed live, follow-up regex audit 2026-09-04): a single-word
# role speaker ("Operator", "Moderator") in FactSet's Name/Title-on-separate-lines
# layout could never match a 2-5-word-only pattern, so it fell through unrewritten
# (no colon added) and was then invisible to process.py's own speaker detection too
# -- silently swallowing the operator's lines as unattributed prose.
_NAME_LINE_RE = re.compile(rf"^{_NAME_WORD_PATTERN}(?:\s+{_NAME_WORD_PATTERN}){{0,4}}$")
_SENTENCE_END_RE = re.compile(r"[.!?:]\s*$")


def _looks_like_name(line: str) -> bool:
    return bool(_NAME_LINE_RE.match(line)) and _is_valid_speaker_name(line)


def looks_like_factset_format(text: str, separator_pattern: str) -> bool:
    """True if the text contains the dotted-separator-line pattern at least twice --
    the one structural marker confirmed from a real FactSet PDF, distinct enough not
    to false-positive on ordinary transcript prose."""
    regex = re.compile(separator_pattern, re.MULTILINE)
    return len(regex.findall(text)) >= 2


def _looks_like_title(line: str) -> bool:
    # "." dropped from the rejection set (confirmed live, regex audit 2026-09-04): a
    # title/affiliation ending in an abbreviation ("ABC Corp.", "XYZ Ltd.") was
    # previously rejected outright. "?"/"!" still reject -- a real title never ends
    # in either. Cap raised 100->150 (same shape as process.py's word/char guard
    # raised earlier today): a verbose real title ("Managing Director and Global
    # Co-Head of Investment Banking, Financial Institutions Group", 91 chars) was
    # already close to the old limit.
    #
    # Majority-Title-Case check added (follow-up regex audit, 2026-09-04): once a
    # bare single-word name (e.g. "Operator") became acceptable with no title line
    # required, ordinary dialogue immediately following it ("Please go ahead.")
    # could satisfy the length/punctuation checks alone and get swallowed as a
    # fabricated "title" -- "Operator — Please go ahead.:". A real title/
    # affiliation is overwhelmingly Title Case; ordinary sentence prose is not.
    if not line or len(line) >= 150 or line.endswith(("?", "!")):
        return False
    words = line.split()
    capitalized = sum(1 for w in words if w[:1].isupper())
    return capitalized >= max(1, (len(words) + 1) // 2)


def reformat_factset_transcript(text: str, separator_pattern: str, banner_patterns: list[str]) -> str:
    """Rewrite Name/Title-on-separate-lines blocks (recognised only immediately
    after a separator line, never mid-paragraph, to avoid mis-firing on ordinary
    text) into "Name — Title:" headers. Drops separator lines and any line
    matching a configured banner/footer pattern (page numbers, copyright lines)."""
    separator_re = re.compile(separator_pattern)
    banner_res = [re.compile(p) for p in banner_patterns]
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    just_saw_separator = True  # start of document counts as a boundary
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if separator_re.match(line):
            just_saw_separator = True
            i += 1
            continue
        if any(b.match(line) for b in banner_res):
            # Only strip a banner-shaped line (page number, copyright, ...) when
            # the text immediately before it looks like a completed sentence.
            # Confirmed live (follow-up regex audit 2026-09-04): a banner pattern
            # as generic as a bare 1-4 digit line can otherwise delete a genuine
            # financial figure that ends up alone on its own line purely from PDF
            # line-wrapping mid-sentence (e.g. "...revenue to\n500\nmillion
            # dollars"). A true page footer/number reliably follows a completed
            # sentence; a wrapped figure does not -- when in doubt, keep the text
            # rather than risk deleting real data.
            if not out or _SENTENCE_END_RE.search(out[-1]):
                i += 1
                continue
        elif just_saw_separator and _looks_like_name(line):
            next_line = lines[i + 1].strip() if i + 1 < n else ""
            if next_line and _looks_like_title(next_line):
                out.append(f"{line} — {next_line}:")
                i += 2
            else:
                # A name-shaped line with no title line following it (e.g. a bare
                # "Operator" turn) -- still a valid single-line header.
                out.append(f"{line}:")
                i += 1
            just_saw_separator = False
            continue
        out.append(line)
        just_saw_separator = False
        i += 1
    return "\n".join(out)
