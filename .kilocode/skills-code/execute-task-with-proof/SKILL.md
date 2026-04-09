---
name: execute-task-with-proof
description: Use when implementing a single task from the execution plan and returning strict proof of what changed and what passed.
---


Implementation checklist:
1. Read the task
2. Change only the required files
3. Run the required commands
4. Run the required tests
5. Compare against acceptance criteria
6. Return:
   - files changed
   - commands run
   - tests run
   - acceptance proof
   - blockers
   - next task

