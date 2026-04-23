# DATA MODEL REDESIGN — Interview Coach v4.0

> Nuevo esquema PostgreSQL + pgvector. Idempotente, replayable, con outbox durable y versionado de contratos.
> Se adopta Alembic para migraciones. Se colapsa el esquema existente (001 + 002 + 002) en baseline `20260422_01`.

---

## 1. Problemas del modelo actual

- Solo `exchanges` (par Q/A post-hoc) representa la interacción. No hay forma de reconstruir el turno segmento a segmento.
- `event_log` existe pero no se puebla desde el pipeline live (solo 1 llamada en `server.py:12843`).
- `persist_queue.py` es en memoria → las escrituras críticas se pierden ante reinicio.
- Migraciones sin versionador: dos archivos `002_*.sql`, orden incierto.
- `sessions.config_id` tiene FK NOT NULL que rompe inserciones → se agregó migración `002_make_config_id_nullable.sql` como fix manual.
- No hay tablas para: `turns`, `segments`, `brain_plans`, `emission_contracts`, `emissions`, `evidence_packs`, `outbox`, `contract_versions`.

---

## 2. Diseño objetivo

### 2.1 Tablas preservadas (de 001/002)

- `user_profiles`
- `achievements` (con embedding)
- `document_chunks` (con embedding)
- `context_profiles`
- `context_document_chunks` (con embedding)
- `interview_configs`
- `insights_workspaces`
- `insights_runs`
- `latency_metrics` (se extiende con `turn_id`)

### 2.2 Tablas nuevas

#### `sessions` (reemplaza 001)
```sql
CREATE TABLE sessions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  config_id         UUID REFERENCES interview_configs(id) ON DELETE SET NULL,
  profile           TEXT NOT NULL DEFAULT 'default',
  status            TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','ended','crashed')),
  started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at          TIMESTAMPTZ,
  summary           JSONB,
  trace_id          TEXT UNIQUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX sessions_status_idx ON sessions(status, started_at DESC);
```

#### `turns`
```sql
CREATE TABLE turns (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id        UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  index_in_session  INT NOT NULL,
  speaker           TEXT NOT NULL
                    CHECK (speaker IN ('interviewer','candidate','unknown')),
  opened_at         TIMESTAMPTZ NOT NULL,
  closed_at         TIMESTAMPTZ,
  close_reason      TEXT CHECK (close_reason IN
                    ('utterance_end','silence','syntactic','timeout','manual','hybrid')),
  close_confidence  REAL CHECK (close_confidence >= 0 AND close_confidence <= 1),
  final_text        TEXT NOT NULL DEFAULT '',
  language          TEXT,
  UNIQUE(session_id, index_in_session)
);
CREATE INDEX turns_session_opened_idx ON turns(session_id, opened_at);
```

#### `segments`
```sql
CREATE TABLE segments (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id        UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id           UUID REFERENCES turns(id) ON DELETE SET NULL,
  seq               BIGINT NOT NULL,
  speaker           TEXT NOT NULL,
  text              TEXT NOT NULL,
  language          TEXT,
  confidence        REAL,
  is_final          BOOLEAN NOT NULL,
  t_start_ms        INT,
  t_end_ms          INT,
  stt_request_id    TEXT,
  provider          TEXT,
  model             TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(session_id, seq)
);
CREATE INDEX segments_turn_idx ON segments(turn_id, seq);
CREATE INDEX segments_session_created_idx ON segments(session_id, created_at);
```

#### `brain_plans`
```sql
CREATE TABLE brain_plans (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id        UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id           UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  snapshot_hash     TEXT NOT NULL,
  stability         TEXT NOT NULL
                    CHECK (stability IN ('draft','stable_candidate','stable')),
  plan_source       TEXT NOT NULL
                    CHECK (plan_source IN ('llm_fast','safe_fallback','cached_stable')),
  confidence        REAL CHECK (confidence >= 0 AND confidence <= 1),
  payload           JSONB NOT NULL,  -- BrainPlan v2
  schema_version    INT NOT NULL DEFAULT 2,
  trace_id          TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX brain_plans_turn_idx ON brain_plans(turn_id, created_at DESC);
CREATE INDEX brain_plans_hash_idx ON brain_plans(snapshot_hash);
CREATE INDEX brain_plans_stability_idx ON brain_plans(stability, created_at DESC);
```

#### `evidence_packs`
```sql
CREATE TABLE evidence_packs (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id        UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id           UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  payload           JSONB NOT NULL,   -- CompactEvidencePack snapshot
  schema_version    INT NOT NULL DEFAULT 1,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX evidence_packs_turn_idx ON evidence_packs(turn_id);
```

#### `emission_contracts`
```sql
CREATE TABLE emission_contracts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id        UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id           UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  brain_plan_id     UUID NOT NULL REFERENCES brain_plans(id) ON DELETE CASCADE,
  evidence_pack_id  UUID REFERENCES evidence_packs(id) ON DELETE SET NULL,
  readiness_score   REAL NOT NULL CHECK (readiness_score >= 0 AND readiness_score <= 1),
  render_shape      TEXT NOT NULL,
  target_length     INT NOT NULL,
  tone              TEXT NOT NULL,
  language          TEXT NOT NULL,
  payload           JSONB NOT NULL,  -- EmissionContract full
  schema_version    INT NOT NULL DEFAULT 1,
  trace_id          TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX emission_contracts_turn_idx ON emission_contracts(turn_id, created_at DESC);
```

#### `emissions`
```sql
CREATE TABLE emissions (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id             UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id                UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  emission_contract_id   UUID NOT NULL REFERENCES emission_contracts(id) ON DELETE CASCADE,
  full_response          TEXT NOT NULL,
  bullets                TEXT[] NOT NULL DEFAULT '{}',
  language               TEXT,
  quality                JSONB,
  latency_ms             INT,
  latency_breakdown      JSONB,
  trace_id               TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX emissions_turn_idx ON emissions(turn_id);
CREATE INDEX emissions_session_created_idx ON emissions(session_id, created_at DESC);
```

#### `event_log` (reemplaza 001 con `seq`)
```sql
CREATE TABLE event_log (
  id                BIGSERIAL PRIMARY KEY,
  session_id        UUID REFERENCES sessions(id) ON DELETE CASCADE,
  seq               BIGINT NOT NULL,
  event_type        TEXT NOT NULL,
  payload           JSONB NOT NULL,
  trace_id          TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(session_id, seq)
);
CREATE INDEX event_log_type_time_idx ON event_log(event_type, created_at);
CREATE INDEX event_log_trace_idx ON event_log(trace_id) WHERE trace_id IS NOT NULL;
```

#### `outbox`
```sql
CREATE TABLE outbox (
  id                BIGSERIAL PRIMARY KEY,
  target_table      TEXT NOT NULL,
  payload           JSONB NOT NULL,
  status            TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','completed','failed','dead')),
  attempts          INT NOT NULL DEFAULT 0,
  max_attempts      INT NOT NULL DEFAULT 5,
  last_error        TEXT,
  trace_id          TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at      TIMESTAMPTZ,
  next_retry_at     TIMESTAMPTZ
);
CREATE INDEX outbox_pending_idx ON outbox(status, next_retry_at) WHERE status IN ('pending','failed');
CREATE INDEX outbox_created_idx ON outbox(created_at);
```

#### `contract_versions`
```sql
CREATE TABLE contract_versions (
  name              TEXT NOT NULL
                    CHECK (name IN ('brain_plan','emission_contract','generated_response','event')),
  version           INT NOT NULL,
  schema            JSONB NOT NULL,
  active            BOOLEAN NOT NULL DEFAULT TRUE,
  introduced_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(name, version)
);
```

#### `latency_metrics` (extender)
```sql
ALTER TABLE latency_metrics
  ADD COLUMN turn_id UUID REFERENCES turns(id) ON DELETE CASCADE,
  ADD COLUMN trace_id TEXT;
CREATE INDEX latency_metrics_turn_idx ON latency_metrics(turn_id);
```

#### `exchanges` (deprecado a vista)
```sql
-- Se mantiene durante 1 release para compatibilidad.
-- En la siguiente release pasará a vista construida por join.
CREATE OR REPLACE VIEW exchanges_compat AS
SELECT
  e.id,
  e.session_id,
  t.index_in_session                                  AS index_in_session,
  t.final_text                                         AS interviewer_utterance,
  t.language                                           AS language_detected,
  bp.payload->'ask'                                    AS question_analysis,
  em.full_response                                     AS suggested_response_text,
  em.quality                                           AS quality_result,
  NULL::TEXT                                           AS user_actual_response,
  em.latency_ms                                        AS latency_ms,
  em.created_at                                        AS created_at
FROM emissions em
JOIN turns t          ON t.id = em.turn_id
JOIN brain_plans bp   ON bp.turn_id = t.id AND bp.stability = 'stable'
JOIN emissions e      ON e.id = em.id;
```

---

## 3. Alembic setup

### 3.1 Estructura de archivos

```
python-core/persistence/migrations/
  alembic.ini
  env.py
  script.py.mako
  versions/
    20260422_01_baseline.py          # colapsa 001+002+002 actuales
    20260422_02_turns_events.py      # añade turns, segments, brain_plans, emission_contracts, emissions, evidence_packs, event_log v2, outbox, contract_versions
    20260422_03_latency_extensions.py # turn_id y trace_id en latency_metrics, vista exchanges_compat
```

### 3.2 `env.py` (esqueleto)

```python
import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from persistence.db import get_database_url

target_metadata = None  # raw SQL migrations

async def run_migrations_online():
    engine = create_async_engine(get_database_url().replace("postgresql://","postgresql+asyncpg://"))
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

asyncio.run(run_migrations_online())
```

### 3.3 Estrategia de baseline sobre volumen existente

Para no destruir la DB de dev que ya corrió 001+002:

```bash
# Si la DB ya tiene 001+002 aplicadas via /docker-entrypoint-initdb.d:
alembic stamp 20260422_01_baseline
# Esto marca la baseline como ya aplicada sin correr SQL.
alembic upgrade head
# Corre 02 + 03 encima.
```

Para DB limpia:

```bash
alembic upgrade head   # corre todas en orden
```

### 3.4 `docker-compose.yml` cambios

Se quita el mount directo de `/docker-entrypoint-initdb.d`:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    ...
    # volumes:
    #   - postgres_data:/var/lib/postgresql/data   (mantener)
    #   - ./python-core/storage/migrations:/docker-entrypoint-initdb.d:ro  (eliminar)
    volumes:
      - postgres_data:/var/lib/postgresql/data
  backend:
    build: ./python-core
    command: >
      bash -c "alembic upgrade head &&
               uvicorn api:app --host 0.0.0.0 --port 8787"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://interview_coach:interview_coach_dev@postgres:5432/interview_coach
      INTERVIEW_COACH_DB_REQUIRED: "true"
```

---

## 4. Outbox pattern

### 4.1 Flujo de escritura

```
Pipeline event -> event_writer.write(event)
  |
  +--> En la misma transacción:
       1. INSERT INTO event_log (session_id, seq, event_type, payload, trace_id)
       2. INSERT INTO outbox (target_table='<x>', payload=<row>, status='pending')
  |
  +--> Worker asíncrono (outbox_worker.py):
       loop:
         rows = SELECT FROM outbox WHERE status='pending' AND next_retry_at <= now() LIMIT 50
         for row in rows:
           UPDATE outbox SET status='processing' WHERE id=row.id
           try:
             apply(row.target_table, row.payload)       # INSERT/UPDATE real
             UPDATE outbox SET status='completed', processed_at=now() WHERE id=row.id
           except Exception as e:
             if row.attempts+1 >= row.max_attempts:
               UPDATE outbox SET status='dead', last_error=str(e) WHERE id=row.id
               (alert / DLQ file)
             else:
               UPDATE outbox SET status='pending', attempts=attempts+1,
                                 next_retry_at=now()+backoff(attempts),
                                 last_error=str(e)
               WHERE id=row.id
```

### 4.2 Fallback a archivo si DB cae

`outbox.py` detecta `asyncpg.CannotConnectNowError` / `ConnectionDoesNotExistError`:

1. Escribir el evento a `.runtime/outbox.ndjson` (JSON line por evento).
2. Al reconectar DB, un proceso `outbox_replay_from_file()` lee el NDJSON, inserta en `outbox` y borra el archivo cuando acaba.

### 4.3 Backoff

`backoff(attempts) = min(60, 2**attempts)` segundos.

---

## 5. Idempotencia y replay

### 5.1 Claves únicas

- `(session_id, seq)` único en `event_log` y `segments`.
- `snapshot_hash` indexado en `brain_plans`; dedup natural.
- `trace_id` único en `sessions`.

### 5.2 Replay determinista

Un script `scripts/replay_session.py <session_id>`:

```python
# Lee event_log en orden, reconstruye:
#  - segments
#  - turns
#  - brain_plans (ejecutando planner en modo plan-only, sin renderer)
# Compara resultados con los ya almacenados -> "regression delta"
```

Esto habilita:
- Detección de regresiones en brain lógica.
- Reconstrucción tras fallo catastrófico.
- Testing con sesiones reales grabadas.

---

## 6. Versionado de contratos

`contract_versions` registra el schema JSON de cada versión activa. Al boot:

```python
# persistence/contract_versions.py
await contract_versions.register(
  name="brain_plan",
  version=2,
  schema=BrainPlan.model_json_schema()
)
```

Al leer `brain_plans.payload` se valida contra el `schema_version` que el row declara. Rollback:
- Si en la release R-1 se quiere volver a `brain_plan v1`, se marca v2 como `active=false`, se desactiva cutover, el código legacy v1 sigue vivo.

---

## 7. Índices y rendimiento

### 7.1 Para hot path (live)

- `segments(session_id, seq)` → append rápido y lookup por orden.
- `turns(session_id, opened_at)` → contexto window last N.
- `brain_plans(turn_id, created_at DESC)` → último plan por turn.
- `brain_plans(snapshot_hash)` → dedup lookup.
- `outbox(status, next_retry_at)` → pick next batch eficiente.

### 7.2 Para analytics

- `event_log(event_type, created_at)` → filtro por tipo.
- `emissions(session_id, created_at DESC)` → timeline de UI.
- `latency_metrics(turn_id)` → breakdown por turn.

### 7.3 pgvector

- `document_chunks USING hnsw (embedding vector_cosine_ops)` ya existe.
- `achievements USING hnsw (embedding vector_cosine_ops)` ya existe.
- `context_document_chunks USING hnsw` ya existe.
- **No** se añaden embeddings a turns/segments por ahora. Se mantiene el vector store para profile + context, no para el historial live.

---

## 8. Migración de datos existentes

### 8.1 De `exchanges` a `turns`+`emissions` (best-effort)

Script `scripts/migrate_exchanges_to_v2.py`:

```python
# Para cada session con exchanges:
#   - Crear 1 turn por exchange (speaker='interviewer', final_text=interviewer_utterance)
#   - Crear 1 brain_plan por exchange (payload sintetizado desde question_analysis)
#   - Crear 1 emission_contract "sintético"
#   - Crear 1 emission con full_response/bullets de suggested_response
# Trace_id = f"migrated:{exchange.id}"
```

Tras migración, la vista `exchanges_compat` produce lo mismo que la tabla original.

### 8.2 Retención

- `event_log`: 90 días rolling por default; config por env `EVENT_LOG_RETENTION_DAYS`.
- `segments`: 30 días por default (son grandes).
- `turns`, `brain_plans`, `emissions`: retención infinita (core artefactos).
- `outbox.status='completed'`: limpiar >7 días.

---

## 9. Criterios de aceptación F2

1. `alembic upgrade head` idempotente en DB limpia.
2. `alembic stamp 20260422_01_baseline` seguido de `alembic upgrade head` idempotente en DB con 001+002 ya aplicadas.
3. Crear una sesión de prueba y emitir 3 respuestas produce:
   - 1 row en `sessions`
   - ≥6 rows en `segments` (partial y final)
   - 3 rows en `turns`
   - ≥3 rows en `brain_plans`
   - 3 rows en `emission_contracts`
   - 3 rows en `emissions`
   - ≥20 rows en `event_log`
   - 0 rows pending en `outbox` transcurridos 5 segundos
4. Detener backend a mid-session → al reiniciar, se completan escrituras pendientes desde `.runtime/outbox.ndjson`.
5. `scripts/replay_session.py <id>` reconstruye los turns y brain_plans sin diff significativo.

---

## 10. Riesgo y mitigación

| Riesgo | Mitigación |
|---|---|
| Baseline destruye datos | Usar `alembic stamp` en DB existentes. Test en DB de dev antes de prod. |
| Outbox se llena (backpressure) | Alertas Prometheus `ic_outbox_queue_size > 1000`. Rate-limit writes a segments si es necesario. |
| Grandes payloads JSON en brain_plans | Comprimir con `pg_toast` natural de PG. Si crece mucho, mover payload a tabla aparte con columna `TOAST`. |
| Migración de `exchanges` pierde info | Best-effort; se conserva `exchanges` intacta durante 1 release. |
| pgvector indexes lentos al reindexar | Indexes con `CONCURRENTLY` en migraciones; medir impacto pre-deploy. |
