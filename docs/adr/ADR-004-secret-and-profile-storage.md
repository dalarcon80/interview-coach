# ADR-004 — Secrets and profile storage (NEVER in JSON on disk)

- **Status:** Accepted (draft, to be ratified at end of F2)
- **Date:** 2026-04-22
- **Deciders:** architect, product owner
- **Supersedes:** `python-core/runtime_config.json` as a secret store (deprecated in F1-T12)

## Context

Two events during F1 forced this ADR:

1. **F1-T10 (stash cleanup) leaked 2 Anthropic API keys** into text patch files that GitHub secret scanning blocked. The keys had been living in `python-core/runtime_config.json` on disk, committed into stashes without the author realizing.
2. **F1-T12 (legacy runtime_config.json removal)** highlighted that the whole concept of "runtime_config.json with api_key inside" is hostile to security, reproducibility, and branch isolation.

Explicit direction from product owner:
> "All API keys and profile data must live in databases. Ensure the architecture contemplates the best databases — vector for LLM RAG, and for keys either the same or another — but nothing burned into code."

## Decision

### Principle
**Secrets and user profile data never live in JSON files on disk.** They live in databases or OS-native secret stores.

### Two separate storage backends

1. **Vector-capable relational store for profile and RAG**
   - **Choice: PostgreSQL + pgvector** (already in the stack, already frozen per `AGENTS.md`).
   - Stores: `user_profiles`, `achievements`, `document_chunks` with embeddings, `context_profiles`, `context_document_chunks`, sessions, turns, segments, brain_plans, emission_contracts, emissions, event_log.
   - Why not a separate vector DB (Qdrant, Weaviate, Pinecone)?
     - Adds an infra component for no measurable gain at 1–3 concurrent sessions.
     - pgvector with HNSW indexes is fine for <10M vectors.
     - Single backup story.

2. **Secret store for API keys**
   - **Choice (target): OS native secret store**
     - macOS: Keychain
     - Linux: Secret Service (libsecret)
     - Windows: Credential Manager
   - Backed by a tiny `secret_store.py` module exposing `get(key) / put(key, value) / delete(key)`.
   - **Fallback**: an **encrypted row in PostgreSQL** (`provider_credentials` table with `AES-GCM` ciphertext, key from env or OS keychain).
   - **Development fallback**: `~/.config/interview-coach/secrets.json` with file mode `0600` (never `git`-tracked, covered by `.gitignore`).

### Runtime config split

`runtime_config.json` is split:
- **Public config** (provider name, model name, enabled flag, latency params): stays in `~/.config/interview-coach/runtime_config.json`. Safe to share.
- **Secrets** (api_key, base_url with credentials, webhook tokens): moved to `secret_store` with a lookup key per provider (e.g. `llm:anthropic`, `stt:deepgram`).

The Pydantic `RuntimeConfig` model gains a helper:
```python
def resolve_with_secrets(self) -> ResolvedRuntimeConfig: ...
```
which hydrates api_key fields from `secret_store.get(f"{kind}:{provider}")` at call time. The in-memory resolved config is short-lived and never persisted.

### Profile storage

`user_profiles` and `interview_configs` stay in PostgreSQL (already schema). The frontend consumes them via `/api/profiles/*` endpoints (to be created in F3 as part of `api/http/session.py`).

The Tauri `localStorage` scoping (`storageProfile.ts`) continues to exist for **UI state only** (selected profile, last-used style, draft text). No credentials in browser/localStorage.

## Consequences

### Positive
- Accidental leaks via stashes, branch swaps, screenshots, editor history become harmless (keys are not in the file system of the project).
- Reproducibility: fresh clone + Keychain import = working dev environment.
- Security posture matches "full_response is primary artifact" product truth: the user is interviewing live, their key cannot be on a shared drive.
- Future multi-user / team support is easier: `provider_credentials` table already typed.

### Negative
- Slightly more complex onboarding: a dev must run `scripts/setup_secrets.sh` (to be written) that prompts and stores in Keychain.
- CI: must use env-var override (`INTERVIEW_COACH_SECRET_OVERRIDE_*`) to inject ephemeral secrets.

### Neutral
- pgvector choice is unchanged (already in stack).

## Alternatives considered

1. **Keep `runtime_config.json` with api_key** — rejected. Reason for this ADR.
2. **Use HashiCorp Vault locally** — over-engineered for single-user / local-first product.
3. **Encrypted SOPS files** — adds git-crypt-style complexity. Does not solve the UX of "just open the app".
4. **OS keychain only, no DB fallback** — fails for Linux servers in CI without libsecret.

## Implementation

Added to `execution_plan.yaml` as new F2 tasks:
- **F2-T17**: `persistence/secret_store.py` with backends (keychain, encrypted-DB, dev-file).
- **F2-T18**: Migrate `RuntimeConfig.api_key` fields to `secret_store`; UI Settings panel prompts and stores via backend endpoint.
- **F2-T19**: `scripts/setup_secrets.sh` for onboarding.
- **F2-T20**: Remove `api_key` field entirely from `RuntimeConfig` Pydantic model and `/api/runtime-config` endpoint payload. The endpoint still accepts `api_key` at write time but immediately pushes it to the secret store and never returns it.

## Compliance HR

- **HR-1**: no impact on live caption.
- **HR-2**: no impact on conversation history.
- **HR-3**: rollback plan: if secret_store fails, temporary env-var fallback (`ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`) per provider.
- **HR-4**: manual coach button still works — it only needs the resolved config, which is hydrated at request time.

## Rollback

- Feature flag `INTERVIEW_COACH_SECRET_STORE=disabled` falls back to env vars.
- Existing deployments with `runtime_config.json` on disk continue to work during the migration window. The legacy path is removed in the release following F2-T20.

## Metrics of success

- `git grep -E 'api_key.*sk-|api_key.*dg_'` returns no hits across the repo.
- Fresh clone + `scripts/setup_secrets.sh` produces a working dev environment without editing any JSON.
- GitHub secret scanning reports zero findings on `main`.

## References

- `docs/audit/AUDIT_REPORT.md` §1 CR-2
- `docs/adr/ADR-003-event-sourced-persistence.md`
- F1-T10 incident: Anthropic keys caught in stash patches
