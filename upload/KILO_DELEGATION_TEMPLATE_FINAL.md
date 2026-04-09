# Kilo Delegation Template

Use this exact prompt for each task.

```text
Read first:
1. AGENTS.md
2. ARCHITECTURE.md
3. config/execution_plan.yaml
4. config/status.json
5. config/test_deck_manifest.md

TASK: <TASK_ID>
PHASE: <PHASE_ID>
GOAL: <GOAL>
ALLOWED_FILES:
- <file 1>
- <file 2>
COMMANDS_TO_RUN:
- <cmd 1>
- <cmd 2>
TESTS_REQUIRED:
- <test cmd 1>
- <test cmd 2>
ACCEPTANCE_CRITERIA:
- <criterion 1>
- <criterion 2>
STOP_RULES:
- Do not change files outside ALLOWED_FILES.
- Stop if any required test fails.
- Stop if architecture drift is needed.
- Do not start the next task.
RETURN_FORMAT:
1. Files changed
2. Commands run
3. Test results
4. Acceptance criteria pass/fail
5. Blockers
6. Recommended next task (do not execute)
```
