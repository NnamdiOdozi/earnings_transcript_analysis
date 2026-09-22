"""What a logged Jev call must carry to be rebuilt later, and the windowing it relies on.

The live log these guard was written before any of this existed: 485 rows storing a
state hash, no question text, and no record of which code built them. Replaying it
found 220 rows that no longer reproduce, all from a coverage pass run while
build_coverage_payload was still being edited -- and because the edits were
uncommitted, a git-commit stamp alone could not have told them apart. Hence
`builders_sha256`, which hashes the builder source directly.
"""
from __future__ import annotations

import hashlib
import json
import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "jev_check", pathlib.Path(__file__).resolve().parents[1] / "scripts/jev_check.py")
jev_check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(jev_check)

QUOTE = "revenue was $81.3 billion, up 17%"


def test_window_keeps_short_evidence_whole():
    text = "Short evidence containing " + QUOTE + " and nothing else."
    sent, note = jev_check.window_around(text, QUOTE, 10_000)
    assert note is None, "nothing was dropped, so there is nothing to report"
    assert QUOTE in sent


def test_window_centres_on_a_quote_past_the_budget():
    """The defect this fixes: the quote used to fall outside a head-slice.

    Python validates the claim against the whole document, so a quote at offset 12,763
    passed validation while Jev was sent only the first 12,000 characters. Jev was then
    asked whether evidence it could not see supported the claim.
    """
    text = ("filler " * 3_000) + QUOTE + (" trailing" * 3_000)
    budget = 1_000
    sent, note = jev_check.window_around(text, QUOTE, budget)
    assert QUOTE in sent, "the quote must survive the window"
    assert len(sent) <= budget
    assert note["reason"] == "windowed"
    assert note["quote_offset"] > budget, "this is the case a head-slice would lose"
    assert note["full_chars"] > note["sent_chars"]

def test_code_version_changes_when_a_builder_changes(monkeypatch):
    """A wording change in build_questions must move the stamp.

    Rephrasing one question once moved its scores from 0.10 to 0.95, so a score is only
    comparable across runs if the wording is pinned. git_commit cannot do this alone --
    the real drift happened between two uncommitted edits.
    """
    before = jev_check.code_version()["builders_sha256"]

    def edited(claim: dict) -> dict:
        return {"q": {"type": "noul", "instructions": "reworded"}}

    monkeypatch.setattr(jev_check, "build_questions", edited)
    assert jev_check.code_version()["builders_sha256"] != before


@pytest.fixture
def run_dir(tmp_path):
    """The smallest run directory load_inputs will accept.

    Locations come from RunPaths, never from joining the run root with a filename --
    that is the one place the layout is expressed, and layout 1 and 2 differ.
    """
    import json

    from earnings.paths import RunPaths

    (tmp_path / "manifest.json").write_text(json.dumps({
        "ticker": "MSFT", "event_id": "2026-q2", "event_date": "2026-07-30",
        "layout_version": 1,
    }))
    paths = RunPaths.at(tmp_path)
    for target in (paths.claims, paths.transcript):
        target.parent.mkdir(parents=True, exist_ok=True)
    paths.claims.write_text(json.dumps([{
        "id": "claim-001", "segment_id": "seg-0001", "speaker": "CFO",
        "claim_text": "Revenue was $81.3 billion.", "quote": QUOTE,
        "values": {"revenue_billions": 81.3}, "period": "Q2 2026",
    }]))
    paths.transcript.write_text(json.dumps({
        "id": "seg-0001", "section": "prepared", "speaker": "CFO",
        "text": "This quarter, " + QUOTE + " and margins held.",
    }) + "\n")
    return tmp_path


def test_state_rebuilds_to_the_same_hash(run_dir):
    """The round trip the replay tool depends on: same inputs, same bytes, same hash."""
    inputs = jev_check.load_inputs(run_dir)
    claim = inputs["by_id"]["claim-001"]
    first, _ = jev_check.build_state(claim, inputs["segments"], inputs["web"], inputs["context"])

    reloaded = jev_check.load_inputs(run_dir)
    second, _ = jev_check.build_state(reloaded["by_id"]["claim-001"], reloaded["segments"],
                                      reloaded["web"], reloaded["context"])
    assert hashlib.sha256(first.encode()).hexdigest() == hashlib.sha256(second.encode()).hexdigest()


def test_changed_run_data_breaks_the_hash(run_dir):
    """The other half: if the transcript is edited, the hash must NOT still match."""
    import json

    inputs = jev_check.load_inputs(run_dir)
    before, _ = jev_check.build_state(inputs["by_id"]["claim-001"], inputs["segments"],
                                      inputs["web"], inputs["context"])

    from earnings.paths import RunPaths

    RunPaths.at(run_dir).transcript.write_text(json.dumps({
        "id": "seg-0001", "section": "prepared", "speaker": "CFO",
        "text": "This quarter, " + QUOTE + " and margins fell.",
    }) + "\n")
    after_inputs = jev_check.load_inputs(run_dir)
    after, _ = jev_check.build_state(after_inputs["by_id"]["claim-001"], after_inputs["segments"],
                                     after_inputs["web"], after_inputs["context"])
    assert hashlib.sha256(before.encode()).hexdigest() != hashlib.sha256(after.encode()).hexdigest()


def test_segment_claims_carry_no_evidence_note(run_dir):
    """Only web evidence is windowed. A segment is one speaker turn and goes in whole."""
    inputs = jev_check.load_inputs(run_dir)
    _, note = jev_check.build_state(inputs["by_id"]["claim-001"], inputs["segments"],
                                    inputs["web"], inputs["context"])
    assert note is None


def test_claim_record_omits_what_python_already_compares():
    """Ids and speaker are not in a state, so they are not in the stored record either.

    Asking Jev about a speaker once had it comparing two identical strings the payload
    builder had itself inserted -- it scored 0.96 and proved nothing.
    """
    rec = jev_check.claim_record({
        "id": "claim-001", "speaker": "CFO", "segment_id": "seg-0001",
        "web_evidence_id": None, "quote": QUOTE, "claim_text": "Revenue rose.",
    })
    assert set(rec) == {"quote", "claim_text"}


def test_stored_record_matches_the_one_the_state_carried(run_dir):
    """The log's copy must be the same object the state embedded, not a paraphrase."""
    import json

    inputs = jev_check.load_inputs(run_dir)
    claim = inputs["by_id"]["claim-001"]
    state, _ = jev_check.build_state(claim, inputs["segments"], inputs["web"],
                                     inputs["context"])
    stored = jev_check.claim_record(claim)
    assert json.dumps(stored, indent=2) in state


def test_stored_record_reveals_what_a_re_extraction_changed(run_dir):
    """Why the record is copied and the segment is not: this is the half that mutates."""
    import json

    from earnings.paths import RunPaths

    before = jev_check.claim_record(jev_check.load_inputs(run_dir)["by_id"]["claim-001"])

    paths = RunPaths.at(run_dir)
    edited = json.loads(paths.claims.read_text())
    edited[0]["values"] = {"revenue_billions": 81.4}   # a re-extraction nudges a figure
    paths.claims.write_text(json.dumps(edited))

    after = jev_check.claim_record(jev_check.load_inputs(run_dir)["by_id"]["claim-001"])
    changed = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
    assert changed == ["values"], "the stored record is what makes the change visible"


def test_dry_run_writes_nothing_and_needs_no_key(run_dir, monkeypatch, capsys):
    """Auditing a run must not alter that run's record.

    Verifying the log format previously required real calls, each of which appended to
    a git-tracked historical log and dropped a triage file into a real run directory.
    Both then had to be undone by hand.
    """
    import sys

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv",
                        ["jev_check.py", str(run_dir), "--mode", "claims", "--dry-run"])

    def refuse(*a, **k):
        raise AssertionError("a dry run must not call the API")

    monkeypatch.setattr(jev_check, "post", refuse)
    before = {p: p.read_bytes() for p in run_dir.rglob("*") if p.is_file()}

    assert jev_check.main() == 0

    after = {p: p.read_bytes() for p in run_dir.rglob("*") if p.is_file()}
    assert after == before, "the dry run altered the run directory"
    assert not (run_dir / "jev_checks.jsonl").exists(), "no call log may be written"
    assert "nothing written" in capsys.readouterr().out


def test_dry_run_row_omits_the_segment_but_keeps_quote_and_claim_text(run_dir, monkeypatch):
    """The split: volatile claim fields verbatim, the immutable segment by reference."""
    import sys

    monkeypatch.setattr(sys, "argv",
                        ["jev_check.py", str(run_dir), "--mode", "claims", "--dry-run"])
    monkeypatch.setattr(jev_check, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))

    captured = {}
    real = jev_check.report_dry_run
    monkeypatch.setattr(jev_check, "report_dry_run",
                        lambda rows, mode, cost: captured.setdefault("rows", rows))
    jev_check.main()

    req = captured["rows"][0]["request"]
    record = req["state_inputs"]["claim_record"]
    assert record["quote"] == QUOTE, "the quote is stored verbatim, uncapped"
    assert record["claim_text"], "claim_text is stored verbatim, uncapped"
    assert "segment" not in json.dumps(req["state_inputs"]).lower()
    assert req["state_ref"]["segment_id"] == "seg-0001", "the segment is referenced"
    assert "and margins held" not in json.dumps(req), "no segment prose in the row"
