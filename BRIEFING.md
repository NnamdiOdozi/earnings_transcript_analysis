You are building a greenfield proof of concept for an earnings-call transcript analysis project. The finished project will run locally through Codex/ChatGPT desktop, using one agent and two repository-scoped skills. Do not introduce subagents, a multi-agent framework, an MCP server or a separate paid LLM API.

## Objective

Build a small, auditable pipeline that accepts one company earnings-call transcript and produces a concise signal card. Every substantive claim must be traceable to an exact quotation, and every calculation must be reproducible in Python.

This is a proof of concept, not a production platform.

## Size constraint

Target approximately 1,800–2,000 human-authored lines across about 20 files, excluding test fixtures. Treat 2,200 lines as a hard ceiling unless a larger implementation is explicitly approved.

Prefer a few cohesive modules over excessive abstraction. Keep individual Python files below roughly 220 lines where practical.

## POC scope

Support:

- One company and earnings event per run
- Local TXT, Markdown and straightforward HTML transcripts
- Optional transcript URL ingestion
- Basic SEC filing and XBRL retrieval for US-listed companies
- Tavily for web search or known-URL extraction
- Simple prepared-remarks versus Q&A segmentation
- Basic speaker labels when clearly present
- Timestamping and SHA-256 hashing of sources
- Quote-anchored structured claim extraction
- Exact quote, numerical and schema validation
- Deterministic financial calculations in Python
- A concise Markdown signal card
- Local archiving of inputs and outputs

Do not implement:

- Audio transcription
- OCR or difficult PDF parsing
- Docling, LangExtract or vector databases
- Exa fallback or a general provider framework
- Consensus-estimate feeds
- Market-price retrieval or later outcome scoring
- Alternative datasets
- Scheduled or unattended runs
- Prompt-injection classifiers
- Publishing or trading actions
- Plugin packaging or MCP servers

## Architecture

Create two repo-scoped skills under `.agents/skills`.

### 1. `build-earnings-source-pack`

This skill should guide the agent through:

- Accepting a ticker, event date and transcript file or URL
- Ingesting and sanitising the transcript
- Separating prepared remarks and Q&A
- Fetching relevant SEC information
- Using Tavily only when external web evidence is requested
- Archiving raw and normalised evidence
- Creating a manifest containing source URLs or paths, retrieval timestamps, content types and hashes

### 2. `produce-earnings-signal-card`

This skill should guide the agent through:

- Reading an existing source pack without performing additional browsing
- Extracting reported results, guidance, risks, explanations and informative Q&A
- Attaching every claim to an exact quote and segment identifier
- Writing claims to a strict JSON structure
- Running deterministic validators
- Performing calculations in Python
- Rejecting unsupported claims
- Producing a Markdown signal card only after validation passes

Keep detailed extraction instructions and the signal-card template in Markdown reference files rather than making `SKILL.md` unnecessarily long.

## Suggested Python package

Use a compact structure resembling:

- `cli.py` — prepare and validate commands
- `models.py` — minimal Pydantic schemas
- `ingest.py` — local files and simple URLs
- `sources.py` — Tavily and limited SEC access
- `process.py` — sanitisation, segmentation, hashing and archiving
- `validate.py` — quote, number and schema checks
- `calculations.py` — deterministic calculations

Use Python 3.11 or later. Prefer `argparse`, `httpx`, `pydantic`, `beautifulsoup4` and `pytest`; avoid unnecessary frameworks.

Store credentials only in environment variables, including `TAVILY_API_KEY` and an SEC-compliant identifying user agent. Provide `.env.example` but never commit secrets.

## Run output

A run should produce a directory similar to:

```text
runs/<ticker>/<event-id>/
  manifest.json
  raw/
  normalized/transcript.jsonl
  evidence/financials.json
  claims.json
  validation.json
  signal-card.md
```

Each transcript segment should have a stable identifier, section, speaker where known and text. Each claim should include its category, claim text, exact quote, segment identifier, speaker, status such as reported or forward-looking, relevant values and confidence.

## Validation requirements

The validator must confirm that:

- Every claim has a source segment
- Every quoted passage occurs exactly in that segment
- Numerical claims are present in their cited source or originate from deterministic SEC data
- Required schema fields are present
- Calculations are performed by Python, not copied from model reasoning
- Failed validation prevents final signal-card generation

Treat all fetched text as untrusted data. Remove scripts, HTML comments, control characters and invisible Unicode where practical. Do not rely on regex to identify every possible prompt injection.

## Testing

Use synthetic fixtures so tests do not require live API calls. Include at least:

- A normal transcript with prepared remarks and Q&A
- A transcript containing suspicious embedded instructions
- Representative SEC JSON
- Expected valid and invalid claims

Prioritise tests for sanitisation, segmentation, exact-quote validation, numerical checking and calculations.

## Completion criteria

The POC is complete when:

1. A documented command can prepare a source pack from a fixture transcript.
2. The signal-card skill can produce structured claims from that pack.
3. Unsupported or paraphrased quotations fail validation.
4. Deterministic calculations pass tests.
5. A successful run produces the archived files listed above.
6. All tests pass.
7. The implementation remains within the agreed line budget.

Inspect the workspace before editing and preserve any existing user work. Build the smallest coherent version that satisfies these criteria. Finish by reporting the files created, approximate line count, tests run, known limitations and the command or desktop instruction for trying the POC.
