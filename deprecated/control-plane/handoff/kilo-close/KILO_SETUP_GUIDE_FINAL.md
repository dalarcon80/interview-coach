# How to run this in Kilo Code

## Recommendation
Use **one direct Kilo agent** with a custom mode.
Do **not** use an orchestrator for this closing stage.

Reason:
- The remaining work depends on your local machine capabilities.
- You need real command execution, real Docker, real API keys, and real macOS validation.
- Adding an orchestrator layer now increases complexity and drift.

Kilo supports custom modes and remembers the last model used per mode through Sticky Models, which is useful for keeping one strong implementation mode dedicated to this project. citeturn568734search0
Kilo can also execute terminal commands directly on your machine through `execute_command`, which is exactly what this closing stage needs for Docker, tests, builds, and local validation. citeturn746339search0turn746339search1

## Suggested mode
Import `KILO_MODE_interview_coach_closer.yaml` into Kilo as a **project mode**.

## Suggested model strategy
- Use a strong code-capable model for this mode.
- Keep the same model on this mode to benefit from Sticky Models. citeturn568734search0

## Suggested Kilo settings
In Kilo settings, prefer:
- always approve allowed execute operations: enabled for safe prefixes only
- always approve write operations: enabled only in this repo if you have git backups
- no delete auto-approval unless absolutely necessary

Suggested allowlist prefixes:
- git
- python
- pip
- pytest
- bash
- docker
- npm
- node
- cargo
- rustup
- curl
- ls
- cat
- grep
- sed
- awk

## Startup sequence in Kilo
1. Open the repo locally on your Mac.
2. Import the custom mode file as a project mode.
3. Paste `KILO_MASTER_PROMPT_FINAL.md` into the chat.
4. Attach or reference:
   - `upload/ARCHITECTURE.md`
   - `LIVE_VIABILITY_REQUIREMENTS.md`
   - `execution_plan_final_live_close.yaml`
   - `config/status.json`
   - `README.md`
5. Instruct Kilo to start with **P0.1**.

## Do not do this
- do not let Kilo start adding features before baseline verification
- do not let Kilo create a second repo
- do not let Kilo “simplify” the architecture
- do not let Kilo declare success from docs instead of commands
