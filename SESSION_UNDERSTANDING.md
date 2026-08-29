# Session understanding: review-gate hardening

Use this checklist to confirm that the workflow changes remain understandable.

## Problem

- [ ] An old semantic verdict could be reused after the brief changed.
- [ ] Later review rounds could skip the deterministic diff step.
- [ ] Snapshot idempotency compared only the report, not the reviewed bundle.
- [ ] A missing hashed file could pass the hash helper.
- [ ] The manifest was parsed but its recorded source bytes were not verified.
- [ ] Some verdicts could contradict their findings or contain no review receipt.

## Solution

- [ ] A report records the claims, brief, and later-round diff SHA-256 hashes.
- [ ] `review_mode` states whether the semantic work was full or diff-based.
- [ ] `check-review` verifies those receipts before accepting or snapshotting.
- [ ] Analysis validation is bound to the manifest and every archived source.
- [ ] The round cap remains terminal but no longer locks unrelated CLI work.
- [ ] Source and process findings provide content-dependent coverage evidence.

## Limits and broader impact

- [ ] Hashes prove artifact identity. They do not prove reviewer comprehension.
- [ ] Source/process findings improve evidence of coverage but remain agent-authored.
- [ ] Old reports without the new receipt fields must be reviewed again.
- [ ] Dead settings and the broad `cli.py` refactor were deliberately not changed.

## Single-agent architecture lesson

- [ ] An agent framework is an orchestration choice. It is not a prerequisite for safe tool use.
- [ ] The LLM Experiments Lab keeps filesystem authority in application code. The model chooses a bounded query and an enumerated target, not a path.
- [ ] Stable context such as the README and architecture source is assembled deterministically. Volatile run state is added separately.
- [ ] Its current implementation has two grep-style tools and one diagnostic tool, with capped results and a bounded tool round.
- [ ] A framework becomes useful when durable state, branching, delegation, approvals, repeated loops, or recovery are real requirements.

## Fresh MSFT FY26 Q2 run-through

- [ ] Peer discovery selects comparables before source-pack construction. Search results do not choose peers automatically.
- [ ] `prepare` archives raw transcript, SEC evidence, raw web hits, and extracted citable web pages with receipts.
- [ ] Archived hits are not claim evidence. Only extracted pages listed in `web-evidence.jsonl` are citable.
- [ ] Claim extraction is semantic, but `analyze` independently checks schema, exact quotes, numbers, citations, and source hashes.
- [ ] Outlook synthesis starts only after claims pass. `validate-outlook` binds the brief to the current claims.
- [ ] Round 1 semantic review is full. `check-review` validates and snapshots the untouched reviewed bundle before any correction.
- [ ] `pass_with_warnings` completes the run under the current policy. Only `fail` or escalation forces another round.
