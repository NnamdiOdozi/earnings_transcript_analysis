---
name: produce-earnings-signal-card
description: Read an existing earnings source pack, extract quote-anchored claims into claims.json, run deterministic validation, produce signal-card.md, then write an agent-authored outlook-brief.md gated on claim-id citations.
---

# Produce Earnings Signal Card

> **Read this file and every reference file it names IN FULL before running any
> command or writing any artifact.** If the output is truncated, continue reading in
> numbered chunks until you reach the end. Do not infer the rest from a partial read.
> The reference files are not optional background: `extraction-instructions.md`
> carries the claim schema, the period rules, the exact-quote rule and the coverage
> receipt, and none of them are restated here.

> **Stage 1 is exhaustive, not selective, over the WHOLE source pack.** Extract one
> claim for every material reported fact, guidance statement, management explanation,
> stated risk and substantive Q&A insight the source pack supports — NOT only the
> claims you expect to cite in the outlook brief. "Source pack" means the transcript
> **and** `evidence/financials.json` **and** `evidence/web-evidence.jsonl`. Working
> the transcript exhaustively and then stopping is a real and observed failure: the
> consensus and peer sources were fetched precisely because the call does not contain
> them, so nothing in the transcript will ever prompt you to use them. Those are very different sets and the second is far
> smaller. Deterministic validation proves the claims you submitted are grounded; it
> is structurally blind to the ones you never wrote, so a thin claims file passes
> every gate exactly as cleanly as a complete one. Confirmed live (JPM/2026-q2): an
> agent working from a partial read of this skill produced roughly a quarter of the
> material claims the same pack supports, and every gate passed.

Use this skill on a source pack already built by `build-earnings-source-pack`. Do
**not** browse the web or fetch new sources in this skill — work only from
`normalized/transcript.jsonl` and `evidence/financials.json` already on disk.

## Fresh extraction is the default

Starting work on a newly prepared source pack means extracting and synthesising
from that pack from scratch. Do not read, copy, adapt, remap, or use as a draft any
prior `claims.json`, `metrics.json`, `signal-card.md`, or `outlook-brief.md` from
`_archive/`, `review/history/`, another event directory, or an earlier run. The
fact that the company or earnings event is unchanged is not permission to reuse
agent-authored work.

Reuse is allowed only when the user explicitly authorizes it for the current run.
Silence, a request to rerun, or a request to correct validation errors is not reuse
consent. If reuse is authorized, state exactly which artifacts will be reused and
disclose that provenance in the final report.

Correcting the current run's `claims.json` or `metrics.json` after a failed
deterministic validation is not prior-run reuse; it is the normal attempt loop in
steps 7–8 below. If prior outputs have already been exposed in the active agent's
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

3. **Extract claims — over every segment, not a sample.** Work through
   `normalized/transcript.jsonl` from the first segment to the last. For each one,
   either extract the claim(s) it supports or consciously judge it immaterial; do not
   skim for the highlights and stop. Prepared remarks are usually one long segment
   carrying many separate reportable facts — a single claim for the whole of it is
   under-extraction, not summary. Q&A answers routinely contain guidance, an
   explanation and a risk in the same turn; each is its own claim.
   Then do the same for `evidence/web-evidence.jsonl`, which no transcript segment
   will ever point you at. Those sources are the pre-event consensus and the peer
   results, and they exist to support the two claim types the call cannot: the
   **surprise** (reported actual versus what was expected) and **peer comparison**
   (how this quarter reads against competitors reporting the same period). If you
   finish extraction having cited none of the peers, you have not finished.
   Follow `reference/extraction-instructions.md` for the generic
   (industry-agnostic) categories, classification taxonomy, how to write exact
   quotes and calculation blocks, and **how to populate `values`**. Exhaustive
   coverage is about claims AND their fields: a reported-fact or guidance claim that
   quotes a financial figure must carry that figure in `values` as a flat
   key -> number. Validation now fails such a claim if `values` is empty.
   Write the result as
   `runs/<TICKER>/<EVENT_ID>/claims/claims.json`, an array of claim objects matching
   `earnings.models.Claim`, each with a unique `id`. Every claim cites exactly one
   evidence source and a `quote` that is an exact substring of it: normally a
   transcript `segment_id`, but **when the run has web evidence
   (`evidence/web-evidence.jsonl`), use it** — cite `web_evidence_id` for facts the
   call itself does not contain, above all the **analyst consensus/expectations** (so
   the beat-or-miss "surprise" can be a claim) and **peer-group results** (see
   `reference/extraction-instructions.md` "Citing web evidence"). Copy every quote,
   do not retype it. Do not use sector-specific vocabulary that isn't the company's
   own — discover what matters from its disclosures, not from a fixed KPI list.
   If you hit a genuine gap the transcript/SEC/web evidence can't fill (e.g. you
   need a price series), `src/earnings/prices.py` has three functions available
   at your discretion, not part of `prepare`/`analyze`. Default to
   `get_price_series(ticker, run_dir=...)` (Yahoo Finance, free, no API key) for
   a plain price query; reach for `get_price_series_fmp(ticker, days=365,
   run_dir=...)` or `get_price_series_alpha_vantage(ticker, compact=True,
   run_dir=...)` specifically when Yahoo has no data for the symbol, or you need
   something those two providers offer beyond price. All three return daily
   OHLCV as `{date, open, high, low, close, volume}` dicts. Always pass
   `run_dir=runs/<TICKER>/<EVENT_ID>` (this run's own directory) so the call —
   request and full response, API key redacted — is logged into this run's own
   `price_lookups.jsonl`, not just the cross-run
   `logs/price_lookups.jsonl`.

4. **Write the coverage receipt.** Record `coverage-receipt.json` beside
   `claims.json`, accounting for every segment id in `normalized/transcript.jsonl`
   **and** every id in `evidence/web-evidence.jsonl` — each either produced claims or
   was deliberately judged immaterial, with a one-line reason for each immaterial
   call. See `reference/extraction-instructions.md`'s
   "Coverage receipt" section for the exact fields and for what counts as immaterial.
   Write it from the segment list, not from memory of what you extracted — building it
   the other way round reproduces whatever you already missed. `earnings analyze`
   checks this file and **fails** if any segment id or web evidence id is unaccounted
   for, or if a row names an id that does not exist. What it cannot check is whether
   a `deliberately_immaterial` call was *right* — that judgement is audited in step 7.

5. **Optionally discover company-defined metrics.** If the transcript supports it,
   also write `runs/<TICKER>/<EVENT_ID>/claims/metrics.json` per
   `reference/extraction-instructions.md`'s Metric section — every metric must cite
   at least one real claim id.

6. **Self-check and record the price-tool decision.** Reread your own `claims.json` once, end to
   end, before running `earnings analyze`. This is a cheap self-critique pass, not
   a re-extraction: look specifically for
   - speaker attribution errors (an analyst's question misattributed as a
     management statement);
   - period-basis errors: quarterly vs. year-to-date/half-year figures conflated,
     or incremental vs. cumulative confused (see extraction-instructions.md's
     "Stating an unambiguous period");
   - a `period` you set but cannot point to actual evidence for. For every claim
     that has a `period`, be able to name the exact quote or evidence passage that
     establishes each part of it (start date, end date, incremental-vs-cumulative).
     If any part is inferred, assumed, or extrapolated rather than stated by the
     source, drop the `period` field on that claim rather than keep a guessed one
     — a missing period is honest, a wrong one is not (this is the same standing
     rule as extraction-instructions.md's period section, called out here because
     it's exactly the kind of thing this self-check pass exists to catch before
     Python ever sees it — Python cannot check period accuracy at all);
   - claims whose `claim_text` doesn't actually match what its cited `quote` says
     in context, not just that the quote text exists.

   Fix anything you find yourself; Python's validators below check groundedness,
   not these judgment errors.

   **After making a fix here, verify it actually landed before moving on** --
   re-read the specific claim(s) you changed, or re-grep `claims.json` for the
   exact string you removed, rather than trusting a bulk find-and-replace's own
   count of how many instances it changed. A multi-instance replace can silently
   miss an occurrence that differs only in whitespace or line-formatting, leaving
   the original problem in place under an untouched claim while you move on
   believing it's fixed. Confirmed live (SBRY/q1-2627, 2026-09-04): a guessed
   `period` value was intentionally removed from three claims via a scripted
   string replace; the tool reported two replacements, that count was trusted at
   face value, and the third instance (`claim-009`, differently formatted) kept
   its guessed period all the way to `signal-card.md` -- caught only by the
   independent reviewer in round 1, not by this self-check step, which is
   supposed to be exactly where it gets caught. This is a general discipline, not
   a period-specific one: it applies to any fix made during this step, not only
   period corrections.

   Decide whether the discretionary price tool was `used`, `not_used`, or
   `attempted_failed`. Give one concise reason. This is an operational receipt,
   not private chain-of-thought. Python will compare the decision with this run's
   `price_lookups.jsonl` and reject a contradiction.

7. **Audit the claims with Jev, then account for every finding.** Optional, and it
   needs an OpenRouter key, but skipping it means the only reading of your claims
   before validation is your own. Jev is a third-party service, so a clone of this
   repo may not have access: if the script exits saying `OPENROUTER_API_KEY` is
   unset, skip this step, say so in your summary, and carry on — the run is still
   valid without it and no later stage fails for the absence. Run:

   ```bash
   uv run python scripts/jev_check.py runs/<TICKER>/<EVENT_ID>
   uv run python scripts/jev_check.py runs/<TICKER>/<EVENT_ID> --mode coverage
   ```

   Do not add `--all-claims` on a normal run: on figure-less and inference claims its
   questions are ill-posed (JPM/2026-q2: ~115 of 135 defects were artefacts).

   Jev is a fast model that returns a probability for a bounded question rather than
   prose. It is **never a gate** — it blocks nothing, and its numbers move a little
   between runs. What it is good at is spotting the kind of defect a deterministic
   check cannot: a figure that is right but attached to the wrong metric name, a
   `claim_text` that asserts more than its own `quote` carries, a qualifier lost in
   extraction.

   The tool writes `claims/jev-triage.json`: the answers worth a second look, in two
   tiers.

   - **`defect`** — Jev's best reading disagrees with what you wrote. Every one of
     these must be answered individually.
   - **`check`** — the expected answer still won, but weakly: a losing option held
     real probability, or the confidence was diffuse. Read these as a group. This
     tier is where lost qualifiers surface. A quote saying "revenue in excess of
     \$2 billion" extracted as `values["revenue_usd_billion"] = 2.0` passes every
     numeric check — 2.0 genuinely appears — but the figure is a floor, not a
     result, and Jev will hold probability on "false" for that value question.

   Record what you did in `claims/jev-dispositions.json`, one entry per `defect`
   item, using the `key` from the triage file verbatim:

   ```json
   {"dispositions": [
     {"key": "claim-017::value__revenue_usd_billion",
      "action": "caveat_added",
      "note": "quote says 'in excess of'; 2.0 is a floor. Caveat added to claim-017."}
   ]}
   ```

   `action` is one of `fixed` (the claim was corrected), `caveat_added` (the claim
   is right but qualified — see below), or `rejected` (Jev is wrong here, and the
   note says why). A rejection with no reason is not a disposition.

   The `check` tier is closed with a single entry keyed `"check-tier"` saying what
   you found when you read the group — it is one advisory, not sixty.

   **When a figure is right but qualified, add a `caveats` entry to the claim
   itself**, not only to the disposition file — one plain sentence, e.g. `"the quote
   says 'in excess of' — 2.0 is a floor, not an exact result"`. The disposition file
   is a record of this step; the caveat travels with the claim into the outlook brief
   and the independent review. Nothing in Python can check that a caveat was
   honoured, which is exactly why it has to be visible to the two agents downstream.

   **The second command audits your coverage receipt**, and it answers the one
   question no other check in this pipeline asks. `analyze` proves every segment is
   accounted for; nothing proves a `deliberately_immaterial` call was correct, and a
   material segment hidden behind a plausible reason is invisible to every gate in the
   run. The audit sends only the segments you called immaterial, with your own
   `outcome` and `reason` deliberately withheld so Jev reads the segment rather than
   agreeing with you. Findings land in `claims/jev-coverage-triage.json` in the same
   two tiers. Answer a `defect` by extracting what you missed; answer a `check` by
   re-reading the segment and either extracting or leaving the call to stand. These
   items go in `jev-dispositions.json` alongside the rest, keyed the same way.

   On the first real run this flagged 0 of 43 and every one of those 43 was correct on
   a hand check — so treat a clean sheet here as a genuine pass, not a formality. It
   costs under a penny.

   `earnings analyze` warns — it does not fail — when a triage file exists with
   defect findings and no matching dispositions. That warning is there because this
   already went wrong once: a JPM run reached the independent reviewer carrying
   thirteen miscitations Jev had already flagged, because the flags sat in a log file
   nobody read.

8. **Validate.** Run:

   ```bash
   uv run earnings analyze --ticker <TICKER> --event-id <EVENT_ID> \
     --extractor-agent <your-agent-name-or-unknown> \
     --extractor-model <actual-model-or-unknown> \
     --extractor-reasoning-effort <actual-effort-or-unknown> \
     --price-decision <used|not_used|attempted_failed> \
     --price-reason "<concise reason>"
   ```

   Record your own agent/harness name (`--extractor-agent`, e.g. "Claude Code",
   "Codex"), plus the model identifier and reasoning effort reported by the host for
   this extraction. The agent name is who ran the stage; the model is what ran
   underneath it, and they are not the same thing. Do not infer any of the three from
   output quality. If the host does not expose one, pass `unknown`; this is declared
   provenance, not independent runtime attestation.

   This runs Python's deterministic validators (exact-quote, numeric, values-present,
   claim-text-quote-traceability, universal-quantifier, calculation,
   inference-citation, metric-provenance, schema) and writes `validation.json`.

   **A passing gate means the claims you submitted are grounded. It never means
   the claims are complete, that a figure sits under the right metric name, or
   that a sentence about a whole set is true.** Those are yours at extraction
   time and the reviewer's afterwards.
   Every invocation also creates a numbered, timestamped folder under
   `claims/history/`, preserving that attempt's exact `claims.json`, optional
   `metrics.json`, validation result, and receipt. Do not delete or rewrite an old
   attempt when correcting the current files.

9. **If validation fails:** the command exits non-zero and does **not** write
   `signal-card.md`. Read `validation.json`, fix the offending claims/metrics
   (correct the quote, drop an unsupported number, fix a calculation block, add a
   missing citation), and re-run step 8. Do not hand-edit `signal-card.md` directly
   and do not bypass a failed validation by writing the card yourself. The rerun
   becomes the next attempt folder; prior failures remain available for analysis.

   **Before resubmitting, check this run's own attempt history, not just the
   latest failure.** If this is attempt 2 or later, read every earlier attempt's
   `claims/history/attempt-NNNN_*/receipt.json` in this run (their
   `issue_counts` are enough — no need to reopen the old `claims.json` unless a
   count alone is ambiguous) before re-running `earnings analyze`. Confirm your
   fix for the current failure doesn't reintroduce a `check` type an earlier
   attempt in this same run already had and fixed — e.g. don't re-break
   `exact_quote` on a different claim while fixing this attempt's `numeric`
   failure. This is a within-run regression check, not the cross-run lessons
   file in step 1 — it exists because nothing else compares attempt N's fix
   against attempt N-2's, and a multi-attempt correction loop can otherwise
   cycle between the same two mistakes without anyone noticing.

10. **If validation passes:** `signal-card.md` is written automatically, grouped by
   category, following `reference/signal-card-template.md`.

## Stage 2: outlook synthesis

Only start this stage once Stage 1's `earnings analyze` has passed.

11. **Write `outlook-brief.md`.** Follow `reference/outlook-brief-template.md`'s
   default structure and freedom envelope. This is interpretive synthesis
   (base/upside/downside cases, what to monitor) — you write it directly, Python
   does not generate it, and you're expected to rank, compare, and draw new
   qualitative conclusions from validated claims, not just restate them. Every claim
   id you cite must exist in this run's `claims.json`, and every material number you
   introduce must be grounded in a claim cited alongside it.

   **Honour the `caveats` on every claim you cite.** A caveat is a plain sentence
   recorded at extraction saying a figure is qualified in a way no check can see —
   most often that a number is a floor or an approximation rather than an exact
   result. If a claim you are citing carries one, the prose must reflect it: write
   "revenue of more than \$2 billion", not "revenue of \$2 billion". Python grounds
   the number 2.0 either way and cannot tell the two sentences apart.

   Before you start, read `claims/jev-triage.json` if the run has one, especially its
   `check` tier. Those are the figures and claims another model found ambiguous, and
   they are the ones most likely to harden into something overstated in your prose.

12. **Self-check the brief before validating.** `earnings validate-outlook` (next
    step) only confirms a cited claim id *resolves* — it cannot tell a correct
    citation from a plausible-looking wrong one, and neither can you rely on it to
    catch an overstated factual claim. Before running it, reread every `[claim-###]`
    citation in the brief against the claim it actually points to:
    - Does the claim you cited actually say what the surrounding sentence
      attributes to it? A citation that resolves but doesn't support the specific
      point being made is a "wrong-but-resolving citation" — the same severity as
      a citation that doesn't resolve at all (see
      `review-earnings-run/reference/reviewer-judgment-remit.md` item 3).
    - Does any factual claim about *sequencing or disclosure* ("only revealed in
      Q&A", "management didn't mention X until...") actually hold up against the
      full evidence, not just the one segment you're citing? Confirmed live
      (SBRY/q1-2627, round 1, 2026-09-04): the brief cited `[claim-002]` (grocery
      growth) next to a quote about "seasonal weakness" that claim-002 doesn't
      contain, and separately asserted a disclosure was made "only later, in
      Q&A" when the prepared remarks had already named it — both wrong, both
      would have been caught by rereading the actual claim and the actual
      transcript passage before writing the sentence, and neither is something
      `validate-outlook` can check.

    Fix anything you find, and re-verify the fix landed (see step 6's note on
    verifying fixes, same discipline applies here).

    **Then audit the citations with Jev**, which reads each cited claim against the
    passage that cites it — the one thing neither you nor `validate-outlook` does
    independently:

    ```bash
    uv run python scripts/jev_check.py runs/<TICKER>/<EVENT_ID> --mode citations
    ```

    Optional on the same terms as step 7: no OpenRouter key means skip it, say so,
    and continue. Run it once after fixing what it finds, then dispose: re-runs move
    the count without adding signal. In a paragraph citing several claims, expect
    `quoted_text_belongs_to_claim` flags on every claim but the one holding the quote.

    This writes `outlook/jev-triage.json` and takes dispositions in
    `outlook/jev-dispositions.json`, same two tiers and same rules as step 7.
    `validate-outlook` warns (never fails) about any `defect` left undisposed, and
    records the warning in `outlook-validation.json`. A
    `defect` here means Jev read the cited claim and found it says nothing about the
    point your sentence uses it for. Measured on JPM/2026-q2-rerun: of 150 citations,
    thirteen came back that way, and the one an independent reviewer later flagged by
    hand was among them.

13. **Validate the brief.** Run:

   ```bash
   uv run earnings validate-outlook --ticker <TICKER> --event-id <EVENT_ID> \
     --author-agent <your-agent-name-or-unknown> \
     --author-model <actual-model-or-unknown> \
     --author-reasoning-effort <actual-effort-or-unknown>
   ```

   Use the identity of the agent that authored the current brief. It may differ from
   the extractor. Again, record `unknown` rather than guessing.

   Fails if the underlying claims haven't passed `analyze`, if any cited claim id
   doesn't resolve, or if a material number isn't grounded in a claim cited
   alongside it. Fix and re-run until it passes.

14. **Report back to the user** the run directory path and a brief summary of both
    `signal-card.md` (evidence appendix) and `outlook-brief.md` (the forward-looking
    read).

## Reference files

- `reference/extraction-instructions.md` — claim categories, classification
  taxonomy, Metric discovery, exact quotes, calculation blocks.
- `reference/signal-card-template.md` — the Markdown structure the rendered
  evidence card follows.
- `reference/outlook-brief-template.md` — the freedom envelope, the default outlook
  structure, and the claim-id/numeric-grounding rules `validate-outlook` enforces.
