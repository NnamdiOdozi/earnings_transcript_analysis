# Checking claims with Jev (TypeSafe System One)

How we use TypeSafe's Jev model to audit extracted claims, what it caught that our
Python gates could not, what it missed, and the question-design mistakes that cost us
two wasted runs. Written after auditing the JPM/2026-q2-rerun run on 2026-09-19.

**Jev is not part of the pipeline.** It has no exit code, blocks nothing, and is not a
gate. It is a manual investigative tool you point at a finished `claims.json`. Do not
describe a Jev result as validation.

## What Jev is

TypeSafe's System One models return typed judgments and probabilities instead of
generated text. You give it **state** (the evidence and the record under audit) and a
set of **questions**, and it returns a probability per question. It is cheap enough
that cost is not a planning consideration: 4.2 cents per million input tokens, free
output. Auditing 72 claims with 494 questions cost 0.84 cents.

Three primitives. Pick by what the answer means:

| Need | Primitive | Returns |
| --- | --- | --- |
| Whether a condition holds | `noul` | probability of yes |
| One of a defined set | `choice` | a pick, plus a distribution over options |
| Degree along a described dimension | `score` | position on ordered levels |

A `noul` near 0.5 means the model finds yes and no roughly equally likely. **It does
not mean "medium".** We misread this initially.

## The endpoint

OpenRouter serves these on a separate decisions endpoint, not chat completions:

```
POST https://openrouter.ai/api/alpha/decisions
{"model": "typesafe/jev-1.13", "state": "...", "questions": {...}}
```

Auth is `Authorization: Bearer $OPENROUTER_API_KEY`. Read the key from the environment
in code — never interpolate it into a shell command, where it lands in the process list
and shell history.

The tool is `scripts/jev_check.py`:

```bash
uv run python scripts/jev_check.py runs/JPM/2026-q2-rerun            # claims carrying values
uv run python scripts/jev_check.py runs/JPM/2026-q2-rerun --all-claims
uv run python scripts/jev_check.py runs/JPM/2026-q2-rerun --limit 3  # smoke test
```

The earlier throwaway versions in `scratch/jev/` are superseded; `scratch/` is
gitignored and those wrote no log.

## The four mistakes we made

These cost real runs. All four produce confident-looking numbers, which is what makes
them dangerous — a broken question does not announce itself.

### 1. Question and criteria pointing opposite ways

We wrote the instruction negatively and the true-criterion positively:

```
instructions: "Does claim_text assert anything the quote does not support?"
criteria.true: "claim_text asserts only what the quote states."
```

Answering the question truthfully makes the criterion false. Jev returned 0.10 and
0.46 — the honest response to an incoherent question, which reads exactly like "your
claim is bad". We made this mistake twice, on three questions.

**Rule: phrase every question positively.** "Is every assertion in claim_text supported
by the quote?" Rewritten, the same claims scored 0.95 and 0.74.

### 2. Asking a question the state cannot answer

We asked whether a claim's `classification` was correct without putting the taxonomy in
the state. Jev was judging `management_opinion` against whatever those English words
suggest, not against this project's five defined labels. Nineteen claims scored below
0.80 and none of those scores mean anything.

**Rule: if the judgment depends on a project-specific definition, paste the definition
into the question.** Better still, use `choice` over the five labels and compare the
pick to the extractor's label in code, rather than asking `noul` "is this right?".

### 3. Circular questions

We asked whether the claim's `speaker` was correct — but the state contained the
speaker name twice, both times placed there by our own payload builder (once in a
segment header we wrote, once in the claim record). Jev was comparing two identical
strings. It scored 0.96 and proved nothing.

Worse, the six claims in that run where `claim.speaker` genuinely disagreed with the
segment's recorded speaker were never sent, because they carried no `values` and our
batch filtered on that. One line of Python found all six exactly.

**Rule: before asking Jev, ask whether Python already knows the answer with
certainty.** If yes, do it in Python. Spend Jev on judgments only.

### 4. Scoping the state too narrowly

We asked whether a claim's `period` was right while giving only the segment the quote
came from. Earnings-call speakers say "this quarter", never "the three months to 30
June 2026" — the period is fixed by the operator's opening and the manifest, elsewhere
in the run. Jev correctly returned 0.57 to an unanswerable question. One line of call
context lifted it to 0.92.

**Rule: a claim's fields are not all verifiable from the segment its quote came from.
Include run-level context.**

## Question IDs are labels, not questions

The key in the `questions` object is for your code. It is not sent to the model. So
`speaker_correct` conveys nothing — all the meaning has to be inside `instructions` and
`criteria`. Naming a question well does not make it a good question.

## What Jev caught that our gates did not

Two defect families, both invisible to `validate.py` at the time:

**Qualifier loss in `values`.** A Microsoft claim recorded `over two billion dollars` as
`{"annual_revenue_run_rate_billions": 2}`. The floor became an exact figure. `claim_text`
kept "above $2 billion"; only the structured value lost it. Jev scored it 0.24 while
scoring a genuinely exact figure in the same claim 0.93 — it distinguished the two.

**`claim_text` over-asserting relative to its own quote.** Thirty-two of 72 claims scored
below 0.80. Four of those stated a *number* absent from the quote, and a deterministic
check confirmed exactly those four — Jev's four lowest scores were the same four claims.
The other 28 were qualitative additions ("its third consecutive record quarter") that no
mechanical check can see.

That second family is now enforced: `check_claim_text_quote_traceable` in `validate.py`.
Jev found the problem; Python now guards it. **That is the intended lifecycle — use Jev
to discover a defect class, then write the deterministic check.**

## What Jev could not catch

The single false statement in that run was `claim-197`: "every large-bank peer reported
double-digit revenue growth". One of four had not.

Jev never saw it. The claim carries no `values`, so our batch filtered it out — and even
unfiltered, verifying it needs four peers' revenue figures compared against four
different source documents, which is not a judgment about one claim against one quote.
The Opus reviewer found it by reading the evidence folder.

**Jev audits a claim against its own cited evidence. It cannot audit a claim against a
set of other documents.** Keep the semantic reviewer for that.

## The payload we now send

`scripts/jev_check.py` builds it. One request per claim, **mixing all three primitives
in a single `questions` object** — `type` is per question, so choice, score and noul
travel together and are answered in parallel.

```json
{
  "model": "typesafe/jev-1.13",
  "state": "CALL CONTEXT: ...\n\nSOURCE SEGMENT (seg-0003, prepared):\n...\n\nEXTRACTED CLAIM RECORD — audit each field separately:\n{ ... }",
  "questions": {
    "claim_vs_evidence": {
      "type": "choice",
      "instructions": "How does the source section relate to the claim in claim_text?",
      "criteria": {
        "supports": "The section states the claim or directly implies that it is true",
        "contradicts": "The section states the opposite of the claim or implies it is false",
        "says_nothing": "The section does not address what the claim asserts, either way"
      }
    },
    "classification": {
      "type": "choice",
      "instructions": "Which label best describes what kind of statement claim_text is?",
      "criteria": {
        "reported_fact": "An actual, already-occurred result.",
        "management_guidance": "Forward-looking guidance given by management.",
        "management_opinion": "Management's own interpretation or opinion, not a hard number.",
        "analyst_question": "The substance of what an analyst asked, from Q&A.",
        "analytical_inference": "A conclusion drawn by the analyst writing the record, not something anyone on the call stated directly."
      }
    },
    "values_capture": {
      "type": "score",
      "instructions": "How completely does the values object capture the figures stated in the quote?",
      "criteria": [
        "The quote states figures and values captures none of them.",
        "values captures some stated figures but omits at least one material figure.",
        "values captures every material figure but omits a minor or incidental one.",
        "Every figure stated in the quote appears in values."
      ]
    },
    "claim_text_traceable": {
      "type": "noul",
      "instructions": "Is every assertion in claim_text supported by the quote alone, without relying on other parts of the source document?",
      "criteria": {
        "true": "The quote alone carries every figure and qualifier claim_text asserts.",
        "false": "claim_text asserts a figure or qualifier absent from the quote."
      }
    },
    "value__expenses_usd_billion": {
      "type": "noul",
      "instructions": "The record extracts values['expenses_usd_billion'] = 27.3. Read the quote. Is that the correct number for that named metric?",
      "criteria": {
        "true": "The quote states this exact figure for the metric named 'expenses_usd_billion'.",
        "false": "Wrong figure, wrong metric, a lost qualifier such as 'over' or 'approximately', or the wrong unit or scale."
      }
    }
  }
}
```

`period_correct` (noul) is added only when the claim carries a `period`. One
`value__<key>` noul is generated per numeric entry in `values`.

### Two schema traps

**`score` criteria are an ordered ARRAY, not an object.** Between two and ten level
descriptions, lowest to highest. Passing an object returns HTTP 400 with
`"expected": "array"`. We hit this on the first run of the new payload. `choice` and
`noul` criteria *are* objects — so the three primitives do not share one shape.

**Each primitive returns a different answer field.** `choice` returns `choice` plus
`confidence` and a distribution; `score` returns a fractional `score` plus `legend`
mapping levels back to descriptions; `noul` returns `noul` alone, with no separate
confidence. Code reading the response has to branch on `type`.

A real response for one claim:

```
claim_vs_evidence            choice -> supports        conf=1
classification               choice -> reported_fact   conf=1
values_capture               score  -> 2.96            conf=0.96
claim_text_traceable         noul   -> 0.92
period_correct               noul   -> 0.91
value__expenses_usd_billion  noul   -> 0.99
```

`values_capture` at 2.96 on a 0-3 scale is the useful shape: near-complete capture,
without collapsing "captured most" and "captured none" into one low boolean.

### How to consume it

`classification` is deliberately **not** asked as "is this label right?". Jev picks the
label; your code compares the pick against what the extractor wrote and flags the
disagreements. That removes the model's need to know your taxonomy is authoritative —
it only has to read the definitions you supplied.

`config.toml [jev]` holds the model id, endpoint, request pause, and the four triage
thresholds. Nothing is hardcoded in the script. What the tool does with the answers is
in "Triage" below — that is the part that decides which of them anyone ever reads.

## Mode 2: checking the brief's citations

```bash
uv run python scripts/jev_check.py runs/JPM/2026-q2-rerun --mode citations
```

This closes a gap no deterministic gate covers. `earnings validate-outlook` proves a
cited claim id **resolves**. It cannot tell a correct citation from a plausible wrong
one, and that exact failure has now bitten this project twice: SBRY/q1-2627 attached a
transcript quotation to a claim that did not contain it, and JPM/2026-q2-rerun cited
`claim-095` — an analyst's separate question about a 77% marginal margin — to support a
sentence counting how many analysts pressed management on operating leverage. Both
citations resolved cleanly. Both were wrong. Only the Opus reviewer caught the second.

It pairs every `[claim-###]` in the brief's argued prose with the claim it points at,
and asks a `choice`: does the claim **support**, **contradict**, or **say nothing about**
the specific point the passage uses it for. A second `noul` asks whether any wording the
passage puts in quotation marks actually appears in the cited claim's quote — the SBRY
failure mode, and an existing rule in `.agents/memory/extractor-lessons.md`.

The evidence appendix is skipped deliberately: it restates each claim's own quote, so
checking a citation there compares a claim against itself.

**It catches the real case.** Run against the pre-correction brief, on the flagged
sentence citing three claims:

```
claim-063: supports      conf=0.70   probs {supports 0.80, says_nothing 0.15, contradicts 0.05}
claim-081: supports      conf=0.91   probs {supports 0.94, contradicts 0.05, says_nothing 0.01}
claim-095: says_nothing  conf=0.62   probs {says_nothing 0.75, supports 0.14, contradicts 0.11}
```

The two sound citations score as `supports`; the miscitation is isolated as
`says_nothing` at 0.75. 145 citations cost 0.47 US cents.

### Known weakness: passages carrying several citations

Over the corrected brief, 132 of 145 came back `supports`, 8 `says_nothing`, 5
`contradicts` — but **59 of 145 had confidence below 0.8**. Confidence on a `choice` is
distribution concentration, so that is the model spreading probability, not the citation
being wrong.

The likely cause is our own framing. The state is the whole paragraph, which often cites
four or five claims for four or five different points, so "the specific point the passage
uses it for" is genuinely ambiguous. Narrowing the passage to the sentence containing the
citation would sharpen it, at the cost of losing context the model sometimes needs. That
is untested. **Treat the current output as a ranked triage list, not a verdict**, and read
the `contradicts` and `says_nothing` rows first.

## Mode 3: auditing the coverage receipt's immaterial calls

`--mode coverage`. The one completeness question nothing else in the pipeline asks.

`validate_coverage_receipt` proves every segment id is *accounted for* in
`coverage-receipt.json`. Its own docstring concedes what it cannot do: prove that a
`deliberately_immaterial` row was the right call. No reviewer is instructed to audit
those rows either, so a material segment hidden behind a plausible one-line reason is
invisible to every gate in the run. On JPM/2026-q2-rerun that is 43 of 109 segments.

One `choice` per immaterial segment, `material` vs `immaterial`, with the project's
materiality bar pasted into the criteria. Segments that produced claims are not sent:
they have already declared themselves material. Two things are deliberately kept out
of the state -- the receipt's `outcome` and its `reason`. Telling Jev what the record
concluded invites agreement, and the error that matters here is the permissive one.

The existing triage rules apply unchanged: `material` winning is a `defect`, and
`immaterial` winning while `material` holds 0.20 or more is a `check`, which is the
grey zone worth re-reading.

### The control run, and why a clean result needs one

`--coverage-scope extracted` re-asks the same question about the 66 segments that DID
produce claims. It writes no triage file -- the expected answer is inverted there, so a
triage file would be a lie -- and just prints the distribution.

This is not optional colour. The first real run flagged 0 of 43, and that number means
nothing on its own: a question that can never say `material` produces exactly the same
result as a perfect receipt. The control is what separates the two.

### Three iterations, and what each one cost

| Question design | Control: material / 66 | Real run: flagged / 43 |
|---|---|---|
| First cut: financial content only, plus a `noul` | 48 | 5, all false positives |
| Criteria widened to the real materiality bar | 55 | 0 |
| Plus the two preceding turns as context | **60** | **0** |

Every step was a fault in our question, and each reproduced a mistake already written
down above.

**The `noul` was mistake 1 wearing new clothes.** It asked whether everything in the
segment was "confined to call logistics, courtesies, or standard boilerplate". All five
flags were fragments like "Yeah, exactly." and "I'm saying the same thing." -- which are
none of those three things, so *false* was the honest answer, and the flag was
meaningless. The question has been deleted rather than repaired: once the criteria
enumerate materiality properly, the `choice` already covers its one distinct job (a
figure buried in a long pleasantry).

**The criteria were mistake 2.** They listed figures, guidance, explanations and risks
-- and omitted analyst questions and management's view of strategy, leadership and
succession, both of which this project records as claims. Jev was applying a narrower
bar than the extractor. Twelve of the 18 initial control disagreements were plain
analyst questions.

**The single-segment state was mistake 4.** A segment is one speaker turn, so a Q&A
answer routinely carries no meaning alone: "Yes. You'll see something this year." is
guidance only beside the question that drew it. Adding the two preceding turns, marked
context-only with the judgement pinned to the target segment, moved the control from
55 to 60. Critically the immaterial set stayed at 0 flagged -- so the context sharpened
the question rather than bleeding materiality into everything.

### What this run actually found

On JPM/2026-q2-rerun, nothing. All 43 immaterial calls stand, and reading them confirms
it: operator logistics, agreement fragments, an interrupted half-sentence. The
extractor's judgement on this run was sound.

That is a real result, not a wasted run, *because* the control shows the question
discriminates: 91% material on claim-bearing segments against 0% on the immaterial set.

The six remaining control disagreements point the other way, at possible
over-extraction. Five sit at 0.58-0.66, which is Jev saying "borderline" rather than
"wrong". One is not borderline: seg-0063 at 0.90 immaterial is Dimon correcting that a
colleague was an options trader rather than an FX spot trader, extracted as claim-099.
That is biography, not a claim about the business. Worth a human look; nothing more.

### Cost and limits

43 calls cost $0.0017, the 66-segment control $0.0030 -- a whole audit plus its control
is well under a penny, the cheapest of the three modes.

What it still cannot see: the extraction instructions count a segment that *contradicts
or qualifies something said elsewhere on the call* as material, and no per-segment
question can ever judge that. Two preceding turns is not the whole call. That case
stays with the reviewer.

## Logging

Every request and response is appended to `logs/jev_checks.jsonl` (cross-run) and
`<run_dir>/jev_checks.jsonl`, following the `price_lookups.jsonl` convention. Each line
records the timestamp, run, claim id, endpoint, question count and ids, a SHA-256 of the
state sent, the HTTP status, the OpenRouter `generation_id`, token counts, cost, and the
full answers.

This exists because the first Jev work in this project left no audit trail at all: the
probabilities were saved but the calls were not logged, so there was no way to confirm
from the repo what had actually been sent or when. The log also pays for itself during
development — the HTTP 400 on the `score` shape above was diagnosed straight from the
logged error body.

## Triage: what happens to the answers

For most of this project's life, Jev's answers went into a log file and stopped
there. That is how JPM/2026-q2-rerun reached the independent reviewer carrying
thirteen miscitations Jev had already found. The tool now turns every run's answers
into a list of things to look at again.

`scripts/jev_check.py` writes `claims/jev-triage.json` (claims mode) or
`outlook/jev-triage.json` (citations mode). The three answer shapes need three
different rules, and the third one is the interesting one.

| Shape | Flagged when |
|---|---|
| `noul` | the probability is below `auto_accept_threshold` (0.7) |
| `choice` | the wrong option won; **or** a losing option holds at least `alternative_probability_floor` (0.20); **or** the confidence is below `choice_confidence_floor` (0.60) |
| `score` | it sits more than `score_shortfall_margin` (0.35) below the top rung of its ladder |

All four thresholds live in `config.toml [jev]`.

**The losing-option rule is the one that earns its keep.** A citation answered
`supports 0.82 / says_nothing 0.17 / contradicts 0.01` is a pass — `supports` won,
and a rule that reads only the winner sees nothing. But the 0.17 is real. In
practice it is usually one of three things: the claim is on the right topic but
does not quite make the point the sentence uses it for; the quote carries a
qualifier the extraction dropped; or the passage is doing more interpretive work
than the citation can carry.

Items come in two tiers, which drive different obligations:

- **`defect`** — Jev's best reading disagrees with the record. A `choice` where the
  wrong option won, a `noul` below 0.5, a `score` more than a full rung short. Each
  one must be answered individually in `jev-dispositions.json`.
- **`check`** — the expected answer won, but weakly. Read as a group.

### Where the thresholds came from

They were measured, not guessed. Replaying the 156 logged JPM/2026-q2-rerun answers:

| accept | rival floor | confidence | flagged | defect | check |
|---|---|---|---|---|---|
| 0.80 | 0.10 | 0.70 | 76 | 14 | 62 |
| 0.70 | 0.20 | 0.70 | 51 | 14 | 37 |
| 0.70 | 0.25 | 0.70 | 51 | 14 | 37 |
| **0.70** | **0.20** | **0.60** | **47** | **14** | **33** |

The bold row is what `config.toml` holds.

Three things that replay settled (2026-09-19):

**The defect count does not move.** A defect is "the wrong option won outright",
which none of these thresholds touch. Tuning here only changes the size of the
advisory tier. The 14 defects include all thirteen citations that came back as
something other than `supports`, one of which the independent reviewer later found
by hand.

**0.10 on the rival floor was too low to point at anything.** It flagged 62 of 156
answers — a 40% flag rate on a brief the Opus reviewer reads in full anyway. The 23
items the move to 0.20 drops all sit between 0.10 and 0.19 rival probability
("supports 0.80, says_nothing 0.19"). What survives is a different animal: several
near coin-flips (0.50/0.49), and one citation that came back `supports 0.48 /
contradicts 0.46` — the only row anywhere near an even split on *contradicts*, and
the single item most worth a human's time in the whole set.

**Above 0.20 the total stops falling.** Rows two and three of the table are
identical at 51. The items do not disappear, they migrate: a distribution with a
0.22 rival is also a diffuse one, so the confidence rule catches what the rival rule
released. Past 0.20 the confidence floor is the binding constraint, which is why the
configured setting takes it to 0.60: that is the four-item difference between rows two
and four, and it leaves the rival rule doing almost all the work (31 of the 33 check
items). A future tightening has to come from the rival floor or from narrowing the
citation passage, not from confidence -- there is very little left on that lever.

### Dispositions

`jev-triage.json` is regenerated on every run of the tool, so an agent's reasoning
cannot live in it. That goes in a sibling file the tool never writes:

```json
{"dispositions": [
  {"key": "claim-017::value__revenue_usd_billion",
   "action": "caveat_added",
   "note": "quote says 'in excess of'; 2.0 is a floor. Caveat added to claim-017."}
]}
```

`action` is `fixed`, `caveat_added`, or `rejected`. A rejection with no reason does
not count as a disposition.

The `check` tier is read as a group and closed as a group, with one entry keyed
`"check-tier"` saying what you found when you read them — e.g. `"all 62 are
says_nothing holding 0.10-0.20 on paragraphs carrying several citations"`. Without
that, the advisory could never be answered and would decay into a line everyone
learns to scroll past.

`earnings analyze` warns — never fails — when defect items have no matching
disposition (`validate.jev_triage_warnings`), and `earnings validate-outlook` runs the
same check over `outlook/jev-triage.json`, recording the warning in
`outlook-validation.json`. The citations stage had no such warning until 2026-09-27,
which is how a run once reached the independent reviewer carrying thirteen flagged
miscitations. Making it fail would put a
probabilistic third-party API on the pipeline's critical path, which contradicts the
rule this whole document opens with. The warning makes ignoring a finding visible
without making the run depend on the finding.

### Where the signal goes next

A triage item is only worth generating if something downstream consumes it. Three
things do:

1. **The extractor** (`produce-earnings-signal-card` step 7) disposes of every
   defect before `earnings analyze`.
2. **The brief author** reads the `check` tier before writing, and honours any
   `caveats` that came out of it. A claim's `caveats` list is a plain sentence saying
   a figure is qualified — a floor, an approximation, a non-standard basis. This is
   the "revenue in excess of \$2 billion extracted as 2.0" case: every numeric check
   passes, and the brief two stages later is written from the number, not the quote.
3. **The independent reviewer** (judgment remit item 11) treats an undisposed defect,
   or a rejection whose reason does not survive reading the claim, as a finding. It
   also checks that caveats were honoured — the only place in the pipeline where that
   can be caught at all.

Nothing in Python checks that a caveat was honoured. That is a hand-off between three
agents, and saying so plainly is more useful than implying the validator covers it.

## Earlier design notes

## Where the mixed-primitive payload came from (implemented, kept for the reasoning)

TypeSafe's own citation-check cookbook uses a better shape than the noul-per-field
grid this project started with: a single `choice` question over the claim and its
source section. That is what `build_questions` now sends.

```
instructions: "How does the section relate to the claim?"
criteria:
  supports:      "The section states the claim or directly implies that it is true"
  contradicts:   "The section states the opposite of the claim or implies it is false"
  says_nothing:  "The section does not address what the claim asserts, either way"
```

`says_nothing` is the important option — it separates "this claim is wrong" from "this
evidence does not speak to it", which our boolean phrasing collapsed into one low score.
The cookbook auto-accepts above 0.8 and routes the rest to a human, and advises starting
the threshold high and lowering it as you gain confidence on your own documents.

Our per-value questions (`values['x'] = n`, is that the right number for that metric?)
are worth keeping — that is where the qualifier-loss finding came from.

## Reading the numbers

Treat a probability as a triage signal, not a verdict. Two runs of the same question on
the same claim gave 0.81 and 0.76, so a single number near your threshold is not stable
enough to gate on. Sort by probability, read the bottom of the list, and check each
against the source yourself before believing it. Every finding in this document was
confirmed by hand before being acted on, and three of the early ones evaporated on
inspection because the question was broken rather than the claim.

The TypeSafe docs put it plainly: typed output guarantees the interface, not the truth.

## See also

- The `typesafe:typesafe-ai` plugin skill, installed at
  `~/.claude/plugins/cache/typesafe-ai/typesafe/<version>/skills/typesafe-ai`. It points
  at the live docs, which are the source of truth for primitives, limits and SDKs.
- `docs/REFERENCE.md` "Known limitations" — what the Python gates do and do not prove.
- `scratch/jev/jpm-rerun-scores.csv` — 660 probabilities from the JPM audit, worst first.

## Replay: rebuilding a logged call

A Jev answer is only evidence if you can still say what was asked and what was sent.
The log stores a sha256 of the state, not the state itself — the run directory is the
system of record and nothing copies the segment text out of it.

The split is by volatility, not by size alone. `claims.json` and `outlook-brief.md` are
small and get REWRITTEN by a later stage, so the log copies the claim record and the
cited passage verbatim; they are the half that makes a mismatch legible. Transcript
segments and web documents are large and never change once normalised, so the log
references them. An earlier version of this stored a character window around the quote
instead — which landed inside the segment text, duplicating the one artifact that was
already immutable while leaving the claim record unpreserved.

What the log adds is enough to rebuild:

| Field | What it is for |
|---|---|
| `request.questions` | The question payload verbatim. Question ids are labels and are never sent to the model, so ids alone record the meaningless half |
| `request.state_ref` | Run directory, mode, subject, claim id, segment or web-evidence id, call context — the recipe |
| `request.state_inputs` | The volatile inputs copied verbatim: the claim record, plus the brief passage for citations. Coverage carries none |
| `request.state_sha256` | Integrity check on the exact bytes sent |
| `request.evidence_note` | Present when web evidence had to be windowed: full length, bytes sent, quote offset |
| `code_version` | `git_commit` plus `builders_sha256`, a hash of the `build_state` and `build_questions` source |

To see the row a run WOULD write, without calling Jev or touching the run:

```sh
uv run python scripts/jev_check.py runs/JPM/2026-q2-rerun --mode claims --dry-run
```

It needs no API key, writes no call log, no index and no triage, and builds the same
row object the live path writes — a dry run that built a different row would prove
nothing. Auditing a run must not alter that run's record.

Rebuild and verify a written log with:

```sh
uv run python scripts/jev_replay.py runs/JPM/2026-q2-rerun
uv run python scripts/jev_replay.py runs/JPM/2026-q2-rerun --subject claim-001 -v
```

It exits non-zero if any row fails to reproduce.

### Why `builders_sha256` and not just the git commit

Replaying the original 485-row log found 220 coverage rows that no longer reproduce.
All came from passes run between 11:55 and 12:00 on 2026-09-20, while
`build_coverage_payload` was still being edited; the commit that finally captured that
work (`d91991f`) landed at 13:16. Every one of those rows would have carried the same
git commit as the rows that do reproduce, so a commit stamp could not have separated
them. Hashing the builder source can. The replay tool reports those rows as
unattributable rather than pretending to diagnose them.

### One owner per artefact

`runs/<ticker>/<event>/jev_checks.jsonl` owns the call rows.
`logs/jev_checks.jsonl` is an index: one line per run, carrying the run tag, mode, call
count, cost, how many calls had evidence windowed, and the path to the real log. The
two files were previously byte-identical duplicates of 390 KB.

### Web evidence is windowed on the quote, not sliced from the head

`[jev] web_evidence_chars` bounds how much of a web document reaches Jev. That budget
is now centred on the quote's actual offset. Previously it was the first N characters,
which meant `check_exact_quote` validated a claim against the whole document while Jev
saw only the opening — so Jev could be asked whether evidence it had never seen
supported the claim, and `says_nothing` looked like a defect in the claim. Two claims
in `runs/JPM/2026-q2-rerun` (claim-191 and claim-201, both citing `web-014`) had quotes
at offset 12,763 against a 12,000-character budget. Neither was ever sent, so no
recorded answer was affected.
