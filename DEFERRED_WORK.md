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
- **Status:** Phase 1 (items 1-4) DONE — 2026-08-29, verified line-by-line
  against blueprint, 155 tests passing (was 149), committed. Phase 2 (item 5,
  reviewer-instruction consolidation + all confirmed drift fixed; the
  manifest.json check in `analyze`; the duplicate-snapshot idempotency fix)
  also DONE — 2026-08-29, 157 tests passing, committed. Dead config (part of
  item 6) and the cli.py structural split (Phase 3) remain OPEN — deliberately
  deferred, not yet scoped in detail. Both phases sent to a fresh Opus-model
  subagent for an independent second review before Phase 3 starts.
