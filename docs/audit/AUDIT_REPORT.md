# AUDIT REPORT — Interview Coach

> Auditoría técnica end-to-end, con evidencia de repo (archivo:línea o commit hash).
> Fecha: 2026-04-22. Autor: Principal Architect + Staff Engineer review.
> Cada hallazgo tiene severidad, causa raíz, evidencia, y recomendación.

---

## 0. TL;DR ejecutivo

El sistema tiene **7 causas raíz** que explican toda la fragilidad reportada. Ningún síntoma es sorprendente una vez vistas las causas.

| # | Causa raíz | Severidad | Síntomas que explica |
|---|---|---|---|
| CR-1 | Persistencia efímera por diseño (queue en memoria, exchanges post-hoc, sin turns/segments/events persistidos) | **Crítica** | "La persistencia se pierde", no hay replay, auditoría imposible |
| CR-2 | Config dual con fuente de verdad ambigua (XDG `~/.config/...` vs repo `python-core/runtime_config.json`) | **Alta** | "Cambiar de rama y perder configuración", API keys desaparecen |
| CR-3 | God-objects (`server.py` 13,129 LOC, `live_brain_service.py` 8,025 LOC, `App.tsx` 3,833 LOC) | **Crítica** | Merges destructivos entre ramas, "se pierden cosas al publicar" |
| CR-4 | `brain` y `emit` acoplados; `BrainPlan` con 40+ campos mezcla semántica y render | **Alta** | Respuesta live no sigue la intención, reintentos, churn de plan |
| CR-5 | Conversation/turn state solo vive en memoria (`HR-2` admite "transitional state") | **Alta** | Sin replay; no hay forma de reconstruir por qué el brain emitió X |
| CR-6 | Higiene del repo destruida (60+ ramas `codex/*`, binarios commiteados, stashes huérfanos, .gitignore 6 líneas) | **Alta** | Confusión operativa, PRs imposibles de revisar |
| CR-7 | Silencio + intención modelados como heurísticas dispersas añadidas por parches reactivos | **Alta** | Respuesta prematura / tardía, re-entry sobre streams, timing inestable |

Estado de bloqueo declarado en `config/status.json`:
- `database_connected: false`
- `live_product_e2e_validated: false`
- `desktop_audio_bridge: "partial"`
- `live_response_usefulness: "stub"`
- `live_session_persistence: "stub"`

---

## 1. Evidencia por causa raíz

### CR-1 — Persistencia efímera por diseño

**1.1 `persist_queue` es una lista Python en memoria.**
- `python-core/storage/persist_queue.py:59` — `self._queue: list[QueueItem] = []`
- Líneas 93–102 implementan una política **drop-oldest** cuando la cola supera 100 items → pérdida explícita de datos bajo presión, con solo un `logger.warning` como registro.
- El proceso muere → todo lo `PENDING` desaparece sin traza. No hay `file-backed queue` ni `outbox` durable.

**1.2 El pipeline solo persiste `exchanges` como resumen post-hoc.**
- `python-core/pipeline/realtime_pipeline.py:714` — `create_exchange(...)` con solo `interviewer_utterance + question_analysis + suggested_response + quality_result`.
- `python-core/storage/session_repo.py:66–99` — el método acepta únicamente esos campos. No hay API para `segments`, `turns`, `brain_plans`, `emissions`, `evidence_packs`.
- Si la sesión se corta a mitad de un turno, ese turno **no existe** en la DB.

**1.3 Existe `event_log` en el schema pero no se llena desde el pipeline real.**
- `python-core/storage/migrations/001_initial_schema.sql:150–157` — tabla `event_log` correctamente definida.
- `grep -n log_event python-core` produce UNA sola invocación real (`python-core/api/server.py:12843`), y está fuera del camino hot del live. El pipeline nunca escribe eventos.

**1.4 `database_connected: false` en estado canónico.**
- `config/status.json:runtime_state.database_connected = false`.
- `python-core/api/server.py:2064–2070` — al arrancar, si la DB falla, solo imprime un warning y continúa en modo degradado silencioso:
  ```python
  db_ok = await check_db_connection()
  if db_ok:
      print("[Interview Coach] Database connection: OK")
  else:
      print("[Interview Coach] Warning: Database connection failed")
  ```

**Severidad:** Crítica. El sistema no puede reconstruir su propia historia.

---

### CR-2 — Fuente de verdad ambigua para runtime config

**2.1 Dos lugares posibles de `runtime_config.json`.**
- `python-core/runtime_config_store.py` apunta por defecto a `~/.config/interview-coach/runtime_config.json` (XDG), con override por `INTERVIEW_COACH_RUNTIME_CONFIG_PATH`.
- `python-core/runtime_config.json` existe en el repo con API keys vacías. `runtime_config_store.py` lo trata como `_LEGACY_CONFIG_PATH`.

**2.2 Tres commits en 12 horas atacando el mismo bug.**
- `8191879b` — "fix: localize runtime config and honor settings model"
- `2005d7f9` — "fix: read stt runtime config from settings store"
- `eef8bfd6` — "fix: stabilize settings-backed runtime and launch"

**2.3 Divergencia real entre ramas por este tema.**
- `main..origin/codex/brain-intent-harden-2026-04-09 --stat` muestra cambios en `adapters/stt_adapter.py`, `api/server.py`, `runtime_config_store.py` simultáneos, cada uno con distinta precedencia de lectura.
- Cambiar de rama cambia qué archivo se lee primero → cambia el proveedor efectivo → la UI reporta "no configurado".

**Severidad:** Alta. La raíz del síntoma "al publicar, se pierden cosas".

---

### CR-3 — God-objects

**3.1 Tamaños literales (wc -l ejecutado):**
- `python-core/api/server.py` = **13,129 líneas**, 166 funciones top-level.
- `python-core/pipeline/steps/live_brain_service.py` = **8,025 líneas**.
- `python-core/pipeline/steps/live_finalizer.py` = 2,050 líneas.
- `python-core/pipeline/steps/response_composer.py` = 2,201 líneas.
- `python-core/pipeline/steps/live_question_planner.py` = 1,762 líneas.
- `python-core/pipeline/steps/insights_service.py` = 1,883 líneas.
- `python-core/adapters/stt_adapter.py` = 1,116 líneas.
- `tauri-app/src/App.tsx` = **3,833 líneas**.

**3.2 `server.py` concentra responsabilidades que deberían ser módulos separados:**
- Routing HTTP (rutas REST)
- WS session manager (`_LiveSessionSTTManager`, ~5000 LOC embebidas)
- Live caption (prohibido tocar por HR-1, pero mezclado en el mismo archivo)
- Orquestación del brain pipeline
- Insights endpoints
- Runtime config read/write
- Lifespan + startup checks

**3.3 Consecuencia operacional:** el diff `main..origin/feature/clean-turn-isolation` cambia **806 líneas** de `server.py`. Un `git merge` manual es prácticamente inviable sin pérdidas silenciosas — que es exactamente lo que el usuario reportó.

**Severidad:** Crítica. Es la raíz física del "se pierden cosas al mergear ramas".

---

### CR-4 — Brain y Emit acoplados; contrato sobrecargado

**4.1 `BrainPlan` v1 mezcla semántica y render.**
- `python-core/contracts/models.py` — la clase `BrainPlan` tiene **40+ campos**. Extracto:
  - Semántica: `ordered_asks`, `coverage_points`, `ask_intents`, `interviewer_need`, `response_requirement`, `question_scope`.
  - Render: `target_length`, `tone`, `directness`, `include_profile_opening`, `evidence_depth`, `metrics_policy`, `delivery_instructions`, `response_shape`.
- Campos con nombres casi idénticos: `resolved_question`, `literal_question`, `contextualized_question`. En la práctica el código usa los tres de forma inconsistente.

**4.2 `live_finalizer.py` (2,050 LOC) reinterpreta la intención.**
- Se supone que solo renderiza una respuesta a partir del plan. En realidad, al ver el tamaño y el hecho de que `live_brain_service.py` sigue tocando decisiones de render, no hay un boundary limpio.

**4.3 No existe `EmissionContract`.**
- Un contrato separado que diga "qué renderizar" (shape, tono, longitud, bullets preview, must_cover, avoid, evidence_pack_ref) nunca se creó. Todo vive dentro de `BrainPlan`.

**Severidad:** Alta. Explica la inestabilidad de la respuesta live respecto a la pregunta real.

---

### CR-5 — ConversationHistory solo en memoria

**5.1 El propio `AGENTS.md` lo admite (HR-2):**
> "Conversation History must be **persistently consultable** — via database, embeddings, or the most efficient mechanism available. In-memory-only history is acceptable only as a transitional state, not as the target architecture."

**5.2 `ConversationTracker` (`python-core/conversation/tracker.py`) mantiene historia en memoria.**
- No hay carga desde DB en cold start.
- No hay escritura en DB cada vez que se agrega un turn.

**5.3 Cuando el backend reinicia, la sesión arranca **en blanco**.**
- Aunque la tabla `sessions` exista, no hay `turns` ni `segments` para reconstruir el state.
- Los `exchanges` son resumen post-hoc, no sirven como rehidratación.

**Severidad:** Alta. Sin esto, replay y auditoría son imposibles.

---

### CR-6 — Higiene del repo

**6.1 Ramas (git branch -a --sort=-committerdate):**
- ~60 ramas `codex/*` + 15+ `stable-*` + feature branches.
- Muchas sin tag ni merge a `main`.
- Un número significativo comparte commit HEAD con otra rama (refs duplicadas).

**6.2 Binarios y artefactos commiteados por error.**
- `codex/brain-intent-harden-2026-04-09` (commit `9d00f486`) añadió `.DS_Store` × 12+, `node_modules/.DS_Store`, `.venv/.DS_Store`, `python-core/.venv/`, `orvantis-interview-coach`.
- `tauri-app/dist/` actualmente versionado en `main`.

**6.3 Working tree actual de `main`:**
- 68 archivos `.pyc` en `deleted:` staged.
- `patch_live_brain_stable.py` (32 KB) untracked en raíz.
- `tauri-app/dist/assets/index-DAiH4bEQ.js` deleted sin commit.
- Archivos de test huérfanos en raíz: `test_conversation_history_in_prompt.py`, `test_cv_text_flow.py`, `test_llm_direct.py`.

**6.4 `.gitignore` actual tiene 6 líneas:**
```
**/.DS_Store
**/__pycache__/
**/*.pyc
**/.pytest_cache/
**/node_modules/
tauri-app/src-tauri/target/
.runtime/
```
Falta: `.venv/`, `python-core/venv/`, `tauri-app/dist/`, `.next/`, `tsconfig.tsbuildinfo`, `bun.lock` (o fijar un manager único).

**6.5 Stashes huérfanos.**
- `refs/stash` presente; log muestra `41a86fbf`, `9d519886`, `9bfa4c68` como WIP de marzo sin limpiar.

**Severidad:** Alta. Ruido constante, merges imposibles, reviews inviables.

---

### CR-7 — Silencio e intención por parches reactivos

**7.1 `silence_detector.py` creció por iteración reactiva.**
- Versión actual: 491 líneas.
- Commits relevantes (cronológicos):
  - `22de66e9` "Do not reanchor silence on utterance-complete finals"
  - `da172247` "Cut silence-time wait on inflight warm"
  - `4fcf10b4` "Fix live silence anchor pre-emit latency"
  - `3d943f9c` "Guard live emit against reentry and resumed speech"
- Cada uno es un parche, no un rediseño.

**7.2 No existe `EndOfTurnDetector` multi-señal.**
- Hoy se usa silencio acústico + `cooldown_sec` del `runtime_config.json`.
- No se combina: `utterance_end` de Deepgram + estabilidad semántica entre finales consecutivos + umbral de duración.

**7.3 Intención progresiva no modelada.**
- Mientras el interviewer habla, no se mantiene una `AskHypothesis` que converja. El brain solo reacciona al `is_final=True`.
- No hay forma de generar un draft semi-estable antes del final sin emitirlo.

**7.4 Decisión de emitir basada en tiempo, no en evidencia.**
- `runtime_config.json` expone `utterance_end_ms`, `silence_threshold_ms`, `min_utterance_duration_ms`, `suggestion_cooldown_sec`. No hay `emit_readiness_score`.

**Severidad:** Alta. Es la raíz directa de las quejas sobre respuestas prematuras/tardías y mal timing.

---

## 2. Inventario de módulos y su estado real

| Módulo | LOC | Estado real | Observaciones |
|---|---|---|---|
| `python-core/api/server.py` | 13,129 | god-object | Necesita fragmentación en `api/http/*` y `api/ws/*`. HR-1 congelada vive aquí embebida. |
| `python-core/pipeline/steps/live_brain_service.py` | 8,025 | god-module | Fragmentar en `brain/*`. |
| `python-core/pipeline/steps/live_finalizer.py` | 2,050 | mezcla brain/emit | Migrar a `emit/*`. |
| `python-core/pipeline/steps/response_composer.py` | 2,201 | legado del modo manual | Coexiste con `live_finalizer` — responsabilidad ambigua. |
| `python-core/pipeline/steps/live_question_planner.py` | 1,762 | parte del brain | Integrar en `brain/planner.py` v2. |
| `python-core/pipeline/silence_detector.py` | 491 | heurística por parches | Reemplazar por `turn/end_of_turn.py`. |
| `python-core/conversation/tracker.py` | ~ | memoria only | Tiene que reconciliarse con `turns`+`segments` en DB. |
| `python-core/storage/*` | ~600 | parcial | `database.py` OK. `persist_queue.py` **no durable**. Ausencia total de turns/segments/events writers. |
| `python-core/adapters/stt_adapter.py` | 1,116 | **funcional** | Deepgram + Whisper local coexisten bien. No tocar. |
| `python-core/adapters/llm_adapter.py` | 535 | **funcional** | OK. |
| `python-core/observability/*` | 2 archivos | parcial | `latency.py` OK, falta tracing OTel y metrics Prometheus. |
| `tauri-app/src/App.tsx` | 3,833 | god-component | Descomponer por página/flow. |
| `tauri-app/src-tauri/src/audio/*` | ~700 | parcial | `macos_capture.rs`, `router.rs` existen pero el bridge e2e no está validado. |

---

## 3. Contratos actuales — problemas específicos

### 3.1 `BrainPlan` (archivo `python-core/contracts/models.py`)

Lista textual de campos (contados del código):
`session_id, utterance_id, revision_id, snapshot_hash, literal_question, contextualized_question, ordered_asks, coverage_points, raw_detected_asks, clause_classifications, supporting_interviewer_context, ask_intents, interviewer_need, response_requirement, question_scope, context_focus, response_family, answer_blueprint, alignment_brief, quality_guardrails, resolved_question, question_completeness, question_type, response_shape, answer_contract, delivery_instructions, tone, directness, include_profile_opening, evidence_depth, metrics_policy, company_context_policy, candidate_context_policy, ordered_coverage_required, target_length, draft_answer, serve_mode, confidence, stability_state, plan_source, generated_at, reasoning_summary, dropped_noise_clauses`.

= **43 campos** en una sola clase. Categorías detectadas:
- Identidad (6): session_id, utterance_id, revision_id, snapshot_hash, generated_at, reasoning_summary
- Semántica del ask (8): literal_question, contextualized_question, resolved_question, ordered_asks, coverage_points, raw_detected_asks, clause_classifications, supporting_interviewer_context
- Interpretación (4): ask_intents, interviewer_need, response_requirement, question_scope
- Plan estructural (4): context_focus, response_family, answer_blueprint, alignment_brief
- Quality (1): quality_guardrails
- **Render (11)**: question_completeness, question_type, response_shape, answer_contract, delivery_instructions, tone, directness, include_profile_opening, evidence_depth, metrics_policy, ordered_coverage_required
- Policies de contexto (2): company_context_policy, candidate_context_policy
- Draft (1): draft_answer
- Meta (4): target_length, serve_mode, confidence, stability_state, plan_source, dropped_noise_clauses

**Conclusión:** los 11 campos de render deben vivir en `EmissionContract`, no en `BrainPlan`.

### 3.2 Campos duplicados / nombres confusos

- `literal_question` vs `contextualized_question` vs `resolved_question`.
- `question_type` vs `response_family` vs `answer_contract` vs `answer_family`.
- `response_shape` vs `answer_shape` (aparece también en `LivePreparedContext`).

### 3.3 Otros contratos sobrecargados

- `LivePreparedContext` (~50 campos, clase en `contracts/models.py`).
- `AssembledContext` mezcla evidence, conversation history, style config, delivery mode, max_words, working_draft.

---

## 4. Persistencia — diagnóstico completo

### 4.1 Rutas de escritura existentes

| Origen | Destino | Durabilidad | Usado en live? |
|---|---|---|---|
| `pipeline/realtime_pipeline.py:714` | `exchanges` (PG) | Sí (si DB up) | No — el pipeline live no pasa por aquí |
| `api/server.py:12843` | `event_log` (PG) | Sí (si DB up) | Parcial (1 caso) |
| `storage/persist_queue.py` | memoria | **No** | Sí (pero se evapora) |
| `conversation/tracker.py` | memoria | **No** | Sí |
| `_LiveSessionSTTManager` (dentro de server.py) | memoria | **No** | Sí |

### 4.2 Lo que NO se persiste en DB hoy

- Segments (eventos STT finales).
- Turns (windows semánticas).
- BrainSnapshots (hash + history refs).
- BrainPlans (ni los "stable" ni los "draft").
- EmissionContracts (no existen siquiera como tipo).
- Evidence packs.
- Silence events.
- Intent hypotheses durante un turno.
- Config changes.

### 4.3 Migraciones con colisión de numeración

- `python-core/storage/migrations/001_initial_schema.sql`
- `python-core/storage/migrations/002_insights_workspace.sql`
- `python-core/storage/migrations/002_make_config_id_nullable.sql`

Dos migraciones con prefijo 002 → el orden depende del FS. Riesgo de idempotencia/drift.

Nunca se adoptó Alembic ni otro versionador. `docker-compose.yml` solo monta `/docker-entrypoint-initdb.d` → las migraciones corren una sola vez al crear el volumen; modificaciones posteriores **no se aplican** al volumen existente.

---

## 5. Live pipeline — diagnóstico de timing

### 5.1 Señales disponibles pero no unificadas

| Señal | Fuente | Uso actual |
|---|---|---|
| `utterance_end` | Deepgram | Usada parcialmente, con "anchors" y "guards" |
| Silencio acústico | RMS buffer en backend | Base de `silence_detector.py` |
| Estabilidad semántica | Sin implementar | — |
| Fin sintáctico (puntuación final) | Sin implementar | — |
| Duración del turno | Implícito | Sin tope configurable |

### 5.2 Decisión de emit

Gobernada por timers (`suggestion_cooldown_sec`, `silence_threshold_ms`). No por un `EmitReadiness` que combine:
- turn_closed
- brain_plan.stability == stable
- evidence retrieved
- language confirmed
- no emit pending

---

## 6. Impacto operacional vs funcional

| Causa raíz | Impacto operacional | Impacto funcional |
|---|---|---|
| CR-1 | Reinicios pierden trabajo; no hay replay | El coach no aprende entre sesiones |
| CR-2 | Dev cambia de rama y rompe setup | La UI reporta "no configurado" falsamente |
| CR-3 | Reviews y merges inviables | Bugfixes tardan días y regresan |
| CR-4 | Iteración lenta en brain | Respuesta no sigue la intención real |
| CR-5 | No se puede auditar | No hay base para mejorar prompts |
| CR-6 | Confusión sobre qué código es canónico | — |
| CR-7 | Latencia variable | Respuestas prematuras o tardías |

---

## 7. Recomendaciones (resumen, detalle en `IMPLEMENTATION_PLAN.md`)

1. **Higiene primero** (F1): `.gitignore` + limpieza + consolidación de ramas.
2. **Persistencia real** (F2): Alembic + tablas nuevas + outbox + fail-loud DB.
3. **Romper god-objects** (F3): sin cambiar semántica, solo fragmentar.
4. **Brain v2 + Emit separado** (F4): con feature flag y A/B.
5. **Observability + replay** (F5): OTel + Prometheus + CLI de replay.
6. **Desktop audio blocker** (F6): solo después de tener persistencia + modularidad.

Ver `IMPLEMENTATION_PLAN.md` y `execution_plan.yaml` para tasks atómicas con criterios de aceptación.

---

## 8. Qué NO debe tocarse (por HR)

- `_handle_display_event()` en `python-core/api/server.py` (HR-1)
- El WS message type `live_caption` (HR-1)
- Streaming Deepgram para live caption (HR-1)
- `tauri-app/src/App.tsx` live caption rendering (HR-1) → solo descomponer el *resto* de App.tsx manteniendo el live caption intacto

## 9. Hipótesis separadas de hechos (honestidad)

- **Hipótesis (no probado):** `live_finalizer.py` hace llamadas LLM redundantes cuando el brain rehace el plan en tail churn. Requiere instrumentación en F5.
- **Hipótesis (no probado):** el bridge de audio macOS vía `router.rs` funciona con mic pero no con system audio en algunas combinaciones de Zoom/Meet. Requiere prueba controlada en F6.
- **Hipótesis (no probado):** algunos de los 55+ branches `codex/*` tienen fixes valiosos que se perdieron. Requiere revisión de cada commit en F1 antes de archivar.
