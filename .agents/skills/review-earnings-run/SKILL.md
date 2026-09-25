---
name: review-earnings-run
description: Dispatch the Outlook_Reviewer subagent (Opus) for a final semantic audit of a completed run's claims and outlook brief, then validate and render its verdict. Use only after earnings validate-outlook has already passed.
---

# Review Earnings Run (Claude Code)

Use this skill after `earnings validate-outlook` has passed for a run. It runs the one
stage that judges meaning rather than structure: is each claim a fair reading of its
cited context, does the outlook narrative fairly represent the evidence, is anything
material omitted.

**Follow `reference/review-round-procedure.md` for the round itself** — prerequisites,
round determination, the deterministic gate and its exit codes. That file is shared with
the Codex path; this one covers only what is specific to dispatching Claude Code's
subagent, which is its step 3.

## Step 3: dispatch the subagent — path only

Use the `Agent` tool with `subagent_type: "outlook-reviewer"`. The entire dispatch
prompt must be the run directory path (e.g. `runs/MSFT/2026-q2/`) plus, for a
diff-eligible round only, the single sentence that `review-diff.json` exists and must be
read first. **Nothing else.** Do not narrate prior findings, do not describe how you
fixed them, do not point at "the sections to look at harder" — not even framed as
helpful context for verifying that a fix landed.

This is not a style preference; it's load-bearing. Confirmed failure mode (LLOY/2026-h1,
2026-09-01): the dispatch prompts for rounds 2 and 3 included a detailed rundown of the
previous round's findings and exactly how each was fixed. Both rounds correctly confirmed
those specific fixes — and both missed citation-precision errors (a claim id that
resolves but is the *wrong* claim for that sentence) that had been sitting unchanged in
the brief since the first draft, through two prior full reviews. The likely mechanism:
narrating "here's what changed and why" concentrates the reviewer's attention on
verifying that narrative, instead of giving the rest of a long brief with dozens of
citations equally fresh scrutiny — even though the remit instructs an independent read.

`review-diff.json` already tells the reviewer mechanically what changed, and the remit
tells it which of that file's fields to use and which not to be steered by. It does not
need your account of why. A full review should be told nothing about earlier rounds at
all; it reads the full bundle itself, per its own agent definition
(`.claude/agents/outlook-reviewer.md`).

## Reference files

- `reference/review-round-procedure.md` — the canonical round mechanics (steps 1-2 and
  4-6). Shared with `review-earnings-run-codex`.
- `reference/reviewer-judgment-remit.md` — the canonical judgment contract the
  `outlook-reviewer` subagent reads: what to judge, the run bundle, diff-based
  re-review, output rules. Also shared with the Codex skill — one copy, not two
  independently drifting ones.
- `reference/review-report-schema.md` — the `ReviewReport`/`ReviewFinding` JSON shape and
  severity guidance, for both the reviewer subagent and anyone reading its output.
