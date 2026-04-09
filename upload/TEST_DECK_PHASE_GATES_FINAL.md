# Interview Coach — Test Deck and Phase Gates

## Principio
Cada fase tiene pruebas obligatorias. No hay cierre “por feeling”.

## F0 — Base
### Commands
- `./scripts/bootstrap.sh`
- `./scripts/doctor.sh`
- `cd python-core && pytest ../tests/unit -q`

### Must pass
- contracts
- provider registry
- question bank
- language policy
- quality gate

## F1 — Audio + Transcript
### Commands
- `cd tauri-app/src-tauri && cargo test || cargo check`
- `cd python-core && pytest ../tests/integration/test_audio_ingest.py -q`
- `cd python-core && pytest ../tests/integration/test_stt_relay.py -q`
- `cd python-core && pytest ../tests/integration/test_transcript_persistence.py -q`

### Manual smoke
- abrir Zoom/Meet o audio local
- confirmar transcript visible en overlay
- confirmar speaker labels
- confirmar persistencia en DB

## F2 — Intelligence
### Commands
- `cd python-core && pytest ../tests/unit/test_question_bank.py -q`
- `cd python-core && pytest ../tests/unit/test_quality_gate.py -q`
- `cd python-core && pytest ../tests/unit/test_language_policy.py -q`
- `cd python-core && pytest ../tests/integration/test_retrieval_pipeline.py -q`
- `cd python-core && pytest ../tests/integration/test_response_composer.py -q`
- `cd python-core && pytest ../tests/integration/test_realtime_pipeline.py -q`

### Must prove
- compound question analysis
- follow-up detection
- relevant retrieval
- gated final response
- no mixed-language final response
- tracker updates state

## F3 — Product behavior
### Commands
- `cd python-core && pytest ../tests/integration/test_styles.py -q`
- `cd python-core && pytest ../tests/integration/test_replay_bundle.py -q`
- `cd python-core && pytest ../tests/unit/test_persist_queue.py -q`
- `cd tauri-app && pnpm test`

## F4 — Simulations + robustness
### Commands
- `cd python-core && pytest ../tests/simulations -q`
- `cd python-core && pytest ../tests/benchmarks -q`
- `cd python-core && pytest ../tests/stability -q`

### Must prove
- score > 75/100
- benchmark report exists
- 30 min stable

## F5 — Expansion
### Commands
- `cd python-core && pytest ../tests/integration/test_event_bus_contract.py -q`
- `./scripts/doctor.sh`
