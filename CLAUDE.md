# Earnings Transcript Analysis (POC)

Auditable pipeline: earnings-call transcript -> quote-anchored claims -> validated
signal card + outlook brief. Python does deterministic work only (ingest,
sanitise, hash, validate, calculate, render). Claim extraction, the outlook
brief, and the final review are agent-authored, via `.agents/skills/`. See
`README.md` first — it's the source of truth for architecture/commands/known
limitations; don't duplicate its content here.

## Entry points

- `.agents/skills/<name>/SKILL.md` — Codex/any-agent skills, run in order:
  `build-earnings-source-pack`, `produce-earnings-signal-card`,
  `review-earnings-run` (Claude Code) / `review-earnings-run-codex` (Codex).
- `.claude/agents/outlook-reviewer.md` — Claude Code subagent for the final
  semantic review (fresh context, dispatched after `validate-outlook` passes).
- `src/earnings/` — all deterministic logic, one module per workflow stage:
  `prepare.py`, `analysis.py`, `outlook.py`, `review.py`, `audit.py`. `cli.py` is
  argparse wiring and dispatch only — put no logic there. Supporting modules:
  `paths.py` (the ONLY place the run-directory layout is expressed — see below),
  `provenance.py` (hashing/staleness gates), `rendering.py`, `research.py`,
  `runio.py`, plus `sources.py`, `validate.py`, `process.py`, `models.py`,
  `config.py`.
- Run layout: a run declares `layout_version` in its `manifest.json`. 2 = staged
  (`claims/`, `outlook/`, `review/`, each with its own `history/`); 1 = the older
  flat root. Old runs are never migrated, so both shapes are live. Ask
  `paths.RunPaths` for a path; never join `run_dir` with a filename yourself.

## Web search: two providers, one active at a time

`config.toml [research] provider` = `"exa"` (default) or `"tavily"` — pure
toggle, no fallback, no dual-run. Both dispatch through
`sources.web_search`/`web_extract`; never call `tavily_search`/`exa_search`
directly from `prepare.py`. **Neither provider's date filter reliably excludes
post-event content** (live-tested both, 2026-08-26) — the client-side
`published_date` check in `cmd_prepare` is the real (partial) guard; the
`outlook-reviewer`'s temporal-integrity check is the backstop for undated hits.
See README "Known limitations" before touching this area.

## Conventions specific to this repo

- No provider SDKs in `sources.py` — raw `httpx` for Tavily/Exa/SEC alike.
- Run `uv run pytest -q` once at the end of a multi-file build, not per feature.
- Docs/tests should not scale linearly with a second provider/path — terse
  pointers over rewrites, `@pytest.mark.parametrize` over duplicated tests.
- Before trusting a third-party API's documented behavior (date filters,
  content endpoints), verify live with a real call — this project has hit two
  cases (Tavily, Exa) where docs didn't match live behavior.
