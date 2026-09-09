# Pipeline assessment against designing_genai_workflows.md

Date: 2026-09-08
Scope: earnings_transcript_analysis pipeline, assessed against the five-step
method in `designing_genai_workflows.md` (same folder).

## Step 1 — human ownership

Satisfied. README states this is not an investment recommendation. No CLI
command outputs a buy/sell/hold decision. `audit-record.json` is built for a
human approver to read the outcome, not act on the system's behalf.

## Step 2 — deterministic where rules exist

Satisfied, and the strongest part of the design. The README's "What Python
does vs. what the LLM does" table is close to a direct restatement of this
step: quote checks, numeric grounding, hashing, workflow gates are all
Python. Matches the paper's point that there's little value paying a model
to re-derive, probabilistically, something you can specify exactly.

## Step 3 — GenAI only where it earns its place

Satisfied. Only three LLM-authored things exist in the whole pipeline: claim
extraction, outlook synthesis, and the independent review. Everything else
is Python. Narrow footprint, no agents added "because you can."

## Step 4 — risk-proportional controls

Satisfied. Two independent layers: deterministic validation (quote/number/
hash checks) and a second, fresh-context agent review judging fairness,
narrative balance, and completeness. `ReviewDiff.auto_escalated` forcing a
fuller review when a diff-only round can't be judged responsibly is a good
example of a proportional control.

## Step 5 — stop and ask a human when ambiguity is material (GAP)

Not satisfied. This is distinct from step 4: step 4 asks whether GenAI
should do a task and with what controls; step 5 asks whether the system
should pause and hand a decision to a person instead of guessing.

Currently, `escalate_full_review` (`src/earnings/cli.py:1513-1564`) always
escalates to *another AI review round*, never to a human. There is no code
path where the pipeline halts and says "this is ambiguous, a person needs to
decide." The escalation mechanism is a step-4 control (stronger AI check),
not a step-5 control (human-in-the-loop).

If a diff review keeps needing full re-review, or the reviewer's findings
conflict across rounds, that is arguably exactly the "material ambiguity"
step 5 says should go to a person.

Tracked in `DEFERRED_WORK.md` ("No human-escalation path when review is
ambiguous").

## Section 5 — the knowledge loop (GAP, expected for a POC)

The paper's idea that validated GenAI patterns should eventually be promoted
into deterministic code doesn't show up in this project yet. Reasonable for
a POC that hasn't run enough real cycles to surface recurring patterns, but
worth tracking rather than leaving silently absent.

Tracked in `DEFERRED_WORK.md` ("No knowledge-loop mechanism").

## Section 2 — architecture / hand-off principles

Satisfied, arguably better than the paper's own worked example. The run
directory's structured, inspectable artifacts (`manifest.json`,
`claims.json`, `outlook-validation.json`, `review-report.json`,
`audit-record.json`) are a direct implementation of "each stage produces a
structured, inspectable output the next stage can use" — with actual
deterministic validation gates between stages, not just narrowly-scoped
model calls passing prose to each other.

## Bottom line

Steps 1-4 and the architecture/hand-off principles are solidly implemented.
The two gaps (step 5 human-escalation, section 5 knowledge loop) are real
but proportionate to a POC's maturity — both are deferred rather than
ignored, in `DEFERRED_WORK.md`.
