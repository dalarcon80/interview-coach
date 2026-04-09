# Simple Live Brain Architecture

## Hard Rules

This is the source of truth for live interview answer generation.

The live path must stay as simple as possible:

`ConsolidatedBlock -> BrainWorker -> Emit`

Mandatory behavior:

- The brain runs in parallel while the interviewer is speaking.
- The system captures the interviewer continuously and must not lose meaningful text.
- The brain analyzes the evolving interviewer block in parallel and decides how to answer before silence.
- At silence, the system uses the latest stable brain decision and emits a fast, high-quality answer.
- The final emit path must not rethink the question from scratch.
- The nominal path must not depend on legacy planners, competing windows, or layered fallbacks.

## Minimal Runtime Design

### 1. ConsolidatedBlock

One source of truth for interviewer speech.

- Maintain a single consolidated interviewer block per active utterance.
- Reconcile streaming revisions into that block.
- Do not keep multiple competing nominal windows for the brain.
- Freeze exactly one consolidated block at silence.

### 2. BrainWorker

One independent per-session worker.

- Runs while the interviewer speaks.
- Recomputes only when the consolidated block changes materially.
- Produces the minimum response contract:
  - `asks`
  - `question_type`
  - `answer_shape`
  - `tone`
  - `use_candidate_context`
  - `use_company_context`
  - `use_metrics`
  - `target_length`
  - `draft_answer`
  - `confidence`
  - `is_complete`

The brain decides:

- what the interviewer is asking
- whether the ask is direct, behavioral, technical, business, or mixed
- whether the answer should be direct, structured, principle/example, walkthrough, or role/actions/outcomes
- whether candidate context, company context, or metrics are needed
- whether a direct draft is safe to emit

### 3. Emit

At silence:

- freeze the consolidated block once
- run one final short brain update on that freeze
- if the brain draft is ready and confidence is sufficient, emit directly
- otherwise run one light polish pass that improves wording only

The polish step must not reinterpret the question or re-plan the answer.

## Simplicity Constraints

The nominal path must not introduce:

- legacy live planner logic
- multiple semantic/tracker sources of truth
- regex-heavy fallback planning as the main path
- separate heavyweight evidence-pack stages as decision-makers
- finalizers that decide strategy

Context selection must stay lightweight:

- if `use_candidate_context = true`, select 1-2 candidate snippets
- if `use_company_context = true`, select 1 company snippet
- if `use_metrics = true`, select 1 supported metric

## Debug Requirements

The UI debug must expose the live brain clearly:

- `consolidated_interviewer_block`
- `revision_id`
- `asks`
- `question_type`
- `answer_shape`
- `tone`
- `use_candidate_context`
- `use_company_context`
- `use_metrics`
- `draft_ready`
- `confidence`
- `brain_updated_while_speaking`
- `served_direct`
- `polish_used`
- `brain_time_ms`
- `freeze_to_emit_ms`

## Acceptance Criteria

- No meaningful interviewer follow-up is dropped.
- The brain updates while the interviewer is speaking.
- The debug view shows real brain decisions, not only fallback artifacts.
- The final answer covers all detected asks.
- Simple and medium questions should answer in under 4 seconds after silence.

## Implementation Order

1. Make the consolidated interviewer block the only nominal source of truth.
2. Implement the minimal BrainWorker contract.
3. Emit directly from the latest stable brain plan whenever possible.
4. Keep only one optional polish pass.
5. Remove legacy nominal dependencies from the live path.
