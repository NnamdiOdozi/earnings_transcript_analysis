# State, capabilities, and budgets

Read this reference when a workflow has shared mutable state, concurrent agents, untrusted inputs, broad tools, retries, or long-running autonomy.

## Append-only audit records

For consequential workflows, record each action as a new event rather than rewriting history. An event can describe a request, tool call, result, state transition, correction, or review verdict.

Append-only history supports reconstruction of what the system knew and did at a particular time. It also makes later corrections visible.

Do not confuse an append-only audit log with the current state view. Derive or store a separate current-state projection when fast access is needed.

## Forward-only correction

Do not erase a failed attempt or silently rewrite its evidence. Record the failure, then begin a new attempt or session linked to the earlier one.

Forward-only history is especially useful when a previous output influenced a later decision. It preserves why the system once believed something that was subsequently corrected.

## Bi-temporal facts

When facts can change or arrive late, store two times:

- Valid time: when the fact was true in the represented world.
- Transaction time: when the system learned or recorded it.

This prevents a later correction from erasing the historical information available to an earlier decision. It is useful for earnings events, changing guidance, incident records, and evolving shared memory.

Do not add bi-temporal storage to static, disposable state without a concrete need.

## Atomic file replacement

When readers must never observe a partial file, write the complete new content to a temporary file in the destination filesystem. Flush it as required, then atomically replace the destination.

Atomic replacement protects readers from half-written content. It does not prevent two writers from replacing one another. Use coordination when multiple writers are possible.

## Locking shared state

Use a lock when concurrent sessions may mutate the same logical state.

Choose the lock boundary around the invariant being protected. A per-session or per-run lock is often clearer than many tiny locks, but the correct boundary depends on what must change together.

The `filelock` Python library can provide a companion lock file for local workflows. A lock needs:

- Defined ownership and scope.
- Timeout or failure behaviour.
- Safe release after errors.
- A policy for stale locks.
- Tests using actual concurrent writers.

Locking is not required when writes are isolated by design, such as one immutable directory per run.

## Read-only procedural memory

Where the runtime supports it, mount core policies and procedural instructions read-only. This prevents a confused or compromised agent from rewriting the rules used to govern its own behaviour.

This control protects file mutation. It does not protect against prompt injection that persuades the model to disregard visible instructions. Capability restrictions and validation remain necessary.

## Trust metadata on shared memory

Shared facts should identify their author, source, verification status, and relevant timestamps. Downstream agents can then distinguish official evidence, deterministic derivation, model inference, and unverified notes.

Avoid a single unexplained numeric trust score. Preserve the reasons for trust so policy can change without losing provenance.

## Capability-based tools

Give the agent the narrowest practical capability for its task.

If an agent only needs to search approved files, a bounded search function is safer and easier to audit than an unrestricted shell. If it only needs read access, do not expose mutation methods.

Capability restriction is stronger than a prompt saying not to use available powers. Prompts influence choices. Capabilities determine possible actions.

### Avoid shell injection in wrappers

A narrow wrapper is not narrow if it interpolates model text into a shell command.

Unsafe design:

```python
os.system(f"grep {pattern} {path}")
```

Safer designs pass arguments without a shell or implement the operation directly:

```python
subprocess.run(["grep", pattern, path], shell=False, check=True)
```

The wrapper must also constrain allowed paths, result size, time, and regular-expression complexity where those could be abused.

## Session budgets

Bound autonomous execution with limits appropriate to the task:

- Maximum input and output tokens.
- Maximum monetary cost.
- Maximum tool calls.
- Maximum retries per operation.
- Maximum wall-clock duration.
- Maximum external mutations.

Record consumption against the run. Define whether exceeding a limit produces `failed`, `blocked`, or a safe partial result. Do not let the model silently extend its own budget.

Budgets should account for subagents and retries. Otherwise delegation can bypass the apparent session limit.

## Kill switch

Long-running or externally consequential agents should have a stop mechanism controlled outside the model. A flag, lease, cancellation token, or supervisory service may be suitable.

Check the stop condition at meaningful boundaries and before external mutations. Define what happens to in-flight work and how interrupted state is recorded.

A kill switch is not a substitute for budgets, authorisation checks, or idempotent operations.
