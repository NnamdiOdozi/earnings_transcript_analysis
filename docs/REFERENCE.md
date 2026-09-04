# Reference: configuration, providers, and operational edge cases

Detail that's useful when you're configuring or debugging a run, but doesn't
belong in the README or the step-by-step workflow. See
[WORKFLOW.md](WORKFLOW.md) for the commands themselves and
[AUDITABILITY.md](AUDITABILITY.md) for what's mechanically guaranteed.

## Environment variables

Set in `.env` (copy from `.env.example`, never commit the real file):

- `EXA_API_KEY` — required when `config.toml [research] provider = "exa"` (the default).
- `TAVILY_API_KEY` — required when `provider = "tavily"`.
- `SEC_USER_AGENT` — required for SEC XBRL lookups (SEC requires a contact
  string in the User-Agent header on every request).

Web search and SEC lookup are both on by default
(`config.toml [research] web_search_enabled` / `sec_enabled`, both `true`).

## Web research provider

**Exa is the default web research provider. Tavily is the supported
backup/alternative.** Toggle with `config.toml [research] provider` (`"exa"`
or `"tavily"`) — this is a pure switch: whichever is configured is the only
one `earnings prepare` calls, no fallback, no dual-run. `cli.py` never calls
`tavily_search`/`exa_search` directly; both go through the provider-agnostic
`sources.web_search()`/`web_extract()`.

### What gets searched for

`earnings prepare` builds queries from two config-driven, industry-agnostic
classes, targeting information the transcript does **not** already contain:

- **consensus** — `config.toml [research] consensus_queries` (5 templates by
  default): analyst estimates/expectations for this event, so the beat-or-miss
  surprise becomes citable. Always run.
- **peer** — `config.toml [research] peer_queries` (5 templates by default),
  one query per template per name passed to `--peers`. With no `--peers`, no
  peer queries run.

Every hit is archived under `raw/web/`, hashed, and timestamped. Up to
`config.toml [tavily]`/`[exa] max_extracted_sources` (default 15) are selected
for full extraction, by round-robin across buckets (consensus, and each peer
separately) rather than a flat score sort — this stops one bucket with
more/higher-scored hits from starving the others.

Search hits per query (`[tavily] max_results` / `[exa] num_results`, default 8)
are deliberately generous relative to the extraction cap: search is cheap
candidate generation, several hits will turn out post-event, undated, or
duplicate, and more query templates increase retrieval *diversity* rather than
just returning a bigger sample of the same ranking. The **retrieval boundary**
(what's searched and archived) is wider on purpose than the **evidence
boundary** (what's extracted into `evidence/web-evidence.jsonl`) and the
**analytical boundary** (what a claim actually cites) — widening query/hit
counts gives the deterministic filters more to screen, it does not by itself
put more material in front of the LLM.

### Exa vs. Tavily differences

Both providers are called through the same generic search/extract flow; the
differences that matter operationally:

- **Config sections.** Provider-specific defaults live under
  `config.toml [tavily]` (`search_depth`, `max_results`,
  `include_answer = false`, `include_raw_content = false` — this project
  needs primary source material, not a provider's own generated summary) and
  `config.toml [exa]` (`type = "auto"`, meaning Exa's own auto neural/keyword
  selection).
- **Prompt-injection defenses.** Tavily states it filters malicious prompt
  injection before it reaches the model; Exa publishes SOC 2 and
  zero-data-retention assurances but no injection-specific filter. Either
  way, extracted content is still bound by this project's own exact-quote and
  number checks (see [AUDITABILITY.md](AUDITABILITY.md#5-guarding-against-prompt-injection)).
- **Calling a provider directly, ad hoc.** `sources.py` also exposes
  `tavily_search`/`tavily_extract` and `exa_search`/`exa_contents` for a
  specific, user-named fetch beyond the standard queries (e.g. "also pull the
  press release from investor relations"). Use whichever pair matches
  `config.toml [research] provider` — don't call the other provider's
  functions directly, since its API key may not even be configured.

### Causality guard: two layers, one weaker than it looks

A source published after the earnings event cannot have informed anything
said on the call, so it must never be citable evidence for a pre-results
outlook.

1. **Server-side, attempted.** The provider's own date-filter parameter
   (Tavily's `end_date`, Exa's `endPublishedDate`) is passed with every query
   when `--event-date` parses as a real date. **Confirmed by live testing on
   2026-08-26: not reliably enforced by either provider** — identical result
   sets were returned with and without the date filter set, including hits
   published years after the cutoff. Still sent (harmless, spec-correct, may
   work on a different plan/API version), but don't treat it as a real
   guarantee.
2. **Client-side, the actual guard.** Any hit whose `published_date` is after
   `--event-date` is dropped from the extraction-selection pool (still
   archived under `raw/web/`, just never extracted). This is real
   enforcement, but with a real gap: most hits — especially evergreen
   stock-data/aggregator pages — carry **no `published_date` at all**, so
   this check can't act on them. Python labels every hit's
   `_temporal_status`/`temporal_status`: `pre_event`, `post_event`,
   `undated`, or `unchecked` when no cutoff was supplied.

Net effect: a *dated* post-event source is reliably excluded. An *undated*
one is labelled but remains eligible — a real gap, not a rounding error. This
matters more now that web search targets **consensus** and **peer** results:
a consensus page is often undated *and* living (the same URL shows the
pre-event estimate before the call and the reported beat/miss after), so an
undated consensus hit fetched long after the event can be post-event-
contaminated and slip through. The `outlook-reviewer`'s temporal-integrity
check is the backstop, and the extraction skill tells the agent to judge
undated content and ignore any peer that reported *after* the event.
Dropping undated hits outright was rejected — too much real material carries
no date.

## SEC configuration

SEC evidence is opt-in per company, not universal. Pass `--sec-cik <numeric
CIK>` to pull revenue / net income / diluted EPS from SEC's company-facts
XBRL API (requires `SEC_USER_AGENT`), or leave it off and the CIK is
auto-resolved from `--ticker` (disable with `config.toml [sec]
resolve_cik_from_ticker = false`).

If the company isn't an SEC registrant discoverable by ticker,
`manifest.json` records `"SEC evidence: not_applicable"` and the run
continues — expected for non-US-listed companies, not a failure.

### Period-end pinning

Add `--sec-period-end <YYYY-MM-DD>` (the XBRL period-end date matching the
earnings event) to pin the pulled facts to that period. Without it, the
latest-by-end fact is used, which can silently be a later quarter or an
annual figure. When multiple facts share the same pinned period end (e.g. a
restatement), the **original (earliest-filed)** fact is selected, so a later
restatement of the same period can't silently replace it.

`config.toml [sec].forms` is informational (documents the filing types this
POC expects to encounter) — it is not yet used to filter or validate filing
types.

## Known limitations

- **Speaker-label detection** is a line-start heuristic; unconventional
  transcript formatting may leave `speaker` as `null`. As of 2026-09-04, names may
  contain any word in any case-bearing script (Latin incl. Extended-A, Cyrillic,
  Greek, ...) -- validated via Python's `str.isupper()` in
  `process._is_valid_speaker_name`, not a hand-enumerated Unicode character-class
  range, after an earlier ASCII/Latin-1-only fix still missed e.g. Czech/Polish
  capitals. Lowercase name particles ("van", "von", "de", ...) are allowed
  mid-name via `config.toml [segmentation] speaker_name_particles`. A "Name,
  Title, Company" header with multiple commas, and a multi-word name up to 10
  words, are both supported. A known, structural (not merely unfixed) limitation
  remains: **case-less scripts (CJK, and any script with no upper/lowercase
  distinction) cannot be detected at all** by an "uppercase first letter"
  heuristic -- this requires layout/typography information (bold, position) that
  the current plain-text PDF extraction discards; see `DEFERRED_WORK.md`'s
  layout-aware PDF extraction entry. A candidate is also rejected if it matches
  `config.toml [segmentation] speaker_denylist_patterns` (known non-name section
  headers like "Forward Looking Statements") or if its dash-separated "title"
  portion contains a digit/currency/percent character (a real title never does;
  catches false positives like "Group Sales — 3.6%:"). All rejections fail
  loudly -- the turn merges into the previous speaker and, if it looks
  speaker-shaped, is recorded as an advisory `near_miss_speakers` entry in
  `segmentation-report.json` -- rather than silently fabricating an attribution.
- **Q&A boundary detection** relies on marker phrases (e.g.
  "question-and-answer session"); transcripts without such a marker are
  treated as entirely "prepared."
- **SEC and web-provider access are thin** — no retry/backoff or pagination
  handling (POC, not a production integration).
- **`official_sources_only` is not domain-filtered** — `prepare` archives
  whatever the search API returns for the narrow generic queries; it does not
  verify each hit's URL is actually the company's own domain or a regulator.
- **Cross-period metric comparison** relies on the agent noticing a
  definition/unit change and flagging it as an `analytical_inference`; Python
  does not itself detect a silently redefined metric.
- **Claim period metadata is agent-judged.** A transcript's own spoken
  figures carry no structured period metadata (unlike SEC/XBRL facts, which
  have explicit `start`/`end` dates), so `Claim.period` — whether a figure is
  quarterly, year-to-date, etc. — remains an agent reading-comprehension
  judgment from context cues ("this quarter" vs. "year-to-date"), not
  something Python can derive; see `extraction-instructions.md`.
- **Parenthetical-negative accounting notation** (`(50) million` meaning
  -\$50M) is not recognized by `extract_numbers`'s number regex — it would be
  read as positive 50. Deliberately not implemented: earnings-call *spoken*
  prose rarely uses this notation (it's a tabular-filing convention), and
  auto-converting `(...)` risks misreading an ordinary parenthetical aside as
  a negative number. Add a conditional pre-pass if this notation is ever
  confirmed to appear in evidence text. Hyphenated ranges ("37%-38%") and
  genuine negatives ("-\$50 million") are both handled correctly.
- **The causality guard's server-side layer is not reliably enforced** — see
  above.
