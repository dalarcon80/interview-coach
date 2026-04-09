# Interview Coach — User Guide

---

## Overview

Interview Coach is a **live interview coaching system** that helps you prepare for and navigate job interviews with AI-powered full-response suggestions. It runs as a macOS desktop application built with Tauri 2, backed by a Python/FastAPI server using real LLM providers (Anthropic Claude, OpenAI) and PostgreSQL with pgvector for intelligent evidence retrieval.

The product operates in two complementary modes:

1. **Preparation Mode** — Upload your CV, build your professional profile, describe the target company/role, and practice with typed questions that receive AI-generated full-response suggestions.
2. **Live Mode** — During a real interview, the system captures audio, transcribes it, detects questions, and provides contextual full-response suggestions in real time.

### What It Is

Interview Coach is a **coach** — it provides structured response suggestions drawing from your actual experience, skills, and achievements. Responses are quality-gated to prevent contradictions, repetition, and language errors.

### What It Is Not

Interview Coach is **not a teleprompter**. It does not write scripts for you to read verbatim. It provides context-aware suggestions that you adapt in your own voice.

### UI Overview

- **Tauri Desktop App** (`tauri-app/`) — The canonical product UI. This is the shipped application.
- **Next.js Preview** (`src/`) — Development preview only, not the final product.

---

## Current Working State

| Area | Status | Description |
|---|---|---|
| **Tauri Desktop App** | ✅ Functional | Full CV intake, AI analysis, rich profile (13+ fields), rich company form (15+ fields), style selector, manual coaching, live coaching with session lifecycle |
| **Next.js Preview UI** | ✅ Functional | Reference implementation — not the shipped product |
| **Python Backend** | ✅ Functional | Real LLM mode, real pgvector retrieval, demo/fallback with explicit labels |
| **Pipeline** | ✅ Functional | 8/10 steps: LanguagePolicy → QuestionAnalyzer → RetrievalPlanner → EvidenceRetriever → ResponseComposer → QualityGate → Emitter |
| **InterviewContext Persistence** | ✅ Functional | localStorage persistence — profile, company, style, CV data survive restart |
| **Audio Capture** | ⚠️ Partial | ScreenCaptureKit capture works, WebSocket forwarding implemented, STT stubbed (needs Deepgram API key) |
| **Tests** | ✅ Functional | 217+ tests, 78+ unit tests passing, verification scripts working |

---

## Getting Started

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| macOS | 12.3+ | Apple Silicon recommended (Tier 1 target). Intel supported. |
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend tooling |
| Rust + Cargo | Latest stable | Required for Tauri desktop build |
| PostgreSQL | 17 + pgvector | Via Docker (`docker-compose up -d`) |
| Docker Desktop | Latest | For PostgreSQL container |
| Anthropic API key | — | Required for real LLM responses (or `OPENAI_API_KEY` as alternative) |

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd interview-coach
   ```

2. **Run the bootstrap script** (installs dependencies automatically):
   ```bash
   bash scripts/bootstrap_macos.sh
   ```
   This checks and installs: Python 3.11+, Node.js/npm, Rust/Cargo, ScreenCaptureKit prerequisites, Python packages, Node packages, and verifies Docker availability.

3. **Start PostgreSQL** (required for real mode):
   ```bash
   docker-compose up -d
   ```
   This provisions PostgreSQL 17 + pgvector with the schema from `python-core/storage/migrations/001_initial_schema.sql`.

4. **Configure API keys**:
   ```bash
   export ANTHROPIC_API_KEY="your-anthropic-key"
   # OR
   export OPENAI_API_KEY="your-openai-key"
   ```

5. **Start the backend** (Terminal 1):
   ```bash
   cd python-core
   pip install -e .
   uvicorn api.server:app --port 8000
   ```
   Backend serves at `http://localhost:8000`.

6. **Start the desktop app** (Terminal 2 — canonical UI):
   ```bash
   cd tauri-app
   npm install
   npm run tauri dev
   ```
   The Tauri window opens and connects to the backend at `http://localhost:8000`.

### Verify Installation

Run the doctor script to check your environment:
```bash
bash scripts/doctor_macos.sh
```

Run the package health check:
```bash
bash scripts/verify_package.sh
```

---

## Features

### Preparation Mode

Preparation mode is the primary workflow for interview preparation. You build your professional context and practice with questions before the actual interview.

#### CV Intake

- Upload or paste your CV/resume text
- The system uses AI to extract structured profile data: name, title, skills, achievements, years of experience, education, certifications, and summary
- Extraction mode is explicitly labeled (`real` when using LLM, `demo` or `fallback` when LLM is unavailable)
- Extracted data automatically populates your candidate profile

**Status**: ✅ Fully functional in Tauri canonical UI

#### Candidate Profile

Build and maintain your professional profile with rich fields:
- Name, email, current role, company
- Professional summary
- Skills (structured list)
- Achievements (with quantifiable metrics)
- Education history
- Languages spoken
- Certifications
- LinkedIn profile, portfolio URL
- Raw resume text

**Status**: ✅ 13+ fields, fully functional with persistence

#### Company Context

Describe the target company and role:
- Company name, industry, size, description, values, culture
- Position title, level, department
- Job description, requirements
- Salary range, location, work mode
- Job posting URL, additional notes

**Status**: ✅ 15+ fields, fully functional with persistence

#### Style Selector

Choose your coaching style:

| Style | Description |
|---|---|
| **Executive** | Strategic, concise, metrics-driven responses for leadership roles |
| **Commercial** | Client-focused, relationship and results-oriented responses |
| **Technical** | Detailed, systematic, architecture and implementation-focused responses |
| **Mixed** | Balanced approach combining elements from all styles (default) |

**Status**: ✅ Dedicated component with descriptions

#### Manual Coaching

1. Type or paste an interview question
2. The system analyzes the question (type detection, intent, compound decomposition)
3. Evidence is retrieved from your profile via pgvector semantic search
4. A full response suggestion is generated using your profile, company context, and chosen style
5. The response passes through a quality gate (6 validation checks)
6. The **full response is displayed as the primary artifact**

**Keyboard shortcuts**:
- `Ctrl+Enter` (Windows/Linux) or `Cmd+Enter` (macOS) — Submit question
- `Esc` — Clear input

**Status**: ✅ Fully functional with ~8.4s latency in real mode

### Live Mode

Live mode provides real-time coaching during actual interviews.

#### Session Control

- Start, pause, and end live coaching sessions
- Session maintains conversation state across multiple questions
- Session lifecycle: idle → active → paused → ended

**Keyboard shortcuts**:
- `Space` — Start/Pause session (when session panel focused)

**Status**: ✅ Fully functional

#### Audio Capture

- System audio capture from video conferencing apps (Zoom, Teams, Meet)
- Microphone capture for your own audio
- Built on macOS ScreenCaptureKit
- Real-time forwarding to backend WebSocket

**Status**: ⚠️ Partial — Capture and forwarding work, STT requires Deepgram API key

#### Live Suggestions

- Full-response suggestions generated as questions are detected
- Quality-gated output with confidence scoring
- Staged output: bullets first (for quick reading), then full response

**Status**: ✅ Fully functional via manual text input

#### Conversation Tracker

- Tracks claims, metrics, achievements across the conversation
- Prevents contradictions and repetition
- Maintains context for follow-up questions
- Visible in live transcript panel

**Status**: ✅ Fully functional

#### InterviewContext Persistence

All your context persists across app restarts:
- Candidate profile (all 13+ fields)
- Company context (all 15+ fields)
- Selected style and language
- CV text and AI analysis results
- Session defaults

Use the "Clear Context" button to reset all stored data.

**Status**: ✅ Fully functional via localStorage

---

## Modes

### Real Mode

When API keys and PostgreSQL are properly configured:
- **LLM**: Anthropic Claude Sonnet (default via `llm_main` alias)
- **Embeddings**: OpenAI text-embedding-3-small for semantic evidence retrieval
- **Database**: PostgreSQL 17 + pgvector for profile/achievement storage
- **STT**: Deepgram Nova-3 multilingual (when audio bridge is wired and API key present)

Responses carry explicit `mode: "real"` labels plus provider and model metadata.

### Demo Mode

When external services are unavailable:
- Simulated responses based on pattern-matching and templates
- Always labeled `mode: "demo"` or `mode: "fallback"`
- Never masquerades as real mode
- Useful for testing without API keys or database

---

## Backend Health

The backend health endpoint at `GET http://localhost:8000/health` reports:
- Database connectivity status
- API key availability
- Overall system health (`healthy` or `degraded`)

The Tauri desktop app shows a backend connection indicator and mode badge (Real/Demo).

---

## API Endpoints

| Endpoint | Method | Purpose | Port |
|---|---|---|---|
| `/health` | GET | System health check | 8000 |
| `/api/suggest` | POST | Manual coaching — submit question, get suggestion | 8000 |
| `/api/analyze-cv` | POST | CV text analysis and structured extraction | 8000 |
| `/ws/pipeline` | WebSocket | Real-time live coaching pipeline | 8000 |

---

## Configuration

### Provider Configuration

Provider settings in [`config/providers.yaml`](../config/providers.yaml):

- **STT**: Deepgram Nova-3 multilingual (primary), Whisper local (fallback)
- **LLM**: Anthropic Claude Sonnet (main), Claude Haiku (fast)
- **Embeddings**: OpenAI text-embedding-3-small

Providers are resolved by logical alias — no model IDs in application code.

### Environment Variables

| Variable | Purpose | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API access for LLM generation | Yes (or `OPENAI_API_KEY`) |
| `OPENAI_API_KEY` | OpenAI API access for embeddings and fallback LLM | Yes (or `ANTHROPIC_API_KEY`) |
| `DEEPGRAM_API_KEY` | Deepgram API for speech-to-text | No (only for live audio mode) |
| `POSTGRES_USER` | Database user (default: `interview_coach`) | No |
| `POSTGRES_PASSWORD` | Database password (default: `interview_coach_dev`) | No |
| `POSTGRES_DB` | Database name (default: `interview_coach`) | No |
| `POSTGRES_PORT` | Database port (default: `5432`) | No |
| `EVIDENCE_RETRIEVER_MODE` | Force `real` or `demo` evidence retrieval | No |

---

## Keyboard Shortcuts

### Global Shortcuts

| Shortcut | Action | Context |
|---|---|---|
| `Ctrl/Cmd + Enter` | Submit question | Question input field |
| `Esc` | Clear input / Close modal | Input fields, dialogs |
| `Ctrl/Cmd + S` | Save form | Profile, Company forms |

### Live Mode Shortcuts

| Shortcut | Action | Context |
|---|---|---|
| `Space` | Start/Pause session | Session control panel (when focused) |
| `Ctrl/Cmd + M` | Toggle mute | Audio settings (when implemented) |

---

## Troubleshooting

### Backend Won't Start

1. Verify Python 3.11+: `python3 --version`
2. Install dependencies: `cd python-core && pip install -e .`
3. Check for port conflicts: `lsof -i :8000`
4. Check for missing dependencies: `pip install -e ".[dev]"`

### No Real Mode Responses

1. Check API keys: `echo $ANTHROPIC_API_KEY`
2. Check database: `docker-compose ps` — PostgreSQL should be running
3. Check backend health: `curl http://localhost:8000/health`
4. Check logs for connection errors: `docker logs interview-coach-db`

### Demo Mode When Expecting Real Mode

If the backend reports `mode: "demo"` when you expect `mode: "real"`:
1. Verify API key is set: `echo $ANTHROPIC_API_KEY`
2. Verify PostgreSQL is running: `docker-compose ps`
3. Restart backend after setting keys
4. Check `/health` endpoint for specific component status

### Tauri App Won't Build

1. Verify Rust toolchain: `rustc --version && cargo --version`
2. Verify macOS 12.3+: `sw_vers -productVersion`
3. Verify Xcode CLI tools: `xcode-select -p`
4. Install Tauri dependencies: `cd tauri-app && npm install`
5. Clean and rebuild: `cd tauri-app && rm -rf node_modules && npm install && npm run tauri dev`

### Database Connection Issues

1. Start PostgreSQL: `docker-compose up -d`
2. Check container: `docker logs interview-coach-db`
3. Verify connectivity: `docker exec interview-coach-db pg_isready`
4. Reset database (WARNING: loses all data): `docker-compose down -v && docker-compose up -d`

### Tests Failing

1. Run quick validation: `bash scripts/test_package.sh quick`
2. Run full verification: `bash scripts/verify_package.sh`
3. Check test collection: `python3 -m pytest tests --collect-only -q`
4. Check Python dependencies: `cd python-core && pip install -e ".[dev]"`

### Audio Capture Not Working

1. Grant Screen Recording permission: System Preferences → Security & Privacy → Screen Recording → Add Tauri app
2. Check macOS version: Must be 12.3+ for ScreenCaptureKit
3. Verify Deepgram API key is set for STT: `echo $DEEPGRAM_API_KEY`
4. Use manual text input as fallback in live mode

### Context Lost After Restart

If profile/company data doesn't persist:
1. Check browser DevTools → Application → Local Storage
2. Verify no privacy settings block localStorage
3. Check for JavaScript errors in console
4. Use "Clear Context" and re-enter data to reset

---

## Known Limitations

| Area | Limitation | Workaround |
|---|---|---|
| **STT Integration** | Deepgram STT requires API key and is stubbed without it | Use manual text input in live mode |
| **Audio Capture** | Requires macOS Screen Recording permission | Grant permission in System Preferences |
| **Real Mode** | Requires PostgreSQL + pgvector + LLM API key | Use demo mode for testing, or set up prerequisites |
| **Platform Support** | macOS is Tier 1; Windows/Linux audio paths are stubs | Use macOS for full functionality |
| **Manual Latency** | ~8.4s for full response in real mode | Bullets appear first for quick reading |
| **CI Pipeline** | Tests run locally only — no GitHub Actions CI | Run verification scripts manually |

---

## Version

Interview Coach v1.0.0 — Documentation Version: Final (F7)

---

*For development documentation, see [`DEVELOPER_RUNBOOK.md`](DEVELOPER_RUNBOOK.md)*
