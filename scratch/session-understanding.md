# Session understanding: discretionary price-tool receipt

- [x] Problem: successful price calls were logged, but a skipped call left no evidence.
- [x] Boundary: record a concise operational reason, not private chain-of-thought.
- [x] Design: the extractor supplies `used`, `not_used`, or `attempted_failed` to `earnings analyze`.
- [x] Persistence: Python stores the checked decision inside existing `validation.json`.
- [x] Integrity: `used` requires a successful run-local lookup receipt.
- [x] Integrity: `attempted_failed` requires attempts and no successful receipt.
- [x] Integrity: `not_used` requires no run-local lookup receipt.
- [x] Staleness: a later price-log change invalidates the prior validation.
- [x] Final visibility: `audit-record.json` copies the validated decision.
- [ ] User mastery check: explain the distinction between `not_used` and `attempted_failed`.
