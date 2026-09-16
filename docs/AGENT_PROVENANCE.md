# Agent provenance

This pipeline records which agent configuration authored each judgment-bearing
stage. The purpose is to make a run easier to reproduce and audit. It does not
claim that a model name proves the analysis is correct.

## What to understand

- [ ] Claim extraction, outlook authoring and independent review are three separate
  agent-authored stages. Each can use a different model or reasoning effort.
- [ ] `claims/validation.json` records the extractor identity supplied to
  `earnings analyze`.
- [ ] `outlook/outlook-validation.json` records the outlook author's identity
  supplied to `earnings validate-outlook`.
- [ ] `review/review-report.json` records the independent reviewer's identity.
- [ ] `audit-record.json` collects all three identities under `agent_provenance`.
- [ ] Python proves that the declared values were schema-valid and propagated into
  the final record. It does not prove that the hosting application actually ran
  that model or effort level.
- [ ] When the host does not expose a value, `unknown` is the honest value. Guessing
  would make the record look more complete while reducing its reliability.

## Why the distinction matters

The earlier JPM run recorded the reviewer only as `gpt-5`, even though the reviewer
had been dispatched as `gpt-5.6-sol` with medium reasoning. Combining or truncating
identity fields made the final audit record less useful. Model and reasoning effort
are now separate bounded fields, so the loss is visible and testable.

The remaining limitation is runtime attestation. The current command-line pipeline
receives provenance from the agent or operator. A future hosting integration could
replace that declaration with a signed or server-generated execution receipt. Until
then, the final audit record labels the common basis as `agent_declared`.
