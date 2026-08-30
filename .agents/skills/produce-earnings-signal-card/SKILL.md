---
name: produce-earnings-signal-card
description: Read an existing earnings source pack, extract quote-anchored claims into claims.json, run deterministic validation, produce signal-card.md, then write an agent-authored outlook-brief.md gated on claim-id citations.
---

# Produce Earnings Signal Card

Use this skill on a source pack already built by `build-earnings-source-pack`. Do
**not** browse the web or fetch new sources in this skill — work only from
`normalized/transcript.jsonl` and `evidence/financials.json` already on disk.

## Stage 1: evidence extraction

1. **Load the pack.** Read `runs/<TICKER>/<EVENT_ID>/normalized/transcript.jsonl`
   (one JSON segment per line: `id`, `section`, `speaker`, `text`) and
   `evidence/financials.json` if present.

2. **Extract claims.** Follow `reference/extraction-instructions.md` for the generic
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

3. **Optionally discover company-defined metrics.** If the transcript supports it,
   also write `runs/<TICKER>/<EVENT_ID>/metrics.json` per
   `reference/extraction-instructions.md`'s Metric section — every metric must cite
   at least one real claim id.

4. **Validate.** Run:

   ```bash
   uv run earnings analyze --ticker <TICKER> --event-id <EVENT_ID>
   ```

   This runs Python's deterministic validators (exact-quote, numeric, calculation,
   inference-citation, metric-provenance, schema) and writes `validation.json`.
   Every invocation also creates a numbered, timestamped folder under
   `_validation_history/`, preserving that attempt's exact `claims.json`, optional
   `metrics.json`, validation result, and receipt. Do not delete or rewrite an old
   attempt when correcting the current files.

5. **If validation fails:** the command exits non-zero and does **not** write
   `signal-card.md`. Read `validation.json`, fix the offending claims/metrics
   (correct the quote, drop an unsupported number, fix a calculation block, add a
   missing citation), and re-run step 4. Do not hand-edit `signal-card.md` directly
   and do not bypass a failed validation by writing the card yourself. The rerun
   becomes the next attempt folder; prior failures remain available for analysis.

6. **If validation passes:** `signal-card.md` is written automatically, grouped by
   category, following `reference/signal-card-template.md`.

## Stage 2: outlook synthesis

Only start this stage once Stage 1's `earnings analyze` has passed.

7. **Write `outlook-brief.md`.** Follow `reference/outlook-brief-template.md`'s
   10-section structure. This is interpretive synthesis (base/upside/downside cases,
   what to monitor) — you write it directly, Python does not generate it. Every claim
   id you cite must exist in this run's `claims.json`.

8. **Validate the brief.** Run:

   ```bash
   uv run earnings validate-outlook --ticker <TICKER> --event-id <EVENT_ID>
   ```

   Fails if the underlying claims haven't passed `analyze`, or if any cited claim id
   doesn't resolve. Fix and re-run until it passes.

9. **Report back to the user** the run directory path and a brief summary of both
   `signal-card.md` (evidence appendix) and `outlook-brief.md` (the forward-looking
   read).

## Reference files

- `reference/extraction-instructions.md` — claim categories, classification
  taxonomy, Metric discovery, exact quotes, calculation blocks.
- `reference/signal-card-template.md` — the Markdown structure the rendered
  evidence card follows.
- `reference/outlook-brief-template.md` — the 10-section outlook structure and the
  claim-id citation rule `validate-outlook` enforces.
