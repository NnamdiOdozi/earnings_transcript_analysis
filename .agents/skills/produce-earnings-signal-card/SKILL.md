---
name: produce-earnings-signal-card
description: Read an existing earnings source pack, extract quote-anchored claims into claims.json, run deterministic validation, produce signal-card.md, then write an agent-authored outlook-brief.md gated on claim-id citations.
---

# Produce Earnings Signal Card

Use this skill on a source pack already built by `build-earnings-source-pack`. Do
**not** browse the web or fetch new sources in this skill — work only from
`normalized/transcript.jsonl` and `evidence/financials.json` already on disk.

## Fresh extraction is the default

Starting work on a newly prepared source pack means extracting and synthesising
from that pack from scratch. Do not read, copy, adapt, remap, or use as a draft any
prior `claims.json`, `metrics.json`, `signal-card.md`, or `outlook-brief.md` from
`_archive/`, `_review_history/`, another event directory, or an earlier run. The
fact that the company or earnings event is unchanged is not permission to reuse
agent-authored work.

Reuse is allowed only when the user explicitly authorizes it for the current run.
Silence, a request to rerun, or a request to correct validation errors is not reuse
consent. If reuse is authorized, state exactly which artifacts will be reused and
disclose that provenance in the final report.

Correcting the current run's `claims.json` or `metrics.json` after a failed
deterministic validation is not prior-run reuse; it is the normal attempt loop in
steps 6–7 below. If prior outputs have already been exposed in the active agent's
context and the user requires an independent fresh extraction, use a fresh-context
agent when available. Otherwise, disclose that strict independence cannot be
guaranteed before proceeding.

## Stage 1: evidence extraction

1. **Read past lessons, if any.** If `.agents/memory/extractor-lessons.md` exists,
   read it before extracting. It holds one-line process lessons the reviewer has
   flagged as generalizable mistakes from prior runs — how to check your own work,
   never facts, quotes, or numbers to reuse. This is not the "fresh extraction"
   rule being relaxed: you still extract this run's claims from this run's evidence
   only; the lessons just tell you what to watch for while doing so.

2. **Load the pack.** Read `runs/<TICKER>/<EVENT_ID>/normalized/transcript.jsonl`
   (one JSON segment per line: `id`, `section`, `speaker`, `text`) and
   `evidence/financials.json` if present.

3. **Extract claims.** Follow `reference/extraction-instructions.md` for the generic
   (industry-agnostic) categories, classification taxonomy, and how to write exact
   quotes and calculation blocks. Write the result as
   `runs/<TICKER>/<EVENT_ID>/claims.json`, an array of claim objects matching
   `earnings.models.Claim`, each with a unique `id`. Every claim cites exactly one
   evidence source and a `quote` that is an exact substring of it: normally a
   transcript `segment_id`, but **when the run has web evidence
   (`evidence/web-evidence.jsonl`), use it** — cite `web_evidence_id` for facts the
   call itself does not contain, above all the **analyst consensus/expectations** (so
   the beat-or-miss "surprise" can be a claim) and **peer-group results** (see
   `reference/extraction-instructions.md` "Citing web evidence"). Copy every quote,
   do not retype it. Do not use sector-specific vocabulary that isn't the company's
   own — discover what matters from its disclosures, not from a fixed KPI list.

4. **Optionally discover company-defined metrics.** If the transcript supports it,
   also write `runs/<TICKER>/<EVENT_ID>/metrics.json` per
   `reference/extraction-instructions.md`'s Metric section — every metric must cite
   at least one real claim id.

5. **Self-check before validating.** Reread your own `claims.json` once, end to
   end, before running `earnings analyze`. This is a cheap self-critique pass, not
   a re-extraction: look specifically for speaker attribution errors (an analyst's
   question misattributed as a management statement), period-basis errors
   (quarterly vs. year-to-date/half-year figures conflated), and claims whose
   `claim_text` doesn't actually match what its cited `quote` says in context, not
   just that the quote text exists. Fix anything you find yourself; Python's
   validators below check groundedness, not these judgment errors.

6. **Validate.** Run:

   ```bash
   uv run earnings analyze --ticker <TICKER> --event-id <EVENT_ID>
   ```

   This runs Python's deterministic validators (exact-quote, numeric, calculation,
   inference-citation, metric-provenance, schema) and writes `validation.json`.
   Every invocation also creates a numbered, timestamped folder under
   `_validation_history/`, preserving that attempt's exact `claims.json`, optional
   `metrics.json`, validation result, and receipt. Do not delete or rewrite an old
   attempt when correcting the current files.

7. **If validation fails:** the command exits non-zero and does **not** write
   `signal-card.md`. Read `validation.json`, fix the offending claims/metrics
   (correct the quote, drop an unsupported number, fix a calculation block, add a
   missing citation), and re-run step 6. Do not hand-edit `signal-card.md` directly
   and do not bypass a failed validation by writing the card yourself. The rerun
   becomes the next attempt folder; prior failures remain available for analysis.

8. **If validation passes:** `signal-card.md` is written automatically, grouped by
   category, following `reference/signal-card-template.md`.

## Stage 2: outlook synthesis

Only start this stage once Stage 1's `earnings analyze` has passed.

9. **Write `outlook-brief.md`.** Follow `reference/outlook-brief-template.md`'s
   default structure and freedom envelope. This is interpretive synthesis
   (base/upside/downside cases, what to monitor) — you write it directly, Python
   does not generate it, and you're expected to rank, compare, and draw new
   qualitative conclusions from validated claims, not just restate them. Every claim
   id you cite must exist in this run's `claims.json`, and every material number you
   introduce must be grounded in a claim cited alongside it.

10. **Validate the brief.** Run:

   ```bash
   uv run earnings validate-outlook --ticker <TICKER> --event-id <EVENT_ID>
   ```

   Fails if the underlying claims haven't passed `analyze`, if any cited claim id
   doesn't resolve, or if a material number isn't grounded in a claim cited
   alongside it. Fix and re-run until it passes.

11. **Report back to the user** the run directory path and a brief summary of both
    `signal-card.md` (evidence appendix) and `outlook-brief.md` (the forward-looking
    read).

## Reference files

- `reference/extraction-instructions.md` — claim categories, classification
  taxonomy, Metric discovery, exact quotes, calculation blocks.
- `reference/signal-card-template.md` — the Markdown structure the rendered
  evidence card follows.
- `reference/outlook-brief-template.md` — the freedom envelope, the default outlook
  structure, and the claim-id/numeric-grounding rules `validate-outlook` enforces.
