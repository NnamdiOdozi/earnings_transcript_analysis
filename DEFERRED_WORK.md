# Deferred Work

Scoped-but-not-executed work items, so they don't get silently forgotten.
This file lists only what is genuinely still open — one entry per item, with
enough context to pick it back up. Once an item is completed or dropped,
remove its entry (the commit history / conversation is the record of how it
was resolved); don't let finished work accumulate here as dead weight.

## Open

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
