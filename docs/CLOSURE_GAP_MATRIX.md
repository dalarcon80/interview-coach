# Interview Coach — Closure Gap Matrix

**Updated**: 2026-03-16  
**Truth labels**: functional · partial · stub · deprecated

## Executive summary

The repository is not missing product ideas. It is missing closure of the canonical desktop live path.

Current truth:
- Tauri already has the canonical product role
- manual/prep path is relatively strong
- backend live STT work has real progress
- desktop live session is still blocked by the microphone/audio bridge path

## Canonical product decisions
1. Tauri is the canonical final UI.
2. Full responses are the primary visible artifact in both manual and live mode.
3. Bullets are secondary preview/support only.
4. The web preview is not the product and must not be used as the canonical validation target.
5. The current blocker is the desktop live path, not more architecture work.

## Current gap map

| Area | Status | Real gap |
|---|---|---|
| Manual/prep coaching | functional | not the current blocker |
| Backend pipeline | functional | preserve, do not redesign |
| Backend live STT runtime | functional | preserve, but it does not prove desktop-live closure |
| Desktop microphone capture | partial | not wired through canonical path |
| Desktop audio bridge | partial | emitter still centered on system capture path |
| STT on desktop path | partial | must be validated from real desktop audio |
| Speaker/turn intelligence | partial | backend progress exists, product path not closed |
| Live response usefulness | stub | cannot close before real desktop live path |
| End-to-end latency | stub | no canonical product evidence yet |
| Session persistence/replay | stub | not wired through canonical live path |

## Immediate implication
The next meaningful product work after control-plane normalization is:
- wire the real microphone capture into the canonical desktop path
- prove desktop audio reaches backend
- prove desktop audio reaches real STT
