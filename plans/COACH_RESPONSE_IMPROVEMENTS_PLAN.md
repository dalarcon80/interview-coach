# Plan de Mejoras para el Sistema de Respuestas del Coach

## Resumen de Problemas y Soluciones

| Problema | Estado Actual | Solución |
|----------|---------------|----------|
| Respuestas truncadas | max_tokens=1024 fijo, sin control de longitud | Agregar parámetro max_words configurable |
| Interview type bloqueado | El selector existe en UI pero no se usa en el prompt | Pasar interview_type al prompt para afectar el estilo |
| Control de longitud | No existe | Agregar slider en UI y enviar al backend |

---

## 1. Análisis del Código Actual

### 1.1 Response Composer (python-core/pipeline/steps/response_composer.py)

**Líneas críticas identificadas:**

- **Línea 470**: `max_tokens: 1024` - hardcoded, causa truncamiento
- **Líneas 700-708**: System prompt con "Keep responses 150-220 words"
- **Líneas 862-890**: Style instructions con word counts fijos por estilo
- **Línea 813**: `_build_prompt()` - necesita recibir max_words como parámetro

### 1.2 Backend API (python-core/api/server.py)

- **Líneas 139-161**: `SuggestRequest` model - agregar campos `max_words` e `interview_type`
- **Línea 1558**: Endpoint `/api/suggest` - extraer y pasar parámetros al pipeline

### 1.3 Frontend

- **CompanyInfoForm.tsx (Líneas 49-55)**: `INTERVIEW_TYPES` ya existe
- **CompanyInfoForm.tsx (Líneas 237-255)**: Selector de interview_type YA EXISTE
- **types/index.ts (Línea 31)**: `CompanyInfo.interview_type` ya existe

**Conclusión**: El problema no es la UI, es que `interview_type` no se está usando en el backend para afectar el estilo de la respuesta.

---

## 2. Diseño de Cambios

### 2.1 Flujo de Datos Propuesto

```mermaid
flowchart TD
    A[UI: max_words slider] --> B[SuggestionRequest]
    C[UI: interview_type selector] --> B
    B --> D[/api/suggest endpoint]
    D --> E[AssembledContext]
    E --> F[ResponseComposer._build_prompt]
    F --> G[Prompt con word count explícito]
    G --> H[LLM Adapter con max_tokens calculado]
    H --> I[Respuesta completa no truncada]
```

### 2.2 Cambios en Backend

#### 2.2.1 Modelos de Datos (contracts/models.py)

```python
class AssembledContext(BaseModel):
    # ... campos existentes ...
    interview_config: dict = Field(default_factory=dict)
    max_words: int = Field(default=200, ge=50, le=500)  # NUEVO
```

#### 2.2.2 SuggestRequest (api/server.py)

```python
class SuggestRequest(BaseModel):
    # ... campos existentes ...
    max_words: Optional[int] = Field(default=200, ge=50, le=500)
    interview_type: Optional[str] = None  # Override del company_info
```

#### 2.2.3 ResponseComposer (pipeline/steps/response_composer.py)

**Cambio 1**: Modificar `_compose_real` para recibir max_words:

```python
async def _compose_real(
    self,
    context: AssembledContext,
    on_bullets: Optional[Callable[..., Awaitable[None]]] = None,
) -> GeneratedResponse:
    # ... código existente ...
    
    # Calcular max_tokens basado en max_words (aprox 1.5 tokens por palabra)
    max_words = getattr(context, 'max_words', 200)
    max_tokens = min(int(max_words * 1.5), 4000)  # Cap en 4000
    
    config = {
        "temperature": 0.7,
        "max_tokens": max_tokens,  # Usar valor calculado
    }
```

**Cambio 2**: Modificar `_build_prompt` para incluir word count:

```python
def _build_prompt(self, context: AssembledContext, style: ResponseStyle) -> str:
    # ... código existente ...
    
    max_words = getattr(context, 'max_words', 200)
    interview_type = context.interview_config.get('interview_type', 'mixed')
    
    # Mapear interview_type a instrucciones específicas
    type_instructions = {
        'behavioral': 'Use STAR method (Situation, Task, Action, Result)',
        'technical': 'Focus on technical depth, trade-offs, and implementation details',
        'system_design': 'Structure as architecture overview → components → trade-offs → scaling',
        'case_study': 'Use business framework: problem → analysis → recommendation → risks',
        'mixed': 'Blend behavioral and technical elements as appropriate',
    }
    
    style_instructions = {
        ResponseStyle.EXECUTIVE: f"""
            Bullets: 3-5 key points, each 1-2 sentences.
            Paragraph: Action → Method → Result with metrics.
            Start with "I" or "In my role as...".
            Include at least ONE quantifiable metric.
            LENGTH: EXACTLY {max_words} words (±10%).
        """,
        # ... otros estilos con LENGTH dinámico ...
    }
    
    # En el prompt final:
    return f"""
    # ... contenido existente ...
    
    INTERVIEW TYPE: {interview_type}
    {type_instructions.get(interview_type, type_instructions['mixed'])}
    
    STYLE: {style.value}
    {style_instructions.get(style, style_instructions[ResponseStyle.MIXED])}
    
    CRITICAL: Generate a response of approximately {max_words} words.
    Count your words and ensure the response is complete, not truncated.
    """
```

### 2.3 Cambios en Frontend

#### 2.3.1 Types (tauri-app/src/types/index.ts)

```typescript
export interface SuggestionRequest {
  // ... campos existentes ...
  max_words?: number;  // NUEVO: 50-500 palabras
}

export interface CompanyInfo {
  // ... campos existentes ...
  interview_type: string;
  max_words?: number;  // NUEVO: opcional, default 200
}
```

#### 2.3.2 CompanyInfoForm - Agregar Control de Max Words

Agregar después del selector de interview_type (línea 255):

```tsx
<div className="space-y-2">
  <div className="flex items-center justify-between">
    <Label>Response length (words)</Label>
    <span className="text-sm font-medium">
      {companyInfo.max_words || 200} words
    </span>
  </div>
  <Slider
    min={50}
    max={500}
    step={10}
    value={[companyInfo.max_words || 200]}
    onValueChange={(value) => update("max_words", value[0])}
    disabled={readOnly}
  />
  <p className="text-xs text-muted-foreground">
    Approximate word count for coach responses
  </p>
</div>
```

#### 2.3.3 App.tsx - Enviar max_words en el request

En la función que hace el request a `/api/suggest`:

```typescript
const requestBody: SuggestionRequest = {
  question: questionText,
  candidate_profile: candidateProfile,
  company_info: companyInfo,
  style_id: style,
  language,
  max_words: companyInfo.max_words || 200,  // NUEVO
};
```

#### 2.3.4 SuggestionDisplay - Mostrar Word Count

Agregar indicador de palabras generadas vs solicitadas:

```tsx
<div className="flex items-center justify-between text-xs text-muted-foreground">
  <span>Target: {targetWords} words</span>
  <span>Generated: {actualWordCount} words</span>
</div>
```

---

## 3. Plan de Implementación Paso a Paso

### Fase 1: Backend - Modelos y Contratos (15 min)

1. **contracts/models.py**: Agregar `max_words` a `AssembledContext`
2. **api/server.py**: Agregar `max_words` e `interview_type` a `SuggestRequest`

### Fase 2: Backend - ResponseComposer (30 min)

1. Modificar `_compose_real` para calcular `max_tokens` desde `max_words`
2. Modificar `_build_prompt` para incluir:
   - Instrucción explícita de word count
   - Instrucciones basadas en `interview_type`
3. Validar que el response no esté truncado

### Fase 3: Frontend - Types (5 min)

1. Agregar `max_words` a `SuggestionRequest` y `CompanyInfo`

### Fase 4: Frontend - UI (20 min)

1. **CompanyInfoForm**: Agregar slider para `max_words`
2. **App.tsx**: Pasar `max_words` en el request
3. **SuggestionDisplay**: Agregar indicador de word count

### Fase 5: Testing (20 min)

1. Verificar que el word count se pasa correctamente
2. Verificar que el prompt incluye la instrucción
3. Verificar que las respuestas no se truncan
4. Verificar que interview_type afecta el estilo

---

## 4. Código de Implementación

### 4.1 Backend - contracts/models.py

```python
class AssembledContext(BaseModel):
    """Full context for response generation"""
    question: str = ""
    analysis: Optional[QuestionAnalysis] = None
    evidence: list[EvidenceChunk] = Field(default_factory=list)
    conversation_summary: str = ""
    conversation_history: list[dict] = Field(default_factory=list)
    topics_already_covered: list[str] = Field(default_factory=list)
    metrics_already_used: list[str] = Field(default_factory=list)
    achievements_referenced: list[str] = Field(default_factory=list)
    style_config: dict = Field(default_factory=dict)
    interview_config: dict = Field(default_factory=dict)
    max_words: int = Field(default=200, ge=50, le=500)  # NUEVO
```

### 4.2 Backend - api/server.py

```python
class SuggestRequest(BaseModel):
    """Request payload for manual /api/suggest coaching path."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    question: str = ""
    questionText: Optional[str] = None
    question_text: Optional[str] = None
    session_id: Optional[str] = None
    candidate_profile: Optional[dict[str, Any]] = None
    company_info: Optional[dict[str, Any]] = None
    style_id: Optional[str] = "professional"
    language: Optional[str] = "en"
    mode: Optional[Literal["real", "demo"]] = None
    profile_id: Optional[str] = None
    history_count: Optional[int] = None
    max_words: Optional[int] = Field(default=200, ge=50, le=500)  # NUEVO
    interview_type: Optional[str] = None  # NUEVO: override de company_info

    # Backward-compatible fields
    style: Optional[str] = None
    candidate: Optional[dict[str, Any]] = None
    company: Optional[dict[str, Any]] = None
```

### 4.3 Backend - ResponseComposer._compose_real

```python
async def _compose_real(
    self,
    context: AssembledContext,
    on_bullets: Optional[Callable[[GeneratedResponse], Awaitable[None] | None]] = None,
) -> GeneratedResponse:
    # ... código existente hasta línea 467 ...
    
    # Calcular max_tokens desde max_words (aprox 1.5 tokens/palabra)
    max_words = getattr(context, 'max_words', 200)
    max_tokens = min(int(max_words * 1.5) + 100, 4000)  # +100 para bullets, cap 4000
    
    config = {
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    
    # ... resto del código ...
```

### 4.4 Backend - ResponseComposer._build_prompt

```python
def _build_prompt(self, context: AssembledContext, style: ResponseStyle) -> str:
    # ... código existente hasta línea 860 ...
    
    max_words = getattr(context, 'max_words', 200)
    interview_type = context.interview_config.get('interview_type', 'mixed')
    
    # Instrucciones específicas por tipo de entrevista
    interview_type_instructions = {
        'behavioral': """
            Use STAR method:
            - Situation: Set the context
            - Task: What was required
            - Action: What YOU specifically did
            - Result: Quantified outcome
            Focus on YOUR actions, not the team's.""",
        'technical': """
            Structure: Problem → Analysis → Solution → Outcome
            Include:
            - Technical trade-offs considered
            - Specific technologies/tools used
            - Implementation details
            - Business impact of technical decisions""",
        'system_design': """
            Structure:
            1. Requirements clarification
            2. High-level architecture
            3. Component breakdown
            4. Data flow
            5. Trade-offs and alternatives
            6. Scaling considerations""",
        'case_study': """
            Use structured business thinking:
            1. Problem understanding
            2. Framework selection
            3. Analysis with data
            4. Recommendation
            5. Risk assessment
            6. Next steps""",
        'mixed': """
            Blend behavioral and technical elements.
            For behavioral aspects: use STAR method.
            For technical aspects: include trade-offs and implementation details.""",
    }
    
    type_instruction = interview_type_instructions.get(
        interview_type, 
        interview_type_instructions['mixed']
    )
    
    # Style instructions con word count dinámico
    style_instructions = {
        ResponseStyle.EXECUTIVE: f"""
            Bullets: 3-5 key points, each 1-2 sentences.
            Paragraph: Action → Method → Result with metrics.
            Start with "I" or "In my role as...".
            Include at least ONE quantifiable metric.
            TARGET LENGTH: {max_words} words (range: {int(max_words * 0.9)}-{int(max_words * 1.1)}).
        """,
        ResponseStyle.COMMERCIAL: f"""
            Bullets: 3-5 key points, each 1-2 sentences.
            Paragraph: Need → Proof → Value → Close.
            Connect to the role requirements.
            End with forward-looking statement.
            TARGET LENGTH: {max_words} words (range: {int(max_words * 0.9)}-{int(max_words * 1.1)}).
        """,
        ResponseStyle.TECHNICAL: f"""
            Bullets: 3-5 key points, each 1-2 sentences.
            Paragraph: Problem → Analysis → Solution → Outcome.
            Include technical trade-offs.
            Connect to business impact.
            TARGET LENGTH: {max_words} words (range: {int(max_words * 0.9)}-{int(max_words * 1.1)}).
        """,
        ResponseStyle.MIXED: f"""
            Bullets: 3-5 key points, each 1-2 sentences.
            Blend styles based on question type.
            Address all sub-questions if compound.
            TARGET LENGTH: {max_words} words (range: {int(max_words * 0.9)}-{int(max_words * 1.1)}).
        """,
    }
    
    # ... código de evidencia y CV ...
    
    return f"""
You are an interview coach helping a candidate answer a question.

QUESTION: {context.question}

PREVIOUS CONVERSATION (for context):
{conversation_section}

CANDIDATE EVIDENCE:
{evidence_section}
{company_filter_instruction}

CANDIDATE PROFILE:
- Name: {candidate_name or "Not provided"}
- Summary: {candidate_summary or "Not provided"}
- Skills: {candidate_skills_text}
- Certifications: {candidate_certs_text}
- Prior achievements:
{candidate_achievements_text}

TARGET COMPANY/ROLE:
- Company: {company_name or "Not provided"}
- Role: {role_title or "Not provided"}
- Industry: {company_industry or "Not provided"}
- Company description: {company_description or "Not provided"}
- Culture signals: {company_culture or "Not provided"}
- Role requirements:
{company_requirements_text}

INTERVIEW TYPE: {interview_type}
{type_instruction}

STYLE: {style.value}
{style_instructions.get(style, style_instructions[ResponseStyle.MIXED])}

ADAPTATION RULES:
- Ground the answer in the candidate profile and retrieved evidence; do not invent facts.
- Explicitly connect at least one candidate skill/achievement to the question.
- Explicitly connect at least one role requirement/culture signal to the response tone or content.
- Keep language natural and interview-ready.

CRITICAL LENGTH REQUIREMENT:
Generate a response of approximately {max_words} words.
The response MUST be complete and well-formed. Do not cut off mid-sentence.
If you cannot fit everything, prioritize the most relevant points.

OUTPUT FORMAT (MANDATORY):
[BULLETS]
- bullet 1
- bullet 2
- bullet 3
[/BULLETS]
[FULL_RESPONSE]
Single polished interview-ready response paragraph of {max_words} words.
[/FULL_RESPONSE]

Generate a response that the candidate can use as a basis for their answer.
The response should be natural, confident, and directly address the question.
"""
```

### 4.5 Frontend - types/index.ts

```typescript
export interface CompanyInfo {
  name: string;
  industry: string;
  size: string;
  culture: string;
  mission: string;
  values: string[];
  tech_stack: string[];
  role_title: string;
  role_level: string;
  role_requirements: string[];
  role_responsibilities: string[];
  interview_type: string;
  interview_focus: string[];
  job_description: string;
  max_words?: number;  // NUEVO
}

export interface SuggestionRequest {
  question?: string;
  session_id?: string;
  candidate_profile?: CandidateProfile;
  company_info?: CompanyInfo;
  style_id?: string;
  language?: string;
  mode?: "real" | "demo";
  profile_id?: string;
  history_count?: number;
  max_words?: number;  // NUEVO
}
```

### 4.6 Frontend - CompanyInfoForm.tsx

```tsx
// Agregar import de Slider
import { Slider } from "@/components/ui/slider";

// Después del selector de interview_type (línea 255), agregar:
<div className="space-y-2">
  <div className="flex items-center justify-between">
    <Label>Response length (words)</Label>
    <span className="text-sm font-medium text-primary">
      {companyInfo.max_words || 200} words
    </span>
  </div>
  <Slider
    min={50}
    max={500}
    step={10}
    value={[companyInfo.max_words || 200]}
    onValueChange={(value) => update("max_words", value[0])}
    disabled={readOnly}
  />
  <p className="text-xs text-muted-foreground">
    Approximate word count for coach responses. Longer responses take more time to generate.
  </p>
</div>
```

---

## 5. Plan de Pruebas

### 5.1 Verificación de Parámetros

```bash
# 1. Verificar que max_words se recibe en el backend
curl -X POST http://localhost:8000/api/suggest \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Tell me about yourself",
    "max_words": 100,
    "interview_type": "behavioral",
    "candidate_profile": {...},
    "company_info": {...}
  }'
```

### 5.2 Verificación de Prompt

```python
# En response_composer.py, agregar logging temporal:
print(f"[DEBUG] max_words in context: {getattr(context, 'max_words', 'NOT SET')}")
print(f"[DEBUG] interview_type: {context.interview_config.get('interview_type', 'NOT SET')}")
```

### 5.3 Verificación de Longitud

```python
# Contar palabras en la respuesta generada
word_count = len(full_response.split())
print(f"[DEBUG] Generated response: {word_count} words (target: {max_words})")
```

### 5.4 Criterios de Aceptación

| Criterio | Verificación |
|----------|--------------|
| max_words llega al backend | Log muestra valor correcto |
| Prompt incluye word count | Log de prompt muestra instrucción |
| Respuesta no truncada | Respuesta termina en oración completa |
| interview_type afecta estilo | Respuesta usa estructura correcta (STAR, etc.) |
| UI muestra contador | SuggestionDisplay muestra palabras generadas |

---

## 6. Rollback Plan

Si algo falla, revertir los cambios en este orden:

1. Frontend: Revertir cambios en `SuggestionDisplay`, `CompanyInfoForm`, `App.tsx`
2. Frontend: Revertir cambios en `types/index.ts`
3. Backend: Revertir cambios en `ResponseComposer`
4. Backend: Revertir cambios en `server.py`
5. Backend: Revertir cambios en `contracts/models.py`

Archivos a respaldar antes de empezar:
- `python-core/pipeline/steps/response_composer.py`
- `python-core/api/server.py`
- `python-core/contracts/models.py`
- `tauri-app/src/types/index.ts`
- `tauri-app/src/components/coach/CompanyInfoForm.tsx`
- `tauri-app/src/App.tsx`
- `tauri-app/src/components/coach/SuggestionDisplay.tsx`

---

## 7. Notas de Implementación

### Sobre Interview Type

El selector de `interview_type` **YA EXISTE** en la UI. El problema es que:
1. Se guarda en `company_info.interview_type`
2. Pero no se está usando en el backend para afectar el prompt
3. La solución es pasarlo explícitamente en `interview_config`

### Sobre Truncamiento

El truncamiento ocurre porque:
1. `max_tokens=1024` está hardcoded
2. Para 200 palabras se necesitan ~300 tokens
3. Para 500 palabras se necesitan ~750 tokens
4. La fórmula `max_tokens = min(int(max_words * 1.5) + 100, 4000)` da margen suficiente

### Sobre Latencia

Mayor `max_words` = mayor latencia:
- 100 palabras: ~1-2 segundos
- 200 palabras: ~2-3 segundos
- 500 palabras: ~4-6 segundos

El usuario debe ser informado de este trade-off en la UI.
