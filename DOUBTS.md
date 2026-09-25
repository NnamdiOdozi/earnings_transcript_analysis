# Doubts

Judgment calls made without user sign-off, so they get reviewed rather than
silently inherited. One entry per call: what was decided, why, and what it
affects. Newest first. Timestamps are ISO 8601 dates.

---

## 1. [2026-09-25] Receipt is four id lists, not a per-claim dictionary with notes

**Decision:** `claim_review_receipt` holds four flat arrays of claim ids
(`reviewed_ok`, `with_findings`, `unverifiable`, `carried_forward`) rather than a
`{claim-id: verdict}` mapping or a per-claim one-line note.

**Why:** the reviewer subagent has `Read, Grep, Glob, Write` and no execution tool, so
every value in the receipt is hand-typed. On the largest live run (JPM/2026-q2-rerun)
that is 203 ids. Four arrays it can read straight off `claims.json` are less
transcription work and less error-prone than 203 key/value pairs, and a short-note
variant would have cost roughly 6k output tokens per round for evidence the findings
already carry.

**Affects:** the receipt records *that* a claim was accounted for, with no per-claim
prose to show for it. If the receipt ever needs to demonstrate engagement rather than
accounting, this is the decision to revisit — and `models.ClaimReviewReceipt` would need
a new shape, not just a new field.

---

## 2. [2026-09-25] The receipt is enforced for new rounds but waived when re-confirming an accepted one

**Decision:** `validate_review_report` takes `require_claim_receipt`, and
`cmd_check_review` passes `False` on exactly one path — when the bundle byte-matches an
already-accepted round (`repeated_accepted_bundle`).

**Why:** every review report written before today lacks the field. Enforcing it
unconditionally would mean an already-approved run could no longer be re-confirmed, for
a rule that postdates its review. This is the same reasoning already applied to the
extraction coverage receipt (see `DEFERRED_WORK.md`, 2026-09-16 entry).

**Affects:** there is one narrow hole. A run whose review was accepted, and whose files
have not changed since, can be re-confirmed without a receipt. Any genuinely new round
— including a new round on an old run — requires a complete one. I judged the hole
acceptable because re-confirmation cannot change a verdict; it only re-renders and
re-writes `audit-record.json` from unchanged files. Worth checking you agree.

---

## 3. [2026-09-25] Extracted `_check_diff_round_bindings` out of `cmd_check_review` mid-change

**Decision:** the round-2+ diff-binding checks moved from inside `cmd_check_review` into
a new `_check_diff_round_bindings` helper in `src/earnings/review.py`, in the same commit
as the behavioural change.

**Why:** a pre-commit complexity hook refused the edit — `cmd_check_review` is already
rated F at cyclomatic complexity 46, and adding the `carried_forward` check took it to
50. The hook's instruction is to refactor or get approval for a revised baseline. I
refactored rather than asking to raise the baseline, since raising it is the one thing
the hook explicitly says not to do unilaterally. The extracted checks are unchanged in
order and effect; only the `carried_forward` check inside it is new.

**Affects:** this mixes a behaviour-preserving move into a behavioural commit, which cuts
against the project's own convention of keeping those separate. The move is small (one
`else:` block, same checks, same order) and the full suite passes, but if you would
rather it had been its own commit, that is a reasonable objection to the sequencing
rather than to the code.

---

## 4. [2026-09-25] Exhaustive item 2 interacts with the deferred "medium blocks acceptance" change

**Decision:** item 2's contract now says explicitly that a partial quote is not itself a
finding, and sets the test as "does the omitted surrounding text change what a reader
would conclude?"

**Why:** the source feedback asked the reviewer to judge whether each quote is
"representative rather than cherry-picked". Applied across 203 claims as a loose
standard, that generates many arguable medium-severity findings. `DEFERRED_WORK.md`
separately holds an agreed-but-unbuilt change making any `medium` finding block
acceptance. Both changes together would plausibly mean no run ever finishes, so the
contract needed a concrete threshold before that second change lands.

**Affects:** if the medium-blocks-acceptance change is implemented, watch the first real
run's `claim_findings` volume closely before assuming the threshold wording is tight
enough. Nothing has been live-tested: no earnings run has been executed against the new
contract yet, so the claimed effect on finding volume is reasoning, not evidence.
