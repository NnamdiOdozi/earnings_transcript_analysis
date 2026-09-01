# Workflow: running the pipeline end to end

This is the operational manual — the commands you actually run, in order, and
what each one does. For *why* the pipeline is split between Python and an
agent, see the README. For *what is mechanically guaranteed* at each gate, see
[AUDITABILITY.md](AUDITABILITY.md). For environment variables, provider
configuration, and edge cases, see [REFERENCE.md](REFERENCE.md).

Each step below is labelled:

- **DETERMINISTIC** — a Python CLI command. Same input, same output, every time.
- **AGENT JUDGMENT** — a human or an LLM agent has to read something and decide.

## 0. Install

```bash
uv sync --extra dev
cp .env.example .env   # fill in EXA_API_KEY / TAVILY_API_KEY / SEC_USER_AGENT
```

Web search and SEC lookup are both on by default. `config.toml [research]
provider` picks which web provider `prepare` calls (`"exa"` by default, or
`"tavily"` — see [REFERENCE.md](REFERENCE.md#web-research-provider)).

## 1. Discover the peer group — `earnings discover-peers`

**AGENT JUDGMENT** (which candidates to keep) over a **DETERMINISTIC** search step.

```bash
uv run earnings discover-peers --ticker MSFT --company-name "Microsoft" \
  [--event-date 2026-07-29]
```

Run this *before* `prepare`. A transcript itself usually names no competitors,
so the peer group has to be searched for, not read off the call. The command
searches for the company's analyst-recognised comparables and extracts a few
candidate pages to `runs/<TICKER>/peer-discovery/candidate-*.md`, hashed and
logged in that directory's own `manifest.json` so the eventual choice is
auditable.

**You (or the agent) read those pages** and pick the ~4 companies that recur
as agreed comparables — that selection is judgment, not the command's. Pass
them into `prepare` as `--peers`. Output is company-level, not per-event (a
company's peers don't shift by the quarter), so re-preparing a quarter never
disturbs it. `--event-date` is an optional safety net: a peer page dated after
it is dropped from extraction (undated ones still pass through). A rerun
archives the prior discovery under `_archive/` first, so stale candidate files
are never left for the agent to read.

## 2. Build the source pack — `earnings prepare`

**DETERMINISTIC.**

```bash
uv run earnings prepare \
  --ticker ACME --event-id 2026-q2 \
  --transcript tests/fixtures/normal_transcript.txt \
  --company-name "Acme Corp" --event-date 2026-07-15 \
  [--sec-cik <numeric CIK>] [--sec-period-end <YYYY-MM-DD>] \
  [--peers "Competitor A" "Competitor B" "Competitor C" "Competitor D"]
```

`--transcript` accepts a local path or a URL — either is fetched (if remote),
archived, and sanitised the same way. Accepted formats: `.txt`, `.md`,
`.html`, `.pdf` (converted via `pypdf`, with the original PDF bytes archived
alongside the converted text). A URL transcript larger than `config.toml
[http] max_fetch_mb` is **rejected**, never silently truncated. Always pass a
real `--event-date` on a live run — it sharpens web-search queries and is what
the causality guard checks against.

This one command does four things, in order:

1. Chooses the run, loads the transcript (and archives it verbatim before any
   sanitisation).
2. Pulls SEC financials, if a CIK is available (see
   [REFERENCE.md](REFERENCE.md#sec-configuration) for CIK resolution and
   period-end pinning).
3. Runs web search for what the call itself does *not* contain: analyst
   **consensus estimates** (always) and, when `--peers` is passed,
   **peer-group results** — see
   [REFERENCE.md](REFERENCE.md#web-research-provider) for how queries are
   built and the causality guard's real coverage.
4. Sanitises the transcript, splits it into speaker-labelled segments, and
   hashes + timestamps everything into `manifest.json`.

A rerun for the same ticker/event archives the prior run to
`_archive/<timestamp>/` first, rather than overwriting it. Agent-authored
claims and outlooks are extracted fresh for the new run; they are reused only
with the user's explicit consent.

**Inspect the pack before extracting claims** (AGENT JUDGMENT): open
`manifest.json` and confirm each source has a sha256 hash, a retrieval
timestamp, and an origin. Open `normalized/transcript.jsonl` and spot-check
that segments look right. If `evidence/web-evidence.jsonl` exists, check each
entry's `temporal_status` (`pre_event`, `undated`, `unchecked`) — a
`post_event` result must never appear as citable evidence.

## 3. Extract and validate claims — write `claims.json`, then `earnings analyze`

**AGENT JUDGMENT** to write `claims.json`, then **DETERMINISTIC** validation.

The agent reads the prepared pack and writes `claims.json`, one quote-anchored
entry per reportable fact (and optionally `metrics.json` for company-defined
metrics). See
`.agents/skills/produce-earnings-signal-card/reference/extraction-instructions.md`
for exactly what a claim needs.

```bash
uv run earnings analyze --ticker ACME --event-id 2026-q2
```

This runs every deterministic validator (exact-quote, numeric, calculation,
calculation-input grounding, claim-text numeric grounding,
inference-citation, metric-provenance, schema) and writes `validation.json`.
**Only if every check passes** does it write `signal-card.md`. A failing
claim — a paraphrased quote, a fabricated number, a wrong derived
calculation, an `analytical_inference` with no cited source claim, a `Metric`
with no `source_claim_ids` — blocks the card and exits non-zero.

**Correction loop:** if `analyze` fails, the agent rewrites the offending
claim(s) in `claims.json` and reruns `analyze`. Every invocation is preserved
under `_validation_history/attempt-<N>_<timestamp>/` (the submitted claims,
optional metrics, the validation report, and a receipt), so failed attempts
stay visible instead of being overwritten. There's no cap on this loop — keep
iterating until validation passes.

## 4. Build and gate the outlook — write `outlook-brief.md`, then `earnings validate-outlook`

**AGENT JUDGMENT** to write the brief, then **DETERMINISTIC** gating.

Once `analyze` passes, the agent writes `outlook-brief.md` — an interpretive,
forward-looking synthesis (base/upside/downside cases) — using
`.agents/skills/produce-earnings-signal-card/reference/outlook-brief-template.md`.

```bash
uv run earnings validate-outlook --ticker ACME --event-id 2026-q2
```

There's no deterministic way to grade "is this a good base case" — this gate
checks only what *can* be checked mechanically. It fails if:

- the underlying claims haven't passed `analyze`;
- any hashed analysis input has changed since `analyze` last ran (archived
  sources, the manifest, transcript, claims, financials, or metrics);
- the brief cites a claim id (`claim-###`) that doesn't exist in this run's
  `claims.json`;
- the brief cites **no** claim ids at all;
- a material number in the brief (one carrying a currency symbol, `%`, a
  magnitude word, bps, or an "x" multiple) isn't grounded in a claim cited
  alongside it — see
  `.agents/skills/produce-earnings-signal-card/reference/outlook-brief-template.md`'s
  "freedom envelope" for exactly what this does and doesn't restrict.

Every conclusion in the brief must trace back to real, validated evidence — but
the agent is free to synthesise new qualitative conclusions from several
validated claims at once; nothing requires every sentence to already exist
verbatim as a claim.

## 5. Independent review — `earnings check-review`

**AGENT JUDGMENT** (a fresh-context reviewer pass), then **DETERMINISTIC** gating.

A second, fresh-context agent pass reads the finished bundle and judges what
Python structurally can't: fair reading of quotes, narrative balance, material
omissions. In Claude Code this is the dedicated `outlook-reviewer` subagent
(`.agents/skills/review-earnings-run/SKILL.md`); elsewhere (Codex) the same
agent runs the review itself as a deliberate final pass
(`.agents/skills/review-outlook-brief/SKILL.md`). Either way, the reviewer
writes `review-report.json`.

```bash
uv run earnings check-review --ticker ACME --event-id 2026-q2
```

The reviewer grades each finding by severity, which determines whether the
run can finish:

| Severity | Plain-English meaning | Permitted verdict | Practical result |
|---|---|---|---|
| `info` | A check was completed or useful context was recorded. Not a problem. | `pass`, or `pass_with_warnings` if another warning exists | No correction required. |
| `low` | A local wording, attribution, or provenance problem that doesn't materially affect the analysis. | `pass` or `pass_with_warnings` | The run may complete; the issue is still recorded. |
| `medium` | A meaningful error exists, but the principal conclusion remains intact. | `pass_with_warnings` | The run completes, but the warning must be shown to the user. |
| `high` | Could materially change how the results, guidance, a central risk, or the outlook conclusion should be understood. | `fail` | The run stops for correction and re-review. |
| `critical` | The evidence or review is fundamentally unreliable (wrong company/period, fabricated support, a compromised evidence boundary). | `fail` | The run stops for correction and re-review. |

The reviewer decides severity because materiality is a matter of meaning, not
arithmetic — Python only enforces the recorded result (`pass` cannot contain a
`medium`/`high`/`critical` finding, and so on).

`check-review` requires `review-report.json` to exist, validates its schema,
artifact hashes, review mode, coverage receipts, verdict consistency, and
every claim id it cites, then renders `review-report.md`. It also requires
that `validate-outlook` has already passed and that `outlook-brief.md` hasn't
changed since (hash match) — the review can't run against a skipped or
subsequently-edited brief.

**Exit codes:**

| Exit | Meaning | What to do |
|---|---|---|
| `0` | Pass | Run complete. |
| `1` | Pass with warnings | Read the warnings; run is still complete. |
| `2` | Fail (or a schema/citation problem) | Not complete — revise `claims.json`/`outlook-brief.md`, don't patch the brief silently. |
| `3` | Reviewer itself judged a diff-based re-review insufficient and asked for a full one | A full review is dispatched again right away; it becomes the next round number, not a free retry. |
| `4` | Round cap reached | Stop entirely — surface the last verdict to the user, don't attempt another correction. |

### Round 1 is always a full review

From round 2 on, run:

```bash
uv run earnings review-diff --ticker ACME --event-id 2026-q2
```

This builds `review-diff.json` — which claims were added/changed/removed
since the last round, which brief sections cite them, and the prior round's
verdict — so the reviewer can target its re-read instead of rereading the
whole bundle.

Four things force a full review regardless of the diff:

1. More than `config.toml [review] diff_review_max_claims_changed` claims changed.
2. A changed claim's `period`/`values` differ.
3. A changed claim is cited in a conclusion-bearing section (Outlook in
   brief / Base / Upside / Downside case).
4. `outlook-brief.md`'s text changed at all since the last round.

`review-diff` only diffs `claims.json` in detail, not brief prose, so any
brief edit forces a full review rather than risk judging a narrative-only
correction from an empty diff. In practice this means most real correction
rounds (which usually touch the brief) escalate to a full review anyway; the
diff mechanism mainly pays off when a round's only change is to
`claims.json` itself.

**CRITICAL ordering rule:** run `check-review` immediately after the
reviewer, *before* touching `claims.json` or `outlook-brief.md` for any
correction. Editing first corrupts the round's snapshot, so the next diff
shows no changes even though real corrections happened.
`cmd_analyze`/`cmd_validate_outlook` refuse to run if an unclosed
`review-report.json` is sitting in the run directory, precisely to catch
this.

A hard cap (`config.toml [review] max_review_rounds`, default 3) refuses a
further review attempt outright once reached — the last verdict must be
surfaced to the user, never silently dropped. See
[AUDITABILITY.md](AUDITABILITY.md#7b-re-reviews-are-targeted-not-free--and-capped)
for why the diff mechanism and the cap exist and what they've caught in
practice.

## Run output layout

```text
runs/<ticker>/<event-id>/
  manifest.json               # source URLs/paths, timestamps, sha256 hashes, provider status, queries sent
  raw/                        # verbatim archived source, before sanitisation
  normalized/transcript.jsonl # sanitised, segmented, speaker-labelled transcript
  segmentation-report.json    # receipt for deliberately omitted structural lines
  evidence/financials.json    # SEC/XBRL evidence, if a CIK was resolved
  evidence/web-evidence.jsonl # extracted, citable web evidence (+ evidence/web/*.md)
  claims.json                 # quote-anchored claims (agent-written)
  metrics.json                # optional: company-defined metrics (agent-written)
  validation.json             # per-claim / per-metric pass/fail detail + real-clock validated_at
  _validation_history/
    attempt-<N>_<timestamp>/  # claims/optional metrics/validation + receipt for every analyze invocation
  signal-card.md               # written only after validation passes
  outlook-brief.md            # agent-authored forward-looking synthesis
  outlook-validation.json     # real-clock record of when validate-outlook last checked outlook-brief.md
  review-report.json          # agent-written semantic review verdict
  review-report.md            # rendered from review-report.json, never hand-written
  review-diff.json            # round 2+: what changed since the last round (Python-built)
  _review_history/round-<N>/  # per-round snapshot of claims/brief/report, for diffing
  _archive/<timestamp>/       # a prior run's files, if this ticker/event was prepared before
```

`discover-peers` writes separately to `runs/<ticker>/peer-discovery/`
(`candidate-*.md` + its own hashed `manifest.json`) — company-level, shared
across that company's quarters, so it sits outside any single event
directory.

### Where each file's content comes from

Two very different origins live in this one directory, and it matters which
is which when deciding how much to trust a number:

| File | Written by | Why |
|---|---|---|
| `manifest.json`, `raw/`, `normalized/transcript.jsonl` | Python | Mechanical fetch/transform of the source — no interpretation. |
| `evidence/financials.json` | Python (SEC XBRL API) | Self-documenting — carries its own filing accession number. |
| `evidence/web-evidence.jsonl` | Python (provider extract API) | Full extracted content, so it's quote-checkable, not just a search snippet. Each entry records a mechanical `temporal_status`. |
| `claims.json`, `metrics.json` | **Agent** | Interpretive — the agent decides what's worth reporting. Python only checks it, never writes it. |
| `validation.json`, `_validation_history/`, `signal-card.md` | Python | Deterministic result, append-only per-attempt snapshots, then a mechanical re-format of already-validated claims. |
| `outlook-brief.md` | **Agent** | Fully interpretive synthesis. Python only validates that the claim ids it cites resolve. |
| `outlook-validation.json` | Python | Real-clock record of when the brief was last checked (the brief itself carries no timestamp). |
| `review-report.json` | **Agent** (fresh-context reviewer) | Judgment Python cannot make, bound to the exact claims/brief/mode/diff hashes. |
| `review-report.md` | Python, from `review-report.json` | Never hand-written, so it can't drift from the structured verdict. |

### Cross-run processing log

Every `earnings prepare` call also appends one line to
`logs/processing_log.jsonl` (repo root, gitignored — local audit trail, not
checked in): timestamp, ticker, event id, the transcript source, and its
sha256/byte length. Unlike `manifest.json` (per-run, moved under `_archive/`
on a rerun), this log accumulates across every run ever prepared.

## Using the skills

Three repo-scoped skills live under `.agents/skills/`, used in order:

- **`build-earnings-source-pack`** — steps 1–2 above.
- **`produce-earnings-signal-card`** — steps 3–4 above (Stage 1: claims and
  `analyze`; Stage 2: the outlook brief and `validate-outlook`).
- **`review-earnings-run`** (Claude Code) or **`review-outlook-brief`**
  (Codex/other environments) — step 5 above.

Point your agent at this repo; it discovers each skill under
`.agents/skills/<name>/SKILL.md` and follows pointers into `reference/`.

## Running the tests

```bash
uv run --extra dev python -m pytest tests/ -q
```

Synthetic fixtures under `tests/fixtures/`, no network access. They cover
prompt-injection safety (embedded instructions stay inert data), the
validators' failure cases (paraphrased quote, fabricated number, wrong
calculation), the consensus/peer web path (queries run, class-tagged,
round-robined so peers aren't starved, causality guard), and three
differently-shaped businesses (SaaS, retailer, insurer) proving no
cross-industry contamination.
