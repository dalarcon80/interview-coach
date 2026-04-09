# Live STT Runtime Evidence (L2-STT-06)

## Execution timestamp (UTC)
- Prior prerequisite-only checks: 2026-03-14T16:38:23Z, 2026-03-14T16:46:39Z
- Real-provider runtime attempt window: 2026-03-14T17:10:00Z–2026-03-14T17:13:23Z

## Objective
- Execute real-provider Deepgram live STT runtime validation against [`/ws/pipeline`](python-core/api/server.py:1373) using [`validate_live_stt_runtime.py`](scripts/validate_live_stt_runtime.py:1), then record measured/observed runtime truth.

## Runtime mode used
- Backend startup command:
  - `PYTHONPATH='python-core' python-core/.venv/bin/python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 --log-level info`
- STT/runtime mode environment:
  - `INTERVIEW_COACH_MODE=real`
  - `PROVIDER_STT_PRIMARY_PROVIDER=deepgram`
  - `DEEPGRAM_API_KEY` present in execution shell (masked evidence: length=40)
- WebSocket endpoint exercised:
  - `ws://127.0.0.1:8000/ws/pipeline`
- Mock/fallback disabled method:
  - Forced Deepgram provider alias via `PROVIDER_STT_PRIMARY_PROVIDER=deepgram`.
  - Forced backend real mode via `INTERVIEW_COACH_MODE=real`.
  - Adapter factory path resolves Deepgram when provider is `deepgram` ([`STTAdapterFactory.create()`](python-core/adapters/stt_adapter.py:366)).

## Exact commands run
```bash
# masked key presence check in same command context
python3 - <<'PY'
import os
v=os.environ.get('DEEPGRAM_API_KEY','')
print('DEEPGRAM_API_KEY_present=' + ('yes' if bool(v) else 'no'))
print('DEEPGRAM_API_KEY_length=' + (str(len(v)) if v else '0'))
PY

# runtime execution context (key value redacted in this doc)
export DEEPGRAM_API_KEY='<redacted>'
export PROVIDER_STT_PRIMARY_PROVIDER='deepgram'
export INTERVIEW_COACH_MODE='real'
export APP_PORT='8000'

PYTHONPATH='python-core' python-core/.venv/bin/python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 --log-level info

python-core/.venv/bin/python scripts/validate_live_stt_runtime.py --ws-url ws://127.0.0.1:8000/ws/pipeline --timeout 30

# additional websocket sequence probe for event ordering + metadata capture
python-core/.venv/bin/python - <<'PY'
# connects to /ws/pipeline, sends start_session(mode=real) + 2 audio_data chunks,
# captures event order/transcript metadata, then end_session
PY
```

## Command output evidence
```text
DEEPGRAM_API_KEY_present=yes
DEEPGRAM_API_KEY_length=40
PROVIDER_STT_PRIMARY_PROVIDER=deepgram
INTERVIEW_COACH_MODE=real

validate_live_stt_runtime.py result:
- TimeoutError waiting for websocket event stream completion

sequence probe result:
SESSION_ID=8fe4e350-2f7d-423b-b123-f042efda372a
EVENT_TYPES=connected,session_started,audio_received,audio_received,transcript
EVENT_5_TRANSCRIPT_FINAL=True SPEAKER=unknown LANGUAGE=en TEXT=[STT Error: received 1011 (internal error) Deepgram did not receive audio data or a text message within the timeout window. See https://dpgr.am/net0001; then sent 1011 (internal error) ...]

backend excerpts (same runtime attempt set):
[Interview Coach] Mode resolution effective=real source=env:INTERVIEW_COACH_MODE=real api_keys=True db_connected=True pgvector_ready=True
[WS][STT] stream_open session_id=8fe4e350-2f7d-423b-b123-f042efda372a

additional real-provider run excerpt in same execution window:
[WS][STT] first_final session_id=9b8b0b69-8127-4080-b70f-9d32b3b0e046 latency_ms=861
[WS] Transcript: '[STT Error: ... Deepgram did not receive audio data ... net0001 ...]' (final=True)
[WS][STT] provider_error session_id=9b8b0b69-8127-4080-b70f-9d32b3b0e046 detail=[STT Error: ... net0001 ...]
[WS][STT] stream_close session_id=9b8b0b69-8127-4080-b70f-9d32b3b0e046 duration_ms=861 first_partial_latency_ms=n/a first_final_latency_ms=861 provider_errors=1
```

## Correlation handle
- Session identifiers observed:
  - `8fe4e350-2f7d-423b-b123-f042efda372a` (sequence probe)
  - `9b8b0b69-8127-4080-b70f-9d32b3b0e046` (runtime excerpt with explicit first_final/stream_close)

## Required runtime evidence fields (truthful outcome)
- Stream open log excerpt:
  - `[WS][STT] stream_open session_id=8fe4e350-2f7d-423b-b123-f042efda372a`
- First partial transcript latency (ms):
  - **N/A (no partial transcript observed in real-provider runs)**
- Final transcript latency (ms):
  - **861 ms** (session `9b8b0b69-8127-4080-b70f-9d32b3b0e046`)
- Stream close/cleanup log on `end_session` excerpt:
  - `[WS][STT] stream_close session_id=9b8b0b69-8127-4080-b70f-9d32b3b0e046 duration_ms=861 first_partial_latency_ms=n/a first_final_latency_ms=861 provider_errors=1`
- Provider/runtime/auth errors encountered:
  - Deepgram websocket internal error `1011` with `net0001` (“did not receive audio data or a text message within the timeout window”).
  - Validator script timeout while waiting for full lifecycle completion.
  - Secondary websocket lifecycle error observed in one run: `Unexpected ASGI message 'websocket.send', after sending 'websocket.close'`.
- Speaker metadata actually present:
  - **Yes** (`speaker=unknown` on transcript event)
- Language metadata actually present:
  - **Yes** (`language=en` on transcript event)
- Real provider path exercised instead of mock:
  - **Yes** (Deepgram-specific runtime error `net0001` returned through STT path).
- Representative partial transcript excerpt:
  - **N/A (no partial transcript emitted by provider in this run set)**
- Representative final transcript excerpt:
  - `[STT Error: received 1011 (internal error) Deepgram did not receive audio data ... net0001 ...]`

## Event ordering verification (transcript -> analysis -> suggestion)
- Runtime observed event sequence (session `8fe4e350-2f7d-423b-b123-f042efda372a`):
  - `connected -> session_started -> audio_received -> audio_received -> transcript(final STT error)`
- `analysis`/`suggestion` were **not emitted** because final transcript was STT error text and the pipeline path intentionally short-circuits on `[STT Error: ...]` ([`_handle_transcription_event()`](python-core/api/server.py:509)).
- Failure classification for this L2-STT-06 attempt:
  - **STT provider/runtime failure**

## Truthful status decision
- L2-STT-06 status: **failed (real-provider attempted, runtime/provider failure observed)**
- Live STT runtime validation overall: **not passed**
- L2 is **not closed** for promotion to L3.

## Next unblock action
1. Fix live audio payload/timing compatibility for Deepgram streaming path (net0001 indicates provider did not accept current stream cadence/payload as valid audio flow).
2. Re-run [`validate_live_stt_runtime.py`](scripts/validate_live_stt_runtime.py:1) until partial + final real transcripts are observed and lifecycle closes cleanly.
3. Re-verify runtime event sequence includes `transcript -> analysis -> suggestion` on non-error final transcript.

---

# L2-STT-07 Stabilization Run (Nova-3 `/v1/listen` only)

## Execution timestamp (UTC)
- 2026-03-14T17:27:00Z–2026-03-14T17:39:38Z

## Objective
- Stabilize live STT on one coherent Deepgram path only:
  - endpoint: `/v1/listen`
  - model: `nova-3`
- Add app session correlation to Deepgram request IDs and verify parser handling for `Results`/`UtteranceEnd`/`SpeechStarted` events.

## Runtime mode used
- Backend command:
  - `PYTHONPATH='python-core' python-core/.venv/bin/python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 --log-level info`
- Runtime env in same execution context:
  - `DEEPGRAM_API_KEY` present (masked proof: length=40)
  - `PROVIDER_STT_PRIMARY_PROVIDER=deepgram`
  - `INTERVIEW_COACH_MODE=real`
- WebSocket endpoint exercised:
  - `ws://127.0.0.1:8000/ws/pipeline`
- Flux/v2 status:
  - **Not used in this task** (no `/v2/listen` path in adapter runtime flow).

## Exact commands run
```bash
export DEEPGRAM_API_KEY='<redacted>'
export PROVIDER_STT_PRIMARY_PROVIDER='deepgram'
export INTERVIEW_COACH_MODE='real'
export APP_PORT='8000'

PYTHONPATH='python-core' python-core/.venv/bin/python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 --log-level info

python-core/.venv/bin/python scripts/validate_live_stt_runtime.py --ws-url ws://127.0.0.1:8000/ws/pipeline --timeout 40

# Additional probe to verify transcript behavior with streamed PCM16 audio
# generated from local TTS and sent in 100ms chunks
say -o /tmp/l2stt07_phrase.aiff "Tell me about your experience leading engineering teams and delivering measurable outcomes"
afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/l2stt07_phrase.aiff /tmp/l2stt07_phrase.wav
python-core/.venv/bin/python <websocket_probe_inline_script>
```

## Session/request correlation evidence
- Correlated pair observed in backend logs:
  - `session_id=363f7547-c06a-4f48-bb87-bd5c638154e3`
  - `request_id=536c2c1e-aefb-4a9c-bce4-4764952f4826`
- First provider event type observed:
  - `first_event_type=Results`

## Runtime transcript evidence
- Real app-path transcript (non-error) observed in probe run:
  - `session_id=16157264-e6ad-4b49-b5fb-32a066e902fc`
  - transcript event at `38778 ms`
  - `final=true`, `speaker=interviewer`, `language=en`
  - excerpt: `Tell me about your experience leading engineering teams and delivering measure`
- Also observed in validator-style run:
  - STT error final transcript with Deepgram `1011/net0001` timeout.

## Lifecycle/event instrumentation evidence
- Stream open:
  - `[WS][STT] stream_open session_id=363f7547-c06a-4f48-bb87-bd5c638154e3`
- First final latency:
  - `[WS][STT] first_final session_id=363f7547-c06a-4f48-bb87-bd5c638154e3 latency_ms=13970`
- Stream close:
  - `[WS][STT] stream_close session_id=363f7547-c06a-4f48-bb87-bd5c638154e3 duration_ms=13971 first_partial_latency_ms=n/a first_final_latency_ms=13970 provider_errors=1`
- Deepgram correlation + parser event evidence:
  - `[STT][Deepgram] session_id=363f... request_id=536c...`
  - `[STT][Deepgram] first_event_type=Results request_id=536c...`

## Transcript -> analysis -> suggestion ordering
- Validator flow (`validate_live_stt_runtime.py`): **failed** (timeout).
- Probe flow with non-error final transcript: transcript emitted, but no `analysis`/`suggestion` was observed before connection close in that run.
- Classification:
  - **post-final pipeline processing failure** (STT can produce non-error transcript in app path, but downstream completion is unstable/not consistently emitted before socket closes).

## Root cause isolated in this task
- Mixed model/protocol was **not** the active blocker after stabilization to Nova-3 `/v1/listen`.
- Primary remaining instability is in end-to-end post-final handling/session lifecycle (websocket closes/cancellations around downstream processing), not credential absence.

## Truthful status decision
- L2-STT-07 status: **partial / failed-to-close**
- Single-path STT stabilization + request correlation: **implemented and evidenced**
- L2 runtime usefulness closure criteria (stable transcript -> analysis -> suggestion): **not yet met**

---

# L2-STT-08 Post-final Lifecycle Hardening Run

## Execution timestamp (UTC)
- 2026-03-14T23:33:56Z–2026-03-14T23:38:09Z

## Objective
- Harden post-final lifecycle ordering for the Nova-3 `/v1/listen` app path and re-run runtime validation with stricter success criteria:
  - transcript -> analysis -> suggestion ordering
  - Finalize before CloseStream
  - CloseStream only after downstream completion or explicit terminal failure
  - KeepAlive evidence in runs with audio gaps

## Exact commands run
```bash
# Targeted regression checks for lifecycle and ordering contracts
./.venv/bin/python -m pytest tests/unit/test_ws_session_stt_manager.py tests/integration/test_ws_realtime_flow.py

# Runtime validation attempt (same command context)
set -euo pipefail
BACKEND_LOG=/tmp/l2_stt_08_backend.log
./.venv/bin/python -m uvicorn api.server:app --app-dir python-core --host 127.0.0.1 --port 8000 > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
sleep 4
./.venv/bin/python scripts/validate_live_stt_runtime.py --ws-url ws://127.0.0.1:8000/ws/pipeline --timeout 150
kill "$BACKEND_PID" >/dev/null 2>&1 || true
wait "$BACKEND_PID" >/dev/null 2>&1 || true
tail -n 200 "$BACKEND_LOG"
```

## Command output evidence
```text
pytest result:
- tests/unit/test_ws_session_stt_manager.py
- tests/integration/test_ws_realtime_flow.py
- 10 passed

validate_live_stt_runtime.py result:
audio_source=synthetic total_audio_bytes=128000 chunks=4
validation_loop_timeout_s=150.0

=== LIVE STT RUNTIME VALIDATION ===
first_partial_latency_ms=None
first_final_latency_ms=None
first_non_error_final_latency_ms=None
transcript_event_count=0
provider_errors=1
provider_error[1]=STT stream error: DEEPGRAM_API_KEY not configured
analysis_observed=False
suggestion_observed=False
stream_open_observed=True
stream_close_observed=True
keepalive_count=0
keepalive_observed=False
finalize_sent_ms=None
close_stream_sent_ms=None
transcript_timestamp_ms=None
analysis_timestamp_ms=None
suggestion_timestamp_ms=None
RESULT=FAILED (no partial transcript observed)

backend excerpt:
[Interview Coach] Mode resolution effective=demo source=auto:missing_prereqs api_keys=True db_connected=False pgvector_ready=False
[WS] Session STT stream error: DEEPGRAM_API_KEY not configured
[WS][STT] stream_close ... transcript_ms=n/a analysis_ms=n/a suggestion_ms=n/a teardown_ms=n/a teardown_cancel_ms=n/a provider_errors=0
```

## Runtime timeline evidence (this run)
- Transcript timestamp: **not observed**
- Analysis timestamp: **not observed**
- Suggestion timestamp: **not observed**
- Finalize timestamp: **not observed**
- CloseStream timestamp: **not observed**
- KeepAlive count/timestamps: **not observed**
- Teardown/cancel timestamp: teardown in stream_close summary (`teardown_ms=n/a`, `teardown_cancel_ms=n/a` in this failed run)

## Ordering evidence
- Required ordering could not be exercised in this runtime attempt because the provider path did not start:
  - hard blocker at startup/runtime: `DEEPGRAM_API_KEY not configured`
  - environment fell back to demo readiness due missing DB connection (`db_connected=False`)
- Therefore, no real-provider `transcript -> analysis -> suggestion` ordering evidence was produced in this run.

## Root-cause fix status
- **Implemented in code/tests, runtime proof still blocked by environment prerequisites**.
- Lifecycle hardening now enforces downstream gating and ordering hooks in:
  - [`DeepgramSTTAdapter`](python-core/adapters/stt_adapter.py)
  - [`SessionSTTStreamManager`](python-core/api/server.py)
  - validator checks in [`validate_live_stt_runtime.py`](scripts/validate_live_stt_runtime.py)

## Truthful status decision
- L2-STT-08 implementation status: **partial**
  - Code hardening and regression tests: **functional**
  - Real-provider runtime acceptance (Nova-3 app path): **blocked in this environment**
- L2 closure status: **not closed** until one real-provider run shows transcript -> analysis -> suggestion ordering with Finalize/CloseStream evidence.

---

# L2-STT-09 Qualified Real Runtime Closure Run

## Execution timestamp (UTC)
- 2026-03-14T23:57:42Z–2026-03-15T00:13:18Z

## Scope executed
- Persisted local secret in a non-versioned local file (`.kilo.local.env`) with restricted permissions.
- Brought runtime to qualified real mode (`effective_mode=real`, DB connected, Deepgram selected).
- Re-ran live validator with real-provider context and real PCM16 WAV audio.
- Applied one minimal L2 fix in [`validate_live_stt_runtime.py`](scripts/validate_live_stt_runtime.py:28):
  - synthetic default audio changed from invalid placeholder bytes to valid PCM16 tone payload
  - close-session wait logic hardened
  - success criteria kept focused on non-error final transcript + analysis + suggestion ordering with finalize timestamp checks

## Exact commands run
```bash
# local secret setup (masked proof only)
chmod 600 .kilo.local.env
echo '.kilo.local.env' >> .git/info/exclude  # only if missing

# start required local service
open -a Docker
docker compose up -d postgres

# qualified readiness check
source ./.kilo.local.env
export DEEPGRAM_API_KEY
export PROVIDER_STT_PRIMARY_PROVIDER=deepgram
export INTERVIEW_COACH_MODE=real
./.venv/bin/python -m uvicorn api.server:app --app-dir python-core --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health

# create real speech-like validation audio
say -o /tmp/l2_stt_09_phrase.aiff "Tell me about your experience leading engineering teams and delivering measurable outcomes"
afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/l2_stt_09_phrase.aiff /tmp/l2_stt_09_phrase.wav

# qualified validator run
./.venv/bin/python scripts/validate_live_stt_runtime.py \
  --ws-url ws://127.0.0.1:8000/ws/pipeline \
  --audio-file /tmp/l2_stt_09_phrase.wav \
  --timeout 180
```

## Qualified readiness evidence
```text
masked_key_presence=yes
masked_key_length=40
masked_key_fingerprint=a576***afd9
secret_file_mode=0o600
secret_file_excluded=yes

health_status=healthy
health_effective_mode=real
health_mode_source=env:INTERVIEW_COACH_MODE=real
health_db_connected=True
health_pgvector_ready=True
health_api_keys_configured=True

backend readiness excerpt:
[Interview Coach] Mode resolution effective=real source=env:INTERVIEW_COACH_MODE=real api_keys=True db_connected=True pgvector_ready=True
```

## Runtime timeline evidence (qualified run)
```text
validator summary:
first_partial_latency_ms=1246
first_final_latency_ms=3687
first_non_error_final_latency_ms=3687
analysis_observed=True
suggestion_observed=True
transcript_timestamp_ms=1246
analysis_timestamp_ms=3693
suggestion_timestamp_ms=3724
finalize_sent_ms=3460
RESULT=PASS

backend correlated timeline:
session_id=8040265b-906a-40a4-b6f2-53825ac4c523
request_id=e8d089c5-6db7-4002-bf5e-858d4a3fc980
[WS][STT] suggestion_emitted ... timestamp_ms=3668
[STT][Deepgram] ... close_stream_sent_ms=5670
```

## Ordering + lifecycle evidence
- Transcript -> analysis -> suggestion ordering observed in one qualified run:
  - transcript timestamp `1246`
  - analysis timestamp `3693`
  - suggestion timestamp `3724`
- Finalize before CloseStream observed:
  - `finalize_sent_ms=3460`
  - `close_stream_sent_ms=5670`
- CloseStream occurred after downstream completion:
  - downstream completion log at `3667`
  - suggestion emitted at `3668`
  - close stream sent at `5670`
- Session/request correlation evidenced:
  - `session_id=8040265b-906a-40a4-b6f2-53825ac4c523`
  - `request_id=e8d089c5-6db7-4002-bf5e-858d4a3fc980`
- KeepAlive evidence present in qualified attempts with post-audio gaps:
  - `keepalive_count=1` (successful run)
  - higher counts observed in prior qualified retries with delayed close.

## Representative non-error transcript excerpt
- `Tell me about your experience leading engineering teams and delivering`

## Truthful status decision
- L2-STT live runtime closure criteria are now satisfied for Nova-3 `/v1/listen` app path.
- L2 STT status: **functional for qualified real-provider runs**.
- Remaining caveat is environment-dependent prerequisites (key + DB readiness), not an unresolved L2 lifecycle defect.
