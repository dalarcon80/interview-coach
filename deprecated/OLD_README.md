# Interview Coach

**macOS-first desktop application that acts as a real-time interview coach.**

Designed for live interview coaching with bullets-first guidance, conversation tracking, and quality-gated suggestions. In `v0.9.0-rc`, the live desktop audio/STT path is still partial and manual transcript input remains an important fallback.

---

## Package Status Summary

| Component | Truth Label | Notes |
|----------|-------------|-------|
| Backend API | **functional** | FastAPI + WebSocket endpoints working |
| Pipeline steps (8/10) | **functional** | Core coaching pipeline available; audio/STT gaps tracked separately |
| InterviewContext persistence | **functional** | localStorage persistence active |
| Tauri UI features | **functional** | Canonical desktop UI path working |
| macOS Audio Capture | **partial** | Not functional end-to-end on desktop realtime path |
| STT adapter | **partial** | Not functional end-to-end; `net0001` lifecycle instability persists |
| Audio bridge | **partial** | Desktop audio bridge to backend is incomplete |
| Demo fallback mode | **demo** | Explicit demo/fallback path when real providers unavailable |
| Windows/Linux audio | **stub** | Placeholder only |
| Session persistence | **stub** | Not functional end-to-end |

---

## Closure Status

**In Progress — see plans/CANONICAL_EXECUTION_PACK.md**

See plans/CANONICAL_EXECUTION_PACK.md for current execution status.

**Current Version**: v0.9.0-rc — release candidate in truth reconciliation, working toward 1.0 stabilization.

---

## What's New in v0.9.0-rc

### Status Alignment Update
- README claims aligned with `config/status.json` truth labels.
- Legacy "F0–F7 complete" framing removed in favor of current P0–P7 execution tracking.
- Release-ready claim removed; package status now explicitly in progress.
- Package summary now labels macOS audio capture, STT adapter, and audio bridge as **partial**.
- Session persistence and Windows/Linux audio are explicitly labeled **stub**.

---

## What is Actively Supported

### Desktop Shell (`tauri-app/`)
- **Purpose**: Canonical product UI — the shipped application
- **Status**: ✅ Functional for the current desktop feature set
- **How to run**: `cd tauri-app && npm run tauri dev`
- **Features**: CV intake, AI analysis, rich forms, style selector, manual/live coaching

### Python Backend (`python-core/`)
- **Purpose**: Core API and WebSocket server
- **Status**: ✅ Functional with real mode and explicit demo fallback
- **How to run**: `cd python-core && python main.py`
- **Endpoints**:
  - `GET /health` - Health check with DB status
  - `POST /api/suggest` - Interview suggestion pipeline
  - `POST /api/analyze-cv` - CV analysis with structured extraction
  - `WS /ws/pipeline` - Real-time WebSocket pipeline

### InterviewContext Persistence
- **Status**: ✅ Functional via localStorage
- **Persists**: Profile (13+ fields), Company (15+ fields), Style, Language, CV text, Analysis results
- **Clear Context**: Available in UI to reset all data

### Realtime UI Components (`src/components/realtime/`)
- **Status**: ✅ Integrated in Tauri app
- **Components**:
  - `SessionControlPanel` - Session management UI
  - `AudioSettingsPanel` - Audio configuration UI
  - `LiveTranscriptPanel` - Transcript display
  - `RealtimeSuggestionPanel` - AI suggestion display

### CV Analysis API (`/api/analyze-cv`)
- **Status**: ✅ Functional with explicit `real` / `demo` / `fallback` mode labeling
- **Current Use**: CV extraction + profile prefill with graceful fallback

### Test Suite
- **Unit Tests**: 78+ passing
- **Integration Tests**: Contract + pipeline + E2E passing
- **Collection**: 217+ tests collected
- **How to verify**: `bash scripts/test_package.sh quick`

---

## What is Partial

### macOS Audio Capture + Audio Bridge (`tauri-app/src-tauri/src/audio/macos_capture.rs`)
- **Status**: ⚠️ Partial — not functional end-to-end in live desktop path
- **What works**: ScreenCaptureKit stream + callback + normalization/chunking
- **Gap (Audio bridge)**: Forwarding from desktop capture into backend realtime pipeline is incomplete
- **Current behavior**: Live path can require fallback/manual transcript input when bridge fails

### STT Adapter (`python-core/adapters/stt_adapter.py`)
- **Status**: ⚠️ Partial — not functional end-to-end
- **What works**: Qualified Deepgram Nova-3 `/v1/listen` runs can succeed
- **Gap**: STT lifecycle instability persists (`net0001`), preventing reliable continuous transcription

---

## What is Stub

### Windows/Linux Audio
- **Status**: Placeholder code only
- **Target**: V1.5

---

## What is Deprecated

| Artifact | Reason | Location |
|----------|--------|----------|
| `examples/websocket/` | Socket.IO demo unrelated to architecture | Moved to `deprecated/examples/` |
| `test_event_bus_contract.py` | Tests legacy event names | Marked as LEGACY in file header |
| Prisma/SQLite | Architecture uses PostgreSQL | Removed from `package.json` |
| next-auth | Not part of frozen architecture | Removed from `package.json` |
| z-ai-web-dev-sdk | Uses external LLM APIs directly | Removed from `package.json` |

---

## How to Verify Package Health

**Last Verified**: 2026-03-14

Commands run (results below):
- `python3 -m pytest tests --collect-only -q` → 217+ tests collected
- `bash scripts/test_package.sh quick` → 78+ unit tests passed
- `bash scripts/verify_package.sh` → PASSED (collection, unit, smoke, lint)

### Quick Validation (Unit Tests Only)
```bash
bash scripts/test_package.sh quick
```

### Smoke Test (Collection + Key Tests)
```bash
bash scripts/test_package.sh smoke
```

### Full Test Suite
```bash
bash scripts/test_package.sh full
```

### Manual Verification
```bash
# 1. Verify test collection
python -m pytest tests --collect-only -q

# 2. Run unit tests
python -m pytest tests/unit -v

# 3. Run contract tests
python -m pytest tests/integration/test_frontend_backend_ws_contract.py -v
```

---

## Architecture

| Layer | Technology | Status |
|-------|------------|--------|
| Desktop Shell | Tauri 2.0 | ✅ Functional |
| Audio Capture | Rust + ScreenCaptureKit | ⚠️ Partial (STT optional) |
| UI | React 18 + TypeScript + TailwindCSS | ✅ Functional |
| Backend | Python 3.11+ / FastAPI | ✅ Functional |
| STT | Deepgram Nova-3 | ⚠️ Optional (stubbed without key) |
| LLM | Claude Sonnet (via alias llm_main) | ✅ Functional |
| Embeddings | OpenAI text-embedding-3-small | ✅ Functional |
| Database | PostgreSQL 17 + pgvector | ✅ Functional |
| Persistence | localStorage (InterviewContext) | ✅ Functional |

**Architecture Version**: v3.2.1 (FROZEN)

---

## Component Status

| Component | Status | Description |
|-----------|--------|-------------|
| Health Endpoint | ✅ Functional | Real DB check, returns healthy/degraded |
| /api/suggest | ✅ Functional | Full pipeline with explicit mode labels |
| /api/analyze-cv | ✅ Functional | Real/demo/fallback with structured extraction |
| WebSocket /ws/pipeline | ✅ Functional | Real pipeline events |
| Session Management | ✅ Functional | Session lifecycle + persistence |
| Evidence Retrieval | ✅ Functional | Real pgvector path with graceful fallback |
| Response Composition | ✅ Functional | Full response primary, bullets secondary |
| Quality Gate | ✅ Functional | Draft/validate/repair/expose |
| Conversation Tracker | ✅ Functional | Prevents contradictions |
| InterviewContext Persistence | ✅ Functional | localStorage implementation |
| macOS Audio Capture | ⚠️ Partial | Capture + forwarding work, STT optional |
| CV Analysis | ✅ Functional | Real/demo/fallback modes |
| Desktop UI (Tauri) | ✅ Functional | Full F1 feature set |
| Next.js Preview | ✅ Functional | Reference only — not shipped |

---

## WebSocket Event Contract

### Server → Client Events
| Event | Payload |
|-------|---------|
| `connected` | `{message, timestamp}` |
| `session_started` | `{session_id, config, mode}` |
| `analysis` | `{question_type, is_compound, sub_questions, ...}` |
| `suggestion` | `{mode, bullets, full_response, confidence, ...}` |
| `session_ended` | `{summary}` |
| `error` | `{message}` |
| `pong` | `{}` |

### Client → Server Events
| Event | Payload |
|-------|---------|
| `start_session` | `{config: {...}}` |
| `transcript_ready` | `{text, is_final, language}` |
| `end_session` | `{}` |
| `ping` | `{}` |

---

## Known Limitations (v0.9.0-rc)

| ID | Component | Issue | Resolution |
|----|-----------|-------|------------|
| LIM-001 | STT | Requires Deepgram API key, stubbed without it | Use manual text input (fully functional) |
| LIM-002 | macOS Audio | Requires Screen Recording permission | Grant in System Preferences |
| LIM-003 | Real Mode | Requires PostgreSQL + LLM API key | Demo mode works without these |
| LIM-004 | Platform | Windows/Linux audio paths not implemented | macOS Tier 1 for current release candidate |
| LIM-005 | Latency | ~8.4s for full response in real mode | Bullets-first display mitigates |

---

## Quick Start

### Desktop App (Canonical — requires macOS)
```bash
cd tauri-app
npm install
npm run tauri dev
```

### Backend
```bash
cd python-core
pip install -e .
python main.py
```

### Web Preview (Development Only)
```bash
bun install
bun dev
# Open via Preview Panel (NOT localhost:3000)
```

### Tests
```bash
# Quick validation
bash scripts/test_package.sh quick

# Full test suite
python -m pytest tests -v
```

---

## Production Requirements

1. **Database**: PostgreSQL 17 + pgvector extension
2. **API Keys**: `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
3. **Optional**: `DEEPGRAM_API_KEY` for live STT
4. **Platform**: macOS 12.3+ (Tier 1)

---

## Documentation

| Document | Purpose |
|----------|---------|
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | End-user documentation |
| [`docs/DEVELOPER_RUNBOOK.md`](docs/DEVELOPER_RUNBOOK.md) | Developer documentation |
| [`docs/CLOSURE_QUALITY_GATES.md`](docs/CLOSURE_QUALITY_GATES.md) | Quality gates and acceptance criteria |
| [`docs/CLOSURE_GAP_MATRIX.md`](docs/CLOSURE_GAP_MATRIX.md) | Gap analysis and closure sequence |
| [`docs/SUPPORT_MATRIX.md`](docs/SUPPORT_MATRIX.md) | Platform support tiers |
| [`config/status.json`](config/status.json) | Component truth |

---

## Development Notes

- **macOS-first**: Current release candidate targets macOS. Windows/Linux are stubs for the later cross-platform phase.
- **Provider abstraction**: STT, LLM, and embeddings are swappable via aliases
- **Quality gate**: Responses are validated BEFORE being shown
- **Audio is partial**: Capture exists, but desktop audio bridge and STT remain incomplete end-to-end
- **Web preview is for development**: Production runs in Tauri
- **Full responses are primary**: Bullets are secondary/loading indicators

---

## License

Private project. All rights reserved.
