## Mandatory agent entry condition

Before running any command or authoring any analysis artifact, read the SKILL.md for
the stage you are performing, and every reference file it requires, **in full**. If a
file's output is truncated, continue reading it in numbered chunks until you reach the
end. Do not infer instructions from a partial read, and do not start work from this
file, `README.md` or `CLAUDE.md` alone -- they summarise the workflow, they do not
contain the rules for executing a stage.

## Stage 1 extraction is exhaustive, not selective

Extract one claim for every material reportable fact, guidance statement, management
explanation, stated risk and substantive Q&A insight the source pack supports. Do not
extract only the claims you expect the outlook brief to cite: that is a different and
much smaller set, and choosing it first is the most common way this pipeline fails
quietly.

Deterministic validation proves that the claims you submitted are grounded. It proves
nothing whatever about the ones you did not submit. A claims file covering a fraction
of the call passes every check exactly as cleanly as a complete one, so a passing
`validation.json` is not evidence that extraction was thorough. Confirmed live
(JPM/2026-q2): an agent that read the skill only partially produced roughly a quarter
of the material claims the same source pack supports, and every gate passed.

Account for your coverage explicitly in `coverage-receipt.json` beside `claims.json`
-- see `produce-earnings-signal-card/reference/extraction-instructions.md`.

## Sensitive files and shell environment

- Never open, read, search, grep, print, parse, summarise, diff, inspect, or enumerate the contents or variable names of `.env`, `.env.*`, or `.envrc` files.
- Never use `cat`, `grep`, `rg`, `sed`, `head`, `tail`, `source`, `dotenv`, Python, or another tool to inspect those files.
- Never enumerate, print, or inspect environment variables that may contain credentials or tokens.
- Do not verify whether secrets exist. Ask the user to verify configuration themselves.
- If work requires a credential, ask the user to run the credential-dependent command and provide sanitised output.
- Treat all secret configuration as user-managed and off-limits.
- Use Bash inside WSL for this repository.
- Do not provide or execute PowerShell, Command Prompt, or Windows virtual-environment commands.
