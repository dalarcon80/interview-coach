# Kilo Mode Guidance

## Ask
Use for:
- understanding current repo truth
- comparing code against architecture
- identifying next valid task
- summarizing blockers

Do not use Ask to implement code.

## Code
Primary implementation mode.

Use for:
- implementing exactly one task
- editing code
- running commands
- updating status after proof

Hard rule:
- one task only
- no phase skipping
- no architecture drift

## Debug
Use only when something fails:
- pytest
- Docker
- FastAPI boot
- Tauri dev
- backend health
- WebSocket flow
- environment setup

## Review
Use after Code finishes a task.
Its job is to approve or reject against acceptance criteria.

## Architect
Use only for:
- ADR updates
- contract/schema alignment
- execution plan corrections
- support matrix / platform policy changes

Do not use Architect to create parallel implementations.

## Orchestrator
Not the default recommendation for this repository.
Use only if the repo is already healthy and you explicitly need multi-step coordination.
