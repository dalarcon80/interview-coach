# Interview Coach

**Canonical product**: Tauri desktop application for real-time interview coaching on macOS Apple Silicon.

## Current truth

- Manual/prep mode: **functional enough**
- Backend pipeline: **functional enough**
- Backend live STT runtime path: **functional enough at backend scope**
- Desktop live session: **not yet functional end-to-end**

### Current blocker
The product is not live-usable yet because the desktop live system audio capture path is not wired end-to-end into the live backend/STT flow.

## What is the product
- `tauri-app/` is the product UI
- `python-core/` is the backend core
- full response is the primary visible coaching artifact
- bullets are preview/support only

## What is not the product
- old root web preview
- `localhost:3000`
- any validation path that does not use the canonical desktop target

## Current execution control
Use these as the only authoritative control-plane sources:
1. `AGENTS.md`
2. `config/status.json`
3. `plans/CANONICAL_EXECUTION_PACK.md`
4. `docs/SUPPORT_MATRIX.md`
5. `docs/CLOSURE_QUALITY_GATES.md`

## Live closure sequence
- N0 normalize control plane
- P0 truth reconciliation
- P1 desktop audio bridge real
- P2 STT real end-to-end on desktop path
- P3 speaker + turn intelligence
- P4 live response usefulness
- P5 end-to-end latency
- P6 persistence and replay
- P7 final hardening and truthful closure

## How to run the canonical product

### Backend
```bash
cd python-core
../.venv/bin/python main.py
```

### Tauri desktop app
```bash
cd tauri-app
npm run tauri dev
```

## Current support statement
- macOS desktop live path: **partial**
- Linux/Windows live audio: **stub**
- web preview: **deprecated / non-canonical**
