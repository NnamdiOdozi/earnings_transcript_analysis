# Deferred Work

Scoped-but-not-executed work items, so they don't get silently forgotten.
This file lists only what is genuinely still open — one entry per item, with
enough context to pick it back up. Once an item is completed or dropped,
remove its entry (the commit history / conversation is the record of how it
was resolved); don't let finished work accumulate here as dead weight.

## Open

### [2026-09-11] Confidence labels for outlook-brief judgments
- **Scope:** while the existing authoring agent writes `outlook-brief.md`, label
  each material judgment or reasoning proposition with `high`, `medium`, or
  `low` confidence. Factual statements copied from the validated claims do not
  need a separate label. This belongs inside the current signal-card-to-outlook
  step, not in a new agent, artifact, or workflow stage.
- **Placement:** keep the label directly in `outlook-brief.md`, immediately
  after the sentence or paragraph containing the relevant proposition. One
  label may cover several sentences when they form a single analytical
  proposition. Do not create a separate confidence file or assign one score to
  the whole document; both approaches would obscure which judgment the label
  describes and could drift out of sync with the prose.
- **Values:** use only `High`, `Medium`, or `Low`. Two levels would be too
  coarse: `Medium` captures a reasonable conclusion that still depends on
  meaningful assumptions. A simple visible form such as `**Confidence:
  Medium**` is sufficient. Do not require a second written rationale because
  the proposition and its existing claim citations already provide the review
  context.
- **Why:** the brief adds interpretation beyond the factual signal card. The
  label should make the author's own uncertainty visible without duplicating
  the existing claim citations or adding another assessment system. Treat it
  as a routing aid, not proof of correctness; low-confidence propositions
  should always be surfaced to the final human reviewer. High and medium
  confidence remain the authoring agent's self-assessment and do not prove that
  the reasoning is correct.
- **Status:** idea only, not started. Keep the implementation deliberately
  small. When this work is taken up, decide only how low-confidence items are
  gathered for human review and whether a missing label should fail validation.

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

### [2026-09-16] Nothing enforces the coverage receipt
- **Scope:** `coverage-receipt.json` is now required by
  `produce-earnings-signal-card` and specified in `extraction-instructions.md`, but no
  Python reads it and no reviewer audits it. Two separable pieces of enforcement are
  missing, and they are NOT equally hard:
  - **Structural completeness is deterministic and cheap.** `analyze` can check that
    the receipt exists, that its segment ids are exactly the set in
    `normalized/transcript.jsonl` with none missing or invented, that every
    `claim_ids` entry resolves in `claims.json`, that `claims_extracted` entries are
    non-empty and `deliberately_immaterial` entries carry a reason. That converts "did
    the agent account for the whole transcript?" from unverifiable to proven, and
    would have caught the JPM under-extraction at the gate. Roughly a validator
    function plus a `RunPaths` property plus a config filename constant.
  - **Materiality judgement is semantic and is not.** No deterministic check can tell
    a correct `deliberately_immaterial` from a wrong one. That belongs to the
    `outlook-reviewer`'s remit -- give it the receipt and ask it to sample the
    segments marked immaterial -- and even then it is a judgement, not a proof.
- **Why it matters:** confirmed live (JPM/2026-q2, 2026-09-16). A desktop agent
  working from a partial read of the skill produced roughly a quarter of the material
  claims the same source pack supports, and every gate passed cleanly. Validation
  proves submitted claims are grounded; it is structurally blind to claims never
  written, so no existing check could have caught it.
- **Status:** documentation only, 2026-09-16. The rule, the receipt schema and the
  immateriality standard are written; the enforcement above is not started. Until the
  structural check lands, a passing run says nothing about extraction completeness --
  say so plainly rather than implying the receipt is a control.

### [2026-09-16] prepare.py and review.py exceed the 500-line guideline
- **Scope:** the cli.py split landed as a strictly behaviour-preserving move, which
  left two modules over the project's 500-line guideline: `prepare.py` (528) and
  `review.py` (516). Neither can be reduced by moving whole functions — `cmd_prepare`
  is 363 lines on its own, so cutting it means restructuring its internals
  (transcript ingest, SEC fetch, web search, extraction selection, manifest assembly
  are all inline in one function).
- **Why deferred:** decomposing `cmd_prepare` is a behavioural change, not a move,
  and mixing it into the split would have made the diff unreviewable — every other
  function in that change is byte-identical to its original, which is what made the
  split verifiable at all.
- **Status:** not started, 2026-09-16. Do this as its own scoped change with the
  test suite green before and after, not bundled with anything else.

### [2026-08-29] Dead config: six settings defined but never read
- **Scope:** `SEC_SUBMISSIONS_URL`, `SEC_FORMS`,
  `RESEARCH_OFFICIAL_SOURCES_ONLY`, `RESEARCH_INCLUDE_PREVIOUS_PERIOD`,
  `TAVILY_SEARCH_DEPTH`, `TAVILY_INCLUDE_EXTERNAL_COMMENTARY` exist in
  `config.toml`/`config.py` but are read nowhere in the pipeline — false
  configurability.
- **Do not remove or wire in without asking** — user wants them kept in case
  they're needed later.

### [2026-09-14] `event_day` temporal status for same-day sources
- **Scope:** add a fourth `TemporalStatus` value for the case
  `published_date == event_cutoff`. Today `cli._classify_temporal_status` uses a
  strict `>` at day granularity, so a hit published *on* the event date is labelled
  `pre_event` by construction -- including everything published after the results
  dropped, which for a pre-market reporter is most of that day's coverage. Touches
  `models.TemporalStatus`, `cli._classify_temporal_status`, the selection filter,
  `web-search-usage.md`, `docs/REFERENCE.md` and tests; roughly 50-60 lines.
- **Why:** confirmed live (JPM/2026-q2, 2026-09-14, cutoff 2026-07-14). Articles
  headlined "JPMorgan Chase posts 27% revenue jump in Q2 2026" and "Goldman Sachs
  delivers 45% Q2 2026 EPS beat" were both stamped `pre_event`, as was `web-011`,
  whose body reads `EPS BEAT 5.59 6.14`. The extracting agent caught all three by
  reading content, but the label actively pointed the wrong way, and the operator
  reviewing the run could not tell from the label why they had been excluded.
- **Decision needed:** whether a same-day hit stays eligible for extraction (labelled
  honestly, judged on content -- consistent with the `undated` treatment) or is
  dropped from the selection pool. Dropping it would exclude genuine morning-of
  previews, so eligible-but-labelled is the likelier answer.
- **Status:** not started, 2026-09-14. The day's cheaper half was done instead:
  `manifest.json` now records `event_date`, and the day-granularity caveat is
  documented in `web-search-usage.md`, `extraction-instructions.md`,
  `docs/REFERENCE.md` and the classifier's own docstring. Related:
  [2026-08-30] full content-level temporal assessment, below.

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
