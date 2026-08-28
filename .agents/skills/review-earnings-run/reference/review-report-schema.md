# review-report.json schema

Matches `earnings.models.ReviewReport`. This is the only file the reviewer
writes, regardless of how it was dispatched — `review-report.md` is rendered
deterministically from it by `earnings check-review`, never written by hand.
Shared by both the Claude Code `outlook-reviewer` subagent and Codex's
`review-outlook-brief` in-session pass — one copy, not two independently
drifting ones (see `reviewer-judgment-remit.md` in this same directory for
why that matters).

```json
{
  "verdict": "pass_with_warnings",
  "review_mode": "full",
  "reviewed_at": "2026-08-25T12:00:00Z",
  "model": "opus",
  "claims_sha256": "<64 lowercase hexadecimal characters>",
  "outlook_brief_sha256": "<64 lowercase hexadecimal characters>",
  "review_diff_sha256": null,
  "source_checks": [
    {
      "severity": "info",
      "artifact": "evidence/web/web-003.md",
      "passage": "n/a",
      "evidence": "Content matches the linked press release; publisher and date consistent with manifest.json.",
      "recommendation": "None."
    }
  ],
  "claim_findings": [
    {
      "severity": "medium",
      "artifact": "claims.json#claim-009",
      "passage": "Management said margins would improve.",
      "evidence": "Full segment context: management said margins would improve 'assuming input costs stabilize' -- claim_text drops the conditional, presenting it as unconditional guidance.",
      "recommendation": "Revise claim_text to preserve the conditional, or reclassify as management_opinion rather than reported_fact."
    }
  ],
  "outlook_findings": [],
  "process_findings": [
    {
      "severity": "info",
      "artifact": "validation.json",
      "passage": "n/a",
      "evidence": "validation.json.ok == true, 13 claims checked, 0 issues -- confirmed present, not re-derived.",
      "recommendation": "None."
    }
  ],
  "unverified_items": [
    "evidence/web/web-005.md was not evaluated -- content was empty on read (see manifest.json note)."
  ],
  "summary": "One medium-severity finding: claim-009 drops a conditional from management's guidance. Otherwise the run is well-supported and industry-appropriate."
}
```

## Field notes

- `verdict`: `"pass"` | `"pass_with_warnings"` | `"fail"`. `fail` should mean at
  least one `high`/`critical` finding exists somewhere in the four finding lists;
  `pass` requires nothing above `low`. `earnings check-review` cross-checks
  verdict against severities and rejects the report if they're inconsistent
  (fixed 2026-08-29) — get it right the first time rather than relying on the
  gate to catch it.
- `review_mode`: `"full"` | `"diff"`. Round 1 is always `"full"`. Every later
  round must bind to `review-diff.json`; `auto_escalated: true` requires `"full"`.
- `claims_sha256`, `outlook_brief_sha256`, `review_diff_sha256`: exact lowercase
  SHA-256 receipts for the reviewed bytes. `review_diff_sha256` is `null` only in
  round 1. These prove version identity, not comprehension.
- `model`: record the actual model/reasoning tier used for this pass (e.g.
  `"opus"`, `"gpt-5.6-medium"`), not a placeholder -- this field is provenance,
  same as everything else in this pipeline.
- `severity`: `"info"` | `"low"` | `"medium"` | `"high"` | `"critical"`. Use `info`
  for confirmations (e.g. "process compliance: validation.json.ok == true"), not
  just problems — a review with zero `source_checks`/`process_findings` entries
  looks like the reviewer skipped reading the manifest.
- `artifact`: a stable pointer — a filename (`"outlook-brief.md"`) or
  `"claims.json#claim-NNN"` for a specific claim. Any `claim-###` pattern anywhere
  in `artifact` or `passage` is checked against `claims.json` by
  `validate_review_report` — a fabricated claim id fails the whole report
  regardless of the reviewer's own verdict.
- `passage`: the exact text being discussed — quote it, don't paraphrase, so a
  human reviewing the report can find it.
- `unverified_items`: things you could not check (missing file, ambiguous
  context) — list them rather than guessing or silently skipping.
- `source_checks` and `process_findings`: each must contain at least one
  substantive entry. Empty arrays are rejected because they provide no evidence
  that the source and deterministic-validation portions of the remit were covered.
