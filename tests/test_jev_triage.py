"""The rules that decide which Jev answers a human or agent must look at again.

Jev is an investigative tool and gates nothing (see docs/JEV_CHECKS.md), so these
tests are not about correctness of the model's opinion. They pin down the translation
from an answer to an obligation -- particularly the losing-option rule, which is the
only one that fires on an answer that otherwise looks like a pass.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "jev_check", pathlib.Path(__file__).resolve().parents[1] / "scripts/jev_check.py")
jev_check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(jev_check)

CLAIM = {"id": "claim-001", "classification": "reported_fact"}
Q = {"instructions": "is the figure right?"}


def triage(qid: str, answer: dict, claim: dict = CLAIM):
    return jev_check.triage_answer(qid, answer, Q, claim)


# --- noul: a single probability ------------------------------------------------------

ACCEPT = jev_check.config.JEV_AUTO_ACCEPT_THRESHOLD


@pytest.mark.parametrize("p,expected", [
    (0.97, None),               # comfortably accepted
    (ACCEPT, None),             # the threshold itself accepts
    (ACCEPT - 0.01, "check"),   # a hair below is worth a look, not a defect
    (0.48, "defect"),           # below an even chance: Jev disagrees outright
])
def test_noul_is_flagged_below_the_accept_threshold(p, expected):
    item = triage("value__revenue", {"type": "noul", "noul": p})
    assert (item or {}).get("severity") == expected if expected else item is None


# --- choice: the interesting one -----------------------------------------------------

def test_choice_flags_a_defect_when_the_wrong_option_wins():
    item = triage("citation_supports_passage", {
        "type": "choice", "choice": "says_nothing", "confidence": 0.62,
        "probabilities": {"says_nothing": 0.75, "supports": 0.14, "contradicts": 0.11}})
    assert item["severity"] == "defect"
    assert "says_nothing" in item["why"] and "supports" in item["why"]


def test_choice_flags_a_losing_option_that_still_holds_real_probability():
    """The rule that earns its keep: supports won, so nothing else would notice."""
    item = triage("citation_supports_passage", {
        "type": "choice", "choice": "supports", "confidence": 0.73,
        "probabilities": {"supports": 0.66, "says_nothing": 0.33, "contradicts": 0.01}})
    assert item["severity"] == "check"
    assert "33%" in item["why"] and "says_nothing" in item["why"]


def test_choice_is_clean_when_the_right_option_wins_decisively():
    assert triage("citation_supports_passage", {
        "type": "choice", "choice": "supports", "confidence": 0.87,
        "probabilities": {"supports": 0.92, "contradicts": 0.08, "says_nothing": 0.0}}) is None


def test_choice_flags_a_diffuse_win_even_with_no_single_strong_rival():
    item = triage("citation_supports_passage", {
        "type": "choice", "choice": "supports", "confidence": 0.55,
        "probabilities": {"supports": 0.94, "contradicts": 0.03, "says_nothing": 0.03}})
    assert item["severity"] == "check"
    assert "confidence" in item["why"]


def test_classification_is_compared_against_the_claim_not_a_fixed_option():
    """Jev picks a label; the record it disagrees with is the claim's own."""
    answer = {"type": "choice", "choice": "management_guidance", "confidence": 1.0,
              "probabilities": {"management_guidance": 1.0, "reported_fact": 0.0}}
    assert triage("classification", answer, CLAIM)["severity"] == "defect"
    assert triage("classification", answer, {"classification": "management_guidance"}) is None


# --- score: a position on a labelled ladder ------------------------------------------

LEGEND = {"0": "captures none", "1": "omits a material figure",
          "2": "omits a minor figure", "3": "captures every figure"}


@pytest.mark.parametrize("value,expected", [(2.98, None), (2.7, None), (2.4, "check"), (1.4, "defect")])
def test_score_is_flagged_by_distance_from_the_top_rung(value, expected):
    item = triage("values_capture", {"type": "score", "score": value, "legend": LEGEND})
    assert (item or {}).get("severity") == expected if expected else item is None


def test_score_quotes_the_rung_it_landed_on(): 
    item = triage("values_capture", {"type": "score", "score": 1.4, "legend": LEGEND})
    assert "omits a material figure" in item["why"]


# --- assembling a whole run ----------------------------------------------------------

def _row(subject, answers, status="ok"):
    return {"subject": subject, "claim_id": subject, "status": status,
            "generation_id": "gen-1", "answers": answers}


def test_build_triage_sorts_defects_first_and_counts_both_tiers():
    rows = [
        _row("claim-002", {"value__x": {"type": "noul", "noul": ACCEPT - 0.05}}),
        _row("claim-001", {"value__x": {"type": "noul", "noul": 0.2}}),
        _row("claim-003", {"value__x": {"type": "noul", "noul": 0.99}}),  # clean, never flagged
    ]
    out = jev_check.build_triage(rows, {}, {}, "claims")
    assert [i["claim_id"] for i in out["items"]] == ["claim-001", "claim-002"]
    assert out["counts"] == {"audited": 3, "flagged": 2, "defect": 1, "check": 1}
    assert out["items"][0]["key"] == "claim-001::value__x"


def test_build_triage_skips_failed_calls():
    """An HTTP error is a tool problem, not a finding about the claim."""
    rows = [_row("claim-001", {}, status="error")]
    assert jev_check.build_triage(rows, {}, {}, "claims")["counts"]["flagged"] == 0


def test_build_triage_quotes_the_question_that_was_actually_sent():
    rows = [_row("claim-001", {"value__x": {"type": "noul", "noul": 0.1}})]
    payloads = {"claim-001": {"value__x": {"instructions": "is values['x'] right?"}}}
    out = jev_check.build_triage(rows, payloads, {}, "claims")
    assert out["items"][0]["asked"] == "is values['x'] right?"


def test_score_quotes_the_rung_below_not_the_nearest_one():
    """2.52 rounds up to 'captures every figure', which would contradict the flag."""
    item = triage("values_capture", {"type": "score", "score": 2.52, "legend": LEGEND})
    assert "omits a minor figure" in item["why"]
