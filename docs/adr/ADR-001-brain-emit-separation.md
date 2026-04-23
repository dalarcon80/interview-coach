# ADR-001 — Separar `brain` de `emit`

- **Status:** Accepted (draft, to be ratified at end of F4)
- **Date:** 2026-04-22
- **Deciders:** architect
- **Supersedes:** contratos v1 monolíticos (`BrainPlan` con 43 campos)

## Contexto

El contrato `BrainPlan` actual (`python-core/contracts/models.py`) mezcla responsabilidades semánticas (qué está pidiendo realmente el interviewer, qué evidencia se necesita, qué coverage_points cubrir) con responsabilidades de render (qué tono usar, qué longitud, si incluir profile opening, qué estilo). Esto se confirma por inspección:

- 43 campos en una sola clase.
- 11 de ellos son puramente de render: `target_length`, `tone`, `directness`, `include_profile_opening`, `response_shape`, `delivery_instructions`, `evidence_depth`, `metrics_policy`, `ordered_coverage_required`, `question_completeness`, `question_type`.
- 3 campos con nombres casi idénticos (`literal_question`, `contextualized_question`, `resolved_question`) que el código usa de forma inconsistente.

`live_finalizer.py` (2,050 LOC) es el módulo que "emite" pero reinterpreta la intención porque el contrato no impone boundary. El resultado: iteración lenta, reintentos, respuestas que no siguen la pregunta real, churn del plan.

## Decisión

Separar formalmente `brain` y `emit` con dos contratos versionados:

1. **`BrainPlan v2`** — puramente semántico. Incluye:
   - `ResolvedAsk` (primary_ask, secondary_asks, focus_order, family, shape_hint, complexity)
   - `InterviewerIntent` (summary, dimensions, evidence_expected, decision_target)
   - `AnswerBlueprint` (required_moves, must_cover, avoid, evidence_requests)
   - `context_window: list[TurnRef]`
   - `confidence`, `stability`, `plan_source`
   - **cero campos de render** (prohibido `tone`, `target_length`, `directness`, etc.)
2. **`EmissionContract`** — puramente de render. Incluye:
   - `render_shape`, `target_length_words`, `tone`, `language`, `bullets_preview`
   - `must_cover`, `avoid`, `style_guard`
   - `evidence_pack_id: UUID`
   - `emit_readiness_score: float`
   - FK a `brain_plan_id`.

Habrá una función explícita `emit.builder.build(plan: BrainPlan, evidence, style_config) -> EmissionContract`. Esa función es el único lugar donde se traduce semántica a render.

El renderer (`emit/renderer.py`) consume `EmissionContract` y produce `GeneratedResponse v2` (full_response primario, bullets apoyo) con un LLM call puntual.

## Consecuencias

### Positivas

- **Iteración independiente**: mejorar el entendimiento del ask no toca el render; mejorar el estilo no toca el brain.
- **Tests más nítidos**: `test_planner_deterministic` sin mocks de LLM de render; `test_builder_from_plan` sin mocks de LLM de brain.
- **A/B más seguro**: se puede reemplazar el planner sin tocar emit, o viceversa, con feature flags separadas.
- **Replay determinista**: dado un `BrainPlan` guardado, el builder debe producir el mismo `EmissionContract` sin llamar a ningún LLM.
- **Persistencia auditable**: tablas `brain_plans` y `emission_contracts` separadas, con FK entre ellas.

### Negativas

- **Coste de migración**: todo código que lea `BrainPlan` v1 debe moverse. Mitigación: mantener `contracts/models.py` v1 como legacy marcado `deprecated`, y coexistir por una release.
- **Dos LLM calls potenciales**: uno para planificación (llm_fast), otro para render. Mitigación: el planner puede usar `safe_fallback` determinista y sólo el renderer llama a LLM en el 80% de los casos.

### Neutras

- Aumenta la cantidad de módulos pero cada uno es pequeño y claro.

## Alternativas consideradas

1. **Dejar todo en `BrainPlan`**: actual. Rechazado por evidencia empírica de fragilidad.
2. **Fusionar `emission_contract` dentro de `brain_plan`**: habría sido más compacto, pero perpetúa el problema.
3. **Solo un `FullResponsePlan` + renderer**: considerado, pero no permite el paso `plan_draft_from_hypothesis` sin comprometer al render.

## Compliance HR

- **HR-1**: no afecta live caption (`live_caption.py` queda fuera).
- **HR-2**: `context_window` respeta la regla 4-turn.
- **HR-3**: contratos v2 coexisten con v1. Rollback = feature flag off.
- **HR-4**: el manual coach endpoint consume `EmissionContract → GeneratedResponse` igual que el live path, pero con su propio `builder` parametrizado (sin EoT detector).

## Implementación

Ver `IMPLEMENTATION_PLAN.md` §F4-T1..F4-T11 y `execution_plan.yaml`.

## Rollback

`INTERVIEW_COACH_BRAIN_V2=false` → pipeline vuelve a legacy (`live_brain_service.py` + `live_finalizer.py`). Contratos v1 intactos durante una release.

## Métricas de éxito

- `BrainPlan v2` jamás contiene campos `tone|target_length|directness|include_profile_opening|evidence_depth` (test automatizado).
- `build(plan, evidence)` es determinista: hash de inputs iguales → hash de output igual (test).
- Tiempo medio `brain.ms` y `emit.ms` medibles por separado en Grafana.
- Iteraciones en brain o emit tocan cero archivos del módulo hermano (medible por `git log --stat`).

## Referencias

- `docs/audit/AUDIT_REPORT.md` §1 CR-4
- `docs/audit/TARGET_ARCHITECTURE.md` §4, §5
- `docs/audit/LIVE_PIPELINE_REDESIGN.md` §4, §7
