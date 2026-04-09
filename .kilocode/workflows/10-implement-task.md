# 10 — Implement Task

Before coding:
1. Read `AGENTS.md`
2. Read `config/status.json`
3. Read `plans/CANONICAL_EXECUTION_PACK.md`
4. Find `active_task` and `next_task` in `config/status.json`
5. Verify the task is valid in the canonical execution pack

Rules:
- implement only `active_task`
- do not skip phase or gate
- do not broaden scope
- do not re-open architecture
- do not use the web preview as product validation

After implementation, return exactly:
1. Task ID
2. Why this is the correct task
3. Files changed
4. Exact commands run
5. Tests run
6. Runtime evidence captured
7. Acceptance proof
8. Truthful status decision
9. Blockers
10. Next recommended task
11. Question: Proceed to the next task?
