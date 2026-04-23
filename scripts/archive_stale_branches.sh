#!/usr/bin/env bash
# =============================================================================
# Interview Coach — F1-T8 archive_stale_branches.sh
# =============================================================================
# Archives the codex/*, claude/*, and feature/* branches listed in
# docs/audit/BRANCH_FORENSICS.md to refs/archive/* and deletes them locally
# and on the origin remote.
#
# Every branch's HEAD SHA is preserved under refs/archive/<original>, so
# `git checkout refs/archive/<name>` still retrieves it.
#
# Pass --dry-run to see what would happen without touching refs.
# =============================================================================

set -euo pipefail

DRY_RUN="${1:-}"

STALE_BRANCHES=$(cat <<'EOF'
claude/compassionate-driscoll
codex/archive-main-before-2026-03-31-post-silence-emit-stream-guard
codex/brain-context-maximizer
codex/brain-intent-clean-2026-04-09
codex/brain-intent-harden-2026-04-09
codex/brain-plan-hash-stability
codex/brain-response-refine-next
codex/brain-semantic-contract-refactor
codex/brain-silence-window-reset-2026-04-09
codex/c5a20994-parsing-only
codex/c5a20994-single-path-brain
codex/checkpoint-live-brain-before-finalizer-fix-20260326
codex/checkpoint-live-brain-pre-cleanup-20260326
codex/deterministic-main-isolation
codex/dev-brain-intent-engine-v1
codex/dev-brain-intent-proof-next
codex/dev-brain-llm-first-v1
codex/dev-brain-response-requirements-v1
codex/dev-cv-fallback-profile-fix-v1
codex/dev-insights-guided-workspace-v1
codex/dev-insights-isolation-fix-v1
codex/dev-insights-module-v1
codex/dev-live-brain-latency
codex/dev-live-brain-next
codex/dev-live-brain-quality-v1
codex/dev-live-emit-after-silence-stream-safe-v1
codex/dev-live-emit-visible-latency-v1
codex/dev-live-latency-pre-emit-v1
codex/dev-live-post-silence-only-from-stable-22de66e9
codex/dev-live-silence-anchor-v1
codex/dev-live-token-governance-v2
codex/dev-post-silence-emit-only-v1
codex/dev-prepare-source-of-truth-v1
codex/freeze-2026-04-06-brain-current-state
codex/live-brain-runtime-hardening
codex/pre-stable-live-brain-2026-03-27-recovered-brain-baseline
codex/semi-stable-2026-03-31-live-brain-contract
codex/stable-2026-04-01-brain-hash-fix
codex/stable-2026-04-01-brain-response-refine-v3
codex/stable-2026-04-06-brain-proof-baseline
codex/stable-live-2026-04-08
codex/stable-live-2026-04-08-publish
codex/stable-live-brain-2026-03-25
codex/stable-live-brain-2026-03-26
codex/stable-live-brain-2026-03-26-post-live-fix
codex/stable-live-brain-2026-03-26-quality-foundation
codex/stable-live-brain-2026-03-27-emit-only-baseline
codex/stable-live-brain-2026-03-27-emit-retry-baseline
codex/stable-live-brain-2026-03-27-quality-good-high-latency
codex/stable-live-brain-2026-03-30-real-stable-baseline
codex/stable-live-brain-2026-03-30-silence-anchor-improved
codex/stable-live-brain-2026-03-31-post-silence-emit-stream-guard
codex/stable-live-brain-2026-04-06-semantic-contract-v2-baseline
feature/clean-turn-isolation
EOF
)

archived=0
failed=0
skipped=0

for branch in $STALE_BRANCHES; do
  # Local archive
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    sha=$(git rev-parse "$branch")
    if [[ "$DRY_RUN" == "--dry-run" ]]; then
      echo "DRY: archive local $branch -> refs/archive/$branch ($sha)"
    else
      git update-ref "refs/archive/$branch" "$sha"
      git branch -D "$branch" >/dev/null 2>&1
      echo "  archived local: $branch -> refs/archive/$branch ($sha)"
    fi
    archived=$((archived + 1))
  else
    skipped=$((skipped + 1))
  fi

  # Remote delete (origin) — archive ref is local-only; the remote just loses the branch
  if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    if [[ "$DRY_RUN" == "--dry-run" ]]; then
      echo "DRY: delete remote origin/$branch"
    else
      if git push origin --delete "$branch" >/dev/null 2>&1; then
        echo "  deleted remote: origin/$branch"
      else
        echo "  could not delete remote: origin/$branch (may already be gone)"
        failed=$((failed + 1))
      fi
    fi
  fi
done

echo ""
echo "Summary: archived=$archived skipped_not_local=$skipped remote_errors=$failed"

if [[ "$DRY_RUN" != "--dry-run" ]]; then
  echo ""
  echo "Recovery: git checkout refs/archive/<branch-name>"
  echo "List: git for-each-ref refs/archive/"
fi
