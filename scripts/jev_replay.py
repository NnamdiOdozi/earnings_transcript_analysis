#!/usr/bin/env python3
"""Rebuild the exact state a logged Jev call was sent, and prove it still matches.

Why this exists: `jev_checks.jsonl` stores a sha256 of the state, not the state. The
hash is a good integrity check but it cannot tell you WHAT was sent, and it cannot say
whether a mismatch means the run directory changed or the state builder did. This tool
answers both -- it re-derives the state from the run directory using the same builders
the auditor used, and it compares the logged `code_version` to the current one.

    uv run python scripts/jev_replay.py runs/JPM/2026-q2-rerun
    uv run python scripts/jev_replay.py runs/JPM/2026-q2-rerun --subject claim-001 -v

Exit code is 1 if any row fails to reproduce, so this can gate a release.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

# jev_check.py is a script, not a package module, so load it by path rather than
# duplicating its builders here. Its builders ARE the definition of a state.
_spec = importlib.util.spec_from_file_location("jev_check", _HERE / "jev_check.py")
jc = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(jc)
except SystemExit:  # its argparse never runs on import, but be safe
    pass


def rebuild_state(row: dict, inputs: dict) -> str | None:
    """The state this row's call would be sent today, or None if not reconstructible.

    Each mode has its own builder, so each needs its own rebuild. Keyed off the logged
    subject rather than re-deriving a whole job list -- a job list depends on CLI flags
    (--limit, --coverage-scope) that the row does not record.
    """
    mode = row.get("check_mode") or "claims"
    subject = row.get("subject") or row.get("claim_id")
    by_id, segments, context = inputs["by_id"], inputs["segments"], inputs["context"]

    if mode == "claims":
        claim = by_id.get(row.get("claim_id"))
        if claim is None:
            return None
        state, _ = jc.build_state(claim, segments, inputs["web"], context)
        return state

    if mode == "coverage":
        if subject not in segments:
            return None
        order = [json.loads(l)["id"] for l in inputs["paths"].transcript.open()]
        pos = {sid: i for i, sid in enumerate(order)}
        i = pos[subject]
        preceding = [segments[order[j]] for j in range(max(0, i - 2), i)]
        return jc.build_coverage_payload(segments[subject], context, preceding)["state"]

    if mode == "citations":
        brief_path = jc.RunPaths.at(inputs["run_dir"]).outlook_brief
        if not brief_path.exists():
            return None
        for passage, cid, key in jc.citation_pairs(brief_path.read_text(), by_id):
            if key == subject:
                return jc.build_citation_payload(passage, by_id[cid])["state"]
        return None

    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", help="run directory whose jev_checks.jsonl to replay")
    ap.add_argument("--subject", help="replay only this claim id or segment id")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="on a mismatch, print the logged window beside the rebuilt one")
    args = ap.parse_args()

    run_dir = pathlib.Path(args.run_dir)
    log = run_dir / "jev_checks.jsonl"
    if not log.exists():
        return print(f"no call log at {log}") or 1

    inputs = jc.load_inputs(run_dir)
    inputs["run_dir"] = run_dir
    current = jc.code_version()

    counts = {"match": 0, "mismatch": 0, "unreplayable": 0, "pre_replay": 0}
    for line in log.open():
        row = json.loads(line)
        req = row.get("request") or {}
        subject = row.get("subject") or row.get("claim_id")
        if args.subject and subject != args.subject:
            continue

        # Rows written before this tool existed carry no questions or state_ref. They
        # are still hash-checkable, but a mismatch cannot be attributed.
        legacy = "questions" not in req
        logged_hash = req.get("state_sha256")
        state = rebuild_state(row, inputs)

        if state is None:
            counts["unreplayable"] += 1
            print(f"  {subject:28} UNREPLAYABLE   its claim or segment is no longer in the run")
            continue

        rebuilt = hashlib.sha256(state.encode()).hexdigest()
        if rebuilt == logged_hash:
            counts["pre_replay" if legacy else "match"] += 1
            if args.verbose:
                print(f"  {subject:28} MATCH")
            continue

        counts["mismatch"] += 1
        logged_cv = row.get("code_version") or {}
        if logged_cv and logged_cv.get("builders_sha256") != current["builders_sha256"]:
            why = (f"the state BUILDER changed "
                   f"({logged_cv.get('builders_sha256')} -> {current['builders_sha256']})")
        elif legacy:
            why = "row predates code_version stamping, so the cause cannot be attributed"
        else:
            why = "the builder is unchanged, so the RUN DATA changed"
        print(f"  {subject:28} MISMATCH       {why}")
        if args.verbose and req.get("state_inputs"):
            # The claim record as it stood, beside the one on disk now -- this is what
            # a re-extraction changes, and the diff a human actually needs to see.
            logged = (req["state_inputs"] or {}).get("claim_record")
            current = jc.claim_record(inputs["by_id"].get(row.get("claim_id"), {}))
            for field in sorted(set(logged or {}) | set(current or {})):
                was, now = (logged or {}).get(field), (current or {}).get(field)
                if was != now:
                    print(f"      {field}: logged {was!r} -> now {now!r}")

    total = sum(counts.values())
    print(f"\n{total} row(s): {counts['match']} match, {counts['pre_replay']} match "
          f"(pre-replay rows, unattributable), {counts['mismatch']} mismatch, "
          f"{counts['unreplayable']} unreplayable")
    print(f"current builders: {current['builders_sha256']} at commit {current['git_commit']}")
    return 1 if counts["mismatch"] or counts["unreplayable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
