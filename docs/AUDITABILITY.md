# How This Project (Earnings Transcript Analyser) Stays Auditable: Governance & Quality Control

*A plain-language guide for non-technical readers. It explains how an earnings-call
transcript becomes a set of checked, traceable claims — and why you can trust each number.*

## Two kinds of checking

Every figure in this pipeline passes through two very different kinds of quality control:

- **Machine checks (Python).** Fast and exact — the computer confirms mechanical facts: did
  this quote really appear in the transcript? Does this number exist in the source? Such checks
  never tire and never have an opinion.
- **Human-style judgement (a reviewer agent).** Some things a computer cannot judge — is a
  claim a *fair* summary, is anything important missing? A separate reviewer step handles those.

Several of these checks are **gates**: the process physically stops and refuses to produce a
final result until the check passes. Nothing half-finished is ever released.

The diagram below is the whole pipeline, left to right, with the check performed at each step
written underneath it. The three **gold boxes are gates** — the run halts there unless the
check passes (the red box shows what "halt" means: no card is produced). The numbered sections
that follow explain each check in turn.

![The pipeline with each check annotated; gold boxes are gates that stop the run on failure](flow_audit.svg)

## 1. Every source is fingerprinted (manifests & hashes)

When a transcript (or a web page, or an SEC filing) is pulled in, the system records it in a
*manifest* — a catalogue of everything used, with a digital fingerprint (a "hash") of the
exact content. The hash we use is **SHA-256**, an industry-standard algorithm; it appears as
the `sha256` field in the manifest:

```json
{
  "path": "raw/transcript.html",
  "retrieved_at": "2026-08-27T13:13:38Z",
  "content_type": "text/html",
  "sha256": "a0c7c16d9ea1bc9eade105...9f34d88",
  "byte_length": 271695
}
```

A hash is like a wax seal: change a single character in the file and the fingerprint changes
completely. So anyone can later prove the transcript we analysed is byte-for-byte the one we
started with — nothing was quietly edited afterwards.

## 2. Every run is logged

Separately, one line is written to a running log for *every* transcript ever processed — when
it happened, which company, and the same fingerprint:

```json
{"timestamp":"2026-08-27T13:13:30Z","ticker":"MSFT",
 "event_id":"2026-q4","sha256":"a0c7c16d...","byte_length":271695}
```

This is the audit trail across the whole history of work — "what did we process, and when" —
without needing to open any individual run.

## 3. The heart of it: every claim is quote-anchored

This is the single most important control. The AI is not allowed to *summarise loosely*. For
every claim it makes, it must copy an **exact quotation** from the source. Python then checks
that the quotation appears, word for word, in the transcript.

For example, the claim "Full-year Azure revenue surpassed \$100 billion, up 41%" carries the
quote *"Azure surpassed \$100 billion, up 41%."* We can confirm it is really there:

```
search the transcript for: "Azure surpassed $100 billion, up 41%"
  → found (1 match)
```

("Search" here means a keyword/pattern search — the classic tool is called *grep* — which
scans text for an exact string or a flexible pattern. A *regular expression*, or "regex", is
that flexible pattern: a way to say "find any dollar amount" or "find any percentage" without
knowing the exact figure in advance.)

**What happens if the AI gets it wrong?** Suppose a claim paraphrases — say it writes "Azure
*reached* \$100 billion" instead of "*surpassed*". The check fails instantly:

```
Validation FAILED: 1 issue(s).
  claim[2] exact_quote: Quote does not occur exactly in seg-0003
```

The run stops. No output is produced. A paraphrase — even a harmless-looking one — is caught,
because "reached" is not what was actually said.

## 4. Numbers must be grounded — and some arithmetic is re-checked

Beyond the quote, every number a claim states must actually appear in the cited source (or in
the official SEC financial data). The AI cannot introduce a figure from thin air; if it does,
validation fails the same way.

For genuinely *calculated* figures, Python re-does the maths itself rather than trusting the
AI's arithmetic. Stated honestly, this covers three specific formulas: **year-over-year
growth**, **margins** (one number divided by another), and **earnings-per-share growth**. So
percentage-change and ratio calculations are independently recomputed and must match to a
tight tolerance. General free-form arithmetic — for example, adding several segment revenues
to check they sum to the reported total — is *not* auto-recomputed today, though every
underlying number is still grounded against the source. We flag this limit rather than
overstate the coverage.

## 5. Guarding against "prompt injection"

Transcripts are untrusted text. A malicious or careless transcript could contain a sentence
like "ignore your previous instructions and…", aimed at hijacking the AI. Four things address
this, and it is worth being precise about each:

- **A best-effort phrase flag.** After sanitisation, the transcript is scanned for a
  configurable list of ~25 common injection wordings ("ignore previous instructions",
  "developer mode", "reveal your system prompt", and so on). Any hit is recorded in the
  manifest and a per-run `injection-scan.json`. This is deliberately **a flag, not a classifier
  and not a gate** — it never blocks the run and never deletes text; it simply makes suspicious
  phrasing *visible* to the reviewer. It is not foolproof (a novel wording will slip past) and
  can be switched off in config if it proves noisy. We claim exactly this much, no more.
- **Invisible-character stripping.** Sanitisation removes zero-width and hidden control
  characters first, closing the obvious trick of hiding an instruction inside normal-looking
  text (the flag then runs on the cleaned text).
- **Containment by design.** All fetched text is treated as **data to be quoted, never commands
  to obey**; the AI is explicitly instructed to ignore instructions embedded in source material.
- **A capped blast radius.** Even if something slips through, the validation above limits the
  damage: the worst an injected line can do is be *quoted verbatim* as a claim (honest — it
  really was said). It cannot change the rules, skip a gate, or invent a number, because Python
  enforces those, not the AI.

For the web pages pulled in for consensus and peer context, we rely on the providers' own
defences: Tavily states it "acts as a firewall … blocking malicious prompt injection attempts
before they ever reach your models"; Exa publishes SOC 2 and zero-data-retention assurances but
no prompt-injection filter specifically. Either way, that evidence is still bound by the same
exact-quote and number checks, which cap its blast radius too.

## 6. Lower cost and more consistency

Handing the mechanical work to Python isn't only about trust — it is also cheaper and steadier.
The expensive, variable AI isn't asked to re-count characters or re-verify sums every run (work
that burns tokens and can drift run to run); it reads the transcript once from a file, not
pasted repeatedly into a chat. Deterministic checks give the *same* answer every time —
repeatability that is itself a governance property.

## 7. Why we still need a human-style reviewer

Machine checks prove existence and arithmetic, not meaning. They cannot tell whether a claim
is a *fair* reading of its quote, whether the outlook narrative is balanced, or whether
something important was left out. So a final **reviewer agent** — run with a fresh, independent
view and no memory of the drafting — reads the finished bundle and judges exactly those things.

On this very run, the reviewer caught real issues the machine checks passed clean: several peer
figures were labelled with the wrong reporting period, and one competitor (Apple) had published
its results the day *after* the call — so they could not have informed it. Both were corrected
before the run was accepted.

## 8. Gates: the line stops if a check fails

Finally, several checks are **gates**, not mere warnings:

- The signal card is written **only if** every quote and number validates.
- The forward-looking brief is accepted **only if** every claim it cites really exists.
- The run is marked complete **only if** the reviewer passes it.

A failure at any gate halts the process. That is what "governance" means here in practice: not
a report written afterwards, but controls wired into the workflow so that an unverified result
*cannot* move forward.

---

*In short: sources are fingerprinted, every run is logged, every claim is anchored to an exact
quotation the computer re-checks, growth and margin figures are recomputed, suspicious phrasing
is flagged, outside text can't issue commands, and a reviewer guards meaning — all behind hard
gates that stop anything unverified from proceeding.*
