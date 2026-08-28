---
name: review-earnings-run
description: Dispatch the Outlook_Reviewer subagent (Opus) for a final semantic audit of a completed run's outlook brief, then validate and render its verdict. Use only after earnings validate-outlook has already passed.
---

# Review Earnings Run

Use this skill after `earnings validate-outlook` has passed for a run. It runs the
one stage that judges meaning rather than structure: is each claim a fair reading
of its quote, does the outlook narrative fairly represent the evidence, is anything
material omitted.

## Steps

1. **Confirm the prerequisite passed.** `run_dir/validation.json` must have
   `"ok": true`, `run_dir/outlook-validation.json` must have `"ok": true` (the
   gate `earnings validate-outlook` writes -- it hash-binds
   `outlook_brief_sha256`/`claims_sha256` to the current files, so a stale or
   hand-edited brief/claims fails here), and `run_dir/outlook-brief.md` must
   exist. If any is missing, stop and go back to `produce-earnings-signal-card`
   first — do not dispatch the reviewer against an unvalidated run.

2. **Determine the review round.** Check whether
   `run_dir/_review_history/` has any `round-*` snapshots.
   - **None exist:** this is round 1. Proceed exactly as step 3 below (full
     review) — nothing else changes.
   - **Any exist:** run
     ```bash
     uv run earnings review-diff --ticker <TICKER> --event-id <EVENT_ID>
     ```
     - **Exit 0:** `review-diff.json` was written. Go to step 3, but when
       dispatching the subagent, additionally tell it explicitly that
       `review-diff.json` exists in the run directory and must be read FIRST,
       before deciding how to proceed. (The subagent's own file,
       `.claude/agents/outlook-reviewer.md`, carries the detailed instructions
       for what to do with it.)
     - **Exit 3:** Python auto-escalated to a full review (too many claims
       changed, a changed claim's period/values differ, or a conclusion-bearing
       brief section cites a changed claim). Dispatch a full review exactly as
       round 1 — ignore `review-diff.json`'s existence for this dispatch.
     - **Exit 2:** the review round cap (`config.toml [review]
       max_review_rounds`) has been reached. **Stop. Do not dispatch anything
       further.** Report to the user that the cap was reached, and surface the
       findings from the last `review-report.json` (whatever its verdict) —
       never claim the run is complete, never silently drop the findings.

3. **Dispatch the subagent.** Use the `Agent` tool with `subagent_type:
   "outlook-reviewer"`. Give it the run directory path (e.g.
   `runs/MSFT/2026-q2/`) and nothing else — it's a fresh context by design and
   reads the full bundle itself per its own agent definition
   (`.claude/agents/outlook-reviewer.md`). Do not summarize prior drafting
   decisions to it; it should judge the finished artifact on its own merits.
   (For a diff-based round, per step 2 above, also tell it `review-diff.json`
   exists and should be read first.)

4. **Wait for `review-report.json`.** The subagent writes only this file — never a
   `.md` file, never edits to `claims.json`/`outlook-brief.md` themselves. If it
   returns without writing the file, treat that as a failed dispatch and retry once
   before escalating to the user.

5. **Run the deterministic gate IMMEDIATELY — before touching claims.json or
   outlook-brief.md for any correction.** This step snapshots the round under
   `_review_history/round-<N>/` for the next `review-diff`. Run it out of order
   (correcting first, running this after) and the snapshot captures your
   *corrected* files against the *old* verdict, silently corrupting round
   history for every future diff-review on this run — the diff will show no
   changes even though real corrections happened, because there is nothing
   left to diff against. Do this step before any drafting work, no exceptions.
   ```bash
   uv run earnings check-review --ticker <TICKER> --event-id <EVENT_ID>
   ```
   This validates `review-report.json`'s schema, checks every claim id it cites
   against `claims.json` (same non-negotiable rule as every other citation check in
   this pipeline), cross-checks the declared `verdict` against the `severity` of
   the reviewer's own findings (`"pass"` requires nothing above `low`,
   `"pass_with_warnings"` requires no `high`/`critical`), enforces the round cap
   even if `review-diff` was somehow skipped, and — only if all of that passes —
   renders `review-report.md` deterministically from the validated JSON, then
   snapshots this round under `_review_history/round-<N>/` for any future
   diff-review.

6. **Report the verdict to the user.**
   - Exit 0 (`pass`): report clean, no action needed.
   - Exit 1 (`pass_with_warnings`): report the warnings from `review-report.md`
     explicitly — the run can be considered complete, but the user should see them.
   - Exit 2 (`fail`, a schema/citation problem, a verdict/severity inconsistency,
     or the round cap being reached): the run is **not** complete. Do not mark it
     done or hand it off as final. Go back to
     Stage 2 drafting for a revision addressing the specific findings (or Stage 1,
     if the finding is about a claim itself), then re-run this skill **from step
     2** (the round-determination step must run again before re-dispatching —
     never assume the same round type as last time). Never silently rewrite
     `outlook-brief.md` on the reviewer's behalf — a human or the drafting step
     should see the specific finding and decide the fix.
   - Exit 3 (`escalate_full_review` set by the reviewer): the diff-based review
     was judged insufficient. Immediately re-dispatch a full review (go to step
     3, full-review branch). Note this DOES consume a round slot toward
     `max_review_rounds` — the escalated attempt is snapshotted like any other
     completed round, so the full review that follows it is the next round
     number, not a free retry. There is no partial-credit *verdict* for the
     diff attempt (it can't pass or fail the run), but it does count against
     the cap — an early, honest escalation is still better than a wrong
     verdict, but it isn't free.

## Reference files

- `reference/reviewer-judgment-remit.md` — the canonical judgment contract the
  `outlook-reviewer` subagent reads (what to judge, run bundle, diff-based
  re-review, output rules). Shared with Codex's `review-outlook-brief` skill —
  one copy, not two independently drifting ones.
- `reference/review-report-schema.md` — the `ReviewReport`/`ReviewFinding` JSON
  shape and severity guidance, for both the reviewer subagent and anyone reading
  its output.
