# Interview Coach — Arquitectura Final v3.2.1 (CONGELADO)

---

## 1. Visión del Producto

App de escritorio (macOS-first) que funciona como coach de entrevistas en tiempo real. Captura audio de videoconferencias (Zoom, Teams, Meet), transcribe lo que dice el entrevistador, analiza la pregunta a profundidad, y sugiere la mejor respuesta posible basada en el perfil del usuario, el rol al que aplica, y el estilo de comunicación elegido.

```
Audio de reunión → Transcripción streaming → Análisis profundo
→ Retrieval de evidencia del perfil → Respuesta verificada
→ Display (bullets inmediatos + respuesta gated)
```

**Diferenciador:** 4 estilos de respuesta (Ejecutivo, Comercial, Técnico, Mixto), análisis de preguntas compuestas multi-capa, coherencia conversacional entre preguntas, y quality gate real que bloquea respuestas malas antes de mostrarlas.

---

## 2. Principios de Diseño

1. **macOS-first**: V1 se desarrolla y prueba en macOS. Windows/Linux en V1.5.
2. **Simplicidad sobre over-engineering**: cada componente hace UNA cosa bien.
3. **Stateful declarado**: el sistema es stateful por naturaleza (la respuesta 5 depende de las 1-4). SessionState como single source of truth con ownership claro.
4. **Latencia como métrica norte** con targets honestos por tier, no marketing.
5. **Workflow explícito, no "multi-agent"**: steps tipados con paralelismo controlado.
6. **Fail gracefully**: si algo falla, degradar con dignidad, nunca crashear.
7. **Provider abstraction**: STT, LLM y embeddings intercambiables via aliases lógicos.
8. **Un solo cerebro de datos**: PostgreSQL + pgvector para todo.
9. **Observability desde día 1**: OpenTelemetry con traces correlacionados.
10. **Quality gate real**: la respuesta pasa validación ANTES de mostrarse al usuario.

---

## 3. Decisiones Técnicas

| ID | Decisión | Razón | Trade-off |
|----|----------|-------|-----------|
| D1 | **Polyglot: Rust + Python + TypeScript** | Audio nativo requiere Rust (ScreenCaptureKit). ML/NLP/RAG funciona mejor en Python. UI es React/TS obligatorio en Tauri | Tres lenguajes = más complejidad de build |
| D2 | **Tauri 2.0** sobre Electron | 10MB vs 150MB bundle, acceso nativo a audio via Rust, mejor rendimiento | Requiere conocimiento de Rust para el módulo de audio |
| D3 | **macOS-first con ScreenCaptureKit** | El desarrollador principal tiene Mac. No fingir cross-platform | Windows/Linux son stubs en V1 |
| D4 | **Dos streams de audio separados** (system + mic) | Elimina speaker diarization: system audio = entrevistador, mic = usuario | Requiere audio loopback del sistema |
| D5 | **PostgreSQL + pgvector** (unificado, via Docker) | Un solo cerebro: relacional + vectores + replay + audit. ACID. Backup unificado | Requiere Docker, más fricción de setup que SQLite |
| D6 | **Provider adapters con aliases lógicos** | STT/LLM/Embedding intercambiables sin tocar código. Defaults en providers.yaml, overrides por env var | Indirección extra en la resolución |
| D7 | **Deepgram Nova-3** multilingual como default STT | 54% menos WER, code-switching EN/ES nativo, Keyterm Prompting | Requiere internet. Whisper local como fallback |
| D8 | **Claude Sonnet** (latest) como default LLM | Excelente seguimiento de instrucciones complejas, buen español, prompt caching | Costo por token alto. Mitigación: prompt caching + respuestas cortas |
| D9 | **Workflow explícito** (no "multi-agent") | Misma funcionalidad que 6 agentes, menos buzzwords, más control y debugging | Menos "sexy" conceptualmente |
| D10 | **Quality Gate: Draft→Validate→Repair→Expose** | La respuesta se valida ANTES de mostrarse. 1 repair si falla. Fallback determinista | Añade ~500ms de latencia a la respuesta completa |
| D11 | **PersistQueue con drop-oldest** bajo presión | Prioridad: la entrevista en vivo no se bloquea. Items droppeados se loguean para recovery manual | Pérdida de datos posible bajo presión extrema de DB |
| D12 | **Timeline 14-16 semanas** para V1 | Realista para audio cross-platform + streaming STT + RAG + LLM + quality gate + overlay + tests | No es "rápido" |

---

## 4. Arquitectura de Alto Nivel

```
┌──────────────────────────────────────────────────────────────┐
│                    TAURI 2.0 SHELL                           │
│                                                              │
│  ┌────────────────────────┐  ┌────────────────────────────┐  │
│  │    RUST NATIVE LAYER   │  │     REACT / TS UI LAYER    │  │
│  │                        │  │                            │  │
│  │  • Audio Capture       │  │  • Overlay (transparent)   │  │
│  │    (ScreenCaptureKit   │  │  • Transcript Panel        │  │
│  │     en macOS)          │  │  • Suggestion Panel        │  │
│  │  • Audio Normalization │  │  • BulletPoints            │  │
│  │  • Stream to Backend   │  │  • Settings / Config       │  │
│  │                        │  │  • QualityWarning          │  │
│  └──────────┬─────────────┘  └──────────┬─────────────────┘  │
│             │ audio chunks (IPC)        │ events (IPC)       │
└─────────────┼───────────────────────────┼────────────────────┘
              │                           │
              ▼                           ▼
┌──────────────────────────────────────────────────────────────┐
│              PYTHON CORE BACKEND (FastAPI + WebSocket)        │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │           REALTIME PIPELINE (stateful)                   │ │
│  │                                                         │ │
│  │  AudioReceiver → STTAdapter → TurnAssembler             │ │
│  │    → LanguagePolicy → QuestionAnalyzer                  │ │
│  │    → RetrievalPlanner → EvidenceRetriever               │ │
│  │    → ResponseComposer → QualityGate → Emitter           │ │
│  │                                                         │ │
│  │  Estado: SessionState (single source of truth)          │ │
│  │  Cada step: input/output tipado (Pydantic)              │ │
│  │  Paralelo donde convenga (retrieval + intent analysis)  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ PROVIDER     │  │ PERSISTENCE  │  │ OBSERVABILITY    │   │
│  │ ADAPTERS     │  │ LAYER        │  │                  │   │
│  │              │  │              │  │ OpenTelemetry     │   │
│  │ STTAdapter   │  │ PersistQueue │  │ Traces + Metrics │   │
│  │ LLMAdapter   │  │ (durable,    │  │ correlacionados  │   │
│  │ EmbedAdapter │  │  retry,      │  │ por step         │   │
│  │              │  │  flush)      │  │                  │   │
│  └──────────────┘  └──────┬───────┘  └──────────────────┘   │
└────────────────────────────┼─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│         POSTGRESQL + pgvector (Docker Compose)               │
│                                                              │
│  • users, profiles, achievements (relacional)                │
│  • document_chunks + embeddings (pgvector)                   │
│  • sessions, exchanges, responses (relacional + temporal)    │
│  • event_log (append-only para replay)                       │
│  • latency_metrics (time-series)                             │
│                                                              │
│  Una sola base. ACID. Backup unificado.                      │
│  Queries que combinan filtros SQL + búsqueda vectorial.      │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. Stack Tecnológico

| Capa | Tecnología | Rol |
|------|-----------|-----|
| Desktop Shell | Tauri 2.0 | Container de la app |
| Audio Capture | Rust + ScreenCaptureKit (macOS) | Captura system audio + mic |
| UI | React 18 + TypeScript + TailwindCSS | Overlay transparente |
| Backend | Python 3.11+ + FastAPI + WebSocket | Pipeline de procesamiento |
| STT (default) | Deepgram Nova-3 multilingual | Transcripción streaming |
| STT (fallback) | Whisper.cpp local | Offline |
| LLM principal | Claude Sonnet (latest via alias) | Generación de respuestas |
| LLM rápido | Claude Haiku (latest via alias) | Clasificación, bullets |
| Embeddings | OpenAI text-embedding-3-small | Vectorización de documentos |
| Vector Store | pgvector (dentro de PostgreSQL) | Búsqueda semántica |
| Database | PostgreSQL 17 (Docker) | Todo lo relacional + vectores |
| Observability | OpenTelemetry | Traces, métricas, logs |
| Testing | pytest + Vitest | Unit, integration, simulations |
| Infra local | Docker Compose | PostgreSQL + pgvector |

---

## 6. Realtime Pipeline — Workflow Explícito

### Mientras el entrevistador habla (cada 2s con parciales):

Trabajo especulativo. NO usa LLM. Solo heurísticas y queries a DB.

```python
async def on_partial_transcript(self, partial: str):
    # PARALELO: clasificación local + pre-carga de evidencia
    intent_task = self._quick_intent_classify(partial)   # Heurísticas
    prefetch_task = self._prefetch_evidence(partial)      # DB query
    intent, chunks = await asyncio.gather(intent_task, prefetch_task)
    self.state.speculative_intent = intent
    self.state.preloaded_chunks = chunks
```

### Cuando el entrevistador termina (silencio > threshold):

```
Step 1: QuestionAnalyzer (LLM rápido, ~400ms)
    → Usa pre-análisis especulativo como contexto
    → Output: QuestionAnalysis (Pydantic)

Step 2: EvidenceRetriever (pgvector query, ~100ms)
    → Refina chunks pre-cargados con análisis real
    → Output: list[EvidenceChunk]

Step 3a: Generate Bullets (LLM rápido, ~300ms)
    → Mini-gate: heurísticas locales (<50ms)
    → Si pasa → MOSTRAR BULLETS al usuario
    → El usuario YA puede empezar a hablar

Step 3b: Generate Full Response (LLM principal, streaming, en buffer)
    → NO se muestra al usuario todavía

Step 4: Quality Gate REAL (~500ms)
    → 6 validaciones sobre la respuesta buffereada
    → Si pasa → MOSTRAR respuesta al usuario
    → Si falla → Repair (1 intento) → Re-validate
    → Si repair falla → FALLBACK: solo bullets

Step 5: Persist (async via PersistQueue)
    → Actualizar ConversationMap
    → Encolar exchange para escritura a DB
```

---

## 7. Contratos de Datos

```python
class QuestionType(str, Enum):
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    SITUATIONAL = "situational"
    CASUAL = "casual"
    FOLLOW_UP = "follow_up"
    STRESS = "stress"
    COMPOUND = "compound"

class ResponseStyle(str, Enum):
    EXECUTIVE = "executive"
    COMMERCIAL = "commercial"
    TECHNICAL = "technical"
    MIXED = "mixed"

class SubQuestion(BaseModel):
    text: str
    type: QuestionType
    priority: str       # "must_answer" | "should_answer" | "nice_to_have"
    weight: float       # 0.0 - 1.0

class QuestionAnalysis(BaseModel):
    primary_type: QuestionType
    is_compound: bool
    sub_questions: list[SubQuestion]
    key_topics: list[str]
    underlying_intent: list[str]
    red_flags: list[str]
    related_to_previous: bool
    builds_on_exchange: int | None
    recommended_style: ResponseStyle
    response_structure: list[str]

class EvidenceChunk(BaseModel):
    text: str
    source: str             # "cv" | "achievement" | "job_desc" | "company"
    relevance_score: float
    metadata: dict

class AssembledContext(BaseModel):
    question: str
    analysis: QuestionAnalysis
    evidence: list[EvidenceChunk]
    conversation_summary: str
    topics_already_covered: list[str]
    metrics_already_used: list[str]
    style_config: dict
    interview_config: dict

class GeneratedResponse(BaseModel):
    bullets: list[str]
    full_response: str
    key_metrics: list[str]
    confidence: float
    style_used: ResponseStyle
    generation_time_ms: int

class QualityResult(BaseModel):
    passed: bool
    score: float
    issues: list[str]
    contradictions: list[str]
    repetitions: list[str]

class LanguageDecision(BaseModel):
    final_language: str         # "es" | "en"
    confidence: float
    method: str
    segments: list[dict]
    user_preference: str | None

class Exchange(BaseModel):
    index: int
    timestamp: datetime
    interviewer_utterance: str
    language_detected: str
    analysis: QuestionAnalysis
    suggested_response: GeneratedResponse
    quality: QualityResult
    user_actual_response: str | None
    latency_ms: int
```

---

## 8. Provider Adapters

### Interfaces abstractas

```python
class STTAdapter(ABC):
    async def connect(self, config) -> None: ...
    async def stream_audio(self, chunks) -> AsyncGenerator[TranscriptEvent, None]: ...
    async def disconnect(self) -> None: ...

class LLMAdapter(ABC):
    async def generate(self, messages, config) -> str: ...
    async def stream(self, messages, config) -> AsyncGenerator[str, None]: ...

class EmbeddingAdapter(ABC):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

### Resolución por alias (providers.yaml)

```yaml
providers:
  stt:
    primary:
      alias: "stt_primary"
      provider: "deepgram"
      model: "nova-3"
      config:
        language: "multi"
        diarize: true
        smart_format: true
        utterance_end_ms: 1500
    fallback:
      alias: "stt_fallback"
      provider: "whisper_local"
      model: "medium"
  llm:
    main:
      alias: "llm_main"
      provider: "anthropic"
      model: "claude-sonnet-4-20250514"
      config: { temperature: 0.3, max_tokens: 300, stream: true }
    fast:
      alias: "llm_fast"
      provider: "anthropic"
      model: "claude-haiku-4-5-20251001"
      config: { temperature: 0.2, max_tokens: 150, stream: false }
  embedding:
    primary:
      alias: "embedding_primary"
      provider: "openai"
      model: "text-embedding-3-small"
      dimensions: 1536

# Override por env var: PROVIDER_LLM_MAIN_MODEL=claude-opus-4-20250514
```

**Regla:** Cero model IDs en código fuente ni en schema SQL. Solo aliases que se resuelven en runtime via providers.yaml + env vars.

---

## 9. Deep Question Analyzer

Las preguntas de entrevista NO son simples. Ejemplo real:

> "Estamos buscando una persona que ocupe el rol de CTO en la compañía, la cual debe poder dar estructura no solo a nivel tecnológico, sino a nivel operativo alineado con las necesidades internas y de nuestros clientes, que permita traer resultados medibles. Para eso nos gustaría saber tu experiencia, si has tenido oportunidad de crear equipos desde cero, cuéntanos más sobre ti."

Esa pregunta contiene **7 sub-preguntas implícitas**: nivel de seniority, estructura tecnológica, estructura operativa, foco interno + cliente, resultados medibles, building from scratch, y narrativa personal.

El QuestionAnalyzer descompone en sub-preguntas con prioridad y peso, identifica underlying_intent (qué quiere escuchar realmente el entrevistador), red_flags (qué evitar), y genera response_structure con tiempos recomendados por sección.

El prompt del analyzer recibe: empresa target, rol, JD resumido, perfil del candidato, e historial de conversación. Esto permite detectar follow-ups y evitar repeticiones.

---

## 10. Conversation Tracker

Mantiene un `ConversationMap` con:

- **claims**: lo que el candidato ya dijo (para no contradecir)
- **metrics_used**: métricas ya mencionadas (para no repetir)
- **achievements_referenced**: logros del perfil ya citados
- **uncovered_gaps**: temas que el entrevistador buscó pero no se cubrieron bien
- **interviewer_values**: temas que el entrevistador parece valorar (inferido)
- **warnings**: contradicciones o repeticiones detectadas

Post cada respuesta del usuario (capturada por mic), el tracker:
1. Extrae nuevos claims
2. Verifica contra el perfil (¿dijo algo no respaldado?)
3. Detecta si cubrió gaps pendientes
4. Extrae métricas mencionadas
5. Actualiza el resumen conversacional

---

## 11. Estilos de Respuesta

### Ejecutivo
Acción → Método → Resultado con métricas. "Yo [ACCIÓN] mediante [MÉTODO], logrando [RESULTADO]." Siempre empieza con "Yo" o "En mi rol como...". Al menos UNA métrica cuantificable. 150-220 palabras.

### Comercial
Necesidad empresa → Tu prueba → Valor futuro. "Entiendo que [necesidad]. En mi experiencia, [logro]. Puedo aportar [valor futuro]." Conecta CADA respuesta con el rol. Cierra mirando hacia adelante.

### Técnico
Problema → Analysis/Trade-offs → Implementación → Outcome. Usa terminología correcta. Menciona herramientas específicas. Habla de trade-offs, no solo de la solución elegida. Conecta lo técnico con impacto en negocio.

### Mixto (Adaptativo)
Auto-detecta según QuestionAnalysis.primary_type: behavioral → Ejecutivo, technical → Técnico, culture fit → Comercial, compound → selecciona per sub-question.

---

## 12. Quality Gate — Draft / Validate / Repair / Expose

### Fase A: Bullets (exposición inmediata)
LLM rápido genera 3-5 bullets → Mini-gate (heurísticas, <50ms) → Si pasa: mostrar → Si falla: swap métrica/claim → Mostrar bullets corregidos.

### Fase B: Respuesta completa (gated)
LLM principal genera en buffer (NO al UI) → Quality Gate REAL:

1. ¿Repite métrica ya usada en exchanges previos?
2. ¿Contradice claim previo del usuario?
3. ¿Cubre sub-preguntas must_answer?
4. ¿Idioma consistente con LanguageDecision?
5. ¿Largo apropiado? (< 250 palabras)
6. ¿Estilo correcto?

Si pasa → exponer. Si falla → Repair (1 intento con instrucciones específicas: "No uses métrica X, ya usada en exchange 2"). Si repair falla → Fallback determinista: solo bullets + "Usa los puntos clave como guía."

---

## 13. Language Policy — Contrato Formal

Reglas en orden de prioridad (la primera que aplica, gana):

1. **Preferencia fija del usuario** → usar ese idioma (confidence 1.0)
2. **Idioma dominante** (>80% de duración del turno) → usar ese
3. **Turno bilingüe** → idioma de la ÚLTIMA oración directa
4. **Confianza baja** (<0.6) → idioma estable de la sesión (últimos 3 exchanges)
5. **Fallback absoluto** → español

**Post-condición obligatoria:** La respuesta debe ser 100% en final_language. Excepciones: nombres propios y términos técnicos sin traducción natural. Quality Gate falla si mezcla idiomas fuera de excepciones.

---

## 14. Schema PostgreSQL + pgvector

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Perfiles
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL, resume_text TEXT,
    created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE achievements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id),
    title TEXT NOT NULL, context TEXT, action TEXT, result TEXT,
    metrics TEXT[], tags TEXT[],
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id),
    source TEXT NOT NULL, section TEXT, content TEXT NOT NULL,
    embedding VECTOR(1536), metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX ON achievements USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Configuración de entrevista (aliases lógicos, NO model IDs)
CREATE TABLE interview_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id),
    company_name TEXT NOT NULL, role_title TEXT NOT NULL,
    job_description TEXT, company_values TEXT[],
    response_style TEXT DEFAULT 'mixed',
    language_preference TEXT DEFAULT 'auto',
    custom_rules TEXT,
    stt_alias TEXT DEFAULT 'stt_primary',
    llm_alias TEXT DEFAULT 'llm_main',
    embedding_alias TEXT DEFAULT 'embedding_primary',
    provider_overrides JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Sesiones
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_id UUID REFERENCES interview_configs(id),
    status TEXT DEFAULT 'active',
    started_at TIMESTAMPTZ DEFAULT now(), ended_at TIMESTAMPTZ,
    summary JSONB
);

CREATE TABLE exchanges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id),
    index_in_session INT NOT NULL,
    interviewer_utterance TEXT NOT NULL, language_detected TEXT,
    question_analysis JSONB NOT NULL,
    suggested_response JSONB NOT NULL,
    quality_result JSONB NOT NULL,
    user_actual_response TEXT, latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Event log (append-only, replay + audit)
CREATE TABLE event_log (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    event_type TEXT NOT NULL, payload JSONB NOT NULL,
    trace_id TEXT, latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON event_log (session_id, created_at);

-- Métricas de latencia
CREATE TABLE latency_metrics (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    exchange_index INT, step_name TEXT NOT NULL,
    duration_ms INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 15. PersistQueue — Trade-off Documentado

Cola interna duradera que reemplaza fire-and-forget.

**Garantías:** Items encolados se escriben eventualmente. Si DB falla: retry con backoff exponencial (max 3). Si el proceso cierra: flush antes de exit via signal handler.

**Trade-off explícito (V1):** Cuando la cola se llena (>100 items, señal de DB caída), la política es DROP OLDEST + LOG del contenido perdido. Bajo presión extrema, los exchanges más antiguos en cola se pierden. Aceptable en V1 porque: (1) la entrevista en vivo no se bloquea, (2) los items droppeados se loguean con WARNING incluyendo contenido serializado para recovery manual, (3) en condiciones normales la cola nunca se llena. El UI muestra "⚠ Algunos datos no se pudieron guardar."

**Alternativas para V2:** Spill-to-disk, WAL local como buffer de emergencia, bloqueo con timeout.

---

## 16. Audio Capture — macOS-First

### ScreenCaptureKit (macOS 13+)

Crate Rust: `screencapturekit-rs`. Captura audio del sistema sin drivers externos. Requiere permiso de Screen Recording (solicitado automáticamente al primer uso).

```
tauri-app/src-tauri/src/audio/
├── mod.rs              # Selección de backend por OS (#[cfg])
├── traits.rs           # AudioCapture trait (interfaz común)
├── macos_capture.rs    # ScreenCaptureKit (V1)
├── windows_capture.rs  # WASAPI loopback (V1.5, stub)
├── linux_capture.rs    # PipeWire (V1.5, stub)
├── mic_capture.rs      # Mic via cpal (cross-platform)
└── router.rs           # Normaliza a PCM 16-bit 16kHz mono, chunks 100ms
```

Windows y Linux: stubs que retornan error descriptivo "Platform not supported in V1."

---

## 17. Targets de Latencia Honestos

| Tier | Contexto | Bullets | Primer token | Respuesta completa |
|------|----------|---------|-------------|-------------------|
| **Tier 1** | Benchmark (red local, APIs calientes) | 0.8-1.2s | 1.0-1.5s | 3-5s |
| **Tier 2** | Producción (WiFi normal, laptop promedio) | 1.2-2.0s | 1.5-2.5s | 4-8s |
| **Tier 3** | Degradado (red lenta, API con carga) | 2.0-3.0s | 2.5-4.0s | 5-12s |

**SLA del producto:** Tier 2 en el 90% de los casos. Si Tier 3 por más de 3 preguntas consecutivas → alertar al usuario.

---

## 18. Bootstrap y Operación Local

**bootstrap.sh** (hardened): Verifica OS, Docker, puertos, versión macOS. Levanta PostgreSQL+pgvector via Docker Compose. Aplica schema con `ON_ERROR_STOP=1` (falla en errores reales, tolera re-ejecución idempotente). Instala deps Python y Node con error real si fallan. Smoke test post-install: verifica que contracts Python importan.

**doctor.sh** (three-tier):
- Tier 1 (Structure): archivos del scaffold existen, .env, API keys
- Tier 2 (Infrastructure): Docker, PostgreSQL, pgvector, schema tables
- Tier 3 (Functional, post-bootstrap): Python imports (contracts, adapters, provider_registry, FastAPI), providers.yaml parsea, Node packages instalados

**Principio**: cero `|| true` en paths críticos. Si algo real falla, el script falla.

---

## 19. Test Deck — Suite de Pruebas Reales

El proyecto incluye un test deck completo en `tests/` con:
- **Fixtures de preguntas reales** (10+ preguntas en ES/EN, desde "cuéntame de ti" hasta stress questions)
- **Perfiles de prueba** (CTO con achievements y métricas verificables)
- **Simulaciones de entrevista completa** (5 exchanges con contexto acumulativo)
- **Tests de Quality Gate** (respuestas que DEBEN fallar validación)
- **Tests de Language Policy** (escenarios bilingües)
- **Tests de coherencia conversacional** (contradicciones, repeticiones, gaps)
- **Evaluación automatizada** con criterios pass/fail por dimensión

Ver `tests/fixtures/`, `tests/simulations/`, y `tests/unit/` para el deck completo.

---

## 20. Riesgos y Mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| Deepgram down | Fallback automático a Whisper local |
| Claude API lento/down | Fallback: mostrar solo bullets (LLM rápido) |
| ScreenCaptureKit permiso denegado | Wizard de setup con instrucciones |
| Transcripción con errores | Transcripción visible para validación antes de confiar |
| Respuesta no relevante | Quality gate bloquea + indicador de confianza |
| Mezcla de idiomas en respuesta | LanguagePolicy + Quality Gate check de idioma |
| PostgreSQL down | PersistQueue con retry; entrevista continúa sin persistir |
| Repetición de métricas | ConversationTracker + Quality Gate check |

---

## 19. Path de Evolución

**V1 (macOS-first):** Desktop local, audio via ScreenCaptureKit, PostgreSQL+pgvector via Docker, pipeline completo con quality gate, 4 estilos, simulaciones.

**V1.5:** Windows (WASAPI) + Linux (PipeWire). Bootstrap.ps1 para Windows. macOS 15+ Core Audio Taps como alternativa a ScreenCaptureKit.

**V2 (Hybrid/Web-ready):** Backend extraído como servicio independiente. Auth + multi-tenant. Chrome extension para audio capture web. Bus externo. Reviewer mode.
