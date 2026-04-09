# Interview Coach

This repository is the single working codebase for the Interview Coach product.

## Product truth

Interview Coach is a **live interview coach**.

The canonical shipped product is:
- **Tauri desktop app** in `tauri-app/`

The following are **not** the product:
- root web preview
- `localhost:3000`
- any old Next.js-only flow

Primary user-facing artifact rules:
- **full_response is the primary visible artifact** in both manual and live mode
- bullets may exist only as **fast preview / support**, never as the product identity

## Current blocker

The product is **not functionally live yet**.
The main blocker is the **desktop live audio path**:
- real system audio capture is not yet wired through the canonical desktop path end-to-end
- the coach must primarily hear the interviewer through desktop system audio from meeting apps
- microphone capture is secondary/optional
- because of that, live session cannot be treated as functional product behavior

Until desktop live system audio works end-to-end, do not treat speaker/turn, usefulness, latency, or persistence as closed product phases.

## Frozen architecture

The architecture is frozen unless explicitly approved.

- Desktop shell: **Tauri 2**
- Native audio capture: **Rust**
- Backend core: **Python 3.11+ / FastAPI / WebSocket**
- UI: **React + TypeScript**
- Persistence backbone: **PostgreSQL + pgvector**
- Product pipeline:
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

## Hard rules — service boundaries

These rules are **mandatory and non-negotiable**. Every agent, every task, every PR must comply. Violation of any rule is a blocking error.

### HR-1: Live Caption is a frozen independent service

Live Caption is a **completely independent service**. It is **frozen**. Do not touch it.

Frozen boundary includes:
- `_handle_display_event()` in `python-core/api/server.py`
- The `live_caption` WebSocket message type
- Deepgram STT streaming behavior for the display path
- Live caption rendering in the Tauri UI (`App.tsx`)

Live Caption receives every STT event (partials + finals) and pushes them to the UI for real-time display. It has **zero dependency** on the coach pipeline, conversation history, or any analysis logic.

No agent may:
- Modify the live caption display path
- Add coach logic inside the live caption handlers
- Gate live caption events on pipeline state
- Change the live caption WebSocket message format

If a change is needed in live caption, it requires explicit owner approval and a separate task with its own rollback plan.

### HR-2: Conversation History is the single source of truth for all coach queries

All coach queries — automatic or manual — must read **exclusively** from the accumulated Conversation History.

The query window rule is:
- If the history contains **4 or more messages**: use the **last 4 messages**
- If the history contains **fewer than 4 messages**: use **all available messages**
- Never query with zero context if any history exists

Conversation History must be **persistently consultable** — via database, embeddings, or the most efficient mechanism available. In-memory-only history is acceptable only as a transitional state, not as the target architecture.

The canonical data flow is:
```
STT finals → TurnAssembler → ConversationTracker (accumulated history)
                                       ↓
                              Coach query reads last 4 turns
                                       ↓
                              Pipeline processes with context
```

No agent may:
- Pass empty `conversation_history=[]` to the coach pipeline when history exists
- Bypass ConversationTracker to feed raw STT events directly to the coach
- Use a different window size without explicit approval
- Mix live caption events into the coach query path

### HR-3: Rollback plan must exist and be executable at any moment

Every version must have a **clear, tested rollback plan** that can be executed in under 2 minutes.

Current rollback target: `backup/v1.0/`

Mandatory rollback files:
- `backup/v1.0/App.tsx` — frontend state
- `backup/v1.0/runtime_config.json` — backend config
- `backup/v1.0/router.rs` — Rust audio routing

Rollback procedure (copy-paste ready):
```bash
cp backup/v1.0/App.tsx tauri-app/src/App.tsx
cp backup/v1.0/runtime_config.json python-core/runtime_config.json
cp backup/v1.0/router.rs tauri-app/src-tauri/src/audio/router.rs
# Restart backend + frontend
```

Before any code change an agent must:
1. Verify the current rollback backup is up to date
2. If the change affects a backed-up file, update the backup **before** modifying
3. Document which rollback scenario applies

No agent may:
- Make changes without a rollback path
- Delete or overwrite backup files without creating a new backup first
- Treat rollback as optional

### HR-4: Manual Coach Button is a fully independent service

The manual coach query button ("Ask Coach") is a **completely independent service**. It must not depend on:
- Live Caption state or events
- STT stream being active
- Auto-trigger logic or silence detection
- Any WebSocket session state beyond Conversation History

The manual coach button logic is:
1. Read the accumulated Conversation History
2. Apply the HR-2 window rule (last 4 messages, or all if fewer than 4)
3. Send the windowed history to the coach pipeline
4. Return the coach response

This must work as a **standalone HTTP endpoint** (not only as a WebSocket message). A user must be able to press the button and get a coach response whether or not a live session is running.

No agent may:
- Couple the manual coach button to live session state
- Require an active STT stream for the manual button to work
- Share mutable state between the auto-trigger path and the manual button path beyond the read-only Conversation History

## Mandatory startup sequence

Before coding, always read in this exact order:
1. `AGENTS.md`
2. `config/status.json`
3. `plans/CANONICAL_EXECUTION_PACK.md`
4. `docs/SUPPORT_MATRIX.md`
5. `docs/CLOSURE_QUALITY_GATES.md`

Before coding, always restate:
1. current phase
2. active task
3. last approved task
4. next valid task
5. active gate
6. canonical validation target
7. forbidden validation targets
8. current blocker

If any of the above cannot be derived from repo truth, stop and report the contradiction before coding.

## Canonical validation target

- `canonical_validation_target = tauri-desktop`
- `forbidden_validation_targets = localhost:3000, web-preview-as-product`

Never validate product closure in the old web preview.

## Environment rules

- For backend Python, use repo virtualenv only:
  - prefer `./.venv`
  - fallback `python-core/.venv` only if root `.venv` does not exist
- Require **Python 3.11+**
- Do not use system `python` if it does not match the repo runtime
- If interpreter/runtime is wrong, stop and report it

## Operating rules

- Work only in this repository.
- Implement **one task at a time**.
- Do not skip phases or gates.
- Do not re-open architecture.
- Do not switch providers.
- Do not bring back the old web preview as product validation path.
- Do not mark anything `functional` without local evidence.
- Do not do doc churn outside N0/P0 and P7.
- Do not add tooling or files that do not directly help close the product.

## Truth labels

Use only these labels:
- `functional`
- `partial`
- `demo`
- `stub`
- `deprecated`

Never use `complete` without local evidence.

## Required response format for every task

1. Task ID
2. Why this is the correct task
3. Files changed
4. Exact commands run
5. Tests run
6. Runtime evidence captured
7. Acceptance proof
8. Truthful status decision
9. Blockers
10. Next recommended task
11. Question: Proceed to the next task?
