# v1.0-Fases1-2 Stable Backup

Created: 2026-03-19
Status: Stable (with Fases 1-2)

## How to Create This Backup

Run these commands from project root:

```bash
mkdir -p backup/v1.0
cp tauri-app/src/App.tsx backup/v1.0/
cp tauri-app/src/lib/api-client.ts backup/v1.0/api-client.ts
cp tauri-app/src/types/index.ts backup/v1.0/types.ts
cp python-core/api/server.py backup/v1.0/server.py
cp python-core/conversation/tracker.py backup/v1.0/
cp python-core/storage/session_repo.py backup/v1.0/
cp python-core/pipeline/silence_detector.py backup/v1.0/
cp python-core/pipeline/realtime_pipeline.py backup/v1.0/
cp python-core/runtime_config.json backup/v1.0/
cp tauri-app/src-tauri/src/audio/router.rs backup/v1.0/
cp python-core/pipeline/steps/question_analyzer.py backup/v1.0/
```

## Files Backed Up

### Frontend
1. `App.tsx` - Frontend WebSocket handlers and live caption logic (includes history_count selector in UI)
2. `api-client.ts` - API client with history_count parameter support
3. `types.ts` - TypeScript types with history_count in SuggestionRequest

### Python Backend (Fases 1-2)
2. `server.py` - API endpoints including /api/suggest, SilenceDetector integration (with debug logs)
3. `tracker.py` - ConversationTracker with get_last_n_turns method
4. `session_repo.py` - SessionRepository with get_recent_exchanges method
5. `silence_detector.py` - SilenceDetector for auto-trigger suggestions
6. `realtime_pipeline.py` - RealtimePipeline with context parameter fix

### Config
7. `runtime_config.json` - STT configuration (Deepgram, local_enabled: false)

### Rust
8. `router.rs` - Rust audio router (cadence delay removed)

### Pipeline Steps
9. `question_analyzer.py` - QuestionAnalyzer with AnalysisContext (includes conversation_history field)

## How to Restore

```bash
# From project root:

# Frontend only:
cp backup/v1.0/App.tsx tauri-app/src/App.tsx

# Python only (Fases 1-2 rollback):
cp backup/v1.0/server.py python-core/api/server.py
cp backup/v1.0/tracker.py python-core/conversation/tracker.py
cp backup/v1.0/session_repo.py python-core/storage/session_repo.py
cp backup/v1.0/realtime_pipeline.py python-core/pipeline/realtime_pipeline.py
rm python-core/pipeline/silence_detector.py

# Config:
cp backup/v1.0/runtime_config.json python-core/runtime_config.json

# Rust:
cp backup/v1.0/router.rs tauri-app/src-tauri/src/audio/router.rs

# Complete rollback (with history_count):
cp backup/v1.0/App.tsx tauri-app/src/App.tsx
cp backup/v1.0/api-client.ts tauri-app/src/lib/api-client.ts
cp backup/v1.0/types.ts tauri-app/src/types/index.ts
cp backup/v1.0/server.py python-core/api/server.py
cp backup/v1.0/tracker.py python-core/conversation/tracker.py
cp backup/v1.0/session_repo.py python-core/storage/session_repo.py
cp backup/v1.0/realtime_pipeline.py python-core/pipeline/realtime_pipeline.py
rm python-core/pipeline/silence_detector.py
cp backup/v1.0/runtime_config.json python-core/runtime_config.json
cp backup/v1.0/router.rs tauri-app/src-tauri/src/audio/router.rs
cp backup/v1.0/question_analyzer.py python-core/pipeline/steps/question_analyzer.py
```

## What Works (v1.0 with Fases 1-2)

- Real-time transcription via Deepgram
- Live Captions showing partials
- Conversation History accumulating finals
- Speaker locked to "Interviewer"
- Dual path: live_caption (display) + transcript (history)
- `/api/suggest` endpoint for manual coaching (Fase 1)
- SilenceDetector for auto-triggered suggestions (Fase 1)
- `get_last_n_turns()` method in ConversationTracker (Fase 2)
- `get_recent_exchanges()` method in SessionRepository (Fase 2)
- **"Question required" bug fix** - Question field now optional in API (backend validation corrected)
- **RealtimePipeline context fix** - Added `context` parameter to pipeline calls
- **Server debug logs** - Added debugging logs to server.py for troubleshooting

## Critical Fixes Applied (2026-03-19)

1. **realtime_pipeline.py**: Added `context` parameter to enable proper context passing
2. **server.py**: Added debug logs for improved troubleshooting
3. **server.py (2026-03-19 v2)**: Added global pipeline registry and ConversationTracker in-memory fix
   - Global registry `_PIPELINES: dict[str, RealtimePipeline]` to maintain pipeline state per session
   - In-memory tracker usage: Pipeline now uses tracker from registry instead of creating new instances
   - Ensures conversation history persists correctly across WebSocket sessions
   - Fixes HR-2 compliance: All coach queries read from accumulated Conversation History
4. **question_analyzer.py (2026-03-19)**: AnalysisContext now includes `conversation_history` field
    - Required for HR-2 compliance: QuestionAnalyzer receives conversation history for context-aware analysis
    - Field added to support proper context passing through the pipeline

## history_count Configurable Feature (2026-03-19)

### Overview
New configurable `history_count` parameter allows users to control how many conversation turns are used for context when generating coach suggestions.

### Components Updated

1. **Frontend - App.tsx**: Added UI selector for history_count (dropdown with options: 2, 4, 6, 8 turns)
2. **Frontend - api-client.ts**: Modified `requestSuggestion()` to include `history_count` parameter in API requests
3. **Frontend - types.ts**: Added `history_count` field to `SuggestionRequest` type
4. **Backend - server.py**: Modified `/api/suggest` endpoint to accept and use `history_count` parameter
   - When provided, uses the specified number of turns instead of default HR-2 rule (4 turns)

### Usage
- Users can select from preset values: 2, 4, 6, or 8 conversation turns
- Default behavior follows HR-2 rule (last 4 messages if available)
- When history_count is explicitly set, it overrides the default window size

### Rollback for history_count
```bash
cp backup/v1.0/App.tsx tauri-app/src/App.tsx
cp backup/v1.0/api-client.ts tauri-app/src/lib/api-client.ts
cp backup/v1.0/types.ts tauri-app/src/types/index.ts
cp backup/v1.0/server.py python-core/api/server.py
```

## Known Issues

- Gap between Live Caption clearing and Conversation History showing
- See plans/CAPTION_TO_HISTORY_GAP_FIX_PLAN.md for fix

## Rollback Time Estimate

- Frontend only: < 30 seconds
- Python only: < 1 minute (requires backend restart)
- Complete rollback: 1-2 minutes
