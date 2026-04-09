# Interview Coach — Closure Analysis vs Z.ai Baseline and World-Class Target

## Brutal summary

The current Kilo-generated repo is **architecturally cleaner** than the earlier Z.ai iterations, but it is **less useful as a product** in the user-visible path.

It optimized for architectural conformity and internal contracts, but it regressed on the highest-value UX flows that actually make the product useful in interview preparation and live assistance:

1. **CV intake + AI profile extraction disappeared from the active UI** even though the API proxy and old components still exist.
2. **Company / role / requirements / style setup is not the main path anymore**. The active page uses a thin dev preview with placeholder session config.
3. **Suggestion quality is worse** because the active path often runs in demo mode and no longer feeds rich candidate/company/CV context from the UI.
4. **Suggestion latency feels worse** because the active visible path uses the realtime pipeline for manual text input, not the faster direct coaching path optimized for typed/manual questions.
5. **Audio still does not work** in the real desktop sense. The Tauri app is still partial and ScreenCaptureKit is still stub.

## Current reality

### What is good now
- Repo structure is much cleaner.
- Frontend/backend websocket contract is more disciplined.
- The backend core exists and is a better long-term base.
- Demo / real / partial / stub labeling is much more honest.
- Tauri app structure exists.
- Tests exist and the unit path is healthy.

### What regressed vs the useful Z.ai path
- Active UI no longer exposes the candidate profile flow.
- Active UI no longer exposes company / role / style / CV context as the primary user journey.
- The product no longer feels like “paste CV, load target company, ask question, get a strong answer”.
- The visible app is now more of a development/realtime preview than a strong coaching tool.

## Product-value judgement

### If the goal is architecture hygiene only
Kilo improved the repo.

### If the goal is the actual Interview Coach product
The current state is **not acceptable as the final user experience**.

Why?
Because the best product behavior came from the older coaching UX path:
- structured candidate/company context,
- CV analysis,
- style-aware suggestion generation,
- fast typed/manual questions.

The new realtime-oriented path is necessary, but it should have been added **without deleting or sidelining the high-value coaching UX**.

## Required product stance

The product must support **both**:

1. **Preparation / manual coaching mode**
   - CV upload or paste
   - AI profile extraction
   - company / role / requirements setup
   - style selection
   - typed question -> strong suggestion fast

2. **Live realtime coach mode**
   - session lifecycle
   - audio/transcript pipeline
   - bullets-first
   - conversation tracker
   - desktop/Tauri/macOS path

If one of these is missing, the product is incomplete.

## Final judgement

Do not discard the repo.
Do not keep iterating randomly.
Do not accept the current UX as the final product.

The correct move is:
- keep the current repo as the baseline,
- restore the lost high-value coaching UX,
- keep the world-class architecture,
- and then close the remaining realtime + desktop gaps.
