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
  `review-earnings-run` (Claude Code) / `review-outlook-brief` (Codex).
- `.claude/agents/outlook-reviewer.md` — Claude Code subagent for the final
  semantic review (fresh context, dispatched after `validate-outlook` passes).
- `src/earnings/` — all deterministic logic (`cli.py`, `sources.py`,
  `validate.py`, `models.py`, `config.py`).

## Web search: two providers, one active at a time

`config.toml [research] provider` = `"exa"` (default) or `"tavily"` — pure
toggle, no fallback, no dual-run. Both dispatch through
`sources.web_search`/`web_extract`; never call `tavily_search`/`exa_search`
directly from `cli.py`. **Neither provider's date filter reliably excludes
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
