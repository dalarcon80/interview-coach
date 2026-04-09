# Interview Coach — Kilo Handoff Final

## Objective
Close the current repository into a usable **live interview coach** product with:
- **Primary utility:** bullets visible fast enough to help the user start talking.
- **Secondary utility:** full response visible shortly after, as reference while the user is already speaking.
- **Killer feature:** conversation tracker that prevents repetition, contradiction, and missing follow-ups.

## Ground truth
Use the **current repository** as the only codebase.
Do **not** create a new repo.
Do **not** redesign the architecture.
Do **not** add major features before closing the remaining gaps.

## Product truth
The product is viable **only if** these conditions are satisfied:
1. **Bullets-first latency is treated as the real SLA.**
2. **Full response is treated as secondary/reference, not primary.**
3. **Conversation tracker quality matters as much as latency.**
4. **Desktop macOS Apple Silicon is the primary supported runtime.**
5. **Windows/Linux are installable and degradable, not feature-parity targets for V1.**
6. **Demo mode and real mode must remain explicitly labeled.**

## How to use this package
Read in this order:
1. `KILO_MASTER_PROMPT_FINAL.md`
2. `LIVE_VIABILITY_REQUIREMENTS.md`
3. `execution_plan_final_live_close.yaml`
4. `KILO_MODE_interview_coach_closer.yaml`
5. the current repo files:
   - `upload/ARCHITECTURE.md`
   - `config/execution_plan.yaml`
   - `config/status.json`
   - `README.md`
   - `config/providers.yaml`

## Recommendation
Use **one direct Kilo agent**, not an orchestrator, for this final closing stage.
