# Live Interview Coach — Product Requirements That Matter

## Real product goal
This system is **not** a teleprompter.
It is a **live coach** that must help inside a 1–3 second useful window after the interviewer stops speaking.

## Product truth
### What must be optimized first
1. **Bullets-first response**
   - Target: visible in ~1.3s–1.8s after end-of-utterance in good conditions.
   - Product interpretation: enough to help the user begin speaking.
2. **Conversation tracker correctness**
   - Must avoid repeated metrics.
   - Must avoid contradictions.
   - Must surface uncovered gaps and interviewer themes.
3. **Question analysis speed and quality**
   - Compound questions matter.
   - Follow-ups matter.
   - Closing questions matter.
4. **Language policy correctness**
   - Must not mix languages unless explicitly allowed.
   - Must choose the right language fast.

### What is secondary
1. **Full gated response**
   - Useful mainly as reference while the user is already speaking.
   - It is not the primary pre-speech artifact.
2. **Fancy UI polish**
   - Useful later.
   - Not a blocker for product truth.
3. **Cross-platform parity**
   - Not for V1.
   - V1 is macOS Apple Silicon first.

## Non-negotiable product decisions
1. **Bullets must never wait for full response gate.**
   - Bullets can have a mini-gate.
   - Full response can be buffered/gated separately.
2. **Question-end detection must be tunable.**
   - Current 1.5s silence detection is acceptable as baseline.
   - Must support tuning for fast interviewers.
3. **Manual fallback must always exist.**
   - If audio or STT fails, the user can paste/type the question.
4. **Stealth and ergonomics matter.**
   - Support low-opacity/secondary-monitor usage later.
   - Do not optimize product around obvious teleprompter behavior.

## Success criteria
### V1 success means:
- Backend real mode works with pgvector + LLM keys.
- Realtime bullets flow works backend-first.
- Desktop Tauri happy path works on macOS.
- Audio capture real path exists on macOS.
- Demo/real/partial/stub labels remain honest.

### V1 does NOT require:
- perfect Windows audio
- perfect Linux audio
- full teleprompter experience
- polished design system
- cloud deployment
