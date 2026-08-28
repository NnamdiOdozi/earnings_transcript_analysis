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

_NAME_RE = re.compile(r"^[A-Z][A-Za-z.'\-]*(\s+[A-Z][A-Za-z.'\-]*){1,4}$")


def looks_like_factset_format(text: str, separator_pattern: str) -> bool:
    """True if the text contains the dotted-separator-line pattern at least twice --
    the one structural marker confirmed from a real FactSet PDF, distinct enough not
    to false-positive on ordinary transcript prose."""
    regex = re.compile(separator_pattern, re.MULTILINE)
    return len(regex.findall(text)) >= 2


def _looks_like_title(line: str) -> bool:
    return bool(line) and len(line) < 100 and not line.endswith((".", "?", "!"))


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
            i += 1
            continue
        if (
            just_saw_separator
            and i + 1 < n
            and _NAME_RE.match(line)
            and _looks_like_title(lines[i + 1].strip())
        ):
            name, title = line, lines[i + 1].strip()
            out.append(f"{name} — {title}:")
            i += 2
            just_saw_separator = False
            continue
        out.append(line)
        just_saw_separator = False
        i += 1
    return "\n".join(out)
