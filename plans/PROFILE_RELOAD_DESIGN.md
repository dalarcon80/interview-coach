# Profile Reload & Reindex Design

## Problem Statement

El usuario necesita poder:
1. **Editar su perfil** (CV, logros, habilidades) después de la carga inicial
2. **Recargar/Reindexar** el perfil en la base de datos para regenerar los embeddings
3. **Verificar** que las respuestas del coach usan el contexto actualizado
4. **Hacer pruebas agresivas** cambiando el perfil y validando que las respuestas cambian

### Estado Actual (Problema)

| Aspecto | Estado |
|---------|--------|
| Carga inicial CV | ✅ Funcional - `/api/analyze-cv` persiste en DB con embeddings |
| Edición de perfil | ✅ Funcional - `CandidateProfileForm` edita en localStorage |
| Persistencia de ediciones | ❌ **ROTO** - Ediciones no se reflejan en DB/embeddings |
| Reindexación | ❌ **NO EXISTE** - No hay forma de regenerar embeddings después de editar |
| Verificación de evidencia | ❌ **NO EXISTE** - No hay visibilidad de qué evidencia se recupera |

## Arquitectura de la Solución

### Flujo Actual vs Deseado

```mermaid
flowchart LR
    subgraph "Flujo ACTUAL (Roto)"
        A[Usuario edita perfil] --> B[Guarda en localStorage]
        B --> C[Pregunta al coach]
        C --> D[Backend busca en DB]
        D --> E[Devuelve evidencia VIEJA]
        E --> F[Respuesta usa contexto desactualizado]
    end

    subgraph "Flujo DESEADO (Fix)"
        G[Usuario edita perfil] --> H[Guarda en localStorage]
        H --> I[Clic "Reindexar Perfil"]
        I --> J[POST /api/profile/reindex]
        J --> K[Backend regenera embeddings]
        K --> L[Usuario pregunta al coach]
        L --> M[Backend busca en DB]
        M --> N[Devuelve evidencia ACTUALIZADA]
        N --> O[Respuesta usa contexto actualizado]
    end
```

### Endpoints Nuevos Requeridos

#### 1. `POST /api/profile/reindex` - Reindexar Perfil
**Propósito:** Regenerar embeddings cuando el usuario edita su perfil manualmente

**Request:**
```json
{
  "profile": {
    "name": "string",
    "current_role": "string",
    "years_experience": 10,
    "skills": ["string"],
    "achievements": ["string"],
    "summary": "string",
    "cv_text": "string"
  }
}
```

**Response:**
```json
{
  "success": true,
  "profile_id": "uuid",
  "embeddings_created": 15,
  "achievements_indexed": 5,
  "chunks_indexed": 10
}
```

**Lógica:**
1. Buscar perfil existente por nombre o crear nuevo
2. Eliminar embeddings antiguos (`achievements` + `document_chunks`)
3. Generar nuevos embeddings para:
   - Cada logro (achievements)
   - Chunks del CV (si hay cv_text)
4. Insertar nuevos registros con embeddings

#### 2. `POST /api/debug/retrieve-evidence` - Verificar Evidencia
**Propósito:** Permitir al usuario ver qué evidencia se recupera para una pregunta

**Request:**
```json
{
  "question": "Tell me about your leadership experience",
  "profile_id": "uuid (opcional)"
}
```

**Response:**
```json
{
  "evidence": [
    {
      "source": "achievement|document_chunk",
      "content": "Led team of 12 engineers...",
      "similarity_score": 0.89,
      "metadata": {...}
    }
  ],
  "total_found": 5,
  "query_used": "leadership experience team management"
}
```

### Cambios en Frontend

#### 1. Botón "Reindexar Perfil" en CandidateProfileForm
- Ubicación: Al lado del botón "Guardar"
- Estado: Loading mientras reindexa
- Feedback: Toast con resultado (X logros indexados, Y chunks indexados)

#### 2. Panel de Debug de Evidencia
- Nueva sección colapsable en `SuggestionDisplay`
- Muestra qué evidencia se usó para generar la respuesta
- Incluye similarity scores

#### 3. Indicador de Estado de Indexación
- Badge que muestra si el perfil está indexado
- Fecha de última indexación

### Base de Datos - Consideraciones

#### Soft Delete vs Hard Delete
Para permitir comparación A/B durante pruebas:
- Opción A: Hard delete + reinsert (más simple, pierde histórico)
- Opción B: Soft delete + marca "active" (permite rollback)

**Decisión:** Opción A (Hard delete) - más simple para el caso de uso actual.

#### Query de Eliminación
```sql
-- Eliminar achievements del perfil
DELETE FROM achievements WHERE profile_id = $1;

-- Eliminar document chunks del perfil
DELETE FROM document_chunks WHERE profile_id = $1;

-- Actualizar timestamp del perfil
UPDATE user_profiles SET updated_at = NOW() WHERE id = $1;
```

## Plan de Implementación

### Fase 1: Backend - Endpoint de Reindexación
1. Crear función `_reindex_profile()` en `server.py`
2. Crear endpoint `POST /api/profile/reindex`
3. Reutilizar lógica de `_persist_cv_embeddings()`

### Fase 2: Backend - Endpoint de Debug
1. Crear endpoint `POST /api/debug/retrieve-evidence`
2. Exponer resultados del `EvidenceRetriever`

### Fase 3: Frontend - UI de Reindexación
1. Agregar método `reindexProfile()` en `api-client.ts`
2. Agregar botón en `CandidateProfileForm`
3. Agregar estado de loading y feedback

### Fase 4: Frontend - Debug de Evidencia
1. Agregar método `debugEvidence()` en `api-client.ts`
2. Crear componente `EvidenceDebugPanel`
3. Integrar en `SuggestionDisplay`

### Fase 5: Testing
1. Script de prueba que:
   - Carga CV inicial
   - Hace pregunta y captura evidencia
   - Edita perfil (cambia logros)
   - Reindexa
   - Hace misma pregunta y verifica evidencia cambió
   - Valida que respuesta cambió

## Criterios de Aceptación

- [ ] Usuario puede editar perfil y clicar "Reindexar"
- [ ] Reindexación regenera embeddings en < 5 segundos
- [ ] Panel de debug muestra evidencia recuperada
- [ ] Cambios en perfil se reflejan en respuestas del coach
- [ ] Script de prueba valida flujo completo

## Labels de Truth

| Componente | Estado Actual | Estado Deseado |
|------------|---------------|----------------|
| `/api/analyze-cv` | functional | functional |
| `/api/profile/reindex` | **stub** | functional |
| `/api/debug/retrieve-evidence` | **stub** | functional |
| UI Reindexar | **stub** | functional |
| UI Debug Evidencia | **stub** | functional |
