---
name: review-earnings-run-codex
description: Codex-side final semantic audit of a completed run's claims and outlook brief, using a fresh subagent when available or a deliberate in-session review pass otherwise. Use only after earnings validate-outlook has already passed.
---

# Review Earnings Run (Codex / non-Claude-Code environments)

Use this skill after `earnings validate-outlook` has passed for a run.

**Follow
`.agents/skills/review-earnings-run/reference/review-round-procedure.md` for the round
itself** — prerequisites, round determination, the deterministic gate and its exit codes.
That file is shared with the Claude Code path; this one covers only what is specific to
running the review as Codex, which is its step 3.

## Step 3: switch role deliberately, then apply the canonical remit

Claude Code has a custom `outlook-reviewer` subagent. In Codex, dispatch a fresh review
subagent when the host exposes that capability. Otherwise apply the same judgment as a
deliberate, separate in-session pass over the finished bundle. In either case, **do not
fold the review into the drafting pass that wrote `outlook-brief.md`.**

Recommended model and reasoning tier for this pass: GPT-5.6, medium reasoning. This is a
judgment task — fair reading, narrative balance, omission-spotting — not a retrieval or
arithmetic one, so don't run it on a fast or low-reasoning tier.

**Read
`.agents/skills/review-earnings-run/reference/reviewer-judgment-remit.md` in full before
starting.** It is the canonical judgment contract, shared with the Claude Code path:
what to judge, the run bundle to read, how a diff-based re-review works, and the exact
output rules. Nothing in it is restated here on purpose — a second copy drifts from the
canonical one over time (confirmed live, 2026-08-29).

Re-read the run bundle fresh, as if you had not drafted it. Do not rely on your memory of
why an earlier drafting decision was made; judge the finished artifact on its own merits.
That independence is harder to hold here than in Claude Code, because you may well be the
same session that wrote the brief — which is exactly why the role switch has to be
deliberate rather than implicit.

## Reference files

Both live under `.agents/skills/review-earnings-run/reference/`, shared with the Claude
Code path:

- `review-round-procedure.md` — the canonical round mechanics (steps 1-2 and 4-6).
- `reviewer-judgment-remit.md` — the canonical judgment contract (step 3 above).
- `review-report-schema.md` — the `ReviewReport`/`ReviewFinding` JSON shape and severity
  guidance.
