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
       before deciding how to proceed. (The canonical judgment contract,
       `reference/reviewer-judgment-remit.md`, carries the detailed instructions
       for what to do with it — the subagent reads it directly, you don't need
       to restate it.)
     - **Exit 3:** Python auto-escalated to a full review (too many claims
       changed, a changed claim's period/values differ, `outlook-brief.md`'s
       text changed at all since the last round, or a conclusion-bearing brief
       section cites a changed claim). Dispatch a full review with
       `review_mode: "full"`. The reviewer must still read and hash
       `review-diff.json`, because it is the receipt that selected full-review mode.
     - **Exit 4:** the review round cap (`config.toml [review]
       max_review_rounds`) has been reached. **Stop. Do not dispatch anything
       further.** Report to the user that the cap was reached, and surface the
       findings from the last accepted `_review_history/round-N/review-report.json` (whatever its verdict) —
       never claim the run is complete, never silently drop the findings.

3. **Dispatch the subagent with a minimal prompt — path only.** Use the `Agent`
   tool with `subagent_type: "outlook-reviewer"`. The entire dispatch prompt
   must be the run directory path (e.g. `runs/MSFT/2026-q2/`) plus, for a
   diff-eligible round only, the single sentence that `review-diff.json` exists
   and must be read first. **Nothing else.** Do not narrate prior findings, do
   not describe how you fixed them, do not point at "the sections to look at
   harder" — not even framed as helpful context for verifying a fix landed.

   This is not a style preference; it's load-bearing. Confirmed failure mode
   (LLOY/2026-h1, 2026-09-01): dispatch prompts for rounds 2 and 3 included a
   detailed rundown of the previous round's findings and exactly how each was
   fixed. Both rounds correctly confirmed those specific fixes — and both
   missed citation-precision errors (a claim id that resolves but is the
   *wrong* claim for that sentence) that had been sitting unchanged in the
   brief since the very first draft, through two prior full reviews. The
   likely mechanism: narrating "here's what changed and why" concentrates the
   reviewer's attention on verifying that narrative instead of giving the rest
   of a long brief with dozens of citations equally fresh scrutiny — even
   though the remit instructs an independent read. `review-diff.json` already
   tells the reviewer mechanically what changed (see the remit's diff-based
   re-review section); it does not need your account of why, and a full review
   should never be told anything about earlier rounds at all — reads the full
   bundle itself per its own agent definition
   (`.claude/agents/outlook-reviewer.md`).

4. **Wait for `review-report.json`.** The subagent writes only this file — never a
   `.md` file, never edits to `claims.json`/`outlook-brief.md` themselves. If it
   returns without writing the file, treat that as a failed dispatch and retry once
   before escalating to the user. The report must contain the current claims,
   brief, and later-round diff hashes described by the canonical remit.

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
   - Exit 2 (`fail`, a schema/citation problem, or a verdict/severity
     inconsistency): the run is **not** complete. Do not mark it done or hand
     it off as final. Go back to Stage 2 drafting for a revision addressing the
     specific findings (or Stage 1, if the finding is about a claim itself),
     then re-run this skill **from step 2** (the round-determination step must
     run again before re-dispatching — never assume the same round type as
     last time). Never silently rewrite `outlook-brief.md` on the reviewer's
     behalf — a human or the drafting step should see the specific finding and
     decide the fix.
   - Exit 3 (`escalate_full_review` set by the reviewer): the diff-based review
     was judged insufficient. Immediately re-dispatch a full review (go to step
     3, full-review branch). Note this DOES consume a round slot toward
     `max_review_rounds` — the escalated attempt is snapshotted like any other
     completed round, so the full review that follows it is the next round
     number, not a free retry. There is no partial-credit *verdict* for the
     diff attempt (it can't pass or fail the run), but it does count against
     the cap — an early, honest escalation is still better than a wrong
     verdict, but it isn't free.
   - Exit 4 (round cap reached): **do not treat this like exit 2.** This is not
     "go correct it" — no amount of drafting fixes an exhausted cap. Stop
     entirely, same as step 2's exit-4 handling, and surface the last accepted
     verdict to the user as final for this run.

## Reference files

- `reference/reviewer-judgment-remit.md` — the canonical judgment contract the
  `outlook-reviewer` subagent reads (what to judge, run bundle, diff-based
  re-review, output rules). Shared with Codex's `review-outlook-brief` skill —
  one copy, not two independently drifting ones.
- `reference/review-report-schema.md` — the `ReviewReport`/`ReviewFinding` JSON
  shape and severity guidance, for both the reviewer subagent and anyone reading
  its output.
