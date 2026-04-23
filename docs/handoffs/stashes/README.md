# Rescued stashes (OUT-OF-REPO)

> **SECURITY NOTE:** The text patches of the original stashes contained **Anthropic API keys** inside the diff of `python-core/runtime_config.json`. GitHub secret scanning blocked the push. The patch files were intentionally removed from the repo and are kept **outside version control** for recovery:
>
> ```
> ~/.cache/interview-coach/rescued-stashes-2026-04-22/
>   2026-03-31-pre-insights-launcher.patch
>   2026-03-31-pre-insights-local-artifacts.patch
> ```
>
> If you need to review their content, do NOT commit them back. Apply with `git apply <path>` into a scratch branch.

## Origin

Both stashes were from 2026-03-31 on `codex/stable-live-brain-2026-03-31-post-silence-emit-stream-guard`, dropped in F1-T10 (2026-04-22).

| Patch | Content summary |
|---|---|
| `2026-03-31-pre-insights-local-artifacts.patch` | 4 `.DS_Store` touches — pure noise. |
| `2026-03-31-pre-insights-launcher.patch` | Binary `.pyc` churn + 17 lines in README + 4 in package.json + updates to `scripts/bootstrap_macos.sh` and `scripts/doctor_macos.sh` + removal of stale `tauri-app/dist/assets/*.js` + **API keys in runtime_config.json diff** (reason for out-of-repo storage). |

## Key-rotation requirement

Any contributor who had these stashes on their disk must consider those API keys compromised and **rotate them in the provider console** (Anthropic dashboard → API keys → revoke).

This incident validates ADR-004 (secret management): **API keys must not live in JSON files on disk**. The target architecture moves them to:
- A DB table encrypted at rest, **or**
- The OS native secret store (macOS Keychain, Linux Secret Service, Windows Credential Manager) via a small abstraction.

Action items tracked in `docs/audit/execution_plan.yaml` as new tasks F2-T17 (secret_store module) and F2-T18 (migrate runtime_config keys out of JSON).
