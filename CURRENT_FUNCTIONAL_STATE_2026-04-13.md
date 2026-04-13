# Current Functional State - 2026-04-13

## Purpose

This file captures the exact technical line that is working now and is intended to be published to `main`.

Primary goal of this line:

- Keep live interview flow working end to end.
- Stop mixing previous interviewer asks with the current one.
- Stop emitting too early on partial interviewer tails.
- Keep brain preparation based on active intent/context instead of hardcoded question heuristics.

## Current Publication Intent

- Source repo: `/Users/dalarcon/projects/prd/interview-coach-v1`
- Current working branch before publishing: `feature/clean-turn-isolation`
- Target branch to publish: `main`
- Publication commit on `main`: `TBD`

## Non-Negotiable Working Rules For This Line

- Do not burn question interpretation into static code paths.
- Brain must work from active interviewer intent and active context window.
- Live flow must continue preparing context while the interviewer is speaking.
- Do not regress `live`, `history`, or already-working session behavior while improving brain.
- Do not emit a suggestion just because a fragment looks question-like if the active interviewer ask is still incomplete.

## What Was Fixed To Reach This Working State

### 1. Provider and runtime configuration

Files:

- `config/providers.yaml`
- `python-core/adapters/provider_registry.py`
- `python-core/pyproject.toml`

What changed:

- `llm.fast` was moved away from Ollama local fallback and configured explicitly to Anthropic Haiku.
- Provider registry now resolves `config/providers.yaml` from the repo root instead of depending on the current working directory.
- `anthropic` was added as an explicit Python dependency.

Why this mattered:

- Backend could start from a different cwd and silently read the wrong provider config.
- Fast brain path was falling back to a local runtime that was not the intended production-like path.

### 2. Brain planner robustness

Files:

- `python-core/pipeline/steps/live_brain_service.py`
- `python-core/pipeline/steps/live_question_planner.py`

What changed:

- Brain timeout was increased to `6.5s` to reduce premature fallback in live mode.
- Live brain parsing was hardened so line-based payloads are accepted instead of failing as `json_not_found`.
- Planner/test coverage was extended for direct-draft recovery behavior when strict JSON planning fails.

Why this mattered:

- Brain was failing too fast and then returning low-quality emergency fallback output.
- Valid LLM responses were sometimes being rejected only because they were not wrapped in strict JSON.

### 3. Active ask isolation and turn-window reset

Files:

- `python-core/pipeline/silence_detector.py`
- `python-core/conversation/tracker.py`
- `python-core/contracts/models.py`
- `python-core/api/server.py`

What changed:

- Realtime context resolution now distinguishes:
  - active interviewer turns
  - historical turns
  - post-commit turns
  - post-freeze turns
- `ActiveAskState` now tracks frozen ask boundaries, not only committed answer boundaries.
- Tracker now records `record_active_ask_frozen(...)` so a served ask can be closed before the next active ask starts.
- Active window selection now uses silence boundaries and turn timing instead of blindly carrying prior interviewer turns forward.
- Frontend, tracker-backed, and DB/history-backed suggest flows now normalize to the same active interviewer window logic.

Why this mattered:

- The coach was accumulating previous interviewer asks into the next one.
- After one answer plus silence, the next question should start a new active block instead of inheriting older context.

### 4. Preventing premature emit on partial interviewer context

Files:

- `python-core/api/server.py`
- `tests/unit/test_ws_session_stt_manager.py`

What changed:

- New gate: `_live_snapshot_requires_more_interviewer_context(...)`
- If brain marks the active ask as partial or unstable, auto-silence does not:
  - emit a suggestion
  - record trigger cooldown
  - freeze the active ask
  - finalize the current live interviewer block
- Freeze/finalize/cooldown now happen only after generation is still current and actually ready to emit.

Why this mattered:

- This was the main regression that caused:
  - early emit before interviewer finished
  - loss of accumulation across fragments
  - worse interpretation because later fragments arrived after the block had already been closed

### 5. Suggest endpoint alignment with live active context

Files:

- `python-core/api/server.py`
- `tauri-app/src/App.tsx`
- `tauri-app/src/types/index.ts`
- `tests/unit/test_api_suggest_context.py`

What changed:

- Manual/live suggest now sends transcript timing (`timestamp_ms`) from the frontend.
- Backend resolves active interviewer context consistently for:
  - frontend conversation history
  - active pipeline tracker
  - DB-backed recent exchanges
- Manual "Get Suggestions" uses the latest interviewer block with silence-aware reset instead of blindly concatenating older interviewer turns.

Why this mattered:

- The debug payload showed cases where the UI displayed multiple interviewer fragments but the backend used only an incomplete tail or the wrong active question.

## Files Carrying The Core Of This Working Behavior

- `python-core/api/server.py`
- `python-core/pipeline/silence_detector.py`
- `python-core/conversation/tracker.py`
- `python-core/contracts/models.py`
- `python-core/pipeline/steps/live_brain_service.py`
- `python-core/pipeline/steps/live_question_planner.py`
- `python-core/adapters/provider_registry.py`
- `config/providers.yaml`
- `tauri-app/src/App.tsx`
- `tauri-app/src/types/index.ts`

## Tests Added Or Updated For This Line

- `tests/unit/test_api_suggest_context.py`
- `tests/unit/test_conversation_tracker.py`
- `tests/unit/test_live_brain_v3.py`
- `tests/unit/test_live_question_planner.py`
- `tests/unit/test_provider_registry.py`
- `tests/unit/test_ws_session_stt_manager.py`

Important regressions now covered:

- latest active interviewer turn is isolated after silence
- latest active interviewer block is isolated after freeze/commit
- suggest context from frontend/tracker/history aligns to the latest active ask
- partial live brain snapshots do not burn state
- richer stabilized snapshot is preferred over earlier partial one

## Commands Used To Validate This Version

### Backend

From repo root:

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1
PYTHONPATH=python-core ./.venv/bin/python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

Expected:

- backend healthy
- db connected
- pgvector ready
- api keys configured
- providers loaded
- effective mode `real`

### Frontend

From:

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1/tauri-app
npm run dev -- --host 127.0.0.1 --port 5174
```

Expected:

- frontend on `http://127.0.0.1:5174`

## Focused Validation Already Run Successfully

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1
PYTHONPATH=python-core ./.venv/bin/python -m pytest tests/unit/test_ws_session_stt_manager.py -k "partial_snapshot_waits_for_more_interviewer_context_without_burning_state or waits_for_stabilization_and_prefers_richer_snapshot or rebuilds_stale_snapshot_before_emitting_response" -q
PYTHONPATH=python-core ./.venv/bin/python -m pytest tests/unit/test_api_suggest_context.py -q
./.venv/bin/python -X pycache_prefix=/tmp/interview-coach-pycache -m py_compile python-core/api/server.py tests/unit/test_ws_session_stt_manager.py
```

## Known Operational Notes

- This repo tracks generated artifacts like `__pycache__` and `tauri-app/dist`. Be careful when “cleaning noise”; stripping files casually can make the repo diverge from the exact currently-working state.
- The current ask-reset behavior depends on both silence boundaries and freeze/commit boundaries.
- If the app starts answering too early again, inspect:
  - whether `_live_snapshot_requires_more_interviewer_context(...)` is being hit
  - whether trigger/freeze/finalize moved earlier again
  - whether frontend timestamps stopped being sent
  - whether the active-turn selection logic in `silence_detector.py` changed

## If This Breaks Later, Check These First

1. `config/providers.yaml` still points `llm.fast` to Anthropic Haiku.
2. `provider_registry.py` still resolves the repo-root config.
3. Live brain timeout is still `6.5s`.
4. Suggest path still builds active context from normalized active turns.
5. Auto-silence still refuses to emit on partial/unstable snapshots.
6. Freeze/finalize/record_trigger still happen only at actual emit time.

## Next Line Of Work After Publishing

After this version is secured on `main`, the next clone/branch should focus on improving brain answer quality only, while preserving:

- active ask isolation
- partial snapshot waiting behavior
- tracker/history/live context reset behavior
- provider/runtime configuration that is already working now
