# Review round procedure

Single canonical source for the *mechanics* of running one review round: the
prerequisites, how the round number and review type are determined, when to run the
deterministic gate, how to recover if you run it out of order, and what each exit code
means.

This is the companion to `reviewer-judgment-remit.md`, which is the canonical source for
the *judgment* — what the reviewer reads and decides. Two files because they have two
audiences: the remit is read by the reviewer, this is read by whoever is driving the
round.

Both dispatch mechanisms point here rather than restating it. The Claude Code skill
(`review-earnings-run`) and the Codex skill (`review-earnings-run-codex`) previously each
carried their own copy of these steps, and the copies drifted exactly as the judgment
copies had: the Codex one was missing the whole out-of-order recovery procedure, and
described `check-review` as validating less than it does. Only genuinely
platform-specific mechanics — how the reviewer is dispatched, which model and reasoning
tier to use — belong in the two thin skill files.

Throughout, `<TICKER>` and `<EVENT_ID>` are the run's identifiers, and `run_dir` is its
directory (e.g. `runs/MSFT/2026-q2/`).

## 1. Confirm the prerequisites passed

All three must hold before a reviewer is dispatched at all:

- `run_dir/claims/validation.json` has `"ok": true`
- `run_dir/outlook/outlook-validation.json` has `"ok": true` — the gate `earnings
  validate-outlook` writes. It hash-binds `outlook_brief_sha256`/`claims_sha256` to the
  current files, so a stale or hand-edited brief or claims set fails here.
- `run_dir/outlook/outlook-brief.md` exists

If any is missing, stop and go back to `produce-earnings-signal-card`. Never dispatch a
reviewer against an unvalidated run.

## 2. Determine the review round

Check whether `run_dir/review/history/` contains any `round-*` snapshots.

**None exist.** This is round 1: always a full review. Go to step 3.

**Any exist.** This is a re-review, and it must pass through the deterministic diff
command first:

```bash
uv run earnings review-diff --ticker <TICKER> --event-id <EVENT_ID>
```

- **Exit 0** — `review-diff.json` was written. Go to step 3. The reviewer must read that
  file first, before deciding how to proceed; the remit's "Diff-based re-review" section
  tells it what to do with the file, so there is no need to restate any of that.
- **Exit 3** — Python auto-escalated to a full review on its own, because too many claims
  changed, a changed claim's `period`/`values` differ, `outlook-brief.md`'s text changed
  at all since the last round, or a conclusion-bearing brief section cites a changed
  claim. Dispatch a full review with `review_mode: "full"`. The reviewer must still read
  and hash `review-diff.json`, because it is the receipt that selected full-review mode.
- **Exit 4** — the review round cap (`config.toml [review] max_review_rounds`) is
  reached. **Stop. Dispatch nothing further.** Report to the user that the cap was
  reached and surface the findings from the last accepted
  `review/history/round-N/review-report.json`, whatever its verdict. Never claim the run
  is complete; never drop those findings silently.

## 3. Get the review done

This is the one step that differs by platform — see your own skill file. Claude Code
dispatches the `outlook-reviewer` subagent; Codex dispatches a fresh review subagent
where the host offers one, and otherwise performs a deliberate in-session pass. Either
way the reviewer applies `reviewer-judgment-remit.md` and nothing else.

## 4. Confirm `review-report.json` was written

The reviewer writes only this file — never a `.md`, never edits to `claims.json` or
`outlook-brief.md`. If the pass finishes without the file on disk, treat it as a failed
dispatch and retry once before escalating to the user.

The report must carry the current claims and brief hashes, the later-round diff hash, the
per-claim `claim_review_receipt`, and the host-reported model and reasoning effort as
separate fields — all per `reviewer-judgment-remit.md`'s "Output" section and
`review-report-schema.md`.

## 5. Run the deterministic gate IMMEDIATELY

Before touching `claims.json` or `outlook-brief.md` for any correction. No exceptions.

```bash
uv run earnings check-review --ticker <TICKER> --event-id <EVENT_ID>
```

This step snapshots the round under `review/history/round-<N>/`, which is what the next
`review-diff` compares against. Run it out of order — correcting first, gating after —
and the snapshot captures your *corrected* files against the *old* verdict, silently
corrupting round history for every future diff-review on this run: the next diff shows no
changes even though real corrections happened, because there is nothing left to diff
against.

`check-review` validates `review-report.json`'s schema; checks every claim id it cites
against `claims.json` (the same non-negotiable rule as every other citation check in this
pipeline); verifies the claims, brief and diff hash bindings; requires the per-claim
`claim_review_receipt` to account for every claim and to agree with the report's own
findings; cross-checks the declared `verdict` against the severity of the reviewer's own
findings (`"pass"` requires nothing above `low`, `"pass_with_warnings"` requires no
`high`/`critical`); and enforces the round cap even if `review-diff` was somehow skipped.
Only if all of that passes does it render `review-report.md` deterministically from the
validated JSON and snapshot the round.

### Recovering from running it out of order

**If you already edited `claims.json` or `outlook-brief.md` before running the gate,** you
are deadlocked: `analyze` refuses because `review-report.json` was never closed, and
`check-review` refuses because its inputs changed. Nothing is lost. Restore both files to
the state the reviewer actually saw, close the round, then re-apply your corrections:

1. Park your corrected files somewhere outside the run directory.
2. Find the reviewed versions by hash, not by guesswork — `review-report.json` records
   `claims_sha256` and `outlook_brief_sha256`. The matching copies are under
   `claims/history/attempt-NNNN_*/` and `outlook/history/attempt-NNNN_*/`. The latest
   attempt folder is *not* necessarily the right one: a blocked `analyze` still writes an
   attempt containing your edits.
3. Copy those two files back, confirm both hashes now match the report, and run
   `check-review`.
4. Copy your corrected files back in and re-run `analyze`, then `validate-outlook`.

Confirmed live (JPM/2026-q2-rerun, 2026-09-19), by an agent that dispatched the reviewer
directly instead of working through a skill, and so never saw this step at all.

## 6. Report the verdict to the user

- **Exit 0** (`pass`) — report clean, no action needed.
- **Exit 1** (`pass_with_warnings`) — report the warnings from `review-report.md`
  explicitly. The run can be considered complete, but the user must see them.
- **Exit 2** (`fail`, or a schema/citation problem, or a verdict/severity inconsistency)
  — the run is **not** complete. Do not mark it done or hand it off as final. Go back to
  Stage 2 drafting for a revision addressing the specific findings (or Stage 1, if the
  finding is about a claim itself), then re-run **from step 2** — the round-determination
  step must run again; never assume the same round type as last time. Never silently
  rewrite `outlook-brief.md` on the reviewer's behalf: a human, or the drafting step,
  should see the specific finding and decide the fix.
- **Exit 3** (`escalate_full_review` set by the reviewer) — the diff-based review was
  judged insufficient. Immediately redo step 3 onward as a full review. This **does**
  consume a round slot toward `max_review_rounds`: the escalated attempt is snapshotted
  like any other completed round, so the full review that follows is the next round
  number, not a free retry. There is no partial-credit *verdict* for the diff attempt (it
  can neither pass nor fail the run), but it does count against the cap. An early, honest
  escalation still beats a wrong verdict — it just isn't free.
- **Exit 4** (round cap reached) — **do not treat this like exit 2.** This is not "go
  correct it"; no amount of drafting fixes an exhausted cap. Stop entirely, as in step 2's
  exit-4 handling, and surface the last accepted verdict to the user as final for this
  run.
