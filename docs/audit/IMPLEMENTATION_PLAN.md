# IMPLEMENTATION PLAN — Interview Coach v4.0

> Plan de ejecución por fases. Cada fase tiene tasks atómicas con criterios de aceptación y rollback. El backlog machine-readable está en `execution_plan.yaml`.

---

## Fases

| Fase | Nombre | Duración estimada | Dependencias |
|---|---|---|---|
| F0 | Audit artifacts | 1 día (ejecución actual) | — |
| F1 | Repo hygiene + branch consolidation | 2–3 días | F0 |
| F2 | Real persistence | 3–5 días | F1 |
| F3 | Break god-objects | 5–7 días | F2 |
| F4 | Brain v2 + Emit separation + EndOfTurnDetector | 5–10 días | F3 |
| F5 | Observability + replay | 3–5 días | F4 |
| F6 | Close desktop audio blocker | 3–7 días | F2 (mín) |

---

## Fase 0 — Audit artifacts (actual)

**Objetivo:** materializar los 11 artefactos de auditoría en el repo.

### Tasks

| ID | Tarea | Archivo | Aceptación |
|---|---|---|---|
| F0-T1 | AUDIT_REPORT.md | `docs/audit/AUDIT_REPORT.md` | Cubre CR-1..CR-7 con evidencia `file:line` o commit hash |
| F0-T2 | BRANCH_FORENSICS.md | `docs/audit/BRANCH_FORENSICS.md` | Lista 39+ branches con acción por cada una |
| F0-T3 | TARGET_ARCHITECTURE.md | `docs/audit/TARGET_ARCHITECTURE.md` | Contiene módulo map, boundaries, contratos v2 |
| F0-T4 | LIVE_PIPELINE_REDESIGN.md | `docs/audit/LIVE_PIPELINE_REDESIGN.md` | EndOfTurnDetector + IntentTracker + emit gate |
| F0-T5 | DATA_MODEL_REDESIGN.md | `docs/audit/DATA_MODEL_REDESIGN.md` | Alembic + tablas nuevas + outbox |
| F0-T6 | IMPLEMENTATION_PLAN.md | `docs/audit/IMPLEMENTATION_PLAN.md` | (este archivo) |
| F0-T7 | execution_plan.yaml | `docs/audit/execution_plan.yaml` | Backlog machine-readable |
| F0-T8 | status.json actualizado | `config/status.json` | Refleja v4.0 draft y phases F0..F6 |
| F0-T9 | ADR-001 | `docs/adr/ADR-001-brain-emit-separation.md` | — |
| F0-T10 | ADR-002 | `docs/adr/ADR-002-stt-provider-strategy.md` | — |
| F0-T11 | ADR-003 | `docs/adr/ADR-003-event-sourced-persistence.md` | — |

**Criterio global F0:** 11 archivos existen, bien linkeados entre sí.

---

## Fase 1 — Repo hygiene + branch consolidation

**Objetivo:** dejar `main` limpio, ramas consolidadas, política de `.gitignore` aplicada, binarios commiteados removidos del head.

### Pre-requisitos
- F0 completada.
- Respaldo manual del directorio `~/.config/interview-coach/` (copia a `backup/xdg-config-2026-04-22/` fuera del repo).

### Tasks

| ID | Tarea | Notas |
|---|---|---|
| F1-T1 | Endurecer `.gitignore` + crear `.gitattributes` | Ver shapes en BRANCH_FORENSICS.md §4.3 |
| F1-T2 | Tag `archive/main-before-consolidation-2026-04-22` + tag `stable-live-brain-2026-04-13` | Safety net |
| F1-T3 | Limpiar working tree de `main` | Mover archivos loose a `tmp/quarantine/` o `deprecated/` |
| F1-T4 | Crear rama `consolidation/v2` | desde `main` |
| F1-T5 | Cherry-pick ordenado | `cefec7c9`, consolidación config (3→1 commit), `aae81ce9` por archivo, código útil de `9d00f486` manual |
| F1-T6 | Correr `pytest tests/ -q` | Debe pasar |
| F1-T7 | Merge `--ff-only` a `main`; push; borrar `consolidation/v2` | — |
| F1-T8 | Script `scripts/archive_stale_branches.sh` + ejecutar | Archiva 30+ ramas a `refs/archive/*` |
| F1-T9 | Decisión explícita sobre 3 branches frontera | `claude/compassionate-driscoll`, `codex/deterministic-main-isolation`, `codex/brain-intent-harden` (contaminada) |
| F1-T10 | `git stash list` → drop o preservar | Marzo WIPs huérfanos |
| F1-T11 | Unificar package manager | Decidir entre `bun`, `pnpm`, `npm` y borrar los demás lockfiles |
| F1-T12 | Borrar `python-core/runtime_config.json` del repo (mover a `deprecated/`) | Único source via XDG tras F2 |

### Criterios de aceptación
- `git branch --list 'codex/*' | wc -l` = 0 (o justificadas las excepciones).
- `git status` limpio en `main`.
- `pytest tests/ -q` verde.
- `grep -r "\.DS_Store" $(git ls-files)` sin resultados.
- `tauri-app/dist/` ignorado o removido.
- Tag `archive/main-before-consolidation-2026-04-22` pusheado.

### Rollback
```bash
git reset --hard archive/main-before-consolidation-2026-04-22
git push --force-with-lease origin main   # SOLO con aprobación explícita del owner
```
Ramas archivadas recuperables vía `git checkout refs/archive/codex/<name>`.

---

## Fase 2 — Real persistence

**Objetivo:** DB encendida, Alembic adoptado, tablas nuevas creadas, outbox implementado, event_log poblado desde el pipeline real, config runtime único (XDG).

### Tasks

| ID | Tarea | Aceptación |
|---|---|---|
| F2-T1 | Añadir `alembic` a `pyproject.toml`; inicializar `python-core/persistence/migrations/` | `alembic init` ejecutado, `env.py` wired |
| F2-T2 | Migración `20260422_01_baseline.py` | Copia SQL de 001+002 actuales, idempotente |
| F2-T3 | Migración `20260422_02_turns_events.py` | Tablas: turns, segments, brain_plans, evidence_packs, emission_contracts, emissions, event_log (v2), outbox, contract_versions |
| F2-T4 | Migración `20260422_03_latency_extensions.py` | `latency_metrics.turn_id`, `latency_metrics.trace_id`, vista `exchanges_compat` |
| F2-T5 | `python-core/persistence/db.py` | Pool asyncpg; fail-loud en startup salvo flag `INTERVIEW_COACH_DB_REQUIRED=false` |
| F2-T6 | `python-core/persistence/outbox.py` | Enqueue + worker + file fallback (`.runtime/outbox.ndjson`) |
| F2-T7 | `python-core/persistence/event_writer.py` | `write(event: PipelineEvent)` → event_log + outbox |
| F2-T8 | `python-core/persistence/session_store.py` | CRUD sessions, turns, segments, brain_plans, etc. |
| F2-T9 | `python-core/config/runtime.py` | Única fuente (XDG), sanitización, hash SHA256 atómico |
| F2-T10 | `python-core/config/providers.py` | Loader de `config/providers.yaml` |
| F2-T11 | Migrar `storage/persist_queue.py` → eliminar usos; redirigir a `outbox.enqueue` | `persist_queue.py` deprecado |
| F2-T12 | `docker-compose.yml` — quitar mount `/docker-entrypoint-initdb.d`; añadir `alembic upgrade head` en `command` del backend | Container up limpio |
| F2-T13 | Script `scripts/migrate_exchanges_to_v2.py` | Best-effort: para cada exchange histórica, crea turn + plan + contract + emission (trace_id prefijo `migrated:`) |
| F2-T14 | Script `scripts/run_db_smoke.py` | Crea sesión fake + 3 turnos + verifica conteos de tablas |
| F2-T15 | Test `tests/integration/test_persistence_roundtrip.py` | Crea sesión en memoria, verifica persistencia + restart |
| F2-T16 | Test `tests/integration/test_outbox_resilience.py` | Cae DB → escribe NDJSON → DB up → drain |

### Criterios de aceptación
- `alembic upgrade head` idempotente en DB limpia y en DB con 001+002.
- Tabla `event_log` tiene ≥20 rows tras una sesión de 3 turnos.
- Killing backend mid-session y reiniciando → no hay pérdida de datos (reconciliado desde NDJSON).
- `status.json.runtime_state.database_connected = true`.

### Rollback
- Quitar migración `20260422_02` y `20260422_03` con `alembic downgrade 20260422_01_baseline`.
- Restaurar `storage/persist_queue.py` desde git.
- `INTERVIEW_COACH_DB_REQUIRED=false` permite degradar temporalmente.

---

## Fase 3 — Break god-objects (sin cambio semántico)

**Objetivo:** fragmentar `server.py` (13,129 LOC) y `App.tsx` (3,833 LOC). Sin alterar comportamiento observable.

### Tasks backend

| ID | Tarea | Target LOC |
|---|---|---|
| F3-T1 | Extraer `_LiveSessionSTTManager` de `server.py` → `pipeline/orchestrator.py` | orchestrator.py ≤ 1500 LOC |
| F3-T2 | Separar rutas HTTP → `api/http/{health,runtime_config,session,coach,insights}.py` | server.py sin rutas inline |
| F3-T3 | Separar WS → `api/ws/live_session.py` | Solo recibe eventos, delega al orchestrator |
| F3-T4 | `api/ws/live_caption.py` — copy EXACTO de `_handle_display_event` + handlers relacionados; marcar `# FROZEN per HR-1`. Test de regresión. | No cambio de comportamiento |
| F3-T5 | `api/__init__.py` factory: `create_app()` ensambla http/ + ws/, aplica middlewares, `lifespan` consolidado | `server.py` deja de existir como punto de entrada |
| F3-T6 | `main.py` nuevo entrypoint delegando a `api.create_app()` | — |

### Tasks frontend

| ID | Tarea | Target LOC |
|---|---|---|
| F3-T7 | Descomponer `App.tsx` en `<LiveSession/>`, `<ManualCoach/>`, `<Settings/>`, `<Insights/>` + router | App.tsx ≤ 400 |
| F3-T8 | Hook `useWsSession` dedicado para manejo WS y reconexión | Reutilizable |
| F3-T9 | Extraer reconciliación de turns a `hooks/useConversationState.ts` | — |
| F3-T10 | Mantener live caption rendering intacto (HR-1) en componente aislado `<LiveCaption/>` | No tocar lógica interna |

### Criterios de aceptación
- `wc -l python-core/api/server.py` ya no aplica (archivo dividido).
- `wc -l python-core/api/__init__.py` ≤ 200.
- `wc -l tauri-app/src/App.tsx` ≤ 400.
- Todos los tests existentes pasan sin modificación.
- Smoke test: arranca backend + Tauri, se crea sesión, se ve live caption funcionando igual que antes.
- Nuevo test `tests/integration/test_live_caption_frozen.py` verifica que el mensaje `live_caption` WS tiene exactamente el mismo shape que antes.

### Rollback
- Git revert de los commits de F3 (uno por task). Mantener el refactor en ramas separadas hasta que el smoke test e2e pase.

---

## Fase 4 — Brain v2 + Emit separation + EndOfTurnDetector

**Objetivo:** crear `brain/`, `emit/`, `turn/` como módulos separados; contratos v2; feature flag; EndOfTurnDetector multi-señal.

### Tasks

| ID | Tarea |
|---|---|
| F4-T1 | `contracts/v2/{brain_plan,emission_contract,generated_response,events}.py` |
| F4-T2 | `brain/intent_tracker.py` con `AskHypothesis` |
| F4-T3 | `brain/ask_decomposer.py` |
| F4-T4 | `brain/context_window.py` (HR-2 compliant, DB-backed) |
| F4-T5 | `brain/planner.py` con `plan_from_turn` y `plan_draft_from_hypothesis` |
| F4-T6 | `brain/quality.py` gate |
| F4-T7 | `emit/emission_contract.py` model |
| F4-T8 | `emit/builder.py` transformación BrainPlan → EmissionContract |
| F4-T9 | `emit/quality_gate.py` (readiness score) |
| F4-T10 | `emit/renderer.py` (LLM call + style) |
| F4-T11 | `emit/style.py` |
| F4-T12 | `turn/segment.py`, `turn/turn.py` models |
| F4-T13 | `turn/assembler.py` |
| F4-T14 | `turn/end_of_turn.py` multi-signal detector |
| F4-T15 | Feature flag `INTERVIEW_COACH_BRAIN_V2` en `config/runtime.py` |
| F4-T16 | Cutover en `pipeline/orchestrator.py`: if flag → v2 path, else → legacy |
| F4-T17 | Tests unit: `test_end_of_turn_detector.py`, `test_intent_tracker.py`, `test_planner_deterministic.py`, `test_builder_from_plan.py`, `test_emit_readiness.py` |
| F4-T18 | Test integration: `test_pipeline_v2_end_to_end.py` |
| F4-T19 | Dashboard A/B (logs + métricas locales) para comparar v1 vs v2 en 50 preguntas fixture |

### Criterios de aceptación
- Con flag ON, una pregunta sintética genera: segments, turn, brain_plan, emission_contract, emission, event_log entries.
- `BrainPlan v2` no contiene ningún campo de render (test automático).
- Latencia p50 v2 ≤ legacy + 10% en fixtures.
- Quality passing rate v2 ≥ legacy - 5% en fixtures.
- Live caption no toca (HR-1 verificado).

### Criterios de cutover
- Feature flag default=true solo tras:
  - 2 semanas de uso local sin regresiones.
  - Métricas `ic_emit_prematures_total` y `ic_emit_late_total` ≤ 5% en sesiones reales.

### Rollback
- `INTERVIEW_COACH_BRAIN_V2=false` y reinicio. Path legacy retorna intacto.

---

## Fase 5 — Observability + replay

**Objetivo:** tracing OTel, métricas Prometheus, CLI replay, dashboards locales.

### Tasks

| ID | Tarea |
|---|---|
| F5-T1 | `observability/tracing.py` con OpenTelemetry, exporter Jaeger/OTLP |
| F5-T2 | `observability/metrics.py` con `prometheus_client` |
| F5-T3 | `observability/logs.py` estructurado JSON |
| F5-T4 | Endpoint `/metrics` expuesto en FastAPI |
| F5-T5 | `docker-compose.yml` añadir servicio `jaeger` y `grafana` + `prometheus` (perfil `dev`) |
| F5-T6 | Script `scripts/replay_session.py <session_id>` — modo plan-only, compara con DB |
| F5-T7 | Grafana dashboards versionados en `docs/observability/dashboards/*.json` |

### Criterios
- `/metrics` devuelve métricas listadas en TARGET_ARCHITECTURE §7.1.
- Jaeger muestra traces con spans `stt → turn → brain → emit → render`.
- `replay_session.py` sobre una sesión grabada reconstruye los brain_plans con diff ≤ 5% semántico.

---

## Fase 6 — Desktop audio blocker

**Objetivo:** cerrar el blocker real — pipeline live end-to-end con system audio de Zoom/Teams.

### Tasks

| ID | Tarea |
|---|---|
| F6-T1 | Validación de `macos_capture.rs` + `router.rs` con test automatizado usando un loopback de Audio Hijack o BlackHole |
| F6-T2 | Métricas en `audio/ingest.py`: `ic_audio_chunks_received_total{source=system|mic}`, RMS histogram |
| F6-T3 | Grabación de referencia (10 min de meeting simulado) → pipeline completo → validar `emissions` table |
| F6-T4 | Banner UI si `audio_chunks_received_total == 0 durante 5s en sesión activa` |
| F6-T5 | Permisos macOS documentados y automatizados donde posible (`tauri-app/src-tauri/src/audio/permissions.rs`) |

### Criterios
- 10 minutos de Zoom real → ≥80 segments con language detected correcto.
- UI muestra respuestas coherentes con las preguntas reales (`live_product_e2e_validated: true`).
- Métrica `ic_emit_prematures_total` ≤ 3 en 10 min.

---

## Dependencias

```
F0 ──> F1 ──> F2 ──> F3 ──> F4 ──> F5
                └──> F6 (a partir de F2, en paralelo a F3/F4)
```

## Riesgos globales

| Riesgo | Mitigación |
|---|---|
| Usuario quiere demo pronto | F2+F3 dan sistema más estable en 1–2 semanas. F4 es donde el impacto de calidad se ve. |
| F3 (god-objects) rompe live caption | Test de regresión HR-1 específico antes de merge. |
| F4 Brain v2 subjetivamente peor | A/B local + feature flag + rollback atómico. |
| F6 macOS system audio inestable | Diagnóstico por vendor (Zoom/Teams/Meet) con matriz de pruebas. |

## Principios de ejecución

1. Un PR por task. Review propio + lint + tests.
2. Nunca borrar nada sin antes archivar (tag, `refs/archive/`, `deprecated/`).
3. Cada fase finaliza con actualización de `config/status.json`.
4. Métricas antes y después de cada fase para detectar regresiones.
