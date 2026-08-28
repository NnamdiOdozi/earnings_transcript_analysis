# Verification and completion gates

Read this reference when a workflow must prove what an agent read, ran, produced, validated, or reviewed.

## Assertion-to-evidence map

Start with a small table. The model's statement never occupies the evidence column.

| Consequential assertion | Authoritative evidence | What it proves | What it does not prove |
|---|---|---|---|
| A file was accessed | Successful read response tied to path and hash | The tool returned that version | The model understood it |
| A command ran | Tool receipt with command identity, exit status, and timestamps | The recorded process executed | Its output is semantically correct |
| An artifact was written | File existence and content hash | Those bytes exist | The artifact satisfies the task |
| Validation passed | Validator output, version, input hash, and successful status | Those inputs passed those rules | The rules are complete |
| Review passed | Review verdict bound to artifact hashes | The reviewer accepted those versions | Later versions also pass |
| The task is complete | Completion gate over required receipts and deliverables | Declared completion conditions hold | Unspecified user needs were met |

When no suitable evidence exists, mark the assertion `unverified`. Do not infer success from plausible prose.

## A single agent does not imply an agent framework

Do not equate reliable tool use with framework adoption. A plain model API can be the simpler reliable design when all of these are true:

- One model owns the request and response.
- The interaction needs only a shallow, bounded tool round.
- The server, not the model, determines paths and access scope.
- Tool arguments and outputs have strict bounds.
- Stable context can be assembled deterministically.
- The workflow does not need resumable state, delegation, branching, or coordinated retries.

The LLM Experiments Lab at `/home/nodozi/projects/NEBIUS_MAR_2026/Nebius_serverless/llm_experiments_lab` is a concrete working example. Its current tracked implementation uses the OpenAI-compatible API directly. It does not use an agent framework.

The design combines:

- A cached project README and cached architecture source appended as stable system context.
- Volatile run state appended to the latest user message so changing data is kept separate from stable context.
- Two grep-style search tools and one diagnostic-snapshot tool.
- Server-derived run and template allowlists. The model never supplies a filesystem path.
- An enumerated file choice for the experiment-file search tool.
- Literal searches with query, match-count, and output-size caps.
- A containment check after server-side path construction.
- Tool output labelled as untrusted data rather than instructions.
- A single preflight tool-call round followed by the answer, which bounds the interaction without a general orchestration engine.
- Tests for allowlist rejection, cross-run rejection, output caps, dispatch, and context ordering.

This pattern is not “framework-free means control-free.” The application code itself performs the orchestration and enforcement. Preserve execution receipts, schema validation, completion gates, and semantic checks where the surrounding task requires them.

Static context injection also has limits. Large files consume tokens on every request and can become stale. Cache only stable, useful material. Prefer retrieval for detail that is large, volatile, or rarely needed. Cap tool results even when the source itself is trusted.

Use an agent framework when it solves a demonstrated orchestration problem. Examples include multi-agent delegation, durable pause and resume, complex branching, approval checkpoints, repeated tool loops, or recovery across process boundaries. Do not introduce one solely because the system calls a model and tools.

## Dataflow integrity

An agent can falsely say it read an input even when it never used it. Reduce this risk by making the input part of the next stage's dataflow.

Useful patterns include:

- Pass the actual content or a verified artifact reference to the next stage.
- Record the input hash in the downstream output.
- Require exact quotations or identifiers that can be resolved against the input.
- Reject outputs tied to stale or unknown input hashes.
- Record transformations from raw input to sanitised input to derived output.

Do not treat a self-reported summary as proof of consumption. Do not treat a file-open event as proof of comprehension.

When comprehension matters, require content-dependent evidence. Examples include a structured extraction, resolved citations, a coverage map, or questions whose answers depend on the source. Avoid brittle trivia tests that prove only keyword matching.

## Execution receipts

A consequential stage receipt should normally identify:

- Workflow, run, session, and stage identifiers.
- Actor or agent identity.
- Start and finish timestamps.
- Tool or command identity.
- Input artifact paths and hashes.
- Exit or tool status.
- Stable reference to raw output.
- Output artifact paths and hashes.
- Validator name and version, when used.
- Error or stopping reason.

Receipts should be produced by the execution layer where practical. A model-authored receipt can be useful metadata, but it cannot independently prove its own assertions.

## Completion gates

A completion gate should check observable conditions rather than ask the model whether it is done.

For a multi-stage workflow, verify:

1. Required predecessor stages passed.
2. Their receipts refer to the expected input versions.
3. Required deliverables exist.
4. Deliverable hashes match validated or reviewed versions.
5. Required structural validators passed.
6. Required semantic review passed.
7. No blocking finding remains open.
8. Budgets and authorisation boundaries were respected.

Use bounded terminal states:

- `completed`: all required gates passed.
- `failed`: a required operation or validation failed.
- `blocked`: progress requires authority, input, or an external state change.
- `unverified`: the work may exist, but required evidence is unavailable or inconsistent.

Do not use `completed_with_unknowns` to conceal a missing required check. Record non-blocking limitations separately.

## Structured output is untrusted input

Validate model-produced JSON or other structured output before use.

- Parse it with a real parser.
- Validate it against a schema.
- Reject missing, additional, or incorrectly typed fields when the contract requires strictness.
- Use enumerations for finite states and categories.
- Check references, paths, identifiers, and hashes against authoritative records.
- Apply business invariants after schema validation.

Syntactically valid JSON can still contain fabricated identifiers, impossible state transitions, or unsupported conclusions.

## Structural and semantic validation

Keep the responsibilities explicit.

Structural validation can check:

- File existence and hashes.
- Schema conformance.
- Required stages and execution order.
- Exact quote presence.
- Citation resolution.
- Allowed state transitions.

Semantic validation can check:

- Whether the evidence supports the conclusion.
- Whether material counterevidence was omitted.
- Whether periods and causal ordering are interpreted correctly.
- Whether uncertainty is represented honestly.
- Whether the deliverable answers the user's actual question.

A semantic reviewer should have independent access to the evidence needed to detect omissions. A packet created by the system under review may assist navigation, but it must not silently narrow the reviewer's evidence boundary.

## Incremental review

After a full review establishes an approved baseline, later reviews may use a semantic diff when quality can be preserved.

Bind the baseline verdict to exact hashes. A diff review should include:

- Old and new changed claims or passages.
- Added and removed evidence.
- Supporting source excerpts.
- Every downstream section that depends on the change.
- Nearby unchanged context.
- Updated structural validation results.

This is the change's dependency closure. Reviewing only edited lines can miss contradictions elsewhere.

Require full re-review when the conclusion changes, evidence eligibility changes, a central period is corrected, several sections are rewritten, dependencies cannot be resolved confidently, or the reviewer requests escalation.

## Reward-hacking checks

An agent may satisfy the visible test without satisfying the purpose. Common examples include hardcoding expected output, weakening a validator, omitting difficult cases, or writing the artifact that the existence check expects without producing meaningful content.

Prefer checks that inspect behaviour and provenance. Keep evaluators independent from the component being evaluated. Review changes to tests and validators with the same care as changes to production output.
