"""Build the JPM coverage receipt from the reviewed segment list and claim citations."""

import json
from collections import defaultdict
from pathlib import Path


RUN_DIR = Path("runs/JPM/2026-q2")

# These are the only segments judged immaterial after the full transcript read.
# Each reason describes the actual content so the judgment remains auditable.
IMMATERIAL_REASONS = {
    "seg-0001": "Document date banner; no company statement or analytical content.",
    "seg-0002": "Operator welcome, recording notice, disclaimer pointer and speaker introduction.",
    "seg-0004": "Operator queue instructions and introduction of the next analyst.",
    "seg-0009": "Operator asks whether the analyst has finished; no substantive content.",
    "seg-0010": "Analyst confirms completion and thanks management.",
    "seg-0011": "Operator introduces the next analyst.",
    "seg-0016": "Analyst closing thanks only.",
    "seg-0017": "Operator introduces the next analyst.",
    "seg-0022": "Analyst acknowledges the answer and closes the exchange.",
    "seg-0023": "Operator introduces the next analyst.",
    "seg-0027": "Analyst acknowledgement only.",
    "seg-0029": "Analyst closing thanks only.",
    "seg-0030": "Operator introduces the next analyst.",
    "seg-0036": "Analyst acknowledges the answer and offers thanks.",
    "seg-0037": "Management closing thanks only.",
    "seg-0038": "Operator introduces the next analyst.",
    "seg-0042": "Brief concurrence with the preceding modeled-deposit-risk answer; no new detail.",
    "seg-0044": "Analyst acknowledges the answer and offers thanks.",
    "seg-0045": "Operator introduces the next analyst.",
    "seg-0047": "Brief assertion repeated with fuller explanation in the following management turns.",
    "seg-0048": "Management acknowledgement while handing over the answer.",
    "seg-0050": "Interrupted handover fragment with no substantive statement.",
    "seg-0052": "Brief agreement with the preceding operating-leverage explanation.",
    "seg-0055": "Analyst acknowledgement only.",
    "seg-0058": "Brief clarification that the speakers agree; no new information.",
    "seg-0059": "Brief agreement only.",
    "seg-0063": "Humorous correction that the executive was an options rather than spot-FX trader; no analytical consequence.",
    "seg-0064": "Analyst closing thanks only.",
    "seg-0065": "Operator introduces the next analyst.",
    "seg-0071": "Analyst closing thanks only.",
    "seg-0072": "Management closing thanks only.",
    "seg-0073": "Operator introduces the next analyst.",
    "seg-0078": "Personal compliment and thanks before the substantive capital-allocation answer.",
    "seg-0080": "Analyst personal aside and closing thanks.",
    "seg-0081": "Personal pleasantry only.",
    "seg-0088": "Operator introduces the next analyst.",
    "seg-0093": "Speaker handover only.",
    "seg-0096": "Analyst agreement, thanks and handover only.",
    "seg-0098": "Closing agreement and thanks only.",
    "seg-0099": "Operator introduces the final analyst.",
    "seg-0105": "Analyst closing thanks only.",
    "seg-0106": "Management closing thanks only.",
    "seg-0107": "Truncated operator closing fragment.",
    "seg-0108": "Management closing thanks only.",
    "seg-0109": "Operator sign-off followed by the standard forward-looking-statements disclaimer.",
}


def main() -> None:
    claims = json.loads((RUN_DIR / "claims/claims.json").read_text())
    claim_ids_by_segment: dict[str, list[str]] = defaultdict(list)
    for claim in claims:
        if segment_id := claim.get("segment_id"):
            claim_ids_by_segment[segment_id].append(claim["id"])

    receipt = []
    segments = [json.loads(line) for line in (RUN_DIR / "normalized/transcript.jsonl").read_text().splitlines()]
    for segment in segments:
        segment_id = segment["id"]
        claim_ids = claim_ids_by_segment.get(segment_id, [])
        if claim_ids:
            receipt.append(
                {
                    "segment_id": segment_id,
                    "outcome": "claims_extracted",
                    "claim_ids": claim_ids,
                    "reason": None,
                }
            )
            continue

        if segment_id not in IMMATERIAL_REASONS:
            raise ValueError(f"Unreviewed segment has neither a claim nor an immaterial reason: {segment_id}")
        receipt.append(
            {
                "segment_id": segment_id,
                "outcome": "deliberately_immaterial",
                "claim_ids": [],
                "reason": IMMATERIAL_REASONS[segment_id],
            }
        )

    extra_reasons = set(IMMATERIAL_REASONS) - {segment["id"] for segment in segments}
    if extra_reasons:
        raise ValueError(f"Reasons supplied for unknown segments: {sorted(extra_reasons)}")

    (RUN_DIR / "claims/coverage-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
