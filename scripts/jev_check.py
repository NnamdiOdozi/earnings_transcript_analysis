"""Audit a run's claims against their own cited evidence using TypeSafe's Jev model.

This is an INVESTIGATIVE TOOL, not a pipeline gate. It blocks nothing, has no bearing
on `earnings analyze`, and a good score here is not validation. Its purpose is to
surface defect classes a deterministic check cannot see, so those classes can then be
turned into real checks in validate.py. See docs/JEV_CHECKS.md.

Every request/response pair is logged to logs/jev_checks.jsonl (cross-run) and to
<run_dir>/jev_checks.jsonl, matching the price_lookups.jsonl convention.

Usage:
    uv run python scripts/jev_check.py runs/JPM/2026-q2-rerun [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from earnings import config  # noqa: E402
from earnings.paths import RunPaths  # noqa: E402

# The five labels come from extraction-instructions.md. Jev cannot judge a
# project-specific taxonomy it has never been shown, so the definitions travel
# with the question -- see docs/JEV_CHECKS.md mistake 2.
CLASSIFICATION_CRITERIA = {
    "reported_fact": "An actual, already-occurred result.",
    "management_guidance": "Forward-looking guidance given by management.",
    "management_opinion": "Management's own interpretation or opinion, not a hard number.",
    "analyst_question": "The substance of what an analyst asked, from Q&A.",
    "analytical_inference": "A conclusion drawn by the analyst writing the record, "
                            "not something anyone on the call stated directly.",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_questions(claim: dict) -> dict:
    """Mixed primitives in one payload: choice, score and noul together.

    Deliberately omits speaker/segment_id checks -- Python compares those exactly, so
    asking Jev is circular and wastes the call (docs/JEV_CHECKS.md mistake 3).
    """
    questions = {
        # choice, not noul: "says_nothing" separates "this claim is wrong" from "this
        # evidence does not speak to it", which a yes/no question collapses into one
        # low score. Wording follows TypeSafe's citation-check cookbook.
        "claim_vs_evidence": {
            "type": "choice",
            "instructions": "How does the source section relate to the claim in claim_text?",
            "criteria": {
                "supports": "The section states the claim or directly implies that it is true",
                "contradicts": "The section states the opposite of the claim or implies it is false",
                "says_nothing": "The section does not address what the claim asserts, either way",
            },
        },
        # choice over the taxonomy, then compare Jev's pick to the record in code --
        # better than asking noul "is this label right?" about a label it cannot define.
        "classification": {
            "type": "choice",
            "instructions": "Which label best describes what kind of statement claim_text is?",
            "criteria": dict(CLASSIFICATION_CRITERIA),
        },
        # score, not noul: capture is genuinely graded, and "some figures captured"
        # is a different situation from "none".
        "values_capture": {
            "type": "score",
            "instructions": "How completely does the values object capture the figures stated in the quote?",
            # score criteria are an ORDERED ARRAY of level descriptions (2-10),
            # lowest to highest -- not an object. An object is rejected with HTTP 400.
            "criteria": [
                "The quote states figures and values captures none of them.",
                "values captures some stated figures but omits at least one material figure.",
                "values captures every material figure but omits a minor or incidental one.",
                "Every figure stated in the quote appears in values.",
            ],
        },
        "claim_text_traceable": {
            "type": "noul",
            "instructions": "Is every assertion in claim_text supported by the quote alone, "
                            "without relying on other parts of the source document?",
            "criteria": {
                "true": "The quote alone carries every figure and qualifier claim_text asserts.",
                "false": "claim_text asserts a figure or qualifier absent from the quote.",
            },
        },
    }
    if claim.get("period"):
        questions["period_correct"] = {
            "type": "noul",
            "instructions": f"The record dates this claim '{claim['period']}'. Is that consistent "
                            "with the call context and the source section?",
            "criteria": {
                "true": "The figures belong to that reporting period.",
                "false": "The figures belong to a different period.",
            },
        }
    for key, value in (claim.get("values") or {}).items():
        if key == "calculation" or not isinstance(value, (int, float)):
            continue
        questions[f"value__{key}"] = {
            "type": "noul",
            "instructions": f"The record extracts values['{key}'] = {value}. Read the quote. Is that "
                            "the correct number for that named metric?",
            "criteria": {
                "true": f"The quote states this exact figure for the metric named '{key}'.",
                "false": "Wrong figure, wrong metric, a lost qualifier such as 'over' or "
                         "'approximately', or the wrong unit or scale.",
            },
        }
    return questions



_CITATION_RE = re.compile(r"\[(claim-\d+)\]")
# The evidence appendix restates each claim's own quote, so checking a citation there
# compares a claim against itself. Only the argued prose is worth judging.
_APPENDIX_RE = re.compile(r"^##\s*10\.\s*Evidence appendix", re.MULTILINE)


def citation_pairs(brief: str, claims_by_id: dict) -> list[tuple[str, str, str]]:
    """(passage, claim_id, passage_key) for every citation in the brief's argued prose.

    A passage is the paragraph or bullet carrying the citation -- enough context for the
    model to judge what the citation is being used to support, which a bare sentence
    often is not.
    """
    cut = _APPENDIX_RE.search(brief)
    body = brief[: cut.start()] if cut else brief
    pairs = []
    for block in [b.strip() for b in body.split("\n\n") if b.strip()]:
        if block.startswith("#"):
            continue
        for cid in dict.fromkeys(_CITATION_RE.findall(block)):
            if cid in claims_by_id:
                pairs.append((block, cid, f"{cid}@{hashlib.sha256(block.encode()).hexdigest()[:8]}"))
    return pairs


def build_citation_payload(passage: str, claim: dict) -> dict:
    """Does the cited claim actually support the point the passage makes?

    `earnings validate-outlook` proves a cited id RESOLVES. It cannot tell a correct
    citation from a plausible wrong one. Confirmed live twice: SBRY/q1-2627 attached a
    transcript quotation to a claim that did not contain it, and JPM/2026-q2-rerun cited
    claim-095 (an analyst's marginal-margin question) to support a sentence about how
    many analysts pressed on operating leverage. Both resolved; both were wrong.
    """
    state = (
        "PASSAGE FROM THE OUTLOOK BRIEF (the point being argued):\n" + passage +
        "\n\nTHE CITED CLAIM:\n" + json.dumps(
            {k: v for k, v in claim.items() if k in ("claim_text", "quote", "classification", "period")},
            indent=2) + "\n"
    )
    return {
        "model": config.JEV_MODEL,
        "state": state,
        "questions": {
            "citation_supports_passage": {
                "type": "choice",
                "instructions": "The passage cites this claim. How does the claim relate to the "
                                "specific point the passage uses it for?",
                "criteria": {
                    "supports": "The claim states, or directly implies, the point the passage cites it for",
                    "contradicts": "The claim states the opposite of that point, or implies it is false",
                    "says_nothing": "The claim is on a related topic but does not address the specific "
                                    "point the passage cites it for",
                },
            },
            "quoted_text_belongs_to_claim": {
                "type": "noul",
                "instructions": "If the passage puts any wording in quotation marks beside this citation, "
                                "does that wording appear in the cited claim's own quote? Answer true if "
                                "the passage quotes nothing.",
                "criteria": {
                    "true": "The passage quotes nothing, or every quoted phrase appears in the claim's quote.",
                    "false": "The passage attributes quoted wording that is not in the cited claim's quote.",
                },
            },
        },
    }


# Lifted from extraction-instructions.md's "What counts as immaterial" AND from the
# five claim classifications, because materiality here is wider than financial content:
# an analyst's question and management's view on succession are both claim-worthy. A
# first cut enumerated only figures/guidance/risk and mislabelled 18 of 66 claim-bearing
# segments as immaterial -- see docs/JEV_CHECKS.md.
MATERIAL_CRITERION = (
    "The segment carries something an equity analyst would record: any figure; any "
    "statement about guidance or outlook, however hedged; management explaining a "
    "reported result; a stated risk, watch area or caveat; management's own view of the "
    "business, its strategy, leadership or succession; or the substance of a question an "
    "analyst asked. A short segment is not immaterial by virtue of being short."
)
IMMATERIAL_CRITERION = (
    "The segment adds nothing an analyst would record. This covers operator logistics and "
    "dial-in instructions, thank-yous and 'next question please', closing pleasantries, "
    "the standard forward-looking-statements disclaimer, a repeated speaker banner, and "
    "short conversational fragments carrying no content of their own -- an interrupted "
    "half-sentence, or bare agreement such as 'Yeah, exactly' or 'I am saying the same thing'."
)


def build_coverage_payload(segment: dict, context: str, preceding: list[dict] | None = None) -> dict:
    """Was a `deliberately_immaterial` row in the coverage receipt the right call?

    validate_coverage_receipt proves every segment id is ACCOUNTED FOR. Its own
    docstring concedes it cannot prove an immaterial judgement was correct, and no
    reviewer is instructed to audit those rows -- the largest unguarded surface left.

    The receipt's own outcome and reason are deliberately kept OUT of the state.
    Telling Jev what the record already concluded invites agreement, and the error that
    matters here is the permissive one: a material segment waved through leaves a hole
    nothing downstream can see.
    """
    # A segment is one speaker turn, so a Q&A answer routinely makes no sense alone:
    # "Yes. You'll see something this year." is guidance only beside the question that
    # drew it. Judging those in isolation mislabelled 11 of 66 claim-bearing segments
    # (docs/JEV_CHECKS.md mistake 4). The preceding turns are for interpretation only --
    # the instructions below pin the judgement to the target segment's own contribution.
    lead = "".join(
        f"[{p['id']}, {p.get('speaker') or 'unattributed'}] {p['text']}\n"
        for p in (preceding or [])
    )
    state = (
        f"CALL CONTEXT: {context}\n\n"
        + (f"PRECEDING TURNS (context only, do not judge these):\n{lead}\n" if lead else "")
        + f"SEGMENT UNDER REVIEW ({segment['id']}, section {segment['section']}, "
          f"speaker {segment.get('speaker') or 'unattributed'}):\n{segment['text']}\n"
    )
    return {
        "model": config.JEV_MODEL,
        "state": state,
        "questions": {
            # choice, not noul: the rival-mass triage rule then does the graded work --
            # "immaterial 0.62 / material 0.38" is the grey zone worth re-reading, and a
            # yes/no probability would collapse that into one number.
            "segment_materiality": {
                "type": "choice",
                "instructions": "Judge only the SEGMENT UNDER REVIEW, reading the preceding "
                                "turns for context. Does that segment contribute anything an "
                                "equity analyst should record as a claim about the business? An "
                                "answer that only makes sense beside the question before it is "
                                "still material if the answer itself carries the content.",
                "criteria": {"material": MATERIAL_CRITERION, "immaterial": IMMATERIAL_CRITERION},
            },
        },
    }


def build_state(claim: dict, segments: dict, web: dict, context: str) -> str:
    if claim.get("segment_id"):
        seg = segments[claim["segment_id"]]
        source = f"SOURCE SEGMENT ({seg['id']}, {seg['section']}):\n{seg['text']}"
    else:
        source = f"SOURCE WEB EVIDENCE ({claim['web_evidence_id']}):\n{web.get(claim['web_evidence_id'], '')}"
    record = {k: v for k, v in claim.items() if k not in ("id", "speaker", "segment_id", "web_evidence_id")}
    return (f"CALL CONTEXT: {context}\n\n{source}\n\n"
            f"EXTRACTED CLAIM RECORD — audit each field separately:\n{json.dumps(record, indent=2)}\n")


# --- triage: turning answers into a list of things to look at again ----------------
#
# The point of this section. Jev's answers used to land in a log file and stop there,
# which is how a run reached the independent reviewer with defects Jev had already
# found. These rules decide which answers the extractor must revisit, and the result is
# written next to the claims so the later stages can see it too.
#
# Three answer shapes need three rules. The subtle one is `choice`: a losing option
# holding real probability mass is a signal even when the winning option is correct.
# "supports 0.82 / says_nothing 0.17" is a pass that deserves a second look.

# For each choice question, the option the extracted record itself implies. `None`
# means "whatever the claim declares", which is how the classification question works.
CHOICE_EXPECTED = {
    "claim_vs_evidence": "supports",
    "citation_supports_passage": "supports",
    "classification": None,
    # only segments the receipt already called immaterial are sent, so the record
    # implies "immaterial"; Jev choosing "material" is a defect by definition.
    "segment_materiality": "immaterial",
}


def _pct(x: float) -> str:
    return f"{x:.0%}"


def triage_answer(qid: str, answer: dict, question: dict, claim: dict) -> dict | None:
    """One Jev answer in, one triage item out -- or None when nothing needs revisiting.

    `question` is the payload that was actually sent, so the item can quote the real
    wording rather than a second copy of it that could drift.
    """
    asked = question.get("instructions", qid)
    kind = answer.get("type")

    if kind == "noul":
        p = answer.get("noul")
        if p is None or p >= config.JEV_AUTO_ACCEPT_THRESHOLD:
            return None
        return {
            "question": qid, "primitive": "noul", "asked": asked, "reading": p,
            "severity": "defect" if p < 0.5 else "check",
            "why": f"Jev puts only {_pct(p)} on this being true.",
        }

    if kind == "choice":
        probs = answer.get("probabilities") or {}
        won = answer.get("choice")
        confidence = answer.get("confidence")
        expected = CHOICE_EXPECTED.get(qid, "supports")
        if expected is None:
            expected = claim.get("classification")
        top = probs.get(won, 0.0)
        # The wrong option won outright: Jev's best reading disagrees with the record.
        if expected is not None and won != expected:
            return {
                "question": qid, "primitive": "choice", "asked": asked,
                "reading": won, "probabilities": probs, "confidence": confidence,
                "severity": "defect",
                "why": (f"Jev's best reading is '{won}' at {_pct(top)}, not the "
                        f"'{expected}' the record implies."),
            }
        # The right option won, but something about HOW it won is unconvincing.
        rivals = {k: v for k, v in probs.items()
                  if k != won and v >= config.JEV_ALTERNATIVE_PROBABILITY_FLOOR}
        if rivals:
            worst = max(rivals, key=rivals.get)
            return {
                "question": qid, "primitive": "choice", "asked": asked,
                "reading": won, "probabilities": probs, "confidence": confidence,
                "severity": "check",
                "why": (f"Jev settled on '{won}' at {_pct(top)} but still put "
                        f"{_pct(rivals[worst])} on '{worst}'."),
            }
        if confidence is not None and confidence < config.JEV_CHOICE_CONFIDENCE_FLOOR:
            return {
                "question": qid, "primitive": "choice", "asked": asked,
                "reading": won, "probabilities": probs, "confidence": confidence,
                "severity": "check",
                "why": (f"Jev picked '{won}' but spread its probability widely "
                        f"(confidence {confidence:.2f})."),
            }
        return None

    if kind == "score":
        value = answer.get("score")
        legend = answer.get("legend") or {}
        if value is None or not legend:
            return None
        top_rung = max(int(k) for k in legend)
        if value >= top_rung - config.JEV_SCORE_SHORTFALL_MARGIN:
            return None
        # The rung BELOW the score, not the nearest one. A 2.52 of 3 rounds up to the
        # top rung, whose text says everything was captured -- so the item read
        # "flagged: every figure appears in values", which is nonsense. The floor rung
        # is the one describing the shortfall being reported.
        nearest = legend.get(str(int(value)), "")
        return {
            "question": qid, "primitive": "score", "asked": asked,
            "reading": value, "top_rung": top_rung,
            "severity": "defect" if value < top_rung - 1 else "check",
            "why": f"Scored {value:.2f} of {top_rung}: {nearest}",
        }

    return None


def build_triage(rows: list[dict], payloads: dict, claims_by_id: dict, mode: str) -> dict:
    """Collect every answer worth revisiting across one whole check run."""
    items = []
    for row in rows:
        if row["status"] != "ok":
            continue
        questions = payloads.get(row["subject"], {})
        claim = claims_by_id.get(row["claim_id"], {})
        for qid, answer in row["answers"].items():
            item = triage_answer(qid, answer, questions.get(qid, {}), claim)
            if item is None:
                continue
            items.append({"key": f"{row['subject']}::{qid}", "subject": row["subject"],
                          "claim_id": row["claim_id"], "generation_id": row["generation_id"],
                          **item})
    order = {"defect": 0, "check": 1}
    items.sort(key=lambda i: (order[i["severity"]], i["claim_id"], i["question"]))
    return {
        "generated_at": _now(), "check_mode": mode, "model": config.JEV_MODEL,
        "thresholds": {
            "auto_accept": config.JEV_AUTO_ACCEPT_THRESHOLD,
            "alternative_probability_floor": config.JEV_ALTERNATIVE_PROBABILITY_FLOOR,
            "choice_confidence_floor": config.JEV_CHOICE_CONFIDENCE_FLOOR,
            "score_shortfall_margin": config.JEV_SCORE_SHORTFALL_MARGIN,
        },
        "counts": {"audited": len(rows), "flagged": len(items),
                   "defect": sum(1 for i in items if i["severity"] == "defect"),
                   "check": sum(1 for i in items if i["severity"] == "check")},
        # Read by the extractor (produce-earnings-signal-card), the brief author and the
        # reviewer. Every item must be answered in jev-dispositions.json before analyze.
        "items": items,
    }


def post(payload: dict, key: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        config.JEV_ENDPOINT, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:400]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir")
    ap.add_argument("--limit", type=int, default=None, help="audit only the first N qualifying claims")
    ap.add_argument("--all-claims", action="store_true",
                    help="audit every claim, not just those carrying values")
    ap.add_argument("--coverage-scope", choices=("immaterial", "extracted"), default="immaterial",
                    help="coverage mode only. immaterial: audit the receipt's immaterial calls "
                         "(the real check). extracted: a CONTROL run over segments that did "
                         "produce claims -- if the question cannot call those material, a clean "
                         "result on the immaterial set means nothing. Writes no triage file.")
    ap.add_argument("--mode", choices=("claims", "citations", "coverage"), default="claims",
                    help="claims: audit claim records against their evidence. "
                         "citations: audit the outlook brief's claim-id citations. "
                         "coverage: audit the segments the coverage receipt called immaterial.")
    args = ap.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set in this shell's environment.")

    run_dir = pathlib.Path(args.run_dir)
    paths = RunPaths.at(run_dir)
    claims = json.loads(paths.claims.read_text())
    segments = {json.loads(l)["id"]: json.loads(l) for l in paths.transcript.open()}
    manifest = json.loads(paths.manifest.read_text())
    context = f"{manifest.get('ticker')} {manifest.get('event_id')} earnings call, event date {manifest.get('event_date')}."

    web = {}
    wp = run_dir / "evidence/web-evidence.jsonl"
    if wp.exists():
        for line in wp.open():
            e = json.loads(line)
            cp = run_dir / e["content_path"]
            web[e["id"]] = cp.read_text(errors="replace")[:12000] if cp.exists() else e.get("title", "")

    by_id = {c["id"]: c for c in claims}
    if args.mode == "coverage":
        receipt = json.loads(paths.coverage_receipt.read_text())
        rows_ = receipt["segments"] if isinstance(receipt, dict) else receipt
        wanted = ("deliberately_immaterial" if args.coverage_scope == "immaterial"
                  else "claims_extracted")
        immaterial = [r["segment_id"] for r in rows_
                      if r.get("outcome") == wanted and r.get("segment_id") in segments]
        # Segments that produced claims have already declared themselves material;
        # asking about them spends calls to confirm what the record already shows.
        order = [json.loads(l)["id"] for l in paths.transcript.open()]
        pos = {sid: i for i, sid in enumerate(order)}
        jobs = [(sid, build_coverage_payload(
                    segments[sid], context,
                    [segments[order[j]] for j in range(max(0, pos[sid] - 2), pos[sid])]), sid)
                for sid in immaterial]
    elif args.mode == "citations":
        brief = RunPaths.at(run_dir).outlook_brief.read_text()
        jobs = [(key_, build_citation_payload(passage, by_id[cid]), cid)
                for passage, cid, key_ in citation_pairs(brief, by_id)]
    else:
        jobs = [(c["id"], {"model": config.JEV_MODEL,
                           "state": build_state(c, segments, web, context),
                           "questions": build_questions(c)}, c["id"])
                for c in claims if args.all_claims or c.get("values")]
    if args.limit:
        jobs = jobs[: args.limit]

    repo_log = pathlib.Path(__file__).resolve().parents[1] / "logs/jev_checks.jsonl"
    repo_log.parent.mkdir(exist_ok=True)
    run_log = run_dir / "jev_checks.jsonl"

    rows, total_cost = [], 0.0
    payloads = {subject: payload["questions"] for subject, payload, _ in jobs}
    for i, (subject, payload, claim_id) in enumerate(jobs, 1):
        status, body = post(payload, key)
        usage = body.get("usage", {})
        total_cost += usage.get("cost", 0) or 0
        answers = {k: v for k, v in (body.get("answers") or {}).items()}
        entry = {
            "timestamp": _now(), "provider": "openrouter", "model": config.JEV_MODEL,
            "run": f"{manifest.get('ticker')}:{manifest.get('event_id')}",
            "check_mode": args.mode, "subject": subject, "claim_id": claim_id,
            "request": {"endpoint": config.JEV_ENDPOINT, "question_count": len(payload["questions"]),
                        "question_ids": sorted(payload["questions"]),
                        "state_sha256": hashlib.sha256(payload["state"].encode()).hexdigest()},
            "status": "ok" if status == 200 else "error", "http_status": status,
            "generation_id": body.get("id"), "error": body.get("error"),
            "usage": {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                      "cost_usd": usage.get("cost")},
            "answers": answers,
        }
        line = json.dumps(entry) + "\n"
        with repo_log.open("a") as f:
            f.write(line)
        with run_log.open("a") as f:
            f.write(line)
        rows.append(entry)
        if i % 10 == 0:
            print(f"  {i}/{len(jobs)}", flush=True)
        time.sleep(config.JEV_REQUEST_PAUSE_SECONDS)

    ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"audited {ok}/{len(rows)} {args.mode} | cost ${total_cost:.4f} | logged to {repo_log} and {run_log}")

    if args.mode == "coverage" and args.coverage_scope == "extracted":
        # A control run's expected answer is the opposite of the triage rule's, so a
        # triage file here would be a lie. Report the distribution instead.
        picks = {}
        for r in rows:
            if r["status"] != "ok":
                continue
            picks[r["answers"]["segment_materiality"]["choice"]] = picks.get(
                r["answers"]["segment_materiality"]["choice"], 0) + 1
        print(f"CONTROL (segments that DID produce claims): {picks}")
        return 0

    triage = build_triage(rows, payloads, by_id, args.mode)
    triage_path = {"citations": paths.outlook_jev_triage,
                   "coverage": paths.jev_coverage_triage}.get(args.mode, paths.jev_triage)
    triage_path.parent.mkdir(parents=True, exist_ok=True)
    triage_path.write_text(json.dumps(triage, indent=2) + "\n")
    c = triage["counts"]
    print(f"triage: {c['flagged']} of {c['audited']} answers need a second look "
          f"({c['defect']} defect, {c['check']} check) -> {triage_path}")
    if c["flagged"]:
        # coverage mode has no dispositions file yet -- it is still investigative, so it
        # asks for a re-read rather than pointing at a disposition workflow that would
        # silently do nothing.
        if args.mode == "coverage":
            print("  Re-read each flagged segment and extract what the receipt missed, or "
                  "record why the immaterial call stands. Jev flags nothing automatically.")
        else:
            print("  Every item must be answered in "
                  f"{(paths.outlook_jev_dispositions if args.mode == 'citations' else paths.jev_dispositions).name} "
                  "before the next stage. Jev flags nothing automatically; a human or agent decides.")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
