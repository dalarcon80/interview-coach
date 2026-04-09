# Plan: Agregar Soporte Whisper Local (Con Rollback)

## Estado Actual

- ✅ `WhisperLocalSTTAdapter` existe en `python-core/adapters/stt_adapter.py`
- ✅ Factory busca `local_enabled` en runtime_config
- ❌ `runtime_config.json` NO tiene campos local_enabled
- ❌ UI no tiene toggle

## Análisis de Errores Anteriores

1. **Cambios muy complejos** - Modifiqué demasiadas cosas a la vez
2. **No probé incrementalmente** - Cambié todo y después probé
3. **UI demasiado compleja** - Agregué dropdowns y toggles que rompieron el formulario
4. **No había rollback** - No tenía forma de volver atrás

## Nuevo Enfoque: Mínimo Impacto

### Estrategia
1. **Solo modificar runtime_config.json** - Agregar campos opcionales
2. **NO modificar UI** - Mantener Settings como está
3. **NO modificar persistence.ts** - Mantener tipos como están
4. **Solo modificar factory** - Donde ya está la lógica
5. **Verificar que Deepgram siga funcionando** después de cada cambio

---

## Plan de Implementación (Steps Pequeños)

### Step 1: Actualizar runtime_config.json
**Archivo**: `python-core/runtime_config.json`

Agregar campos opcionales al final (sin romper config existente):
```json
{
  "stt": {
    "provider": "deepgram",
    "model": "nova-3",
    "api_key": "...",
    "enabled": true,
    "local_model": "small",
    "local_enabled": false
  }
}
```

**Verificar**: Reiniciar backend, probar Deepgram

### Step 2: Verificar Factory
**Archivo**: `python-core/adapters/stt_adapter.py`

La factory ya tiene la lógica:
```python
local_enabled = stt_config.get("local_enabled", False)
if local_enabled:
    return WhisperLocalSTTAdapter(...)
```

**Verificar**: Logs muestran `local_enabled=False` para Deepgram

### Step 3: Test Whisper (manual)
Editar runtime_config.json:
```json
"local_enabled": true
```
Reiniciar backend, verificar que cargue Whisper

### Step 4: UI (opcional, solo si steps 1-3 funcionan)
Si todo funciona, agregar UI simple más adelante

---

## Rollback Plan

Si algo falla:

1. **Step 1**: Eliminar `local_model` y `local_enabled` de runtime_config.json
2. **Backend**: Reiniciar, Deepgram debe funcionar

---

## Archivos a Modificar

| Archivo | Cambio | Riesgo |
|--------|-------|--------|
| `python-core/runtime_config.json` | Agregar 2 campos | BAJO (campos nuevos, no rompen) |
| `python-core/adapters/stt_adapter.py` | Ya tiene lógica | BAJO (ya existe) |

**Archivos QUE NO tocamos**:
- `persistence.ts` ❌
- `SettingsPanel.tsx` ❌  
- `server.py` ❌

---

## Verificación Requerida

Después de cada step:

1. ✅ TypeScript compila
2. ✅ Python syntax válido
3. ✅ Backend inicia sin errores
4. ✅ Deepgram funciona (probar en UI)
5. ✅ Logs muestran configuración correcta

---

## Orden de Ejecución

1. [ ] Modificar runtime_config.json
2. [ ] Reiniciar backend
3. [ ] Verificar Deepgram funciona
4. [ ] Revisar logs: debe mostrar `local_enabled=False`
5. [ ] (Opcional) Test Whisper
6. [ ] (Opcional) Agregar UI

¿Procedemos con Step 1?