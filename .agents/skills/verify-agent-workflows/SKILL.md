---
name: verify-agent-workflows
description: Design or audit multi-step agent workflows whose claims about inputs, tool execution, outputs, completion, provenance, budgets, or semantic correctness must be independently verifiable. Use for autonomous or delegated workflows; do not invoke for ordinary one-step coding or writing tasks.
metadata:
  version: "0.2.0"
---

# Verify Agent Workflows

Build workflows in which evidence, rather than the model's narrative, determines what happened.

## Core rule

A model's statement that it read, ran, checked, wrote, or completed something is a claim. It is not proof.

For every consequential claim, identify an authoritative receipt. Examples include a tool response, input hash, exit status, validated output, or independent review verdict. If required evidence is absent, report the outcome as unverified rather than successful.

## Scope the controls

Match the controls to the likely harm and the workflow's autonomy.

- Use lightweight existence and validation checks for low-risk, reversible work.
- Use input and output hashes, append-only receipts, budgets, and independent review when agents operate across stages or sessions.
- Add locks, atomic replacement, or a kill switch only when concurrent writes or long-running autonomous execution make them useful.
- Restrict capabilities when an agent does not need a broad tool. Do not rely on a prompt prohibition when the capability itself can be removed.

Do not add elaborate infrastructure merely to make a one-step task look rigorous.

## Do not require an agent framework by default

A bounded single-agent system can be reliable without an agent framework. Prefer a plain model API call with deterministic context assembly and narrow, server-controlled tools when one model owns the turn, the tool loop is shallow, and no durable orchestration state is required.

The absence of a framework does not remove the need for controls. Resolve paths and authority outside the model, allowlist tool targets, validate arguments, cap results and tool rounds, label retrieved content as data rather than instructions, and preserve tool receipts. Add a framework only when the workflow genuinely needs features such as resumable state, delegation, branching, approval checkpoints, or coordinated retries.

Read [verification-and-gates.md](references/verification-and-gates.md) for the concrete LLM Experiments Lab pattern and its limits.

## Verification workflow

### 1. Define the consequential assertions

List what must be true before the workflow may advance or finish. Include claims about:

- Required inputs read or consumed.
- Tools and commands executed.
- Successful exit status.
- Artifacts created or updated.
- Validation performed.
- Review completed.
- Budgets and stopping conditions respected.

For each assertion, name its authoritative evidence and the response when that evidence is missing or contradictory.

### 2. Preserve dataflow integrity

Make downstream stages consume the actual upstream artifact or its content hash. Do not let a prose summary stand in for required input.

Where comprehension matters, mere file access is insufficient. Require a content-dependent output, structured extraction, exact citation, or independent semantic check. A read log proves access, not understanding.

Read [verification-and-gates.md](references/verification-and-gates.md) when designing stage receipts, dataflow checks, completion gates, structured-output validation, or incremental review.

### 3. Verify execution from tool evidence

Derive status from logged tool responses. Do not copy the model's account of what a tool returned.

Preserve enough information to connect each action to its session, inputs, result, and outputs. Keep raw tool evidence or a stable reference to it when the workflow is consequential.

### 4. Gate advancement and completion

Before a stage advances, verify its required inputs, execution receipt, outputs, and validation result. Before accepting `completed`, check that the requested deliverable exists and matches the reviewed or validated version.

Use explicit states such as `completed`, `failed`, `blocked`, and `unverified`. Do not silently convert missing evidence into success.

### 5. Separate structural and semantic correctness

Structural checks establish facts such as file existence, schema validity, execution order, hashes, and citation resolution. They cannot establish that an interpretation is accurate, balanced, useful, or honest.

Use an independent semantic review when meaning matters. Bind the review to exact artifact hashes so later edits cannot inherit an earlier verdict.

### 6. Bound autonomy

Set limits proportional to the workflow. Consider token, cost, tool-call, retry, and wall-clock budgets. Define what happens when a limit is reached. Long-running or externally consequential systems should have a reliable stop mechanism.

Read [state-capabilities-and-budgets.md](references/state-capabilities-and-budgets.md) when shared state, concurrent writers, broad tools, untrusted input, or autonomous loops are present.

### 7. Design for known model weaknesses

Assume the model may underestimate complexity, miss downstream consequences, reward-hack a test, agree with a flawed premise, or confidently describe an action that did not happen.

Use observable invariants and external checks rather than asking the model to be more careful.

Read [agent-failure-modes.md](references/agent-failure-modes.md) when threat-modelling a workflow or diagnosing a reliability failure.

## Required output when applying this skill

Produce the smallest useful design or audit containing:

1. Consequential assertions and authoritative evidence.
2. Existing controls and concrete gaps.
3. Proposed gates or capability restrictions, ranked by risk reduction.
4. Structural and semantic validation responsibilities.
5. Budgets and stopping conditions where relevant.
6. Residual limitations that the controls cannot prove.

Distinguish requirements from optional hardening. Do not claim that a control works until its observable behaviour has been tested.

## Source provenance

For the original conversation notes and Prof Rod attribution, read [prof_rod_keep_agents_honest.txt](references/prof_rod_keep_agents_honest.txt). Use it to trace the source material or reconsider the maintained guidance, not as an additional always-loaded procedure.
