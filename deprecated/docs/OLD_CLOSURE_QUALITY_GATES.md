# Interview Coach — Closure Quality Gates

This document defines the acceptance criteria and quality gates for declaring the Interview Coach product complete.

---

## Phase Completion Status

| Phase | Status | Evidence |
|-------|--------|----------|
| F0: Truth + canonical scope | ✅ Complete | Gap matrix refined, USER_GUIDE.md, DEVELOPER_RUNBOOK.md created |
| F1: Restore product value | ✅ Complete | Tauri UI has CV intake, AI analysis, rich profile, company, style, full-response display |
| F2: InterviewContext persistence | ✅ Complete | localStorage persistence, reloadable after restart |
| F3: Fast manual coaching | ✅ Complete | Direct /api/suggest path with rich context, full response primary |
| F4: Real mode | ✅ Complete | Auto mode detection, real pgvector + LLM + CV analysis, demo as explicit fallback |
| F5: Live usefulness | ✅ Complete | Session lifecycle, tracker integration, manual fallback in live mode |
| F6: Audio real | ⚠️ Partial | Capture wired, forwarding to WebSocket, STT stubbed |
| F7: Operations closure | ✅ Complete | This document, final docs, verified package |

---

## Functional Gates

### F0 Gates — Truth + Canonical Scope

- [x] Architecture frozen at v3.2.1
- [x] Product decisions documented (Tauri canonical, full responses primary, bullets secondary)
- [x] Gap matrix created with closure sequence F0-F7
- [x] Truth labels defined (functional, demo, partial, stub, deprecated)

### F1 Gates — Restore Product Value

- [x] Tauri is the canonical UI (Next.js is preview only)
- [x] CV intake and AI analysis work end-to-end
- [x] Candidate profile has 13+ fields
- [x] Company info has 15+ fields
- [x] Style selector with 4 built-in styles (Executive, Commercial, Technical, Mixed)
- [x] Full response is primary visible artifact in coaching
- [x] Modality selector (manual vs live) functional

### F2 Gates — InterviewContext Persistence

- [x] Candidate profile persists across restarts
- [x] Company info persists across restarts
- [x] Style and language persist across restarts
- [x] CV text and analysis persist across restarts
- [x] Clear Context function works
- [x] localStorage implementation verified

### F3 Gates — Fast Manual Coaching

- [x] Manual suggest uses direct pipeline (not realtime)
- [x] Rich context sent to backend (profile + company + style)
- [x] Response prioritizes full_response over bullets
- [x] Latency ~8.4s in real mode (acceptable for v1.0)
- [x] Mode labels explicit (real/demo/fallback)

### F4 Gates — Real Mode

- [x] Backend auto-detects real vs demo mode
- [x] /health endpoint reports truthful mode
- [x] Real mode uses actual LLM and pgvector
- [x] Demo mode explicitly labeled in all responses
- [x] Frontend shows mode indicator clearly
- [x] Graceful degradation when services unavailable

### F5 Gates — Live Usefulness

- [x] Session lifecycle (idle → active → paused → ended)
- [x] Conversation tracker tracks questions
- [x] Full response visible in live mode
- [x] Manual text input works in live mode
- [x] Staged emission (bullets first, then full)
- [x] Multi-turn context maintained

### F6 Gates — Audio Real

- [x] ScreenCaptureKit capture implemented in Rust
- [x] Audio data emits Tauri events
- [x] Frontend forwards audio to backend WebSocket
- [x] Permission handling on macOS
- [ ] STT adapter fully integrated (stubbed, needs Deepgram API key)

**Note**: F6 is intentionally partial for v1.0. The audio capture and forwarding infrastructure is in place, but end-to-end STT requires a Deepgram API key which is optional. Manual text input provides full functionality.

### F7 Gates — Operations Closure

- [x] USER_GUIDE.md finalized
- [x] DEVELOPER_RUNBOOK.md finalized
- [x] CLOSURE_QUALITY_GATES.md created
- [x] README.md updated
- [x] status.json updated with truthful component statuses
- [x] verify_package.sh runs without errors
- [x] test_package.sh runs without errors

---

## Verification Commands

Run these to verify the product:

```bash
# Backend syntax check
cd python-core && python3 -m py_compile api/server.py

# Frontend build
cd tauri-app && npm install && npm run build

# Rust check
cd tauri-app/src-tauri && cargo check

# Test collection
python3 -m pytest tests --collect-only -q

# Unit tests
bash scripts/test_package.sh quick

# Smoke tests
bash scripts/test_package.sh smoke

# Full verification
bash scripts/verify_package.sh

# Environment doctor
bash scripts/doctor_macos.sh
```

---

## Component Status Summary

| Component | Status | Notes |
|-----------|--------|-------|
| Tauri UI | ✅ functional | Canonical UI with all F1 features |
| Next.js UI | ✅ functional | Preview only — not shipped |
| Python Backend | ✅ functional | Real mode with explicit demo fallback |
| Pipeline steps | ✅ functional | 8/10 steps implemented |
| Audio capture | ⚠️ partial | Capture + forwarding work, STT stubbed |
| InterviewContext persistence | ✅ functional | localStorage implementation |
| Real mode | ✅ functional | When prerequisites met |
| Demo mode | ✅ functional | Explicit fallback |
| Quality gate | ✅ functional | Draft→Validate→Repair→Expose |
| Conversation tracker | ✅ functional | Prevents contradictions |
| Tests | ✅ functional | 217+ collected, 78+ unit passing |

---

## Known Limitations (Acceptable for v1.0)

1. **STT requires Deepgram API key** and is stubbed without it. Manual text input is the fallback.
2. **Audio capture requires macOS Screen Recording permission**. System prompts for this on first use.
3. **Real mode requires PostgreSQL + pgvector + LLM API key**. Demo mode works without these.
4. **Windows/Linux audio capture paths** are stubs only. macOS is Tier 1 target for v1.0.
5. **Manual coaching latency** is ~8.4s in real mode. Bullets-first display mitigates this.
6. **CI pipeline** runs locally only. GitHub Actions not configured for v1.0.

---

## Release Criteria

The product is releasable when:

- [x] All F0-F5 gates pass ✅
- [x] F6 has functional capture and forwarding (STT is known limitation)
- [x] F7 documentation is complete ✅
- [x] verify_package.sh runs without errors ✅
- [x] test_package.sh smoke passes ✅
- [x] status.json reflects truthful component states ✅

---

## Quality Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Unit tests passing | 75+ | 78+ |
| Test collection | Clean | 217+ collected |
| Backend syntax | Clean | ✅ Pass |
| Frontend build | Clean | ✅ Pass |
| Rust check | Clean | ✅ Pass |
| Documentation | Complete | ✅ All docs finalized |

---

## Version

Interview Coach v1.0.0 — Closure Date: 2026-03-14

---

*See also: [`CLOSURE_GAP_MATRIX.md`](CLOSURE_GAP_MATRIX.md) for gap analysis and closure sequence.*
