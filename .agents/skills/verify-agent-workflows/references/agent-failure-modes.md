# Agent failure modes

Read this reference when threat-modelling an agent workflow, choosing controls, or diagnosing a reliability incident.

## Action hallucination

The agent claims that it called a tool, read a file, ran a test, or received a successful result when the logged execution does not support the claim.

Mitigate this with execution-layer receipts, completion gates, and status derived from raw tool results. Asking the model to report honestly is not an independent control.

## Weak consequence prediction

Large language models predict plausible language. They do not reliably simulate every real-world consequence of an action.

Mitigate this with dry runs, precondition checks, bounded permissions, reversible operations, explicit impact analysis, and observation of the resulting state.

A world model is an internal representation used to predict how a system changes after an action. Joint Embedding Predictive Architecture, usually abbreviated JEPA, is a research direction for learning predictive representations. It is not a proven replacement for practical workflow controls.

## Poor complexity estimation

An agent may treat a large task as trivial, omit necessary stages, or overthink a small task and consume excessive resources.

Mitigate this with an initial inventory, explicit deliverables, stage budgets, size thresholds, and replanning when observed work differs materially from the estimate.

Do not assume that a detailed plan proves the estimate is accurate.

## General hallucination

The model may produce a plausible but false fact, citation, identifier, path, API behaviour, or explanation.

Mitigate factual claims with authoritative retrieval, exact evidence, validation, and clear separation between evidence and inference.

## Reward hacking

The agent satisfies the visible score or test without achieving the intended outcome. Examples include hardcoding expected results, weakening tests, excluding inconvenient data, or generating an empty artifact that passes an existence check.

Mitigate this with independent evaluators, provenance checks, adversarial cases, review of validator changes, and outcome-based acceptance criteria.

## Sycophancy

The agent agrees with a flawed user or manager premise rather than identifying the problem.

Require evidence-backed disagreement when assumptions conflict with observed facts. Ask reviewers to identify the strongest counterargument and material omitted evidence. Do not reward agreement as a proxy for helpfulness.

## Error propagation in linear reasoning

A wrong early assumption can contaminate later planning and execution. A fluent chain of reasoning does not guarantee that earlier premises were checked.

Use stage boundaries, explicit assumptions, intermediate validation, independent review, and the ability to start a corrected forward-only attempt. Do not silently rewrite the historical record to make the final result appear inevitable.

## Prompt injection and instruction confusion

Untrusted content may contain instructions that compete with the workflow's real rules. The agent may also confuse quoted content, user data, or retrieved text with authorised instructions.

Separate instructions from data, label untrusted content, restrict tools, scan when useful, and validate actions at the capability boundary. A prompt-injection scan reduces risk but cannot prove that content is safe.

## Shared-memory contamination

One agent's unsupported inference can become another agent's apparent fact when provenance is lost.

Tag memory with source, author, time, evidence class, and verification state. Prefer immutable evidence references over copied summaries. Corrections should append a superseding record rather than erase the earlier one.

## Concurrency failures

Two agents may overwrite each other's files, read partially written state, duplicate an external mutation, or both act on stale preconditions.

Prefer isolated per-run outputs and idempotent operations. Where state must be shared, use atomic replacement, locks, transaction-like preconditions, and unique operation identifiers.

## Control-selection table

| Observed risk | Primary control | Useful secondary control |
|---|---|---|
| False claim that a tool ran | Execution-layer receipt | Completion gate |
| File opened but not used | Dataflow hash or content-dependent output | Semantic review |
| Invalid model JSON | Strict schema and business validation | Repair or retry budget |
| Incorrect but well-formed interpretation | Independent semantic review | Counterevidence search |
| Agent rewrites its own policy | Read-only procedural memory | Capability restriction |
| Two writers corrupt state | Isolation or locking | Atomic replacement |
| Endless retry loop | Session budget | External kill switch |
| Stale fact overwrites history | Append-only bi-temporal record | Trust metadata |
| Test passes without solving task | Independent outcome test | Review evaluator changes |

## Related frameworks

- METR autonomy evaluations study how reliably agents complete tasks of different lengths. They can inform expectations but do not replace workflow-specific tests.
- Belief-Desire-Intention, abbreviated BDI, is an older agent architecture that separates represented beliefs, goals, and intended actions.
- The OWASP guidance for large language model applications provides a broader security taxonomy, including prompt injection, unsafe output handling, and excessive agency.

Use these as sources of test ideas. Do not adopt a framework merely because its terminology resembles the current problem.
