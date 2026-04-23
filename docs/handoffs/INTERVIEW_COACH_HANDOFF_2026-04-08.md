# Interview Coach Handoff

Date: 2026-04-08
Owner context: Daniel / Codex session handoff

## 1. Objective and non-negotiable rules

These are the working rules that must remain the source of truth for future work:

1. Brain must follow a single path. No parallel fallback path should be allowed to answer in place of the semantic brain.
2. No heuristics-based "burned brain" or shortcut response path.
3. Brain should prepare in parallel while the interviewer is speaking.
4. Tracker, history capture, silence detection, and other live capture mechanics should not be rewritten unless there is a proven defect there.
5. The main job is to prepare the brain so it can separate:
   - interviewer context
   - actual ask
   - ordered asks when there is more than one
   - response contract for emit
6. The brain must receive clearer structure and better instructions, not more fallback logic.

## 2. Project map

Canonical local checkout:
- `/Users/dalarcon/projects/prd/interview-coach-v1`

Canonical GitHub remote:
- `https://github.com/dalarcon80/interview-coach.git`

Important note:
- This local checkout is the source of truth for future branches, tags, and versions.
- The old `interview-coach-v1-stable-run` worktree was removed after the stable snapshot was tagged.
- The active working branch in this checkout is `codex/brain-intent-clean-2026-04-09`.

## 3. Stable / reference branches

These are the main reference points found in the repo and should be treated as the branch map for rollback and comparison:

- `codex/stable-live-brain-2026-03-26` -> `838c157ce9222edf7f7557366fb9b1891b68078c`
- `codex/stable-live-brain-2026-03-27-emit-only-baseline` -> `99d45c77641f3ed3856e9998813ffb11d9d42444`
- `codex/stable-live-brain-2026-03-27-emit-retry-baseline` -> `0feb1bec6e3e9c412668b7cbdcb30674380bd8fe`
- `codex/stable-live-brain-2026-03-30-real-stable-baseline` -> `22de66e9b26d88deb461c7dbb555d530fced86ce`
- `codex/stable-live-brain-2026-03-31-post-silence-emit-stream-guard` -> `3d943f9c189110753e233c95a3d279370292e22b`
- `codex/stable-live-brain-2026-04-06-semantic-contract-v2-baseline` -> `c5a20994e5a7eb8d7596a9d060ff5041b0eeaeb7`
- `codex/stable-2026-04-06-brain-proof-baseline` -> `7b0c81679b32e4a713c8e73f7831c1590d2ed60d`

Current runtime base commit:
- `8191879b3c7f8d0c52a2c2b8b8cc49d8a88f5ad2`
- Commit message: `fix: localize runtime config and honor settings model`

GitHub status:
- `main` now points to the same stable commit as the collaboration branch
- runtime config is loaded from the user config path, not from the repo checkout

## 4. What was broken

There were two different problem categories mixed together:

### A. Runtime / environment issues

- The PostgreSQL container entered a restart loop.
- Health endpoint degraded to:
  - `db_connected=false`
  - `pgvector_ready=false`
  - `effective_mode=demo`
- That caused the app to run in degraded/demo behavior even when the frontend and backend were alive.

Root cause found in Docker logs:
- stale / corrupted lock file at `/var/run/postgresql/.s.PGSQL.5432.lock`

### B. Live brain behavior issues

The live brain drifted away from the intended model:

- the brain sometimes received an ambiguous monolithic question block
- the system still had alternate response-serving paths that could bypass the intended semantic ownership
- freeze behavior could fail to produce the intended brain-driven contract when the desired plan was not ready
- the user expectation remained:
  - one path
  - strong semantic analysis
  - explicit differentiation between context and ask
  - ordered asks when needed
  - robust contract passed to emit

### C. Silence-to-emit regression

There was also a separate runtime regression after silence:

- hard silence could already be satisfied
- but auto-suggestion was still blocked if `display_caption` looked recent
- that caption could stay recent because duplicate or echoing partials kept refreshing it
- result: live transcription appeared healthy, but no final answer was emitted after silence

### D. Completed-turn-to-silence scheduling regression

After the previous fix, another more precise defect was confirmed in backend logs:

- live transcription and finalized interviewer turns were still being recorded correctly
- but the completed interviewer turn did not explicitly arm the silence trigger for its own generation
- that left the final answer path depending on an earlier caption-driven hard-silence gate still being alive
- when that prior gate was missing or stale, no `[AUTO][SILENCE]` path ran at all
- result: live captions continued, finalized interviewer turns existed, but no `suggestion` event was emitted

## 5. What was changed in the stable runtime worktree

All code changes were made in:
- `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run`

Files changed:
- `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run/python-core/contracts/models.py`
- `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run/python-core/api/server.py`
- `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run/python-core/pipeline/steps/live_brain_service.py`
- `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run/python-core/pipeline/steps/live_finalizer.py`
- `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run/tests/unit/test_live_brain_v3.py`
- `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run/tests/unit/test_brain_response_requirements_v1.py`
- `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-stable-run/tests/unit/test_ws_session_stt_manager.py`

### Summary of code changes

#### Brain snapshot was split explicitly

`BrainSnapshot` now carries explicit fields so the brain does not need to infer everything from one flat text blob:

- `active_question_text`
- `active_turns`
- `historical_turns`
- `primary_question_source`
- `active_ask_key`

#### Server live path was constrained

In the live server path:

- live planning serves only `llm_fast`
- `cached_stable` is no longer accepted as a live answer-serving path
- `immediate_safe_fallback` was removed from normal answer serving
- readiness checks now require the correct snapshot identity, using exact `active_ask_key` matching when present
- the live brain timeout was raised from `3.4s` to `6.0s`, and the freeze wait grace was increased to `1.25s`, so the semantic brain has enough time to finish before the silence path gives up with `timeouterror`

#### Brain prompt was made structurally explicit

The fast planner prompt now separates:

- `ACTIVE ASK BLOCK`
- `SUPPORTING INTERVIEWER CONTEXT`
- `RECENT CONVERSATION HISTORY`

Intent:
- only the active ask block may create `literal_question` and `ordered_asks`
- history/context may enrich need and response framing but may not invent asks

#### Finalizer was tightened

The finalizer now trusts the `llm_fast` path only for direct brain-driven draft/blueprint use in the live route.

#### Runtime config must stay local

`python-core/runtime_config.json` originally pointed the live LLM path at Anthropic. That key was published in GitHub and then revoked by Anthropic on `2026-04-09`, which caused `authenticationerror` and forced the brain into fallback/salvage behavior.

Current stable runtime rule:

- `llm.provider` and `llm.model` are taken from Settings and are the source of truth for the live brain
- `llm.api_key` stays local-only and is resolved from the user runtime config path, not from the repo
- runtime config now loads/saves from `~/.config/interview-coach/runtime_config.json` by default, or from `INTERVIEW_COACH_RUNTIME_CONFIG_PATH` if set
- the STT adapter factory now reads the same local runtime config store, so STT uses the key saved in Settings instead of the sanitized repo checkout
- `python-core/runtime_config.json` is sanitized before publish
- do not reintroduce the revoked Anthropic key from history or commit a new one into the repo
- the legacy migration path now skips sanitized empty configs so a publish-safe repo snapshot cannot overwrite a valid local runtime with empty credentials

#### Silence-to-emit gate was normalized

In the live auto-silence path:

- `hard_silence` is now the single source of truth for emit readiness
- recent `display_caption` freshness no longer blocks emit once hard silence is already satisfied
- this prevents duplicate or echoing partial caption updates from suppressing the final suggestion indefinitely

#### Completed interviewer turns now arm the silence trigger directly

In `python-core/api/server.py`:

- every completed interviewer turn now explicitly schedules the silence-triggered suggestion path for that exact generation
- completed turns also ensure the hard-silence gate is armed even when interviewer activity epoch is already non-zero
- this keeps one answer path (`_try_auto_trigger_suggestion`) but removes the hidden dependency on an older caption gate surviving
- added backend log lines:
  - `[AUTO][SILENCE] hard_silence_gate_scheduled`
  - `[AUTO][SILENCE] hard_silence_gate_fired`
  - existing `[AUTO][SILENCE] schedule_debounce`

This is the critical normalization for the bug where:

- live captions kept working
- finalized interviewer turns were visible
- but realtime suggestions never appeared after silence

## 6. Current runtime state

As of this handoff:

### Backend

- Health URL: `http://127.0.0.1:8000/health`
- Current status after DB repair:
  - `status=healthy`
  - `db_connected=true`
  - `pgvector_ready=true`
  - `effective_mode=real`
  - `mode_source=auto:prereqs_ok`

### Database

Container:
- `interview-coach-db`

Port:
- `5433 -> 5432`

Current state:
- healthy

Database URL expected by app:
- `postgresql://interview_coach:interview_coach_dev@localhost:5433/interview_coach`

### Local runtime restored

The local user runtime config at `~/.config/interview-coach/runtime_config.json` was restored from the last known-good Deepgram STT snapshot outside the repo. That keeps the credential local-only while allowing the live STT adapter to connect again after the sanitized publish.

### Current local processes

- backend: `python-core/api/server.py`
- frontend dev server: `tauri-app` Vite on `http://localhost:5174`
- desktop app: `tauri-app/src-tauri/target/debug/interview-coach`

### Frontend / app

Vite:
- `http://localhost:5174/`

Tauri:
- launched from the stable-run worktree

## 7. Exact DB repair that worked

The DB fix that actually restored the environment was:

1. Inspect logs and confirm bogus socket lock file:
   - `docker logs --tail 60 interview-coach-db`
2. Remove the broken container instance:
   - `docker rm -f interview-coach-db`
3. Recreate postgres from compose in the main repo:
   - `cd /Users/dalarcon/projects/prd/interview-coach-v1 && docker compose up -d postgres`

Why this was safe:
- the broken lock file was in `/var/run/postgresql`, which belongs to the container runtime filesystem
- the actual data remained in the named volume
- recreating the container preserved the DB contents while removing the corrupted runtime lock

## 8. Start / verify commands

### Start DB

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1
docker compose up -d postgres
```

### Verify DB

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker logs --tail 50 interview-coach-db
```

### Start backend from stable runtime

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1/python-core
PYTHONPATH=. /Users/dalarcon/projects/prd/interview-coach-v1/.venv/bin/python api/server.py
```

### Start Tauri app from stable runtime

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1/tauri-app
npm run tauri -- dev
```

### Verify runtime mode

```bash
curl -s http://127.0.0.1:8000/health
```

Expected healthy result:

```json
{
  "status": "healthy",
  "db_connected": true,
  "pgvector_ready": true,
  "effective_mode": "real"
}
```

## 9. Tests that passed

Executed in the stable runtime worktree:

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1
PYTHONPATH=python-core /Users/dalarcon/projects/prd/interview-coach-v1/.venv/bin/python -m pytest tests/unit/test_live_brain_v3.py tests/unit/test_brain_response_requirements_v1.py -q
```

Result:
- `106 passed`

Additional targeted regression after the silence/emit fix:

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1
PYTHONPATH=python-core /Users/dalarcon/projects/prd/interview-coach-v1/.venv/bin/python -m pytest tests/unit/test_ws_session_stt_manager.py -k 'recent_display_caption or same_silence_window_after_answer or interviewer_resumes_during_emit' -q
```

Result:
- `5 passed`

Additional full websocket/session regression suite after the completed-turn scheduling fix:

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1
PYTHONPATH=python-core /Users/dalarcon/projects/prd/interview-coach-v1/.venv/bin/python -m pytest tests/unit/test_ws_session_stt_manager.py -q
```

Result:
- `68 passed`

Important note:
- passing tests confirm the implemented constraints and regressions that were added
- they do not guarantee that the semantic quality now matches the exact historical "best" behavior the user remembers

## 10. Current git reality

This matters because the workspace is operationally messy and should be treated carefully.

### Worktrees

The canonical checkout is:

- `/Users/dalarcon/projects/prd/interview-coach-v1`
- active branch: `codex/brain-intent-clean-2026-04-09`

The old stable-run worktree has already been removed.

Operational rule:
- keep future work on named Git branches in the canonical checkout
- do not create extra Desktop folders or ad hoc worktrees
- ignore transient local noise such as `.DS_Store` through Git, not by scattering new copies of the repo

## 11. Known unresolved product issue

Even after the structural single-path changes, the user still reports that the brain behavior does not yet fully match the expected historical quality.

The exact complaint is not only "wrong output" but:

- the brain should understand the interviewer’s real intention across recent turns
- it should decide what is context vs actual ask
- it should detect multiple asks when present
- it should produce a strong contract for emit
- it should do this without fallback contamination

This remains the main product gap.

In other words:
- environment is now repaired
- runtime is in `real`
- tests pass
- but semantic behavior still needs another comparison pass against the genuinely preferred stable behavior

## 12. Recommended next step

Do not keep adding fallback logic.

The next safe step is:

1. choose the exact historical branch/commit that best matches the remembered behavior
2. run the same real transcript through:
   - that historical baseline
   - current stable runtime worktree
3. compare the actual brain inputs and outputs at:
   - active ask extraction
   - ordered asks
   - resolved question
   - response requirement
   - final emit contract
4. apply only the minimal semantic delta needed to recover the old behavior

If this is not done by direct side-by-side comparison, the work risks drifting again.

## 13. Short operational summary

At the end of this session:

- DB was repaired and brought back to healthy
- backend is no longer stuck in demo mode
- runtime is working in real mode
- a single-path live brain structure was enforced in code
- tests for that path are passing
- the remaining issue is semantic fidelity versus the historically preferred stable behavior

## 14. Paths to keep handy

Main repo / canonical local path:
- `/Users/dalarcon/projects/prd/interview-coach-v1`

GitHub remote:
- `https://github.com/dalarcon80/interview-coach.git`

Stable branch / tag:
- `codex/stable-live-2026-04-08`
- `stable-live-2026-04-08`

Backend server:
- `/path/to/fresh/worktree/python-core/api/server.py`

Brain service:
- `/path/to/fresh/worktree/python-core/pipeline/steps/live_brain_service.py`

Brain finalizer:
- `/path/to/fresh/worktree/python-core/pipeline/steps/live_finalizer.py`

Brain snapshot model:
- `/path/to/fresh/worktree/python-core/contracts/models.py`

Primary live brain tests:
- `/path/to/fresh/worktree/tests/unit/test_live_brain_v3.py`

Response requirement tests:
- `/path/to/fresh/worktree/tests/unit/test_brain_response_requirements_v1.py`

## 15. Clean run commands

Use the stable branch/tag snapshot:

Backend:

```bash
cd /path/to/a/fresh/worktree/python-core
/Users/dalarcon/projects/prd/interview-coach-v1/.venv/bin/python api/server.py
```

Frontend:

```bash
cd /Users/dalarcon/projects/prd/interview-coach-v1/tauri-app
npm run tauri -- dev
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

Notes:
- `npm run dev` only starts Vite; it does not launch the Tauri shell.
- `npm run tauri -- dev` is the correct command for the desktop app.
- The old `interview-coach-v1-stable-run` worktree was removed after the stable snapshot was tagged.
- The active collaboration branch is `codex/brain-intent-clean-2026-04-09` in the canonical checkout.
- If you need a new branch from the stable snapshot, create it in `/Users/dalarcon/projects/prd/interview-coach-v1` and publish it to GitHub when ready.

## 16. Stable Git Snapshot

Use this exact snapshot as the stable reference:

- Branch: `codex/stable-live-2026-04-08`
- Tag: `stable-live-2026-04-08`
- Commit: `015eac65` (`Publish stable live snapshot for GitHub`)
- Backup local tag: `stable-live-2026-04-08-internal` -> `cde32722` (`Stabilize live brain snapshot and tracker compatibility`)

The next brain iteration should start from the plan in:

- `/Users/dalarcon/Desktop/PLAN_BRAIN_IMPROVEMENT_2026-04-08.md`

## 17. Git Publication Status

Published `main` on GitHub from a clean worktree rooted at `015eac65`:

- `main` -> `9d00f486` (`Publish Anthropic env-backed live runtime`)
- abandoned collaboration branch: `codex/brain-intent-harden-2026-04-09`
- clean restart branch: `codex/brain-intent-clean-2026-04-09`
- clean restart branch pushed to GitHub: `codex/brain-intent-clean-2026-04-09`
- contract restoration commit on the clean restart branch: `7cc855b2` (`fix: restore brain question scope contract`)
- cleanup commit on the clean restart branch: `f3a5ab38` (`chore: normalize repository checkout`)
- canonical local checkout: `/Users/dalarcon/projects/prd/interview-coach-v1`
- publish worktree: `/Users/dalarcon/projects/prd/worktrees/interview-coach-v1-main-publish`

The main publication is intentionally based on the clean published snapshot so GitHub does not ingest the oversized historical blobs from the runtime-hardening branch. The Anthropic key stays out of the repo and is resolved from `ANTHROPIC_API_KEY` locally.
