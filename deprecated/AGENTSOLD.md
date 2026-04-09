# Interview Coach

This repository is the single working codebase for the Interview Coach product.

## Product intent

Interview Coach is a **live interview coaching** system.
Its real value in live interviews is:

- **bullets first**
- **conversation tracker continuity**
- **language correctness**
- **quality gating that prevents bad advice**
- **desktop-first experience on macOS Apple Silicon**

The product is **not** a teleprompter.
The product is a **coach** that should surface useful bullets fast enough to guide the user's opening response, while a fuller response may arrive slightly later as reference.

## Frozen architecture

The architecture is frozen unless the user explicitly approves a change.

- Desktop shell: **Tauri 2**
- Native audio capture: **Rust**
- Backend core: **Python 3.11+ / FastAPI / WebSocket**
- UI: **React + TypeScript**
- Persistence backbone: **PostgreSQL + pgvector**
- Explicit pipeline:
  - AudioReceiver
  - STTAdapter
  - TurnAssembler
  - LanguagePolicy
  - QuestionAnalyzer
  - RetrievalPlanner
  - EvidenceRetriever
  - ResponseComposer
  - QualityGate
  - Emitter
- Quality gate flow:
  - Draft
  - Validate
  - Repair
  - Expose

## Product priorities

Priority order is:

1. Package health and truthful status
2. Backend real mode
3. Realtime usefulness
4. Desktop/macOS happy path
5. Release hardening

Do **not** add new features until the current phase is truly closed.

## Live interview constraints

The critical latency target is not "full response instantly".
The critical target is:

- bullets visible quickly enough to help the user start speaking
- stable tracker state across the conversation
- no contradictory or language-broken output
- graceful degradation when real mode is unavailable

Use these practical assumptions:

- bullets matter more than full prose for real-time usefulness
- the conversation tracker is a first-class feature
- follow-ups and compound questions are high-value cases
- short factual questions are not the primary optimization target

## Operating rules

- Work only in this repository.
- Do not create a second architecture or parallel implementation.
- Do not reintroduce SQLite, Prisma, or ChromaDB into the core path.
- Do not hide demo mode behind real-looking labels.
- Do not mark a component complete if it is still demo, partial, or stub.
- Do not mark a phase complete unless its acceptance checks actually pass locally.
- Do not trust `config/status.json` blindly; verify it against commands and code.
- Use `plans/CANONICAL_EXECUTION_PACK.md` as the execution-plan source of truth.
- See plans/CANONICAL_EXECUTION_PACK.md for the active execution plan.
- Implement one task at a time.
- Run the required tests for each task.
- Update status honestly after each approved task.

## Required reading order for any serious task

1. `README.md`
2. `config/status.json`
3. `plans/CANONICAL_EXECUTION_PACK.md`
4. `docs/SUPPORT_MATRIX.md`
5. relevant files in `python-core/`, `src/`, `tauri-app/`, and `tests/`

## Output discipline

For every task, return:

1. files changed
2. exact commands run
3. tests run
4. acceptance proof
5. blockers
6. next task

## Truth labels

Use these labels consistently:

- `functional`
- `demo`
- `partial`
- `stub`
- `deprecated`

Never use `complete` unless the path is actually exercised and verified.
