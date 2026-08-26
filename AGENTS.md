## Sensitive files and shell environment

- Never open, read, search, grep, print, parse, summarise, diff, inspect, or enumerate the contents or variable names of `.env`, `.env.*`, or `.envrc` files.
- Never use `cat`, `grep`, `rg`, `sed`, `head`, `tail`, `source`, `dotenv`, Python, or another tool to inspect those files.
- Never enumerate, print, or inspect environment variables that may contain credentials or tokens.
- Do not verify whether secrets exist. Ask the user to verify configuration themselves.
- If work requires a credential, ask the user to run the credential-dependent command and provide sanitised output.
- Treat all secret configuration as user-managed and off-limits.
- Use Bash inside WSL for this repository.
- Do not provide or execute PowerShell, Command Prompt, or Windows virtual-environment commands.
