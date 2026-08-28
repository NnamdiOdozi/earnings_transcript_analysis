# Deferred Work

Scoped-but-not-executed work items, so they don't get silently forgotten. One
entry per item: date, source, what was scoped, current status. Never delete an
entry — mark it DONE or DROPPED in place instead, with a date, so the history
of what was considered and why stays visible.

## Open

### [2026-08-2x] cli.py structural refactor
- **Source:** interrogated in-session as a blueprint (RunPaths/SearchQuery/
  SearchHit dataclasses; split into storage/web/sec/research/render/prepare/
  analyze modules), explicitly deferred pending go-ahead.
- **Status:** OPEN — not started. Confirmed still not done as of 2026-08-29;
  this is the item that motivated creating this file, after going
  unmentioned for several sessions and the user having to ask whether it
  happened.
- **Note:** the 2026-08-29 third-party audit (below) independently flags the
  same file ("cli.py is carrying too many responsibilities", 1,231 lines) —
  treat that as corroboration, not a separate item.

### [2026-08-29] Third-party audit findings (review-diff, hash gates, reviewer-report enforcement, doc drift, dead config)
- **Source:** external agent audit of the pipeline, independently verified
  line-by-line in-session (see conversation) — every specific claim checked
  out true against the actual code.
- **Scope, in priority order (per audit + independent agreement):**
  1. `review-diff` never diffs `outlook-brief.md` prose, only claims — a
     narrative-only correction can produce an empty diff and no escalation.
     Interim fix: auto-escalate whenever the brief's bytes changed since the
     last round, full stop. Real fix (later): section-level old-vs-new diff.
  2. Hash gates are incomplete and fail open: `check-review` never checks
     `claims_sha256` (only `outlook_brief_sha256`), and `validation.json`/
     `outlook-validation.json` are parsed as raw dicts (`json.loads` +
     `.get`) rather than validated against their Pydantic models, so a
     hand-written `{"ok": true}` sails through. Fix: one shared
     schema-validate + hash-require + hash-match helper, used at every gate,
     not three independently-drifting call sites (duplication is what
     caused the drift in the first place).
  3. A review-report `verdict` isn't cross-checked against finding
     `severity` — `pass` can coexist with a `critical` finding and
     `check-review` won't catch it. This one check is purely mechanical
     (arithmetic over structured JSON) and belongs in Python; the rest of
     the reviewer's judgment correctly stays out of Python's reach.
  4. Round cap enforced only in `review-diff`, not in `check-review` —
     belt-and-suspenders gap if a round is ever closed without going
     through `review-diff` first.
  5. Reviewer instructions triplicated across `.claude/agents/
     outlook-reviewer.md` + two `.agents/skills/review-*/SKILL.md` files,
     with confirmed drift: an 11-vs-"ten checks" count mismatch, stale
     `raw/tavily/*.json` paths (production writes `raw/web/`), one file
     missing the `outlook-validation.json` prerequisite the other has, and
     escalation described as "no penalty" in one place vs. "consumes a
     round" in another (both technically defensible on their own terms, but
     read as a contradiction side by side). Consolidate to one canonical
     contract + thin per-environment dispatch adapters.
  6. Smaller/lower-priority, each independently confirmed: `analyze` never
     validates `manifest.json`; repeated `check-review` calls on an
     unchanged report create redundant round snapshots; six config values
     (`SEC_SUBMISSIONS_URL`, `SEC_FORMS`, `RESEARCH_OFFICIAL_SOURCES_ONLY`,
     `RESEARCH_INCLUDE_PREVIOUS_PERIOD`, `TAVILY_SEARCH_DEPTH`,
     `TAVILY_INCLUDE_EXTERNAL_COMMENTARY`) are defined but read nowhere —
     implement or remove, don't leave them as false configurability; no
     atomic writes/no concurrency lock (both correctly flagged as
     acceptable for a POC, not urgent).
- **Status:** Phase 1 (items 1-4) and Phase 2 (item 5, `manifest.json` check,
  snapshot idempotency) DONE — 2026-08-29, committed.

  A fresh Opus-model subagent independently reviewed both phases together
  (given no conversation context, asked to verify each claimed fix against
  the real code rather than trust the commit messages) and found a genuine
  deadlock: the round-cap check in `check-review` ran *after* rendering and
  writing `review-report.md`, so a capped-out round still overwrote the file
  with a verdict that was never accepted, and because it was never
  snapshotted, the earlier unclosed-report gate stayed permanently tripped —
  every one of `analyze`/`validate-outlook`/`check-review`/`review-diff`
  refused, with no CLI path back short of raising the cap in config. I
  reproduced this myself end-to-end before accepting the finding. Fixed
  same-day: the cap check now runs first, before any parsing or writing, in
  both commands, and returns a distinct exit code (4, not 2) so the skills
  can tell "stop entirely, cap reached" apart from "fail, go correct it" —
  they were being conflated, which was itself part of the confusion. Also
  fixed from the same review: a test that claimed to test the fail-open hash
  gate but actually only exercised schema rejection (the real gate path was
  untested); `manifest.json`'s check deepened from existence-only to
  schema-validated with at least one recorded source; a stale "three things
  force a full review" claim in README.md (now four); a stale pointer in
  `review-earnings-run/SKILL.md` to a file that no longer carries the content
  it pointed to; a missing escalation trigger in that same file's list (its
  Codex twin had been updated, it hadn't); and an internal contradiction in
  the canonical reviewer file ("this same round" vs. "consumes a round
  slot") that both SKILL.md wrappers stated correctly but the canonical
  source didn't. 159 tests passing. Not yet independently re-reviewed a
  third time — the fix itself hasn't been audited by a fresh pass, only
  self-reviewed and manually reproduced.

  Dead config (part of item 6) and the cli.py structural split (Phase 3)
  remain OPEN — deliberately deferred, not yet scoped in detail.

### [2026-08-28] Phase 3 scope expansion: close residual review-receipt gaps before refactoring
- **Source:** independent adversarial re-review of the Phase 1/2 changes. The
  ordinary suite passed, but direct bypass probes showed that the completion
  labels were too broad.
- **Scope:**
  1. Bind every semantic verdict to the exact `claims.json` and
     `outlook-brief.md` bytes. For round 2+, also require a current,
     schema-valid `review-diff.json`, bind the verdict to its hash, and validate
     the declared `full`/`diff` review mode.
  2. Make snapshot idempotency compare the whole reviewed bundle, not only
     `review-report.json`.
  3. Treat a missing hashed target as a failed hash gate. Recheck all analysis
     input hashes downstream. Verify each manifest source exists and matches its
     recorded byte length and SHA-256 before analysis.
  4. Make an exhausted round cap a terminal policy result without leaving the
     rest of the CLI mechanically locked by an unaccepted report. Always point
     users to the last accepted history snapshot, not the unaccepted working file.
  5. Require content-dependent source and process review entries. Enforce both
     directions of verdict/severity consistency, including `fail` requiring a
     `high` or `critical` finding.
  6. Reconcile the full-review escalation instructions. An auto-escalated later
     round still reads and hash-binds `review-diff.json`, because that file is the
     deterministic receipt selecting full-review mode.
- **Status:** DONE — 2026-08-28. Implementation and regression tests written,
  then independently verified live: a second, more skeptical review pushed
  back on 4 of the original points (snapshot identity, cap-exhaustion
  mutation risk, explicit regression tests for scenarios A/B/F/G, manifest
  path containment); on re-checking the actual code, 2 of the 4 were already
  correctly handled (snapshot identity via full-bundle-byte comparison in
  `_review_bundle_matches_snapshot`; path containment via `is_relative_to` in
  `_manifest_source_errors`), and the other 2 were genuine test-coverage gaps,
  closed by adding
  `test_check_review_rejects_round_two_without_review_diff_when_cap_not_reached`
  and `test_check_review_refuses_mutated_bundle_after_cap_exhausted`. Also
  live-validated end-to-end (token-light: reused cached sources/claims, zero
  new LLM calls) against a scratch copy of the MSFT 2026-q2 run, exercising
  round-1 pass_with_warnings, an edited claim, auto-escalation via
  `review-diff`, and round-2 pass_with_warnings. Full suite passes with 168
  tests. The requested independent GPT-5.6 Sol medium review was dispatched
  but could not start because that model's usage limit had been reached; the
  user assigned the independent review to another agent instead, which is the
  re-review described above.
- **Explicit exclusions:** Do not remove the six currently-unused settings. The
  user may need them later. Do not perform the broad `cli.py` refactor in this
  phase. Those two earlier entries remain open exactly as requested.
