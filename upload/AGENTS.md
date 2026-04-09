# Interview Coach — AI Agent Instructions

## What This Is
macOS-first desktop app (Tauri 2.0) that captures audio from video conferences,
transcribes via streaming STT, analyzes interviewer questions deeply, and suggests
optimized responses with quality verification before display.

## Stack
- **Desktop**: Tauri 2.0 (Rust audio capture + React UI)
- **Backend**: Python 3.11+ (FastAPI + WebSocket)
- **STT**: via adapter interface (default: Deepgram Nova-3 multilingual)
- **LLM**: via adapter interface (default: Claude Sonnet for generation, Haiku for classification)
- **Embeddings**: via adapter interface (default: OpenAI text-embedding-3-small)
- **Database**: PostgreSQL 17 + pgvector (Docker Compose)
- **Observability**: OpenTelemetry

All providers are resolved by logical alias from `config/providers.yaml`. Zero model IDs in code or SQL.

## Architecture
Polyglot (Rust + Python + TypeScript). Stateful by design.
Pipeline: AudioReceiver → STTAdapter → TurnAssembler → LanguagePolicy → QuestionAnalyzer → RetrievalPlanner → EvidenceRetriever → ResponseComposer → QualityGate → Emitter.
Quality Gate: Draft → Validate → Repair → Expose. Blocks before showing.
Storage: PostgreSQL + pgvector ONLY. No SQLite. No ChromaDB.

## Directory Structure
```
tauri-app/src-tauri/src/audio/  # Rust audio capture (ScreenCaptureKit macOS)
tauri-app/src/                  # React UI (components/ + hooks/)
python-core/pipeline/steps/     # Each pipeline step (typed in, typed out)
python-core/adapters/           # STT, LLM, Embedding interfaces + implementations
python-core/conversation/       # Tracker, claims, coherence
python-core/styles/             # Executive, commercial, technical, mixed
python-core/contracts/models.py # ALL Pydantic data contracts
python-core/storage/            # DB connection, migrations, PersistQueue
config/                         # providers.yaml, execution_plan.yaml, status.json
tests/                          # unit, integration, simulations, benchmarks
```

## Test Deck
The project ships with a real test deck in `tests/`:
- `tests/fixtures/profiles/cto_profile.py` — CTO profile with 6 achievements and verifiable metrics
- `tests/fixtures/questions/question_bank.py` — 13 real interview questions (ES/EN/mixed), quality gate fail/pass cases, language policy cases
- `tests/simulations/scenarios/cto_startup.py` — Full 5-exchange CTO simulation with evaluation criteria
- `tests/unit/test_contracts.py` — Pydantic model validation (runnable now)
- `tests/unit/test_provider_registry.py` — Provider alias resolution (runnable now)
- `tests/unit/test_question_bank.py` — Fixture coverage and simulation structure (runnable now)
- `tests/unit/test_quality_gate.py` — Quality gate fail/pass case validation (runnable now)
- `tests/unit/test_language_policy.py` — Language policy case validation (runnable now)

Run: `cd python-core && python -m pytest ../tests/unit/ -v`

## How to Work
1. Read `config/execution_plan.yaml` for tasks with acceptance criteria
2. Read `config/status.json` for current progress
3. Each task specifies: files_to_create, acceptance_criteria, commands_to_run, rollback
4. After completing a task: run its acceptance criteria, update status.json, commit with `[TASK_ID] description`

## Phases
- F0 (Weeks 1-2): Scaffold + Docker + Contracts + Providers
- F1 (Weeks 3-5): Audio capture + STT + Transcript UI
- F2 (Weeks 6-8): Ingestion + Analysis + Retrieval + Generation + QualityGate + Tracker
- F3 (Weeks 9-11): All styles + Coherence + Settings + Hotkeys + Robust persistence
- F4 (Weeks 12-14): Simulations + Benchmarks + Replay + Hardening
