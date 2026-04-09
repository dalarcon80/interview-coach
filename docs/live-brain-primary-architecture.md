# Live Brain Primary Architecture

This document is the mandatory reference for the live interview flow.

## Primary Principles

1. `Brain` reads `Conversation History` in parallel while the interviewer is speaking.
2. `Brain` is the only component that interprets the interviewer question, sub-questions, and answer strategy.
3. No deterministic response-building layer may be added after `Brain`.
4. `Brain` must prepare the response before silence whenever the question is complete enough.
5. On silence, the system should only hand the prepared result to `Emit` or serve the prepared brain draft directly when the architecture allows it.

## Mandatory Brain Responsibilities

- Read the latest consolidated `Conversation History` continuously.
- Detect the main question and all sub-questions in order.
- Decide the response shape and directness.
- Decide whether company or candidate context is required.
- Tailor the answer strategy to the role and interview context.
- For business questions, prioritize role, what was done, and outcomes.
- For technical questions, prioritize technical depth, solution choices, leadership, and achieved results.
- Build the response structure before silence so the final stage is short.

## Prohibited Patterns

- No deterministic fallback that invents or rewrites the answer outside `Brain`.
- No extra post-brain rules that reinterpret the question after `Brain` already decided it.
- No extra complexity in the silence path that can override a richer brain understanding.

## Current Implementation Direction

- `Conversation History` is the source of truth for `Brain`.
- The live snapshot sent to `Brain` must prefer the richest version of the interviewer turn across UI-equivalent history, tracker history, and semantic history.
- Losing the last interviewer follow-up is treated as a correctness bug because it changes the asks that `Brain` sees.
