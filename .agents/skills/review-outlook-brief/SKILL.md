---
name: review-outlook-brief
description: Codex-side final semantic audit of a completed run's outlook brief, using a fresh subagent when available or a deliberate in-session review pass otherwise. Use only after earnings validate-outlook has already passed.
---

# Review Outlook Brief (Codex / non-Claude-Code environments)

Claude Code uses its custom `outlook-reviewer` subagent. In Codex, dispatch a
fresh review subagent when the host exposes that capability. Otherwise apply the
same judgment as a deliberate, separate in-session pass over the finished bundle.
In either case, do not fold the review into the drafting pass that wrote
`outlook-brief.md`.

Recommended model/reasoning for this pass: GPT-5.6, medium reasoning. This is a
judgment task (fair reading, narrative balance, omission-spotting), not a
retrieval or arithmetic task -- don't run it on a fast/low-reasoning tier.

**Read
`.agents/skills/review-earnings-run/reference/reviewer-judgment-remit.md` in
full before step 3 below.** It is the canonical judgment contract shared with
the Claude Code path -- what to judge, the run bundle to read, how a
diff-based re-review works, and the exact output rules. Nothing in that file
is restated here on purpose: a second copy drifts from the canonical one over
time (confirmed live, 2026-08-29). This skill only covers what's genuinely
different about running as Codex -- the steps below.

## Steps

1. **Confirm the prerequisite passed.** `run_dir/validation.json` must have
   `"ok": true`, `run_dir/outlook-validation.json` must have `"ok": true` (the
   hash-binding gate `earnings validate-outlook` writes), and
   `run_dir/outlook-brief.md` must exist. If any is missing, stop and go back
   to `produce-earnings-signal-card` first.

2. **Determine the review round.** Check whether `run_dir/_review_history/`
   contains any `round-*` snapshots.
   - **None exist:** this is round 1 -- a full review. Proceed to step 3.
   - **Any exist:** this is a re-review. Run
     ```bash
     uv run earnings review-diff --ticker <TICKER> --event-id <EVENT_ID>
     ```
     - **Exit 0:** `review-diff.json` was written. Read it first in step 3, per
       the canonical file's "Diff-based re-review" section.
     - **Exit 3:** Python auto-escalated to a full review on its own (too many
       claims changed, a changed claim's period/values differ, the brief's text
       changed at all since the last round, or a conclusion-bearing brief
       section cites a changed claim). Read and hash `review-diff.json` as the
       scope-decision receipt, but do a full review with `review_mode: "full"`.
     - **Exit 4:** the review round cap (`config.toml [review]
       max_review_rounds`) is reached. **Stop here.** Do not draft another
       review-report.json. Report to the user that the cap was hit and restate
       the findings from the last accepted `_review_history/round-N/review-report.json` (whatever its
       verdict) -- never claim the run is complete, never drop the findings
       silently.

3. **Deliberately switch role, then apply the canonical judgment remit.**
   Re-read the run bundle fresh, as if you had not drafted it -- see the
   canonical file's "Run bundle to read" and "What you ARE here to judge"
   sections for the full file list and the eleven checks. Do not rely on your
   memory of why an earlier drafting decision was made -- judge the finished
   artifact on its own merits. If `review-diff.json` exists, follow the
   canonical file's "Diff-based re-review" section for how to use it,
   including when to set `escalate_full_review: true` instead of forcing a
   verdict.

4. **Write `review-report.json`**, per the canonical file's "Output" section
   and `reference/review-report-schema.md` (in
   `.agents/skills/review-earnings-run/reference/`, shared with the Claude
   Code path) for the exact shape. Include the required current artifact hashes;
   `check-review` rejects a report copied from another artifact version or round.

5. **Run the deterministic gate IMMEDIATELY -- before touching claims.json or
   outlook-brief.md for any correction.** Run it out of order (correcting
   first, running this after) and the snapshot below captures your *corrected*
   files against the *old* verdict, silently corrupting round history for
   every future diff-review on this run -- the next diff will show no changes
   even though real corrections happened, because there is nothing left to
   diff against. Do this step before any drafting work, no exceptions.
   ```bash
   uv run earnings check-review --ticker <TICKER> --event-id <EVENT_ID>
   ```
   This validates the schema, checks every claim id cited against `claims.json`,
   cross-checks your declared `verdict` against your findings' severities, and
   -- only if that passes -- renders `review-report.md` and snapshots this
   round under `_review_history/round-<N>/` for any future diff-review.

6. **Report the verdict to the user.**
   - Exit 0 (`pass`): report clean, no action needed.
   - Exit 1 (`pass_with_warnings`): report the warnings from `review-report.md`
     explicitly -- the run can be considered complete, but the user should see them.
   - Exit 2 (`fail`, a schema/citation problem, or a verdict/severity
     inconsistency): the run is **not** complete. Go back to Stage 2 drafting
     for a revision addressing the specific findings (or Stage 1, if the finding
     is about a claim itself), then re-run this skill **from step 2** -- the
     round-determination step must run again before you re-review, never assume
     the same round type as last time. Never silently rewrite `outlook-brief.md`
     yourself.
   - Exit 3 (`escalate_full_review` set in step 4): the diff-based review was
     judged insufficient. Immediately redo step 3 onward as a full review. Note
     this DOES consume a round slot toward `max_review_rounds` -- the escalated
     attempt is snapshotted like any other completed round, so the full review
     that follows it is the next round number, not a free retry. There is no
     partial-credit *verdict* for the diff attempt (it can't pass or fail the
     run), but it does count against the cap -- an early, honest escalation is
     still better than a wrong verdict, but it isn't free.
   - Exit 4 (round cap reached): **do not treat this like exit 2.** This is not
     "go correct it" -- no amount of drafting fixes an exhausted cap. Stop
     entirely, same as step 2's exit-4 handling, and surface the last accepted
     verdict to the user as final for this run.

## Reference files

- `.agents/skills/review-earnings-run/reference/reviewer-judgment-remit.md` --
  the canonical judgment contract (steps 3-4 above).
- `.agents/skills/review-earnings-run/reference/review-report-schema.md` -- the
  `ReviewReport`/`ReviewFinding` JSON shape and severity guidance.
