# BRANCH FORENSICS — Interview Coach

> Estado real de ramas, drift, riesgo y política de consolidación.
> Fecha: 2026-04-22. Basado en `git branch -a --sort=-committerdate`, `git log --all`, `git diff --stat`.

---

## 1. Inventario actual

- **Total refs**: 62 (locales + remotas, excluye `HEAD`).
- **Ramas locales únicas**: ~39 (excluyendo duplicados local/remoto).
- **Tags**: 17 (`stable-*`, `stable-live-*`, `stable-live-brain-*`).
- **Stashes huérfanos**: 3 commits en `refs/stash` (`41a86fbf`, `9d519886`, `9bfa4c68`, marzo 2026).
- **Working tree de `main`**: sucio (68 `.pyc` staged deleted, varios archivos modificados sin commit).

## 2. Clasificación por bucket

### 2.1 Canónica
| Rama | HEAD | Fecha | Acción |
|---|---|---|---|
| `main` | `734400f0` | 2026-04-13 | Mantener. Limpiar working tree en F1-T1. |

### 2.2 Candidatas a merge (drift valioso)
| Rama | HEAD | Diff vs main | Acción |
|---|---|---|---|
| `feature/clean-turn-isolation` | `aae81ce9` | 806 LOC en `server.py`, 403 en `silence_detector.py` | **Cherry-pick por archivo** (no merge directo) |
| `codex/brain-silence-window-reset-2026-04-09` | `cefec7c9` | Fix reset de window al revisar interviewer | **Cherry-pick** si aplica limpio |
| `codex/brain-intent-clean-2026-04-09` | `eef8bfd6` | Settings-backed runtime | Consolidar con `2005d7f9`/`8191879b` en **un solo commit** |

### 2.3 Últimas snapshots estables (solo tag)
| Rama | Tag equivalente | Acción |
|---|---|---|
| `codex/stable-live-2026-04-08` | `stable-live-2026-04-08` | **Borrar rama** — tag suficiente |
| `codex/stable-live-2026-04-08-publish` | mismo commit | **Borrar rama** |
| `codex/stable-live-brain-2026-04-06-semantic-contract-v2-baseline` | `stable-live-brain-2026-04-06-semantic-contract-v2` | **Borrar rama** |
| `codex/stable-2026-04-06-brain-proof-baseline` | `stable-2026-04-06-brain-proof-baseline` | **Borrar rama** |
| `codex/stable-2026-04-01-brain-response-refine-v3` | `stable-2026-04-01-brain-response-refine-v3` | **Borrar rama** |
| `codex/stable-live-brain-2026-03-25..30..31..*` | `stable-live-brain-*` múltiples | **Borrar ramas** |

### 2.4 Ramas experimentales muertas (sin tag, sin merge, sin valor claro)
Lista completa (15+):

```
codex/brain-semantic-contract-refactor
codex/c5a20994-parsing-only
codex/c5a20994-single-path-brain
codex/brain-context-maximizer
codex/brain-response-refine-next
codex/brain-plan-hash-stability
codex/semi-stable-2026-03-31-live-brain-contract
codex/stable-2026-04-01-brain-hash-fix
codex/dev-cv-fallback-profile-fix-v1
codex/dev-insights-guided-workspace-v1
codex/dev-insights-isolation-fix-v1
codex/dev-insights-module-v1
codex/dev-post-silence-emit-only-v1
codex/dev-prepare-source-of-truth-v1
codex/dev-live-emit-visible-latency-v1
codex/dev-live-emit-after-silence-stream-safe-v1
codex/dev-live-post-silence-only-from-stable-22de66e9
codex/dev-live-silence-anchor-v1
codex/dev-live-latency-pre-emit-v1
codex/dev-live-token-governance-v2
codex/dev-brain-response-requirements-v1
codex/dev-brain-intent-engine-v1
codex/dev-brain-llm-first-v1
codex/dev-live-brain-quality-v1
codex/checkpoint-live-brain-before-finalizer-fix-20260326
codex/checkpoint-live-brain-pre-cleanup-20260326
codex/dev-live-brain-next
codex/archive-main-before-2026-03-31-post-silence-emit-stream-guard
codex/dev-live-brain-latency
codex/dev-brain-intent-proof-next
codex/freeze-2026-04-06-brain-current-state
codex/deterministic-main-isolation
codex/live-brain-runtime-hardening
codex/pre-stable-live-brain-2026-03-27-recovered-brain-baseline
```

**Acción**: archivar a `refs/archive/codex/<name>` y borrar localmente y en remoto. El SHA sigue accesible vía el ref de archivo.

### 2.5 Ramas contaminadas (binarios commiteados)
| Rama | Problema |
|---|---|
| `codex/brain-intent-harden-2026-04-09` | `node_modules/.DS_Store` × 12+, `.venv/.DS_Store`, `python-core/.venv/`, `orvantis-interview-coach`, `.DS_Store` múltiples |
| `claude/compassionate-driscoll` | Verificar antes de decidir; comparte HEAD con `codex/brain-intent-clean-2026-04-09` |

**Acción**: cherry-pick **solo los cambios `.py`** útiles; el resto se descarta. Archivar rama completa.

---

## 3. Drift concreto entre `main` y ramas activas

### 3.1 `main..origin/feature/clean-turn-isolation --stat` (extracto real)

| Archivo | LOC cambiadas | Tipo |
|---|---|---|
| `python-core/api/server.py` | 806 | reduce |
| `python-core/pipeline/silence_detector.py` | 403 | reduce |
| `python-core/conversation/tracker.py` | 139 | refactor |
| `python-core/pipeline/steps/live_brain_service.py` | 52 | refactor |
| `python-core/pipeline/steps/live_question_planner.py` | 65 | refactor |
| `python-core/adapters/provider_registry.py` | 33 | refactor |
| `python-core/contracts/models.py` | 3 | fix |
| `tauri-app/src/App.tsx` | 20 | refactor |
| `CURRENT_FUNCTIONAL_STATE_2026-04-13.md` | 244 | delete |

**Interpretación**: la rama es una **reducción** de código ya aplicada sobre main. El riesgo no es semántico sino mecánico — el merge de 806 líneas en `server.py` se sobrepone con cambios actuales no commiteados.

### 3.2 `main..origin/codex/brain-intent-harden-2026-04-09 --stat` (extracto real)

Cambios útiles (revisar):
- `python-core/adapters/llm_adapter.py` (71 LOC)
- `python-core/adapters/stt_adapter.py` (10 LOC)
- `python-core/adapters/provider_registry.py` (33 LOC)
- `python-core/api/server.py` (991 LOC, mayoría reducción)
- `python-core/contracts/models.py` (19 LOC)

Contaminación:
- 20+ archivos `.DS_Store` añadidos
- `node_modules/` referenciado
- `orvantis-interview-coach` (entrada misteriosa en raíz; debe ser ignorada)

---

## 4. Política de consolidación (decisión: rebase selectivo)

### 4.1 Paso 0 — Safety net

```bash
git fetch --all --prune
git tag archive/main-before-consolidation-2026-04-22 main
git push origin archive/main-before-consolidation-2026-04-22
```

### 4.2 Paso 1 — Limpiar working tree de `main`

- Descartar `.pyc` staged deleted (son artefactos).
- Decidir por archivo los siguientes uncommitted changes:
  - `.gitignore` modificado → incorporar en el **endurecimiento** (F1-T1).
  - `package.json` modificado → revisar si es intencional (manager único); si sí, commit en F1.
  - `python-core/adapters/stt_adapter.py` modificado → revisar diff, decidir.
  - `python-core/api/server.py` modificado → revisar diff, decidir.
  - `python-core/runtime_config_store.py` modificado → revisar diff, decidir.
  - `tauri-app/src/App.tsx` modificado → revisar diff, decidir.
  - `tauri-app/src/hooks/usePersistedState.ts` modificado → revisar diff, decidir.
  - `tauri-app/src/lib/persistence.ts` modificado → revisar diff, decidir.
  - `tests/unit/test_runtime_config_store.py` modificado → revisar diff, decidir.
- Mover untracked de raíz a cuarentena:
  - `INTERVIEW_COACH_HANDOFF_2026-04-08.md` → `docs/handoffs/2026-04-08.md` o `tmp/quarantine/`.
  - `PLAN_BRAIN_IMPROVEMENT_2026-04-08.md` → `docs/plans-archive/` (si tiene valor histórico).
  - `patch_live_brain_stable.py` → `tmp/quarantine/` (32 KB en raíz no puede quedarse).
  - `python-core/runtime_flags.py` → si se usa, commitear en F1; si no, borrar.
  - `scripts/profile_stack.sh` → commitear o borrar.
  - `tauri-app/scripts/` → commitear o borrar.
  - `tauri-app/src/lib/storageProfile.ts` → commitear o borrar.
- Commit de limpieza:
  ```bash
  git add -A
  git commit -m "chore(repo): clean working tree and quarantine loose files"
  ```

### 4.3 Paso 2 — Endurecer `.gitignore` y `.gitattributes`

`.gitignore` target (en F1-T1):
```
# OS / editors
**/.DS_Store
**/Thumbs.db
**/.vscode/
**/.idea/

# Python
**/__pycache__/
**/*.pyc
**/*.pyo
**/*.egg-info/
**/.pytest_cache/
**/.mypy_cache/
**/.ruff_cache/
**/.venv/
python-core/venv/
python-core/.venv/

# Node
**/node_modules/
**/.next/
**/npm-debug.log*
**/pnpm-debug.log*
**/yarn-debug.log*

# Tauri / Rust
tauri-app/src-tauri/target/
tauri-app/dist/
tauri-app/node_modules/

# TypeScript
**/tsconfig.tsbuildinfo

# Runtime / local
.runtime/
.kilo.local.env

# Backups de build
**/*.tmp
**/*.bak
```

`.gitattributes` nuevo:
```
* text=auto eol=lf
*.png binary
*.jpg binary
*.docx binary
*.pdf binary
*.lock -text
```

### 4.4 Paso 3 — Crear rama de trabajo

```bash
git checkout -b consolidation/v2 main
```

### 4.5 Paso 4 — Cherry-pick ordenado

**Orden canónico** (probado con `git cherry-pick --no-commit` + review):

1. **`cefec7c9` — brain-silence-window-reset**
   - Esperar cero conflictos (solo toca `live_brain_service.py`).
   - Si conflicto, abortar y dejar para F4.

2. **Consolidación config (3 commits en 1)**
   - Aplicar cambios de `8191879b` + `2005d7f9` + `eef8bfd6` manualmente sobre un archivo único.
   - Commit: `chore(config): single-source runtime config via XDG`.

3. **`aae81ce9` — feature/clean-turn-isolation** (cuidado)
   - `git cherry-pick --no-commit aae81ce9`
   - Si conflicto en `server.py`, revisar hunk por hunk (recordar HR-1 sobre `_handle_display_event`).
   - Commit por archivo:
     - `refactor(silence): isolate turn window logic`
     - `refactor(server): drop dead WS scaffolding`
     - `refactor(tracker): simplify state transitions`
     - `chore(contracts): minor trim`

4. **Código útil de `codex/brain-intent-harden-2026-04-09`** (manual)
   - **No** usar `cherry-pick` directo (arrastra binarios).
   - Crear patch con `git show 9d00f486 -- python-core/adapters python-core/contracts python-core/api/server.py`
   - Revisar, aplicar, commitear aparte.

5. **Validar**
   ```bash
   pytest tests/ -q
   python -m pyflakes python-core/ || true
   ```

### 4.6 Paso 5 — Fast-forward a `main`

```bash
git checkout main
git merge --ff-only consolidation/v2
git push origin main
git branch -d consolidation/v2
```

### 4.7 Paso 6 — Archivar resto

Script `scripts/archive_stale_branches.sh` (se crea en F1-T1):

```bash
#!/usr/bin/env bash
set -euo pipefail

# Ramas a archivar (listas en 2.4 + 2.3 + 2.5)
STALE_BRANCHES=$(cat <<'EOF'
codex/brain-semantic-contract-refactor
codex/c5a20994-parsing-only
codex/c5a20994-single-path-brain
# ... (completa)
EOF
)

for branch in $STALE_BRANCHES; do
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    sha=$(git rev-parse "$branch")
    git update-ref "refs/archive/$branch" "$sha"
    git branch -D "$branch"
    echo "Archived $branch -> refs/archive/$branch ($sha)"
  fi
  # Borrar también remoto si existe
  if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    git push origin --delete "$branch" || echo "skip remote $branch"
  fi
done
```

### 4.8 Paso 7 — Limpiar stashes

```bash
git stash list
# Revisar cada uno manualmente
git stash drop N  # o mantener si tiene valor
```

---

## 5. Riesgo por rama (matriz)

| Rama | Probabilidad de valor | Costo de evaluar | Riesgo si se archiva sin revisar |
|---|---|---|---|
| `feature/clean-turn-isolation` | **Alta** | Medio | Alto — contiene reducción útil |
| `codex/brain-silence-window-reset-2026-04-09` | **Alta** | Bajo | Medio — un fix aislado |
| `codex/brain-intent-clean-2026-04-09` | Media | Bajo | Bajo — ya aplicado en main parcialmente |
| `codex/brain-intent-harden-2026-04-09` | Media | Medio | Medio — contaminado, extraer solo `.py` |
| `claude/compassionate-driscoll` | Baja | Bajo | Bajo |
| `codex/live-brain-runtime-hardening` | Baja | Bajo | Bajo |
| `codex/dev-*` (15+) | Baja | Medio (muchas) | Bajo si archivo |
| `codex/stable-live-*` | Nula (ya tag) | Nulo | Nulo |
| `codex/checkpoint-*` | Nula | Nulo | Nulo |

---

## 6. Criterios de aceptación de Fase 1

- `git branch --list 'codex/*' | wc -l` = 0 (salvo ramas activas residuales aprobadas explícitamente).
- `git status` en `main` limpio.
- `pytest tests/ -q` verde.
- `.gitignore` contiene todas las entradas listadas en 4.3.
- Tags `stable-*` intactos (17 preservados).
- Refs `archive/*` creados para cada rama archivada.
- Tag `archive/main-before-consolidation-2026-04-22` pusheado a remoto.

---

## 7. Ramas a **decidir explícitamente con el usuario** antes de archivar

Para evitar perder contexto de 2 ramas que comparten HEADs recientes:

- `claude/compassionate-driscoll` (+ icon = ahead of something): ¿conservar?
- `codex/brain-intent-harden-2026-04-09` (contaminada pero reciente): **extract-only**.
- `codex/deterministic-main-isolation`: nombre sugiere trabajo actual.

La Fase 1 se pausa en el paso 6 para confirmación antes de archivar estas 3.

---

## 8. Observaciones adicionales

### 8.1 Duplicación local/remota
Varias ramas aparecen como local + remote con mismo HEAD:
- `codex/stable-live-2026-04-08` y `origin/codex/stable-live-2026-04-08`
- `codex/stable-live-2026-04-08-publish` y su remoto
- `codex/brain-silence-window-reset-2026-04-09` y su remoto

Archivar local primero, luego `git push origin --delete <branch>`.

### 8.2 Tags redundantes
Los siguientes tags comparten commit con otros:
- `stable-live-brain-2026-03-30-real-stable-baseline` y `stable-live-brain-2026-03-30-silence-anchor-improved` (mismo commit `22de66e9`).
- `stable-live-2026-04-08` y la rama `codex/stable-live-2026-04-08-publish`.

No se borran tags (son historia). Solo se borran ramas apuntando a ellos.

### 8.3 Tag faltante propuesto
`stable-live-brain-2026-04-08` (commit de `main` `734400f0`) — el estado actual no tiene tag. Proponerlo en F1-T2:

```bash
git tag -a stable-live-brain-2026-04-13 734400f0 -m "Snapshot pre-consolidation"
git push origin stable-live-brain-2026-04-13
```
