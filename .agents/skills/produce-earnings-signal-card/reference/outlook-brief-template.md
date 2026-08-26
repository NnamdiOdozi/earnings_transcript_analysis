# Outlook brief template

`outlook-brief.md` is written by **you** (the agent), not by Python — synthesising a
scenario or judging what's "most plausible" is interpretive work, and this POC has no
LLM call inside the product code to do it deterministically. Python's only role is to
gate the brief: it will not be considered valid until `earnings validate-outlook`
confirms every claim id you cite actually exists in the run's validated `claims.json`.

Write it only after `earnings analyze` has passed (`validation.json` has `"ok":
true`) — an outlook built on unvalidated claims is not auditable.

## Structure

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
- Do not introduce a metric or driver here that isn't backed by a claim already in
  `claims.json` — if you notice something worth flagging that you didn't capture as
  a claim, go back and add the claim first, then cite it.
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
exist yet, or if any cited claim id doesn't resolve.
