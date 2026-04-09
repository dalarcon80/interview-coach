# Final Kilo Setup Guide

## Supported Kilo project structure

Use:

- `AGENTS.md`
- `.kilocode/rules/`
- `.kilocode/rules-code/`
- `.kilocode/rules-architect/`
- `.kilocode/rules-debug/`
- `.kilocode/rules-review/`
- `.kilocode/rules-ask/`
- `.kilocode/skills/`
- `.kilocode/skills-code/`
- `.kilocode/skills-architect/`
- `.kilocode/skills-debug/`
- `.kilocode/skills-review/`
- `.kilocode/skills-ask/`
- `.kilocode/workflows/`

Do **not** create `workflows-code/` or similar.
Workflows live only in `.kilocode/workflows/`.

## Recommended repo setup sequence

1. Copy this package into repo root
2. Reload VS Code
3. Open Kilo panel
4. Start in **Ask**
5. Use `KILO_FIRST_MESSAGES.md`
6. Execute `/00-baseline-verify.md`
7. Move to **Code** only after baseline truth is established
