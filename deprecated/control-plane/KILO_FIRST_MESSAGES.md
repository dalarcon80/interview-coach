# First Messages for Kilo

## Message 1 — Ask mode

Read:
- AGENTS.md
- README.md
- config/status.json
- config/execution_plan.yaml
- docs/SUPPORT_MATRIX.md
- KILO_MODE_GUIDANCE.md

Tell me:
1. current repo truth
2. active path vs deprecated path
3. package-health blockers
4. product blockers
5. the next valid task

Do not code yet.

## Message 2 — Run baseline workflow

/00-baseline-verify.md

## Message 3 — Code mode, single task

Implement only the next valid task from config/execution_plan.yaml.
Follow AGENTS.md, project rules, project skills, and the selected phase acceptance criteria.

Return:
1. files changed
2. commands run
3. tests run
4. acceptance proof
5. blockers
6. next task
