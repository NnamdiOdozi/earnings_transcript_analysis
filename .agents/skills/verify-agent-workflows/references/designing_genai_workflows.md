2
Designing GenAI workflows
Deciding what should be deterministic, agentic or human
Sep 08, 2026
1. Introduction

An actuary with an idea for automation is no longer short of tools. It is easy to build an agent, then several agents, then a system to coordinate them. The harder question is more specific: does this problem need GenAI at all, and, if it does, which parts of the solution should remain deterministic?

This article provides a five-step method for answering that question one task at a time. It asks whether each task belongs to deterministic code, to generative AI (GenAI) or to a person. The method tends to produce a smaller system than the one first imagined. A piece of conventional code or a single scoped model call will often do the job as well as an agent, at lower cost and with fewer places to fail.

The IFoA GenAI Working Party has already described the opposite end of this scale. The Agentic Model Office (Ramsay, 2025) sets out an organisation-wide, agent-first operating model built on a taxonomy of manager, worker and workflow agents. This article works at the level of a single task, for one person building one system, and starts from restraint rather than ambition. It also puts into practice a point made in the working party’s Substack article, ‘Everyone is riding the AI hype. Here’s what people are getting wrong’: not everything needs orchestration.
2. Two things to get right before applying the method

Before deciding how many components a system needs, or whether it needs agents at all, two things repay attention.

Map the real end-to-end process, and design the hand-offs. Write the workflow down first: inputs, outputs, the stages between them, the dependencies, the decision points and the places where a person is currently involved.

The connections between components deserve as much attention as the components themselves. Each stage should produce a structured, inspectable output that the next stage can use: input, task, output, next task. If you can read and check the intermediate outputs, you can debug, test and review the system. If the components pass each other free-form prose, a failure three stages back will surface only at the end, if at all.

Keep components narrow, and keep them few. Give each component one bounded job: what it receives, what it must produce, and where its responsibility stops. A single component that researches, drafts, checks and signs off its own work is hard to test and easy to distrust.

The opposite error is just as real. Every additional component is another call to pay for, another source of latency, and another place to fail. Anthropic (2024) recommends the same discipline for systems built on large language models: find the simplest solution that works, and add complexity only where it demonstrably improves results.

Cost is often misunderstood here. Adding components usually increases token usage and processing cost, so unnecessary complexity is not free. Dividing work across narrowly scoped components can nonetheless be cheaper than asking one agent to do everything. Neither design is automatically the cheaper one, so each additional component should be justified on its own terms.

Errors also propagate. A flawed output from one stage is passed to later stages, where it can shape subsequent decisions and become progressively harder to trace. A workflow whose output anyone relies on therefore needs checks along the way, not only at the end.
3. A five-step decision method

The method is a single ordered sequence of questions, applied to each task on the process map (Figure 1). The order matters: accountability is settled first, deterministic code is preferred next, GenAI is used only where it earns its place, controls are set in proportion to the cost of a wrong answer, and a person is consulted whenever ambiguity is material.

    Does this task require human ownership or professional judgement? If it does, the decision stays with a person. Technology can still support them by gathering evidence, running calculations, flagging issues or drafting text for review, but it does not own the outcome.

    If the task can be delegated, can it be done reliably with clear rules, calculations, mappings or conventional code? If so, use deterministic code. There is little value in paying a model to re-derive, probabilistically, something you already know how to specify exactly. “Deterministic” here means that the same input produces the same output every time. Model outputs can vary between runs, even when the model is configured to minimise randomness.

    If the task cannot be specified as rules or code, does GenAI add genuine value? If it does, use it. If it does not, leave the task with a person or redesign the process. This question is often skipped, and the result is a system more complicated than the problem requires.

    If GenAI could do the task, should it? That depends on the risk: the consequence of an error, the likelihood of one occurring, and how quickly it would be spotted and put right. Higher-risk tasks need stronger controls, such as independent checks and human sign-off.

    Is the ambiguity material enough that the system should stop and ask? A targeted question to a person is almost always better than a confident guess that has to be unpicked later.

This is a practitioner’s heuristic rather than a formal governance framework. Step 4 in particular relies on judgement, applying controls in proportion to the risk. The aim is a decision that can be explained and defended, rather than a rule set that covers every case.

Figure 1: The five-step decision method applied to a single task. The factors listed at step 4 are weighed together rather than applied as separate branches. Author’s own diagram.
4. A worked example: the system used to write this article

This article was produced by a small set of narrowly scoped components, each chosen using the five-step method. Interpretation, synthesis, challenge and review were delegated to GenAI. Accountability, editorial judgement and the decision to publish stayed with the author.

Figure 2: The editorial system behind this article. Each box is labelled by type: human, deterministic, or scoped GenAI call. Author’s own diagram.

The workflow has seven parts:

    Author (human). Defines the topic, directs the workflow, reviews outputs, resolves disagreements, decides what is included, draws the conclusions and approves publication.

    Idea-Challenger (GenAI). Pressure-tests the brief by questioning assumptions, identifying gaps and suggesting alternative perspectives.

    Archivist (GenAI). Searches the working party’s back catalogue for related articles, earlier ideas and potential overlap.

    Researcher (GenAI). Identifies external evidence, then checks the factual claims in the draft against the cited sources.

    Structure-and-Style Editor (GenAI). Proposes an outline, reviews the draft’s structure and clarity, and checks consistency with house style.

    Claims Register (deterministic). Stores factual claims, sources and verification status in a structured form that can be reviewed and updated while drafting.

    Working Files and Logs (deterministic). Store the thinking logs, cross-reference lists, outlines, decisions and other intermediate outputs passed between stages and retained for review.

Each GenAI component is a single scoped model call over a defined set of files, not an autonomous agent. The author sets the sequence, decides how each output is used, and remains responsible for every substantive editorial decision: the choice of argument, the evidence relied on, the conclusions drawn and the decision to publish.

The hand-offs are simple, inspectable artefacts. Because the intermediate outputs can be read directly, a recommendation can be accepted, rejected or revised before it influences a later stage. Calling this a multi-agent system would overstate it. Nothing here acts autonomously, and the person is not brought in only at the end.

Some outputs become durable knowledge: a style question settled, a reference confirmed, a preferred approach documented. At present these are usually rediscovered from scratch each time. Capturing and reusing them would let later runs of the workflow spend less effort on settled questions and more on genuinely new ones.
5. The knowledge loop: tasks move from GenAI to deterministic code

A task’s classification is not permanent. A task that needs GenAI today because it is unfamiliar, ambiguous or hard to specify may become routine as experience accumulates. Once a response has been validated often enough to trust, it can be captured as a rule, template, checklist or piece of conventional code. The task then moves from step 3 of the method to step 2, and GenAI capacity is freed for whatever is genuinely novel. Figure 3 shows the progression.

Figure 3: The knowledge loop. As patterns are validated and codified, tasks move from GenAI-supported interpretation to deterministic execution, reserving GenAI for novel or ambiguous problems. Author’s own diagram.
6. Conclusion: questions to ask before building

The goal is modest: to avoid building something more complicated than the problem requires, and to be able to sketch a sensible shape before committing to it. More agents are not a sign of sophistication. The design to aim for is as simple as the problem allows, with clear responsibilities, inspectable hand-offs, independent checks where the stakes justify them, and a person accountable for the decisions that matter.

Some questions to work through before building:

    What is the real end-to-end process, including its inputs, outputs, stages, decision points and human interventions?

    Which tasks carry professional judgement or accountability that must stay with a person?

    Which tasks can be done reliably with rules or conventional code?

    Which tasks genuinely need interpretation, synthesis or generation, and which am I automating only because I can?

    For each GenAI task, what would a wrong answer cost, and how quickly would I catch it or undo it?

    For each GenAI output that matters, what checks it independently: a deterministic test, a second model, or a person?

    Where does each component’s responsibility end, and what exactly passes to the next?

    Where should the system stop and ask me, rather than guess?

    Which recurring patterns could become fixed rules once they have been validated enough times?

References

Anthropic (2024) Building effective agents, 19 December. Available at: https://www.anthropic.com/engineering/building-effective-agents.

Ramsay, D. (2025) The Agentic Model Office: AI agents and the future of insurance organisations. think, edition 13. London: Institute and Faculty of Actuaries. Available at: https://actuaries.org.uk/think-edition-13-the-agentic-model-office-ai-agents-and-the-future-of-insurance-organisations/.