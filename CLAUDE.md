# Earnings Transcript Analysis (POC)

Auditable pipeline: earnings-call transcript -> quote-anchored claims -> validated
signal card + outlook brief. Python does deterministic work only (ingest,
sanitise, hash, validate, calculate, render). Claim extraction, the outlook
brief, and the final review are agent-authored, via `.agents/skills/`. See
`README.md` first — it's the source of truth for architecture/commands/known
limitations; don't duplicate its content here.

## Mandatory agent entry condition

Before running a command or authoring any artifact, read the SKILL.md for the stage
you are performing and every reference file it requires, **in full** -- continuing
through truncation in numbered chunks rather than inferring from a partial read. This
file is an orientation summary; it is not sufficient to run a stage from.

Stage 1 extraction is **exhaustive, not selective**: one claim per material reportable
fact, guidance statement, explanation, risk and substantive Q&A insight in the source
pack, not just the ones the outlook brief will cite. Validation proves submitted
claims are grounded; it cannot detect claims you never wrote. See `AGENTS.md` and
`produce-earnings-signal-card/reference/extraction-instructions.md`.

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

## Jev / TypeSafe claim auditing

Before any Jev work, invoke the `typesafe:typesafe-ai` skill and read
`docs/JEV_CHECKS.md`. The skill is a plugin; only its one-line description is in
context by default, so it will not load itself. `docs/JEV_CHECKS.md` carries the
payload schema, the four question-design mistakes that cost real runs, and what Jev
provably cannot check.

Jev is an investigative tool, never a gate: it blocks nothing, and probabilities move
between runs (0.81 vs 0.76 on the same question). Use it to discover a defect class,
then write the deterministic check in `validate.py`. Tool: `scripts/jev_check.py`,
`--mode claims`, `--mode citations`, or `--mode coverage` (audits the coverage
receipt's `deliberately_immaterial` calls -- the one completeness question
`validate_coverage_receipt` explicitly cannot answer; always run its
`--coverage-scope extracted` control, since a question that can never say "material"
produces the same clean result as a perfect receipt). Every call is logged to `logs/jev_checks.jsonl`.

The answers do not stop at the log. The tool writes `jev-triage.json` beside the
stage's artifacts: a two-tier list of answers worth revisiting, where `defect` means
Jev's best reading disagrees with the record and `check` means the expected answer
won weakly — a losing option holding real probability, which is usually a lost
qualifier ("in excess of $2bn" extracted as `2.0`). The extractor answers each defect
in `jev-dispositions.json`; `earnings analyze` warns (never fails) on undisposed
ones; a claim whose figure is right but qualified carries a `caveats` sentence that
the brief author must honour and the reviewer checks. Nothing machine-checks the
honouring — that is a hand-off between three agents, not a validator.

## Conventions specific to this repo

- No provider SDKs in `sources.py` — raw `httpx` for Tavily/Exa/SEC alike.
- Run `uv run pytest -q` once at the end of a multi-file build, not per feature.
- Docs/tests should not scale linearly with a second provider/path — terse
  pointers over rewrites, `@pytest.mark.parametrize` over duplicated tests.
- Before trusting a third-party API's documented behavior (date filters,
  content endpoints), verify live with a real call — this project has hit two
  cases (Tavily, Exa) where docs didn't match live behavior.
- Record the host-reported model and reasoning effort for every agent-authored
  stage. Extraction passes them to `earnings analyze`, outlook authoring passes
  them to `earnings validate-outlook`, and review writes them into
  `review-report.json`. Use `unknown` rather than guessing. The final
  `audit-record.json` labels these values as agent-declared provenance.
