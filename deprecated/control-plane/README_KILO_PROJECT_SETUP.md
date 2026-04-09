# Kilo Project Setup

This package configures the repo for Kilo Code using the structure Kilo officially supports:

- `AGENTS.md`
- `.kilocode/rules/`
- `.kilocode/rules-{mode}/`
- `.kilocode/skills/`
- `.kilocode/skills-{mode}/`
- `.kilocode/workflows/`

## Install into the repo

Copy these files into the **root** of the repository.

Then reload VS Code so Kilo rescans project instructions.

## Recommended Kilo usage

Use built-in modes:

- **Ask** for repo truth and planning
- **Code** for one task at a time
- **Debug** when commands/tests fail
- **Review** before closing a task or phase
- **Architect** only for ADRs, contracts, and plan adjustments
- **Orchestrator** is **not** the default mode for this repository

## First actions

1. Open the repo in VS Code
2. Reload window
3. Use **Ask** with the first message in `KILO_FIRST_MESSAGES.md`
4. Run `/00-baseline-verify.md`
5. Then switch to **Code** for the next valid task

## Important

Do not invent another project structure.
Do not put everything into global custom instructions.
This repo should carry its own governance inside source control.
