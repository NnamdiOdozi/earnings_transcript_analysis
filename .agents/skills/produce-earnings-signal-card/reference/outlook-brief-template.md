# Outlook brief template

`outlook-brief.md` is written by **you** (the agent), not by Python — synthesising a
scenario or judging what's "most plausible" is interpretive work, and this POC has no
LLM call inside the product code to do it deterministically. Python's role is to gate
the brief on what's mechanically checkable: every claim id you cite must exist in the
run's validated `claims.json`, and every material number you introduce must be
grounded in a claim cited alongside it (see "The freedom envelope" and "Rules"
below). It never judges whether your interpretation is *right* — that's the
independent reviewer's job.

Write it only after `earnings analyze` has passed (`validation.json` has `"ok":
true`) — an outlook built on unvalidated claims is not auditable.

## The freedom envelope: constrain the facts, not the thinking

Python controls the facts (exact quotes, grounded numbers, reproducible
calculations, claim ids). Everything else here is your interpretive judgment, and
you are expected to use it, not hedge behind restating claims verbatim.

**You may:** rank developments by importance; combine several validated claims into
a new qualitative conclusion; compare evidence from different sources; identify
tensions and contradictions; challenge management's own explanation; distinguish
structural from temporary drivers; form qualitative hypotheses; describe
conditional scenarios; identify counterevidence and missing information; assess
which assumption the outlook depends on most; say what evidence would falsify or
strengthen your interpretation; adapt emphasis to the company and sector.

**You may not:** invent factual premises, quotations, or numerical values; present
uncited outside knowledge as if it were evidence from this run; quietly change a
period, unit, or metric definition; convert a possibility into a stated fact;
manufacture a consensus estimate or peer result that isn't in `claims.json`; hide
uncertainty behind confident prose.

A new qualitative proposition is welcome even when no single source states it
verbatim — that is exactly what synthesis is for. For example:

```text
The outlook appears increasingly dependent on volume recovery rather than
further pricing gains [claim-012][claim-018][claim-021].
```

No claim needs to say that sentence. What's required is that (1) the claims cited
are validated, (2) the conclusion is legible as analysis, not restated fact, and
(3) the independent reviewer can check whether it actually follows from them. You
do **not** need to turn this sentence into a new `claims.json` entry to use it here
— see extraction-instructions.md's `analytical_inference` classification for when a
conclusion belongs in `claims.json` instead (typically: a discrete, individually
citable finding you expect other sections to reuse), versus writing it directly in
the brief's prose (a one-off synthesis specific to this section).

Mark the boundary naturally in prose rather than with rigid per-sentence labels —
"Management reported...", "The evidence suggests...", "Our interpretation is...",
"A plausible explanation is...", "This would be challenged if..." — so a reader can
always tell a reported fact from your reading of it.

**Before finalising, find the strongest evidence against your base case.** Either
work it into the conclusion or explain in prose why it's less persuasive than what
you led with. An outlook that only cites confirming evidence while an available
claim cuts the other way is exactly what the independent reviewer is told to look
for (see `reviewer-judgment-remit.md`).

Questions worth asking yourself before you write, not new JSON fields to fill in:
what are the three to five most consequential developments; what actually changed
this quarter; what surprised positively or negatively; where does management's
narrative conflict with other evidence; what was management pressed hardest on in
Q&A; which developments are temporary versus potentially structural; which
evidence supports the base case and which cuts against it; what is the largest
unresolved uncertainty; what assumption is doing the most work in the outlook; what
observable development would change the view.

## Default structure

The sections below are the default analytical structure, not a rigid template —
every numbered item's *coverage* is still mandatory (a bank, a semiconductor
company, and an insurer should not read as structurally identical), but you may
combine two sections when one is thin, add a company-specific subsection, give an
unusually important issue more space, or skip an optional subsection with
genuinely nothing to say. Don't drop guidance, base/upside/downside, risks,
monitoring indicators, or claim citations — those are the core coverage this
format exists to guarantee.

```markdown
# Outlook Brief: <TICKER> — <EVENT_ID> (<REPORTING END DATE, e.g. 30 June 2026>)

## 1. Outlook in brief
State the reporting period covered by this run's headline figures unambiguously
in the first sentence -- "N months to DD Mon YYYY" (e.g. "3 months to 31 Dec
2025"), not "Q2 FY2026" or "FY2026" alone, which fix an end date but leave the
start date and incremental-vs-cumulative question open. Use the `period` value
already stated on the relevant claims (see extraction-instructions.md) rather
than re-deriving it. Then give a concise synthesis of the likely direction over
the next reported period and, where evidence permits, the financial year.

## 2. What changed
Compare current statements with previous guidance, expectations or management
commentary. Cite claim ids, e.g. "revenue guidance raised from ... to ...
[claim-004][claim-011]".

## 3. Management guidance
Present explicit guidance, ranges, time horizons and qualifications. State clearly
if management gave no quantitative guidance this period.

## 4. Business drivers
Company-specific demand, pricing, volume, cost, capacity, execution or regulatory
drivers discovered from the evidence — not a sector template.

## 5. Base case
The most plausible development supported by current and prior-period evidence.

## 6. Upside case
Conditions that could produce a better outcome, and the observable evidence that
would support it.

## 7. Downside case
Conditions that could produce a worse outcome, and the observable warning signs.

For 5–7, state each scenario as **conditions → mechanism → consequence →
observable indicators**, e.g. "if demand normalises earlier than management
expects and current pricing holds [claim-016] → unit volumes recover before any
further price increase is needed → margin expands without a pricing catalyst → a
verifiable rise in reported volume growth next quarter." You may be creative about
plausible combinations of validated drivers; you may not fabricate a numerical
outcome (a specific revenue or margin figure) that isn't itself grounded in a
cited claim.

## 8. What to monitor
Dynamically selected, company-relevant indicators — not a fixed sector list.

## 9. Uncertainties and missing evidence
Undisclosed guidance, inconsistent metric definitions, unavailable sources, or
weakly supported conclusions.

## 10. Evidence appendix
A table or list linking every conclusion above back to a claim id, e.g.:

- [claim-004] "..." (exact quote) — segment seg-0007
- [claim-011] "..." (exact quote) — segment seg-0012
```

## Rules

- The title line must state the reporting end date in brackets (e.g. "MSFT —
  2026-q4 (30 June 2026)") — `<EVENT_ID>` alone (e.g. "2026-q4") does not tell a
  reader which calendar date the run's headline figures are anchored to.
- Every claim id you write (in any section, in the form `claim-###`) must exist in
  `claims.json` — `earnings validate-outlook` fails the whole brief on the first
  unknown id.
- No investment recommendations, price targets, or invented numerical forecasts.
  Scenarios are conditional interpretations of disclosed evidence, not predictions.
- **Qualitative synthesis is free; new numbers are not.** `earnings validate-outlook`
  checks that any *material* number you write — one carrying a currency symbol, `%`,
  a magnitude word (million/billion/...), bps/basis points, or an "x" multiple — is
  already grounded in a claim cited in that same passage. A number with none of
  those markers (a section ordinal, a day-of-month, a plain count like "15 seats")
  isn't checked. If a number you want to use isn't grounded this way, either drop
  it, cite the claim that actually contains it, or — if it's a genuine new
  calculation — add it to `claims.json` as a proper `calculation` block first (see
  extraction-instructions.md) and run `earnings analyze` again, so Python recomputes
  it rather than trusting it in prose.
- Escape **every** literal `$` in this file, with no exception, including inside
  the evidence appendix's `"..."` quotes (write `\$81.3B`, not `$81.3B`). Many
  Markdown renderers (KaTeX/MathJax-enabled previews, including some IDE viewers)
  treat a pair of unescaped `$` as inline-math delimiters and scan the *whole
  document*, not per-section -- two dollar amounts anywhere in the file, even in
  different sections, can pair up and silently swallow everything between them
  (spaces and punctuation vanish). Confirmed on this project's own first MSFT run
  (2026-08-26). An earlier version of this rule exempted the evidence appendix
  "to preserve verbatim fidelity" -- that was wrong: nothing in this pipeline
  machine-checks the appendix's quoted text against the source (only claim-id
  citations are validated), so escaping there costs nothing and closes the same
  hazard. `earnings validate-outlook` will fail the gate if any unescaped `$`
  remains anywhere in the file.

## Validating

```bash
uv run earnings validate-outlook --ticker <TICKER> --event-id <EVENT_ID>
```

Fails (non-zero exit) if `validation.json` isn't `ok`, if `outlook-brief.md` doesn't
exist yet, if any cited claim id doesn't resolve, or if a material number (see
Rules above) isn't grounded in a claim cited alongside it.
