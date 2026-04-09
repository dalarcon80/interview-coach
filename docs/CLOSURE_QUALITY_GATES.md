# Interview Coach — Closure Quality Gates

This document defines the only quality gates that count for product closure.

## GN0 — Control-plane normalization
Pass only if:
- AGENTS.md is the mandatory startup file
- Kilo can derive phase, task, next task, gate, canonical target, and forbidden targets from repo truth only
- no workflow points to `config/execution_plan.yaml`
- no authoritative file says bullets are the primary product artifact
- the old web preview is clearly non-canonical

False positives that do NOT count:
- a plan existing without restart-safe continuity
- multiple docs still giving different instructions

## GL0 — Desktop audio capture
Pass only if:
- `start_capture()` works on the canonical Tauri desktop path
- `stop_capture()` works cleanly
- backend receives stable audio chunks from desktop system-audio path (primary)
- microphone path is secondary/optional and validated separately

False positives that do NOT count:
- microphone-only proof when system-audio path is still unwired
- script-generated audio that bypasses the desktop product path

## GL1 — Desktop-to-backend bridge
Pass only if:
- Audio frames flow from Tauri desktop → WebSocket → Python backend
- Frontend correctly forwards audio events to backend
- Correlation ID (session_id) consistent across the chain

False positives that do NOT count:
- synthetic audio bypassing the real capture path
- frontend/backend not connected via WebSocket

## GL2 — Real STT on desktop path
Pass only if:
- desktop audio produces real partial transcript
- desktop audio produces real final transcript
- utterance end is usable
- the validated path is the canonical desktop path

False positives that do NOT count:
- backend-only validators using WAV or synthetic audio
- provider-only tests that bypass the desktop path

## GL3 — Speaker / turn correctness
Pass only if:
- speaker changes are usable
- interviewer turns are consolidated correctly
- turn finalization is usable
- one-shot triggering is correct

False positives that do NOT count:
- backend-only speaker logic without canonical desktop runtime proof
- defaulting missing speaker metadata to interviewer

## GL4 — Useful live response
Pass only if:
- full response is the primary visible output
- bullets are only preview/support
- tracker influences the live response
- manual fallback exists when appropriate
- live usefulness is demonstrated with real prompts

False positives that do NOT count:
- transcript-only success
- bullets-only success
- response quality claims without runtime evidence

## GL5 — Latency
Pass only if:
- end-to-end latency is measurable
- STT latency <3s for typical utterances
- total latency (capture → STT → response) is documented

False positives that do NOT count:
- latency claims without end-to-end measurement
- partial path latency only

## GL6 — Persistence / replay
Pass only if:
- transcript, suggestions, tracker, and latency metrics are saved
- saved live sessions are reviewable

False positives that do NOT count:
- in-memory-only sessions
- persistence that is not reachable from the canonical product path

## GL7 — Final release
The product is only releasable if:
- manual mode works
- live desktop mode works end-to-end
- latency is measurable end-to-end
- persistence/replay works
- docs/status tell the truth
