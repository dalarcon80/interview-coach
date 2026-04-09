# Backup v1.3 - Functional Conversation History State

**Created:** 2026-03-19
**Status:** Functional

## Description

This backup represents a functional state where `conversation_history` works correctly end-to-end:

### Functional Components

1. **Frontend sends conversation_history correctly** (`tauri-app/src/App.tsx`)
   - Transcripts are captured and included in the request
   - `conversation_history` array is properly populated with speaker turns
   - History is sent to backend via WebSocket or HTTP

2. **Backend receives and processes conversation_history** (`python-core/api/server.py`)
   - Server correctly receives the conversation_history in requests
   - Pipeline processes the history to generate contextual suggestions
   - HR-2 window rule is applied (last 4 messages, or all if fewer than 4)

3. **Full Response Artifact**
   - Primary visible artifact is the full_response
   - Bullets exist only as fast preview/support

### Key Features Working

- STT transcription capture
- Speaker turn detection and labeling
- Conversation history accumulation
- Contextual coach queries with proper history window
- Manual coach button functionality (HR-4 independent service)

### Rollback Instructions

To rollback to this state:

```bash
cp backup/v1.3/App.tsx tauri-app/src/App.tsx
cp backup/v1.3/server.py python-core/api/server.py
# Restart backend + frontend
```

### Files Included

| File | Description |
|------|-------------|
| `App.tsx` | Frontend with functional conversation_history |
| `server.py` | Backend with functional conversation_history processing |
| `README.md` | This file |

### Known Limitations

This backup is from the pre-live-audio phase. The main blocker remains:
- Desktop live system audio path not fully wired end-to-end
- Product is not yet functionally live
