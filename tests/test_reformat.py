"""FactSet-style PDF transcript reformatting: detection, rewriting, and (the point
of the module) that the rewritten output actually plugs into process.segment_transcript."""
from earnings.process import sanitize, segment_transcript
from earnings.reformat import looks_like_factset_format, reformat_factset_transcript

_SEPARATOR_PATTERN = r"^[.]{10,}\s*$"
_BANNER_PATTERNS = [
    r"^FINAL TRANSCRIPT\s*$",
    r"^Copyright ©.*$",
    r"^\d{1,4}\s*$",
]

_FIXTURE = """FINAL TRANSCRIPT
..........................
Jane Smith
Chief Executive Officer
Thank you for joining us today. We had a strong quarter.
Revenue grew twenty percent year over year.
..........................
John Doe
Chief Financial Officer
Our margins improved this quarter.
3
Copyright © 2026 FactSet CallStreet, LLC
"""

_ORDINARY_PROSE = (
    "This is a normal transcript with no dotted separators at all, just prose.\n"
    "Another ordinary line here.\n"
)


def test_looks_like_factset_format_detects_fixture():
    assert looks_like_factset_format(_FIXTURE, _SEPARATOR_PATTERN) is True


def test_looks_like_factset_format_false_on_ordinary_prose():
    assert looks_like_factset_format(_ORDINARY_PROSE, _SEPARATOR_PATTERN) is False


def test_reformat_factset_transcript_rewrites_headers_and_drops_noise():
    out = reformat_factset_transcript(_FIXTURE, _SEPARATOR_PATTERN, _BANNER_PATTERNS)
    assert "Jane Smith — Chief Executive Officer:" in out
    assert "John Doe — Chief Financial Officer:" in out
    # Separator, banner, and page-number lines must be dropped.
    assert "." * 10 not in out
    assert "FINAL TRANSCRIPT" not in out
    assert "Copyright ©" not in out
    # Prose is preserved.
    assert "Thank you for joining us today. We had a strong quarter." in out
    assert "Our margins improved this quarter." in out


def test_reformatted_output_segments_with_correct_speakers():
    """The whole point of this module: its output must plug into the existing
    segmenter and produce non-None speakers matching the fixture's names."""
    out = reformat_factset_transcript(_FIXTURE, _SEPARATOR_PATTERN, _BANNER_PATTERNS)
    sanitized = sanitize(out, is_html=False)
    segments = segment_transcript(sanitized)
    speakers = [seg.speaker for seg in segments]
    assert "Jane Smith" in speakers
    assert "John Doe" in speakers
    assert all(s is not None for s in speakers)


def test_reformat_factset_transcript_handles_non_ascii_name_and_abbreviated_title():
    # Regression (regex audit, 2026-09-04): _NAME_RE had the same ASCII-only bug
    # fixed in process.py today, untouched -- and _looks_like_title separately
    # rejected a title ending in an abbreviation period ("Corp."). Both fixed by
    # reusing process.py's name validator and dropping "." from the title guard.
    fixture = (
        "..........................\n"
        "Bláthnaid Bergin\n"
        "Chief Financial Officer, ABC Corp.\n"
        "Thank you for the question.\n"
    )
    out = reformat_factset_transcript(fixture, _SEPARATOR_PATTERN, _BANNER_PATTERNS)
    assert "Bláthnaid Bergin — Chief Financial Officer, ABC Corp.:" in out


def test_reformat_factset_transcript_handles_bare_role_speaker():
    # Regression (follow-up regex audit, 2026-09-04): _NAME_LINE_RE required 2-5
    # words, so a single-word role speaker ("Operator") right after a separator,
    # with no title line following, fell through unrewritten (no colon added) --
    # invisible to process.py's own speaker detection downstream too.
    fixture = (
        "..........................\n"
        "Operator\n"
        "Please go ahead.\n"
    )
    out = reformat_factset_transcript(fixture, _SEPARATOR_PATTERN, _BANNER_PATTERNS)
    sanitized = sanitize(out, is_html=False)
    segments = segment_transcript(sanitized)
    assert any(seg.speaker == "Operator" for seg in segments)


def test_reformat_factset_transcript_preserves_wrapped_number_mid_sentence():
    # Regression (follow-up regex audit, 2026-09-04): a banner pattern as generic
    # as a bare 1-4 digit line ("^\d{1,4}\s*$", used for page numbers) previously
    # stripped ANY standalone digit line, including a genuine financial figure
    # that ends up alone on its own line purely from PDF line-wrapping -- silently
    # deleting real data. Banner-stripping is now gated on the preceding line
    # looking like a completed sentence, which a true page footer always follows
    # and a wrapped mid-sentence figure never does.
    fixture = (
        "..........................\n"
        "Simon Roberts\n"
        "Chief Executive Officer\n"
        "We are guiding revenue to\n"
        "500\n"
        "million dollars this year.\n"
        "..........................\n"
    )
    out = reformat_factset_transcript(fixture, _SEPARATOR_PATTERN, _BANNER_PATTERNS)
    assert "500" in out.split("\n")
