# F1-T5 Cherry-pick resolution

**Date:** 2026-04-22
**Status:** No-op — all targets were already integrated into `main`.

## Context

`docs/audit/BRANCH_FORENSICS.md` §4.5 listed a planned cherry-pick sequence:

1. `cefec7c9` — brain-silence-window-reset
2. `8191879b` + `2005d7f9` + `eef8bfd6` — runtime-config consolidation
3. `aae81ce9` — feature/clean-turn-isolation
4. Extracted `.py` from `9d00f486` — brain-intent-harden (avoiding binary contamination)

## Verification

```bash
for br in cefec7c9 aae81ce9 eef8bfd6 2005d7f9 8191879b 7b44582a 9d00f486; do
  if git merge-base --is-ancestor "$br" main; then echo "$br: YA en main"; fi
done
```

Result:
- `aae81ce9` → ancestor of main
- `eef8bfd6` → ancestor of main
- `2005d7f9` → ancestor of main
- `8191879b` → ancestor of main
- `9d00f486` → ancestor of main
- `7b44582a` → ancestor of main (alternate SHA of the same patch as `cefec7c9`)

`git diff 7b44582a cefec7c9` is **empty**. The two commits are textually identical (one is likely a rebase/force-update of the other).

`git rev-list --count main..codex/brain-intent-harden-2026-04-09` = **0**. The "drift" reported in F0 audit was caused by:
- Binary contamination (`.DS_Store`, `node_modules`, `.venv`) only on that branch, which main does not track.
- F0 artifacts added to main (docs/audit/, docs/adr/, etc.) after audit, which appear in the reverse direction.

## Conclusion

`main` already contains all the useful code from the candidate branches. The only real problem was repo hygiene (addressed in F1-T1 and F1-T3) and stale branch references (to be addressed in F1-T8).

**F1-T5 is a no-op.** The consolidation/v2 branch was created as safety net but no cherry-picks are required. It can be fast-forwarded or just deleted.

## Decision

- Keep `consolidation/v2` branch as the integration point for F1-T6 (pytest) and F1-T12 (runtime_config.json move).
- Skip cherry-picks (no commits to pick).
- Continue with F1-T6.
