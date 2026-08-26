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
   `"ok": true` and `run_dir/outlook-brief.md` must exist. If either is missing,
   stop and go back to `produce-earnings-signal-card` first — do not dispatch the
   reviewer against an unvalidated run.

2. **Dispatch the subagent.** Use the `Agent` tool with `subagent_type:
   "outlook-reviewer"`. Give it the run directory path (e.g.
   `runs/MSFT/2026-q2/`) and nothing else — it's a fresh context by design and
   reads the full bundle itself per its own agent definition
   (`.claude/agents/outlook-reviewer.md`). Do not summarize prior drafting
   decisions to it; it should judge the finished artifact on its own merits.

3. **Wait for `review-report.json`.** The subagent writes only this file — never a
   `.md` file, never edits to `claims.json`/`outlook-brief.md` themselves. If it
   returns without writing the file, treat that as a failed dispatch and retry once
   before escalating to the user.

4. **Run the deterministic gate.**
   ```bash
   uv run earnings check-review --ticker <TICKER> --event-id <EVENT_ID>
   ```
   This validates `review-report.json`'s schema, checks every claim id it cites
   against `claims.json` (same non-negotiable rule as every other citation check in
   this pipeline), and — only if that passes — renders `review-report.md`
   deterministically from the validated JSON.

5. **Report the verdict to the user.**
   - Exit 0 (`pass`): report clean, no action needed.
   - Exit 1 (`pass_with_warnings`): report the warnings from `review-report.md`
     explicitly — the run can be considered complete, but the user should see them.
   - Exit 2 (`fail`, or a schema/citation problem in the report itself): the run is
     **not** complete. Do not mark it done or hand it off as final. Go back to
     Stage 2 drafting for a revision addressing the specific findings (or Stage 1,
     if the finding is about a claim itself), then re-run this skill from step 2.
     Never silently rewrite `outlook-brief.md` on the reviewer's behalf — a human
     or the drafting step should see the specific finding and decide the fix.

## Reference files

- `reference/review-report-schema.md` — the `ReviewReport`/`ReviewFinding` JSON
  shape and severity guidance, for both the reviewer subagent and anyone reading
  its output.
