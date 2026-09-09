# Deferred Work

Scoped-but-not-executed work items, so they don't get silently forgotten.
This file lists only what is genuinely still open — one entry per item, with
enough context to pick it back up. Once an item is completed or dropped,
remove its entry (the commit history / conversation is the record of how it
was resolved); don't let finished work accumulate here as dead weight.

## Open

### [2026-09-09] `--company-name`/`--event-date` are unvalidated free text
- **Scope:** `cli.py:811-812` takes `--company-name` and `--event-date` as
  whatever string is typed on the command line (falling back to `--ticker`/
  `--event-id` if omitted), with no cross-check against the transcript's own
  text or SEC's registrant name. Both seed every web-search query
  (`build_consensus_queries`/`build_peer_queries`) and the causality-guard
  cutoff (`_parse_event_cutoff`), so a wrong or ambiguous value propagates
  silently into search results and the post-event filter.
- **Why:** raised while reviewing where these flags come from. There's
  currently no deterministic step that derives or verifies company identity
  or event date from the source document itself; it's entirely
  operator/agent-supplied and unvalidated. Also unclear/unenforced by
  convention alone: whether `--event-date` should be the call date or the
  transcript's publish date — the causality guard needs the call date, but
  nothing checks which one was actually passed.
- **Status:** explicitly deferred, not started. Possible direction: derive a
  candidate company name/date from the transcript itself (e.g. cover page,
  first segment) and warn (not block) on a mismatch with the flag value,
  rather than trusting the flag blindly.

### [2026-09-09] Tighten review-pass threshold: no `medium`+ findings should be accepted
- **Scope:** `validate_review_report` (`src/earnings/validate.py:646-657`)
  currently allows `pass_with_warnings` with `medium`-severity findings
  present (it only blocks `high`/`critical`). `cmd_check_review`
  (`cli.py:1538-1545`) treats `pass_with_warnings` as a terminal, accepted
  verdict — writes `audit-record.json`, exits 0. User wants the bar raised:
  a run should only be accepted (pass or pass_with_warnings) if every
  finding is `low` or `info`; any `medium`-or-above finding should force a
  `fail` (i.e. require a correction round) rather than being accepted with
  just a warning.
- **Why:** user's explicit call — medium severity findings currently slip
  through as accepted output with only a warning; user wants them to block
  acceptance same as high/critical.
- **Status:** explicitly deferred, not started. Touches
  `validate_review_report`'s verdict-severity checks and the existing tests
  in `tests/test_cli_e2e.py` that assert current `pass_with_warnings`
  behavior with medium findings (e.g.
  `test_check_review_audit_record_aggregates_across_rounds`) — those would
  need updating to the new rule. Confirm with user whether this also
  requires reclassifying `pass_with_warnings`'s purpose (still useful for
  low/info-only warnings) versus removing it, before implementing.

### [2026-09-08] No human-escalation path when review is ambiguous
- **Scope:** add a path where `check-review`'s escalation logic can hand a
  decision to a person instead of forcing another AI review round.
- **Why:** assessed the pipeline against
  `.agents/skills/verify-agent-workflows/references/designing_genai_workflows.md`'s
  five-step method. Steps 1-4 (human owns the final call, Python does what's
  provable, GenAI only where it earns its place, independent review as a
  risk-proportional control) are all satisfied. Step 5 ("stop and ask a
  person when ambiguity is material") is not: `escalate_full_review`
  (`src/earnings/cli.py:1513-1564`) always routes to another AI review round,
  never to a human. If a diff review keeps needing full re-review, or
  findings conflict across rounds, that is arguably the material ambiguity
  step 5 says should go to a person, not to another LLM call.
- **Status:** explicitly deferred, not started. Full assessment:
  `.agents/skills/verify-agent-workflows/references/pipeline-assessment-2026-09-08.md`.

### [2026-09-08] No knowledge-loop mechanism (validated GenAI patterns -> deterministic code)
- **Scope:** a way to notice when an agent-authored judgement call has become
  routine/validated enough to promote into deterministic Python (rule,
  template, or code), per the same design doc's section 5.
- **Why:** same assessment as above. This project is a POC and hasn't run
  enough cycles to need this yet, but nothing currently tracks candidate
  patterns for promotion, so it will stay invisible even once one exists.
- **Status:** explicitly deferred; revisit once the project has run enough
  real cycles that recurring agent judgement calls become visible (e.g. via
  repeated reviewer findings of the same shape across runs).

### [2026-08-2x] cli.py structural refactor
- **Scope:** split `cli.py` (1,231 lines) into `RunPaths`/`SearchQuery`/
  `SearchHit` dataclasses plus separate storage/web/sec/research/render/
  prepare/analyze modules. Blueprinted in-session but not started.
- **Do not start without asking** — explicitly deferred pending user go-ahead.
  A 2026-08-29 third-party audit independently flagged the same file for the
  same reason; that's corroboration, not a second item.

### [2026-08-29] Dead config: six settings defined but never read
- **Scope:** `SEC_SUBMISSIONS_URL`, `SEC_FORMS`,
  `RESEARCH_OFFICIAL_SOURCES_ONLY`, `RESEARCH_INCLUDE_PREVIOUS_PERIOD`,
  `TAVILY_SEARCH_DEPTH`, `TAVILY_INCLUDE_EXTERNAL_COMMENTARY` exist in
  `config.toml`/`config.py` but are read nowhere in the pipeline — false
  configurability.
- **Do not remove or wire in without asking** — user wants them kept in case
  they're needed later.

### [2026-08-30] Full content-level temporal assessment system
- **Scope:** an agent-authored assessment for each web page, exact dated passage,
  date meaning, evidence hash and a Python gate over that assessment.
- **Status:** explicitly deferred. The implemented POC records the cheaper
  `pre_event`/`post_event`/`undated`/`unchecked` metadata status and retains the
  reviewer as the content-level hindsight check. Revisit only if point-in-time
  proof becomes a research-grade or regulatory requirement.

### [2026-08-30] Establish a repository-wide Ruff baseline
- **Scope:** choose a project-specific Ruff configuration and address or baseline
  the existing diagnostics before applying automatic formatting across legacy files.
- **Status:** Ruff is now a development dependency, but only the new validation
  history module is lint-clean in this change. Do not run a broad auto-format until
  the repository's existing wide-line style and intentional Unicode test data have
  explicit rules.

### [2026-09-04] Layout-aware PDF extraction for speaker detection
- **Scope:** a new PDF-ingestion path that preserves page/position/font
  information (via pypdf's `visitor_text` API or a switch to PyMuPDF's
  block/line/span structure) instead of the current `ingest.py:_extract_pdf_text`
  flattening straight to plain text. Speaker detection would move from
  regex-on-flattened-text to scoring structural signals (bold + left-aligned +
  short line → likely speaker; centered/underlined → section heading; repeated
  top/bottom line across pages → header/footer), with an optional
  low-confidence-only constrained LLM fallback that maps numbered source blocks
  to speakers (never rewrites content; Python verifies every output block id
  exists and nothing was invented or dropped).
- **Why:** two rounds of regex hardening on `process.py`/`reformat.py` (fixing
  Unicode support, name particles, multi-comma affiliations, denylisted
  headers, metric-shaped false positives, FactSet role speakers and banner
  over-stripping — see `docs/REFERENCE.md`'s Known Limitations) closed every
  concretely-verified bug found so far, but the approach has a structural
  ceiling: case-less scripts (CJK, and any script with no upper/lowercase
  distinction) cannot be detected by any spelling-based heuristic, only by
  layout/typography. A third-party review independently proposed the same
  architecture, correctly diagnosing that PDF flattening discards exactly the
  information (bold, position, font) that makes speaker detection reliable and
  script-agnostic.
- **Status:** explicitly deferred, not started. This is a new extraction
  pipeline (page-aware text/spans → structural cleanup → confidence-scored
  speaker-candidate state machine → segments + anomaly receipt → optional LLM
  fallback), realistically 300–600+ lines with real design decisions (PyMuPDF
  vs. pypdf, how much of the state machine to build, whether to build the LLM
  fallback at all) — squarely an Opus-planning-tier item per this project's own
  >250-line rule, not a Sonnet patch. The project is explicitly a POC per
  `README.md`; the current one-off-reformatter-per-new-vendor pattern (see
  `build-earnings-source-pack/SKILL.md`'s self-healing step) is a working,
  if manual, escape hatch. Revisit if the project moves past POC status, or if
  a third vendor layout (or a case-less-script transcript) makes the one-off
  script pattern start costing more than the layout-aware rewrite would.
