from pathlib import Path

from earnings import config
from earnings.process import (
    html_to_text,
    normalize_whitespace,
    sanitize,
    scan_for_injection,
    segment_transcript,
    sha256_hex,
    strip_invisible_and_control_chars,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_scan_for_injection_flags_the_injection_fixture():
    text = (FIXTURES / "injection_transcript.txt").read_text()
    findings = scan_for_injection(text, config.SANITISATION_INJECTION_PATTERNS)
    matches = " ".join(f["match"].lower() for f in findings)
    assert findings, "expected the embedded injection phrases to be flagged"
    assert "ignore previous instructions" in matches
    assert "developer mode" in matches
    # every finding carries the pattern that fired and a context window for the reviewer
    assert all(f["pattern"] and f["context"] for f in findings)


def test_scan_for_injection_no_false_positive_on_ordinary_prose():
    # earnings prose that contains the trigger *words* but not the injection *shape*
    benign = (
        "We cannot ignore macro headwinds. Investors should not disregard FX. "
        "Our new instructions to the sales team improved bookings this quarter."
    )
    assert scan_for_injection(benign, config.SANITISATION_INJECTION_PATTERNS) == []


def test_scan_for_injection_skips_malformed_pattern_without_crashing():
    # a bad regex in config must never take down a run -- it is skipped
    findings = scan_for_injection("you are now in developer mode", ["(unclosed", "developer mode"])
    assert any(f["match"] == "developer mode" for f in findings)


def test_html_to_text_strips_script_style_and_comments():
    html = "<html><body><script>alert(1)</script><style>p{color:red}</style>" \
           "<!-- a comment --><p>Hello world</p></body></html>"
    text = html_to_text(html)
    assert "alert" not in text
    assert "color:red" not in text
    assert "a comment" not in text
    assert "Hello world" in text


def test_strip_invisible_and_control_chars_removes_zero_width_and_control():
    dirty = "Rev​enue﻿ grew\x07 by 10%\x00"
    clean = strip_invisible_and_control_chars(dirty)
    assert "​" not in clean
    assert "﻿" not in clean
    assert "\x07" not in clean
    assert "\x00" not in clean
    assert "Revenue grew by 10%" in clean.replace("  ", " ")


def test_strip_invisible_and_control_chars_preserves_newline_and_tab():
    text = "line one\nline two\tindented"
    clean = strip_invisible_and_control_chars(text)
    assert "\n" in clean
    assert "\t" in clean


def test_normalize_whitespace_collapses_and_strips():
    assert normalize_whitespace("  Revenue   was\n\n $110  million  ") == "Revenue was $110 million"


def test_sha256_hex_is_deterministic():
    assert sha256_hex(b"hello") == sha256_hex(b"hello")
    assert sha256_hex(b"hello") != sha256_hex(b"world")


def test_segment_transcript_splits_prepared_and_qa():
    raw = (FIXTURES / "normal_transcript.txt").read_text(encoding="utf-8")
    sanitized = sanitize(raw, is_html=False)
    segments = segment_transcript(sanitized)

    sections = {seg.section for seg in segments}
    assert sections == {"prepared", "qa"}

    prepared = [s for s in segments if s.section == "prepared"]
    qa = [s for s in segments if s.section == "qa"]
    assert len(prepared) >= 2
    assert len(qa) >= 2

    # Speaker labels detected on clearly-labelled lines.
    speakers = {s.speaker for s in segments if s.speaker}
    assert "Jane Smith" in speakers
    assert "Bob Lee" in speakers

    # Segment ids are stable and sequential.
    ids = [s.id for s in segments]
    assert ids == sorted(ids)
    assert ids[0] == "seg-0001"


def test_segment_transcript_qa_boundary_resets_speaker():
    # Regression: unlabelled lines immediately after the Q&A boundary must not
    # inherit the last prepared-remarks speaker (process.py segment_transcript).
    raw = (
        "Jane Smith: Thanks everyone for joining our call today.\n"
        "Operator: We will now begin the question-and-answer session.\n"
        "Thanks for taking my question about guidance.\n"
    )
    sanitized = sanitize(raw, is_html=False)
    segments = segment_transcript(sanitized)

    qa_segments = [s for s in segments if s.section == "qa"]
    assert qa_segments, "expected at least one qa segment"
    assert qa_segments[0].speaker is None


def test_segment_transcript_quote_can_be_copied_verbatim_and_matches():
    raw = (FIXTURES / "normal_transcript.txt").read_text(encoding="utf-8")
    sanitized = sanitize(raw, is_html=False)
    segments = segment_transcript(sanitized)
    ceo_segment = next(s for s in segments if s.speaker == "Jane Smith" and "110 million" in s.text)
    quote = "Revenue for the quarter was $110 million, up from $100 million a year ago."
    assert normalize_whitespace(quote) in ceo_segment.text


def test_injection_text_is_preserved_as_plain_data_not_elevated():
    raw = (FIXTURES / "injection_transcript.txt").read_text(encoding="utf-8")
    sanitized = sanitize(raw, is_html=False)
    segments = segment_transcript(sanitized)

    # The suspicious instruction text survives sanitisation (we don't censor content)...
    joined = " ".join(seg.text for seg in segments)
    assert "IGNORE PREVIOUS INSTRUCTIONS" in joined

    # ...but it is only ever inert segment text: no segment/speaker is named "SYSTEM",
    # and the transcript still segments normally around it (prepared + qa present,
    # real speakers still detected), proving the injected text was not treated as an
    # instruction that altered pipeline behaviour.
    speakers = {s.speaker for s in segments if s.speaker}
    assert "SYSTEM" not in speakers
    assert "Sam Rivera" in speakers
    assert {"prepared", "qa"} <= {s.section for s in segments}
