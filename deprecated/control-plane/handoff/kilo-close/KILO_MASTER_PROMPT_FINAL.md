1. upload/ARCHITECTURE.md
2. LIVE_VIABILITY_REQUIREMENTS.md
3. execution_plan_final_live_close.yaml
4. config/status.json
5. README.md
6. config/providers.yaml

## Architecture you must preserve
The world-class target architecture is frozen:
- Tauri 2.0 desktop shell
- Rust native audio layer
- Python FastAPI + WebSocket backend
- React + TypeScript UI
- PostgreSQL + pgvector as the only persistent data backbone
- Explicit pipeline, not a vague multi-agent mesh:
  AudioReceiver -> STTAdapter -> TurnAssembler -> LanguagePolicy -> QuestionAnalyzer -> RetrievalPlanner -> EvidenceRetriever -> ResponseComposer -> QualityGate -> Emitter
- Draft -> Validate -> Repair -> Expose for the full response
- Bullets-first path optimized separately for live usefulness
- Conversation tracker treated as a first-class product capability
- Provider aliases only; no hardcoded model IDs in Python or SQL
- macOS Apple Silicon Tier 1, Windows/Linux installable with graceful degradation

## Product truth you must preserve
This product is a **live coach**, not a teleprompter.
The real value in live mode is:
1. fast bullets
2. conversation tracker
3. language correctness
4. compound/follow-up handling

The full response is secondary and can arrive later.
Do not optimize the product around the full response at the expense of bullets-first usefulness.

## Execution algorithm
1. Reproduce local truth first.
2. Close package health first.
3. Close real backend mode next.
4. Close realtime usefulness next.
5. Close desktop macOS happy path after backend is truly useful.
6. Then harden release/installability.

## Required response after every task
1. Task ID
2. Files changed
3. Exact commands run
4. Test results
5. Acceptance proof
6. Blockers
7. Next task

## Starting point
Start with P0.1 from execution_plan_final_live_close.yaml.
