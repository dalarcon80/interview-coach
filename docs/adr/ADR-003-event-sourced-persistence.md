# ADR-003 — Event-sourced persistence con outbox y replay

- **Status:** Accepted (draft, to be ratified at end of F2)
- **Date:** 2026-04-22
- **Deciders:** architect

## Contexto

El estado live del sistema hoy no es durable:

- `python-core/storage/persist_queue.py:59` — cola en memoria (`list`). Drop-oldest a los 100 items.
- `exchanges` como única tabla transaccional que persiste la interacción, y solo como resumen post-hoc (Q+A pair).
- No se persisten: `segments`, `turns`, `brain_plans`, `emission_contracts`, `emissions`, `evidence_packs`, `silence events`, `intent hypotheses`.
- `event_log` existe en schema desde 001, pero solo 1 llamada real en todo el código (`server.py:12843`), fuera del hot path.
- `database_connected: false` en `config/status.json` confirma que el backend suele correr sin DB, en modo degradado silencioso.

Consecuencias observadas por el owner:
- "La persistencia se pierde."
- "Cambiar de rama hace que desaparezcan cosas."
- Imposibilidad de auditar por qué el brain respondió X.
- Imposibilidad de reconstruir una sesión tras un crash del backend.

## Decisión

Adoptar **event sourcing interno** con **outbox pattern** y **replay determinista** sobre PostgreSQL.

### Puntos clave

1. **`event_log` es la fuente de verdad operacional.**
   - Tabla append-only.
   - Shape: `(id BIGSERIAL, session_id UUID, seq BIGINT, event_type TEXT, payload JSONB, trace_id TEXT, created_at TIMESTAMPTZ)`.
   - UNIQUE `(session_id, seq)` garantiza ordering determinista.
2. **Transición de estado pasa por el bus de eventos**, no por escritura directa a tablas destino.
   - `events/bus.py` — in-process asyncio typed bus.
   - `persistence/event_writer.py` — sub del bus, escribe cada evento a `event_log` + entrada en `outbox`.
3. **Outbox drena a tablas destino.**
   - Tabla `outbox (id, target_table, payload, status, attempts, next_retry_at, last_error)`.
   - Worker `outbox_worker.py` corre async, toma lotes de `pending`, INSERT/UPDATE en la tabla destino, actualiza estado.
   - Backoff: `min(60, 2**attempts)` segundos.
   - DLQ: `status='dead'` tras `max_attempts`; se loggea y se expone métrica.
4. **Fallback a archivo si DB cae.**
   - `outbox.enqueue()` detecta `asyncpg.CannotConnectNowError` → escribe NDJSON en `.runtime/outbox.ndjson`.
   - Al reconectar, `outbox_replay_from_file()` inserta en tabla `outbox` y borra el NDJSON.
5. **Fail-loud en startup.**
   - Backend sale con código ≠ 0 si DB no responde, salvo `INTERVIEW_COACH_DB_REQUIRED=false`. Fin del "modo degradado silencioso".
6. **Replay determinista.**
   - `scripts/replay_session.py <session_id>` lee `event_log` en orden, reconstruye segments → turns → brain_plans → emission_contracts.
   - Comparación contra `brain_plans` realmente guardados → detección de regresiones.
7. **Versionado de contratos.**
   - Tabla `contract_versions` registra el JSON Schema activo.
   - Cada row (`brain_plans.payload`, etc.) declara `schema_version`.

### Tablas nuevas

Ver `DATA_MODEL_REDESIGN.md` §2.2 para el schema completo:
- `turns`, `segments`, `brain_plans`, `evidence_packs`, `emission_contracts`, `emissions`, `event_log` (v2 con `seq`), `outbox`, `contract_versions`.

### Alembic

- Se abandona `/docker-entrypoint-initdb.d` para migraciones.
- Adopción de Alembic bajo `python-core/persistence/migrations/`.
- Baseline `20260422_01` colapsa 001+002+002 actuales.
- Migraciones incrementales desde ahí.

## Consecuencias

### Positivas

- **Replay**: cualquier sesión pasada puede reconstruirse a partir de su event_log.
- **Auditabilidad**: "¿por qué el brain dijo X?" tiene respuesta concreta leyendo `brain_plans.payload` + `event_log`.
- **Resiliencia**: matar el backend mid-session ya no pierde datos.
- **Observabilidad**: un trace id recorre todo el pipeline, incluyendo las escrituras DB.
- **Testing**: sesiones reales grabadas son fixtures de regresión.

### Negativas

- **Complejidad extra**: bus, outbox, worker, NDJSON fallback, Alembic.
- **Overhead de escritura**: 1 evento = 1 INSERT a `event_log` + 1 INSERT a `outbox` + 1 INSERT eventual a la tabla destino. Mitigación: batching en el worker, `UNLOGGED` no se usa porque queremos durabilidad.
- **Espacio en disco**: event_log puede crecer rápido. Mitigación: retention rolling por env (`EVENT_LOG_RETENTION_DAYS=90`).

### Neutras

- Todo evento live implica I/O; esto se ve sólo si hay regresión, no es un problema per se a la escala esperada (1-3 sesiones concurrentes, <100 eventos/s).

## Alternativas consideradas

1. **Kafka / NATS / Redis Streams**: over-engineered para un producto local-first single-user. Rechazado.
2. **SQLite local-first**: descartado porque ya hay PG requerido por pgvector (RAG).
3. **Solo `event_log` sin outbox**: escrituras directas a tablas destino → sin idempotencia ni recuperación de fallas transitorias. Rechazado.
4. **Persistencia síncrona en el hot path**: bloquea latencia. Rechazado.

## Compliance HR

- **HR-1**: el bus interno no afecta live caption. `live_caption.py` sigue emitiendo por WS sin pasar por `event_writer` (puede emitir eventos al bus, pero no debe bloquearse).
- **HR-2**: `context_window.py` lee de `turns` (DB-backed) + cache en memoria; rehidrata en cold start.
- **HR-3**: baseline Alembic + tag `archive/main-before-consolidation-2026-04-22` + `backup/v1.x/` existentes cubren rollback.
- **HR-4**: manual coach lee de `session_store.get_recent_turns(session_id, n=4)` — no depende del bus live.

## Implementación

Ver `IMPLEMENTATION_PLAN.md` §F2 y `execution_plan.yaml`.

## Rollback

- `alembic downgrade 20260422_01_baseline` revierte las tablas nuevas.
- Restaurar `storage/persist_queue.py` desde git.
- Flag `INTERVIEW_COACH_DB_REQUIRED=false` permite correr temporalmente sin DB mientras se decide.

## Métricas de éxito

- `ic_outbox_queue_size` se mantiene típicamente <10 en operación normal.
- Tras matar el backend durante una sesión, al reiniciar, `SELECT count(*) FROM event_log WHERE session_id=X` tiene todos los eventos esperados (0 pérdidas).
- `scripts/replay_session.py` reconstruye brain_plans con ≤5% diff semántico contra los guardados.
- `database_connected: true` en `status.json` de forma estable.

## Referencias

- `docs/audit/AUDIT_REPORT.md` §1 CR-1 y §4
- `docs/audit/DATA_MODEL_REDESIGN.md`
- `docs/audit/TARGET_ARCHITECTURE.md` §4.7
