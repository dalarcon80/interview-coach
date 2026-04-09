# Interview Coach — Canonical Execution Pack

**Version**: 1.0.0  
**Frozen Date**: 2026-03-15  
**Source of Truth**: This document supersedes all prior execution plans  
**Status**: ACTIVE — This is the only canonical control plane

---

## Purpose

This pack resolves truth conflicts in the repository and provides one canonical execution path from the current real state to a truly functional live interview coach product. It is not a redesign. It is a consolidation and ordering of the actual work required.

---

# Section 1: MASTER_EXECUTION_PLAN

## 1.1 Frozen Rules (Non-Negotiable)

| # | Rule | Violation Consequence |
|---|------|----------------------|
| FZ-01 | Tauri is the ONLY shipped UI | Next.js is preview/dev only, never the product |
| FZ-02 | Full responses are PRIMARY visible artifact | Bullets are secondary/support only |
| FZ-03 | No provider switching | Deepgram STT, Anthropic/OpenAI LLM frozen |
| FZ-04 | PostgreSQL + pgvector only | No SQLite, no Prisma, no ChromaDB in core path |
| FZ-05 | Architecture is frozen at v3.2.1 | No changes without explicit written approval |
| FZ-06 | Truth labels only: functional, partial, demo, stub | No "complete" without evidence |
| FZ-07 | One task at a time | No parallel implementation, no phase skipping |
| FZ-08 | No doc churn outside P0 and P7 | Docs serve implementation, not replace it |

## 1.2 Real Starting State (Truth Reconciliation)

**What Actually Works (Verified)**:
- Backend FastAPI/WebSocket: functional — real mode when API keys present
- Pipeline 8/10 steps: functional — LanguagePolicy, QuestionAnalyzer, RetrievalPlanner, EvidenceRetriever, ResponseComposer, QualityGate, TurnAssembler
- STT adapter Deepgram: partial — exists, qualified runs show Nova-3 `/v1/listen` path works
- Conversation tracker: functional
- InterviewContext persistence: functional — localStorage implementation
- macOS audio capture: partial — ScreenCaptureKit + normalization + WebSocket forwarding exists
- Speaker fallback correction: functional — recent backend progress preserved
- L3-TURN-02 interviewer turn assembly: functional — recent backend progress preserved

**What is Actually Broken/Partial**:
- Desktop-to-STT bridge: partial — audio forwards to backend, but STT lifecycle needs hardening
- Audio ingestion E2E: partial — Rust capture → WebSocket → STT chain exists but timing/gating issues
- Live response usefulness: partial — pipeline works but bullets-first UX conflicts with full-response-primary requirement
- Session persistence: partial — SessionRepository exists but not wired to WS handler
- Real end-to-end latency: unverified — no evidence of acceptable live interview latency

**Critical Truth Conflicts Resolved**:
- status.json overstates readiness (claims F0-F5, F7 "complete")
- Gap matrix accurately describes gaps but dates to March 13
- Live STT evidence shows qualified real-provider runs but also failures
- Prior docs emphasize bullets-first; frozen handoff requires full-response-primary

**Resolution**: Full response is PRIMARY UX artifact. Bullets are internal optimization ONLY.

## 1.3 Explicitly Out of Scope

| Item | Reason |
|------|--------|
| Windows/Linux audio capture | Stub only, target v1.5 |
| CI/CD pipeline (.github/workflows) | Local verification only for this closure |
| New provider integrations | Frozen per FZ-03 |
| Mobile app | Not in frozen architecture |
| Cloud deployment | Desktop-first product |
| New AI models | Use existing aliases only |
| Feature expansion beyond live coaching | Scope locked |

## 1.4 Phases in Execution Order

### P0: Truth Reconciliation (Foundation)
**Objective**: Establish truthful baseline before any implementation work.

**Tasks**:
- P0-T0: Audit and correct config/status.json to match verifiable reality
- P0-T1: Update README.md to remove inflated claims
- P0-T2: Archive stale execution plans, establish this pack as canonical
- P0-T3: Verify package health commands actually pass

**Gate**: GL0 — All verification commands pass, status reflects truth

**Approval Review**:
- Files: config/status.json, README.md
- Evidence: Command outputs captured
- Blocker: Any claim without verification proof

---

### P1: Desktop Audio Bridge Real
**Objective**: System audio from desktop (meeting apps) reliably reaches backend WebSocket. Microphone is secondary/optional.

**Tasks**:
- P1-T1: Validate canonical desktop system-audio capture (ScreenCaptureKit)
- P1-T2: Route system-audio frames through canonical AudioFrame emitter to backend
- P1-T3: Prove system-audio → backend produces stable STT chunks
- (Optional later): Microphone capture as secondary/optional path

**Gate**: GL1 — Audio ingestion E2E

**Approval Review**:
- Evidence: System audio from desktop visible in backend logs
- Test: 30-second system audio capture session completes without drops

---

### P2: STT Real End-to-End on Desktop Path
**Objective**: Captured audio produces real transcripts through Deepgram Nova-3.

**Tasks**:
- P2-T1: Harden STT adapter lifecycle (open/close per session)
- P2-T2: Fix timing/cadence issues causing Deepgram net0001 timeout
- P2-T3: Implement transcript-to-pipeline handoff with correlation logging

**Gate**: GL2 — STT real

**Approval Review**:
- Evidence: Real transcript from captured audio in under 3 seconds
- Test: 10 consecutive sessions produce transcripts without STT errors

---

### P3: Speaker + Turn Intelligence
**Objective**: Reliable interviewer/user speaker detection and turn assembly.

**Tasks**:
- P3-T1: Integrate speaker fallback correction into live path
- P3-T2: Harden L3-TURN-02 interviewer turn assembly
- P3-T3: Implement turn boundary detection (pause-based + STT utterance end)

**Gate**: GL3 — Speaker/turn

**Approval Review**:
- Evidence: 90%+ accurate speaker labeling in test scenarios
- Test: Multi-turn conversation maintains speaker identity

---

### P4: Live Response Usefulness
**Objective**: Full responses are primary UX; bullets are secondary optimization.

**Tasks**:
- P4-T1: Refactor Emitter to prioritize full_response in UI events
- P4-T2: Implement staged display (bullets preview, full response primary)
- P4-T3: Harden conversation tracker continuity across live turns
- P4-T4: Wire SessionRepository for persistence

**Gate**: GL4 — Live response

**Approval Review**:
- Evidence: Full response visible within 10 seconds of turn end
- Test: Multi-turn session maintains context, no contradictions

---

### P5: End-to-End Latency
**Objective**: Achieve acceptable latency for live interview use.

**Tasks**:
- P5-T1: Instrument full pipeline latency (audio → transcript → suggestion)
- P5-T2: Optimize critical path (likely QuestionAnalyzer + RetrievalPlanner)
- P5-T3: Implement fast-path for simple factual questions

**Gate**: GL5 — Latency acceptance

**Approval Review**:
- Evidence: P95 latency under 8 seconds for bullets preview
- Evidence: P95 latency under 15 seconds for full response
- Test: Real-time interview simulation feels usable

---

### P6: Persistence and Replay
**Objective**: Sessions survive restart; replay for review.

**Tasks**:
- P6-T1: Wire PersistQueue for async session writes
- P6-T2: Implement session list/history UI in Tauri
- P6-T3: Implement session replay (view past coaching)

**Gate**: GL6 — Persistence/replay

**Approval Review**:
- Evidence: Session persists to PostgreSQL
- Evidence: Session reloads after app restart
- Test: Full session replay from history

---

### P7: Final Hardening and Truthful Closure
**Objective**: Package is release-ready with honest documentation.

**Tasks**:
- P7-T1: Finalize USER_GUIDE.md with actual capabilities
- P7-T2: Finalize DEVELOPER_RUNBOOK.md with verification steps
- P7-T3: Update SUPPORT_MATRIX.md with truthful platform status
- P7-T4: Final status.json with verified component states
- P7-T5: Final package verification across all gates

**Gate**: GL7 — Final release

**Approval Review**:
- Evidence: All gates GL0-GL6 pass
- Evidence: Documentation matches actual product
- Decision: Go / No-Go for v1.0.0 release

---

## 1.5 Simplified Execution Order (R1-R7)

```
R1: Product truth alignment (CURRENT)
    ↓
R2: Runtime LLM/STT provider configuration
    ↓
R3: Manual mode with real providers
    ↓
R4: Desktop system audio capture
    ↓
R5: Real STT on desktop path
    ↓
R6: Speaker/turn detection
    ↓
R7: Live response usefulness
```

### R1: Product truth alignment (CURRENT)
**Objective**: Ensure all authoritative files consistently express correct product truth.

**Key Truths**:
- System audio from meeting apps is the PRIMARY live input
- Microphone capture is SECONDARY/OPTIONAL
- full_response is the PRIMARY visible artifact
- bullets are preview/support only

**Gate**: GN0 — Control-plane alignment verified

---

# Section 2: TASK_CARDS

## 2.1 Standard Task Card Template

```markdown
### Task ID: {PHASE}-{NUMBER}

**Context**: {What exists, what was just completed, what this builds on}

**Goal**: {Single concrete outcome}

**Strict Scope**:
- IN: {Explicitly included}
- OUT: {Explicitly excluded}

**Acceptance Criteria**:
1. {Criterion with evidence}
2. {Criterion with evidence}
3. {Criterion with evidence}

**Deliverable Format**:
- Files changed: {list}
- Commands to verify: {list}
- Evidence to capture: {what to log}

**Next-Task Rule**: {Condition for proceeding to next task}
```

---

## 2.2 Instantiated Task Cards

---

### Task ID: P0-T0

**Context**: status.json claims F0-F5, F7 "complete" and F6 "partial", but verification against actual code shows gaps in audio bridge, STT lifecycle, and UI parity. This task establishes truth before any implementation.

**Goal**: Correct config/status.json to reflect verifiable reality using only functional/partial/demo/stub labels.

**Strict Scope**:
- IN: Status file corrections, README.md alignment, evidence capture
- OUT: No code changes, no new features

**Acceptance Criteria**:
1. status.json "current_phase" reflects actual blocker (P0, not F7)
2. All component_status entries use truth labels only (functional/partial/demo/stub)
3. runtime_state reflects actual verified state, not aspirational state
4. known_gaps includes audio bridge, STT lifecycle, latency verification
5. phase_status P0-P7 updated to match this execution pack

**Deliverable Format**:
- Files changed: config/status.json, README.md
- Commands to verify: bash scripts/verify_package.sh
- Evidence to capture: Command outputs, before/after status diff

**Next-Task Rule**: Proceed to P0-T1 when status.json is truthful and verify_package.sh passes.

---

### Task ID: P0-T1

**Context**: README.md contains closure claims that overstate readiness (e.g., "F0-F7 Complete", "Product is release-ready"). Must align with truthful status.

**Goal**: Update README.md to remove inflated claims and accurately describe current capabilities and limitations.

**Strict Scope**:
- IN: README.md edits only, honest labeling of partial features
- OUT: No architecture changes, no feature additions

**Acceptance Criteria**:
1. "Closure Status" table removed or marked as "In Progress"
2. "Package Status Summary" uses truth labels consistently
3. macOS Audio Capture section clearly states "partial — STT bridge incomplete"
4. No "release-ready" or "v1.0.0" claims without all gates passing
5. Version changed to reflect pre-release state (e.g., v0.9.0-rc)

**Deliverable Format**:
- Files changed: README.md
- Commands to verify: Manual review
- Evidence to capture: Diff showing removed claims

**Next-Task Rule**: Proceed to P0-T2 when README.md is truthful.

---

### Task ID: P0-T2

**Context**: Multiple execution plans existed (execution_plan.yaml, handoff plans, this pack). Need single canonical source.

**Goal**: Establish this pack as the only active control plane.

**Strict Scope**:
- IN: Verify stale plans archived, add CANONICAL marker to this pack
- OUT: No changes to implementation code

**Acceptance Criteria**:
1. config/execution_plan.yaml does not exist — already removed from repo
2. handoff/ plans clearly marked as reference only, not active
3. This pack (plans/CANONICAL_EXECUTION_PACK.md) contains ACTIVE marker
4. AGENTS.md updated to reference this pack as source of truth

**Deliverable Format**:
- Files changed: N/A — execution_plan.yaml already removed
- Commands to verify: ls -la config/, ls -la plans/
- Evidence to capture: Directory listing showing no execution_plan.yaml

**Status**: COMPLETE — execution_plan.yaml removed during N0 normalization.

---

### Task ID: P0-T3

**Context**: Package health claims must be verifiable. Need baseline confirmation before implementation work.

**Goal**: Run all verification commands and capture truthful results.

**Strict Scope**:
- IN: Command execution, output capture, status documentation
- OUT: No code fixes (document failures for P1)

**Acceptance Criteria**:
1. bash scripts/test_package.sh quick — output captured
2. bash scripts/test_package.sh smoke — output captured
3. bash scripts/verify_package.sh — output captured
4. python -m pytest tests --collect-only -q — count verified
5. All results logged to worklog.md with timestamps

**Deliverable Format**:
- Files changed: worklog.md (or similar evidence log)
- Commands to verify: Re-run any failed command
- Evidence to capture: Complete command outputs

**Next-Task Rule**: Proceed to P1-T1 when baseline established (failures documented, not necessarily fixed).

---

### Task ID: P1-T1

**Context**: Real system audio capture exists in the Rust macos_capture module (ScreenCaptureKit) but is not validated end-to-end through the canonical desktop path. Microphone is secondary/optional.

**Goal**: Validate canonical desktop system-audio capture (primary) and confirm readiness for backend routing.

**Strict Scope**:
- IN: macos_capture module (system audio), Tauri commands.rs integration
- OUT: STT integration (P2), microphone path (later optional phase)

**Acceptance Criteria**:
1. `start_audio_capture` Tauri command invokes real ScreenCaptureKit system-audio stream
2. System audio from meeting apps (e.g., Zoom, Teams) captured successfully
3. Permission dialog appears on first call (or permission already granted)
4. Audio frames are produced when capture is active
5. Error states (permission denied, device unavailable) are handled gracefully

**Deliverable Format**:
- Files changed: tauri-app/src-tauri/src/commands.rs, tauri-app/src-tauri/src/audio/macos_capture.rs
- Commands to verify: Manual system audio capture from desktop app
- Evidence to capture: Permission dialog appears OR system audio frames logged

**Next-Task Rule**: Proceed to P1-T2 when real system-audio capture triggers on Tauri command invocation.

---

### Task ID: P1-T2

**Context**: Real system-audio frames need to reach the Python backend via WebSocket. Microphone is secondary/optional.

**Goal**: Route system-audio frames through canonical AudioFrame emitter to backend.

**Strict Scope**:
- IN: AudioFrame router, Tauri event emission, frontend WebSocket, backend WebSocket handler
- OUT: STT processing (P2), transcript handling

**Acceptance Criteria**:
1. AudioFrame Router emits PCM16 chunks at correct cadence from real system audio
2. Tauri event carries audio data to frontend WebSocket
3. Frontend forwards to backend without corruption
4. Backend receives audio_data events with correct payload
5. Correlation ID (session_id) consistent across chain

**Deliverable Format**:
- Files changed: tauri-app/src-tauri/src/audio/router.rs, tauri-app/src/App.tsx, python-core/api/server.py
- Commands to verify: Backend log inspection during live session
- Evidence to capture: Session trace showing end-to-end audio flow

**Next-Task Rule**: Proceed to P1-T3 when system audio reliably reaches backend.

---

### Task ID: P1-T3

**Context**: Real system audio is now reaching the backend. Need to prove end-to-end STT works on the canonical desktop path. Microphone is secondary/optional.

**Goal**: Prove system-audio → backend produces stable STT chunks.

**Strict Scope**:
- IN: End-to-end audio path, Deepgram STT integration, transcript handling
- OUT: Speaker/turn intelligence (P3), response generation

**Acceptance Criteria**:
1. Real speech from system audio (meeting app) produces partial transcript
2. Real speech produces final transcript with <3s latency
3. Utterance boundaries are usable
4. Path is the canonical desktop path (not synthetic/test audio)

**Deliverable Format**:
- Files changed: Any fixes needed in audio path or STT integration
- Commands to verify: Live session with real system audio
- Evidence to capture: Transcript output from real system audio input

**Next-Task Rule**: Proceed to P2-T1 when stable STT is demonstrated.

---

### Task ID: P2-T1

**Context**: Deepgram STT adapter exists but lifecycle (per-session open/close) needs hardening to prevent resource leaks and timing issues.

**Goal**: Harden STT adapter lifecycle: open on session start, close on session end, handle errors gracefully.

**Strict Scope**:
- IN: python-core/adapters/stt_adapter.py, WebSocket handler STT integration
- OUT: Audio capture changes (P1), transcript processing (P2-T3)

**Acceptance Criteria**:
1. STT stream opens on start_session with correlation logging
2. STT stream closes on end_session with duration metrics
3. Provider errors (net0001, auth failures) handled without crashing
4. Session isolation — no cross-session audio contamination
5. Memory leak check — multiple start/end cycles stable

**Deliverable Format**:
- Files changed: python-core/adapters/stt_adapter.py, python-core/api/server.py (WS handler)
- Commands to verify: python scripts/validate_live_stt_runtime.py
- Evidence to capture: STT lifecycle logs, memory usage

**Next-Task Rule**: Proceed to P2-T2 when lifecycle is robust.

---

### Task ID: P2-T2

**Context**: Deepgram returns net0001 timeout errors — indicates timing/cadence issues with audio stream.

**Goal**: Fix timing/cadence to prevent Deepgram timeout (net0001) errors.

**Strict Scope**:
- IN: Audio chunk timing, WebSocket send cadence, STT adapter buffering
- OUT: Audio capture (P1), transcript processing (P2-T3)

**Acceptance Criteria**:
1. Audio chunks sent at 100ms intervals (not bursty)
2. Initial chunk sent within 500ms of stream open
3. No gaps longer than 200ms during active capture
4. Deepgram net0001 errors eliminated in test runs
5. First partial transcript received within 2 seconds of speech

**Deliverable Format**:
- Files changed: Audio forwarding chain, STT adapter buffering
- Commands to verify: scripts/validate_live_stt_runtime.py
- Evidence to capture: Timing logs, error rate metrics

**Next-Task Rule**: Proceed to P2-T3 when net0001 errors eliminated.

---

### Task ID: P2-T3

**Context**: Transcripts arrive from STT but need reliable handoff to pipeline with correlation tracking.

**Goal**: Implement transcript-to-pipeline handoff with correlation logging.

**Strict Scope**:
- IN: WebSocket handler transcript event, pipeline process_question call
- OUT: STT adapter (P2-T1/T2), pipeline steps (P4)

**Acceptance Criteria**:
1. Transcript from STT triggers pipeline within 100ms
2. Correlation chain: session_id → request_id → transcript_id logged
3. Event sequence logged: transcript → analysis → suggestion
4. STT errors short-circuit pipeline gracefully (no processing)
5. Transcript metadata (language, speaker) preserved through chain

**Deliverable Format**:
- Files changed: python-core/api/server.py (WS handler)
- Commands to verify: Integration test with real STT
- Evidence to capture: Correlation trace logs

**Next-Task Rule**: Proceed to P3-T1 when transcript reliably triggers pipeline.

---

### Task ID: P3-T1

**Context**: Speaker fallback correction exists in backend but needs integration into live path.

**Goal**: Integrate speaker fallback correction into live WebSocket path.

**Strict Scope**:
- IN: Speaker detection logic, WebSocket transcript handling
- OUT: Audio capture, STT adapter, turn assembly

**Acceptance Criteria**:
1. Unknown speaker transcripts trigger fallback correction
2. Interviewer/user labels applied with confidence score
3. Fallback decisions logged for debugging
4. No blocking on speaker detection (async with default)

**Deliverable Format**:
- Files changed: python-core/api/server.py, speaker detection modules
- Commands to verify: Test with ambiguous speaker audio
- Evidence to capture: Speaker labeling accuracy logs

**Next-Task Rule**: Proceed to P3-T2 when speaker fallback integrated.

---

# Section 3: QUALITY_GATES

## GL0: Truth Gate (P0 Completion)

**Pass Criteria**:
- status.json uses only truth labels (functional/partial/demo/stub)
- No component marked "functional" without verification evidence
- README.md contains no inflated claims
- Single canonical execution plan established

**Evidence Required**:
- status.json diff showing corrections
- README.md diff showing removed claims
- File listing showing archived stale plans

**False Positives** (must NOT count):
- Status claims without command output evidence
- "Complete" labels on partial implementations
- Assertions that "code exists" equals "functional"

**Go/No-Go Rule**: GO when all documentation truthfully describes verifiable state.

---

## GL1: Audio Ingestion E2E (P1 Completion)

**Pass Criteria**:
- macOS capture permission UX guides user through grant/deny
- Audio frames from ScreenCaptureKit reach backend WebSocket
- Capture lifecycle (start/stop/pause) works without crashes
- 30-second capture session completes with <1% frame loss

**Evidence Required**:
- Backend logs showing audio_data events
- Session correlation trace (Rust → Tauri → WebSocket)
- Manual test log: 10 start/stop cycles without error

**False Positives** (must NOT count):
- Capture code exists but untested end-to-end
- Audio "works" in isolation but not through full chain
- Manual audio file playback instead of live capture

**Go/No-Go Rule**: GO when live captured audio reliably reaches backend.

---

## GL2: STT Real (P2 Completion)

**Pass Criteria**:
- Deepgram Nova-3 produces real transcripts from captured audio
- First partial transcript within 2 seconds of speech
- No net0001 timeout errors in 10 consecutive sessions
- STT lifecycle (open/close) without resource leaks

**Evidence Required**:
- validate_live_stt_runtime.py output showing real transcripts
- Latency metrics: first_partial, first_final
- Memory profile: stable across multiple sessions

**False Positives** (must NOT count):
- STT works with pre-recorded files but not live
- Occasional success with frequent failures
- Mock/fallback STT labeled as real

**Go/No-Go Rule**: GO when real STT works reliably from live capture.

---

## GL3: Speaker/Turn (P3 Completion)

**Pass Criteria**:
- 90%+ speaker labeling accuracy (interviewer vs user)
- Turn boundaries detected correctly (utterance end)
- Multi-turn conversation maintains speaker identity
- Fallback correction works for ambiguous cases

**Evidence Required**:
- Speaker accuracy test results
- Turn boundary detection logs
- Multi-turn session trace showing correct attribution

**False Positives** (must NOT count):
- Speaker detection works on clean test audio only
- Manual speaker assignment as "automation"
- Single-turn accuracy claimed as multi-turn success

**Go/No-Go Rule**: GO when speaker/turn detection works in realistic scenarios.

---

## GL4: Live Response (P4 Completion)

**Pass Criteria**:
- Full response is primary visible artifact in UI
- Bullets appear as secondary preview only
- Conversation tracker maintains context across turns
- No contradictions or repetition in follow-up responses

**Evidence Required**:
- UI screenshot showing full response primary
- Multi-turn session showing tracker continuity
- Contradiction detection log (should be empty)

**False Positives** (must NOT count):
- Full response exists but bullets are primary UX
- Tracker works for 2 turns but fails at 3+
- Manual verification only, no automated check

**Go/No-Go Rule**: GO when live responses are useful and continuous.

---

## GL5: Latency Acceptance (P5 Completion)

**Pass Criteria**:
- P95 bullets preview latency: <8 seconds
- P95 full response latency: <15 seconds
- Latency instrumentation in all pipeline steps
- Real interview simulation feels "responsive enough"

**Evidence Required**:
- Latency histogram from 50+ test sessions
- Per-step latency breakdown
- User experience test (subjective but documented)

**False Positives** (must NOT count):
- Best-case latency only (no P95)
- Local test without network/stt overhead
- "Feels fast" without measurement

**Go/No-Go Rule**: GO when latency is measured and acceptable for live use.

---

## GL6: Persistence/Replay (P6 Completion)

**Pass Criteria**:
- Sessions persist to PostgreSQL via SessionRepository
- Session history visible in Tauri UI
- Session replay shows full conversation
- Persistence survives app restart

**Evidence Required**:
- Database query showing stored sessions
- UI screenshot of session history
- Replay trace matching original session

**False Positives** (must NOT count):
- In-memory session storage
- Session list without full replay
- Partial persistence (metadata only, no content)

**Go/No-Go Rule**: GO when sessions are fully persistent and replayable.

---

## GL7: Final Release Gate (P7 Completion)

**Pass Criteria**:
- All gates GL0-GL6 pass
- Documentation matches actual product capabilities
- Package verification scripts pass
- No known critical bugs

**Evidence Required**:
- Gate completion checklist (all GL0-GL6)
- Documentation review sign-off
- verify_package.sh output
- Known issues list (should be minor only)

**False Positives** (must NOT count):
- Documentation written before implementation
- Gates "mostly" pass with exceptions
- Known critical workarounds documented as "acceptable"

**Go/No-Go Rule**: GO for v1.0.0 release when all criteria met with evidence.

---

# Section 4: STATUS_TRUTH_MODEL

## 4.1 Versioning Recommendation

**Current**: v0.9.0-rc  
**Target**: v1.0.0 (after GL7)  
**Schema**: semver with rc (release candidate) for pre-release phases

## 4.2 Current Phase Recommendation

**Truth**: P0 (Truth Reconciliation)  
**Rationale**: Status inflation and documentation conflicts must be resolved before implementation work proceeds with clarity.

## 4.3 Runtime State Schema

```json
{
  "runtime_state": {
    "backend_functional": "boolean — API responds, basic endpoints work",
    "database_connected": "boolean — PostgreSQL connected and queryable",
    "api_keys_configured": "boolean — At least one LLM provider key present",
    "audio_capture_functional": "boolean — Rust capture emits audio_frames",
    "audio_bridge_functional": "boolean — Audio reaches backend WebSocket",
    "stt_functional": "boolean — Real STT produces transcripts",
    "live_pipeline_functional": "boolean — Audio → STT → pipeline → response E2E",
    "interview_context_persistence_functional": "boolean — localStorage persistence works",
    "session_persistence_functional": "boolean — SessionRepository wired and working",
    "latency_acceptable": "boolean — Meets P95 targets",
    "quality_gates_passed": ["array of GL IDs that have passed"]
  }
}
```

## 4.4 Recommended Current Values

Based on verification against code and evidence:

```json
{
  "runtime_state": {
    "backend_functional": true,
    "database_connected": "conditional — true when Docker PostgreSQL running",
    "api_keys_configured": "conditional — true when ANTHROPIC_API_KEY or OPENAI_API_KEY set",
    "audio_capture_functional": true,
    "audio_bridge_functional": false,
    "stt_functional": "partial — Nova-3 /v1/listen works in qualified runs but net0001 errors persist",
    "live_pipeline_functional": false,
    "interview_context_persistence_functional": true,
    "session_persistence_functional": false,
    "latency_acceptable": "unverified — no measurement evidence",
    "quality_gates_passed": ["GL0 pending — truth reconciliation in progress"]
  }
}
```

## 4.5 Component Status Truth Labels

| Component | Truth Label | Evidence |
|-----------|-------------|----------|
| Backend API | functional | Health, suggest, analyze-cv endpoints work |
| Pipeline steps | functional | 8/10 implemented, process questions |
| STT adapter | partial | Nova-3 works, lifecycle issues remain |
| Audio capture | functional | ScreenCaptureKit emits frames |
| Audio bridge | partial | Forwarding exists, timing issues |
| Desktop UI (Tauri) | functional | All F1 features present |
| InterviewContext persistence | functional | localStorage implementation |
| Session persistence | stub | Repository exists, not wired |
| Conversation tracker | functional | Claims/metrics tracking works |
| Quality gate | functional | Draft/validate/repair/expose works |

## 4.6 Direct Rewrite for config/status.json

See P0-T0 for full status.json rewrite. Key changes:
- version: "0.9.0-rc"
- current_phase: "P0"
- phase_status: Align with P0-P7 from this pack
- runtime_state: Use 4.4 values above
- component_status: Use 4.5 labels
- Remove all "complete" claims for incomplete phases

---

# Section 5: PHASE_REVIEW_CHECKLIST

## P0: Truth Reconciliation

**What Must Be Reviewed**:
- [ ] status.json truth labels accurate
- [ ] README.md claims supported by evidence
- [ ] Single canonical plan established
- [ ] Package verification commands pass

**Evidence Required**:
- status.json diff
- README.md diff
- Command output logs (verify_package.sh, test_package.sh)

**Blocks Approval**:
- Any claim without verification evidence
- Multiple active execution plans
- Status inconsistent with code

**Go/No-Go Decider**: Architect review of documentation truth

**If Partial**: Document specific gaps, proceed to P1 with known issues listed

**Kilo Forbidden**:
- Starting implementation before P0 complete
- Creating new docs instead of fixing existing
- Making code changes to "fix" doc conflicts

---

## P1: Desktop Audio Bridge Real

**What Must Be Reviewed**:
- [ ] Permission UX handles grant/deny
- [ ] Audio reaches backend WebSocket
- [ ] Capture lifecycle works
- [ ] No crashes or memory leaks

**Evidence Required**:
- Manual test log (10 cycles)
- Backend audio_data event logs
- Session correlation traces

**Blocks Approval**:
- Audio not reaching backend
- Permission UX missing or broken
- Memory leaks detected

**Go/No-Go Decider**: GL1 evidence review

**If Partial**: Document specific failure modes, do not proceed to P2

**Kilo Forbidden**:
- Skipping to STT integration if bridge incomplete
- Implementing other platforms
- Adding features to capture (effects, filtering)

---

## P2: STT Real End-to-End

**What Must Be Reviewed**:
- [ ] Real transcripts from live audio
- [ ] No net0001 errors
- [ ] Latency under 2s for first partial
- [ ] Lifecycle without leaks

**Evidence Required**:
- validate_live_stt_runtime.py output
- Latency metrics
- Memory profile

**Blocks Approval**:
- net0001 errors persist
- >50% STT failure rate
- Resource leaks

**Go/No-Go Decider**: GL2 evidence review

**If Partial**: Debug specific STT issues, do not proceed to P3

**Kilo Forbidden**:
- Proceeding with mock/fallback STT
- Ignoring net0001 errors
- Adding new STT providers

---

## P3: Speaker + Turn Intelligence

**What Must Be Reviewed**:
- [ ] Speaker labeling 90%+ accurate
- [ ] Turn boundaries detected
- [ ] Multi-turn continuity

**Evidence Required**:
- Speaker accuracy test
- Turn boundary logs
- Multi-turn session trace

**Blocks Approval**:
- <90% speaker accuracy
- Turn detection missing
- Multi-turn failures

**Go/No-Go Decider**: GL3 evidence review

**If Partial**: Improve speaker/turn detection, do not proceed to P4

**Kilo Forbidden**:
- Proceeding without speaker detection
- Manual speaker assignment as "automation"

---

## P4: Live Response Usefulness

**What Must Be Reviewed**:
- [ ] Full response primary in UI
- [ ] Tracker continuity across turns
- [ ] No contradictions

**Evidence Required**:
- UI screenshots
- Multi-turn session logs
- Contradiction detection results

**Blocks Approval**:
- Bullets still primary
- Tracker loses context
- Contradictions present

**Go/No-Go Decider**: GL4 evidence review

**If Partial**: Fix UX or tracker, do not proceed to P5

**Kilo Forbidden**:
- Keeping bullets-first UX
- Skipping tracker hardening

---

## P5: End-to-End Latency

**What Must Be Reviewed**:
- [ ] P95 latency measured
- [ ] Targets met (bullets <8s, full <15s)
- [ ] Per-step instrumentation

**Evidence Required**:
- Latency histogram
- Per-step breakdown
- UX test feedback

**Blocks Approval**:
- P95 bullets >8s
- P95 full >15s
- No measurement

**Go/No-Go Decider**: GL5 evidence review

**If Partial**: Optimize slow steps, do not proceed to P6

**Kilo Forbidden**:
- "Feels fast" without measurement
- Accepting latency regression

---

## P6: Persistence and Replay

**What Must Be Reviewed**:
- [ ] Sessions persist to DB
- [ ] History visible in UI
- [ ] Replay works

**Evidence Required**:
- DB query results
- UI screenshots
- Replay traces

**Blocks Approval**:
- In-memory only
- No UI for history
- Replay broken

**Go/No-Go Decider**: GL6 evidence review

**If Partial**: Fix persistence wiring, do not proceed to P7

**Kilo Forbidden**:
- Partial persistence (metadata only)
- Skip replay functionality

---

## P7: Final Hardening

**What Must Be Reviewed**:
- [ ] All gates GL0-GL6 pass
- [ ] Documentation accurate
- [ ] Package verification passes

**Evidence Required**:
- Gate completion checklist
- Documentation review
- verify_package.sh output

**Blocks Approval**:
- Any gate incomplete
- Doc/implementation mismatch
- Critical bugs

**Go/No-Go Decider**: GL7 final review

**If Partial**: Fix remaining issues, repeat P7

**Kilo Forbidden**:
- "Almost done" release
- Documentation ahead of implementation
- Known critical issues as "acceptable"

---

# Section 6: EXECUTION PROTOCOL FOR KILO

## Mandatory Response Format (After Every Task)

Kilo must respond with exactly these 11 items:

```markdown
### Task Completion Report

**1. Task ID**: {P#-T#}

**2. Why This Is The Correct Task**: 
{Reference to master plan phase/objective, dependency chain}

**3. Files Changed**:
- {file path} — {what changed}
- {file path} — {what changed}

**4. Exact Commands Run**:
```bash
{command with exact arguments}
{command with exact arguments}
```

**5. Tests Run**:
- {test file} — {result}
- {test file} — {result}

**6. Runtime Evidence Captured**:
```
{verbatim output or log excerpt}
```

**7. Acceptance Proof**:
- [ ] {criterion} — {evidence}
- [ ] {criterion} — {evidence}
- [ ] {criterion} — {evidence}

**8. Truthful Status Decision**:
{functional/partial/demo/stub} — {justification}

**9. Blockers**:
{None | Specific blockers with IDs}

**10. Next Recommended Task According To Master Plan**:
{P#-T#} — {brief rationale}

**11. Question: Proceed to the next task?**
{Yes | No — reason}
```

## Mandatory Rules

| Rule | Violation Consequence |
|------|----------------------|
| One task at a time | Context limit exceeded, quality drops |
| No phase skipping | Architecture gaps, untestable state |
| No new capability while blocker alive | Wasted work on broken foundation |
| No doc churn outside P0 and P7 | Docs drift from implementation |
| No architectural drift | Frozen architecture violation |
| No "complete" claim without evidence | Status inflation, trust loss |
| Switch to Code mode for .ts/.py/.rs changes | Architect mode cannot edit code |
| Update todo list after each task | Progress tracking |

## Mode Switch Rules

| Scenario | Action |
|----------|--------|
| Editing .md files only | Stay in Architect mode |
| Editing .ts/.py/.rs files | Switch to Code mode |
| Running commands | Either mode (command can run in both) |
| Debugging failures | Switch to Debug mode |
| Planning/Architecture | Stay in Architect mode |

## Task Boundary Checklist

Before starting a task:
- [ ] Previous task completed and reported
- [ ] Todo list updated
- [ ] No active blockers
- [ ] Files to touch identified

After completing a task:
- [ ] All 11 report items filled
- [ ] Evidence captured verbatim
- [ ] Truthful status assigned
- [ ] Next task identified
- [ ] Todo list updated
- [ ] User confirmation for next task

---

# APPENDIX: Conflict Resolution Log

## A.1 Bullets-First vs Full-Response-Primary

**Conflict**: AGENTS.md and prior docs emphasize bullets-first usefulness. Frozen handoff requires full-response-primary.

**Resolution**: Full response is PRIMARY visible artifact. Bullets are internal optimization for latency reduction, displayed secondary. This aligns with product goal (interview coach, not teleprompter).

**Implementation**: P4-T1/T2 refactors Emitter/UI to prioritize full_response.

## A.2 Status Overstatement

**Conflict**: status.json claims F0-F5, F7 "complete", F6 "partial", product "release-ready".

**Resolution**: Truthful labels only. Current phase is P0 (truth reconciliation). Product is v0.9.0-rc, not v1.0.0.

**Implementation**: P0-T0 rewrites status.json with accurate labels.

## A.3 Multiple Execution Plans

**Conflict**: execution_plan.yaml already removed — no longer exists in repo.

**Resolution**: This pack is the ONLY active control plane. Prior plans already archived.

**Implementation**: P0-T2 marked complete — execution_plan.yaml removed.

## A.4 Live STT State

**Conflict**: status.json claims "audio_stt_functional: true" but LIVE_STT_RUNTIME_EVIDENCE.md shows qualified runs with failures.

**Resolution**: STT is partial — Nova-3 path works but timing issues (net0001) remain.

**Implementation**: P2-T2 fixes timing/cadence.

---

# END OF CANONICAL EXECUTION PACK

**This document is the single source of truth for Interview Coach closure.**

All prior execution plans are deprecated. All status claims must be verifiable against this pack.

**Next Action**: Execute P0-T0 (correct status.json to truthful state).
