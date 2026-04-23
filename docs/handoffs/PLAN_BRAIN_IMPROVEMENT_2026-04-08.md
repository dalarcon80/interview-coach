# Brain Improvement Plan

Branch: `codex/stable-live-2026-04-08`
Tag: `stable-live-2026-04-08`

## Goal

Keep the current single strict live path, but make the brain better at:

1. Identifying the real interviewer intent from the latest actionable turn.
2. Separating question vs supporting context without heuristic blending.
3. Building a stronger response contract for Emit.
4. Preserving parallel preparation while the interviewer is still speaking.

## Current Failure Pattern

The problematic case is not a missing suggestion engine. It is intent misclassification across a short conversation window.

Example:

- `I also have experience ... I am on projects right now in Colombia`
- `... I just wanted to talk about your experience with data, data strategy ... summarize the type of position that you have had?`
- `Tell me a little bit more about Globant.`
- `Okay. So does that mean that you work on projects yourself?`

The latest actionable ask should become the primary target:

- `Does that mean that you work on projects yourself?`

The earlier turns should be support only. They should not pull the answer back to a general Globant description.

## Operating Principles

1. One active ask, one answer contract.
2. Earlier turns are support, not alternate asks, unless the new turn is clearly a follow-up to the same subject.
3. No heuristic fallback that rewrites the answer path.
4. No mixing of interviewer preamble into the final ask.
5. Brain thinks in parallel while the interviewer is talking.

## Proposed Brain Contract

The brain should always emit these conceptual blocks:

- `active_question_text`
- `supporting_interviewer_context`
- `ordered_asks`
- `interviewer_need`
- `response_requirement`
- `context_focus`
- `resolved_question`

Rules:

- `active_question_text` is the latest actionable ask only.
- `supporting_interviewer_context` can explain why the ask matters, but cannot become a new ask.
- `ordered_asks` must contain only the asks the candidate should actually answer.
- `resolved_question` must be short and direct.

## Improvement Phases

### 1. Ask Chain Builder

Normalize the last N interviewer turns into:

- ask turns
- clarification turns
- contextual setup turns
- self-disclosure turns

Then decide:

- what the latest actionable ask is
- whether older turns are still part of the same ask chain
- what should be kept as support only

### 2. Intent Compiler

Convert the active ask into a stable intent contract:

- question family
- response mode
- answer order
- evidence priority
- required context

Examples:

- `Tell me more about Globant` -> company/role context answer
- `Does that mean that you work on projects yourself?` -> personal scope / hands-on involvement answer
- `Summarize the type of position you've had` -> experience summary answer

### 3. Evidence Selector

Pick evidence only after the ask is fixed.

Rules:

- If the ask is about personal work style, prioritize role scope and responsibilities.
- If the ask is about a company, answer the company question directly and briefly.
- If the ask is compound, answer in the order the interviewer is actually asking.

### 4. Emit Contract Writer

Emit should receive a contract that is already resolved.

The contract should tell Emit:

- what the primary ask is
- what context is safe to weave in
- what to avoid
- how direct the answer should be

## Acceptance Criteria

The following should produce the right contract:

- Latest ask: `Does that mean that you work on projects yourself?`
- Output should not default to a Globant company summary.
- Earlier Globant turns should only support the answer.
- The response should explain hands-on project involvement clearly and directly.

## Non-Goals

- No safe fallback path for the brain.
- No heuristic ask merging.
- No response that answers a stale prior question when a new ask is available.
- No separate alternate brain path for live vs silence.

## Implementation Notes

- Keep the current stable branch/tag as the baseline.
- Change the brain contract first, then adjust the evidence/emit path if needed.
- Prefer strict data structures over prompt-only fixes.
- Preserve parallel preparation while the interviewer is still speaking.
