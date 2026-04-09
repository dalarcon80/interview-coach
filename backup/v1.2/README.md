# Backup v1.2 - Conversation History Fix

**Fecha:** 2026-03-19  
**Propósito:** Punto de rollback antes de arreglar el bug donde `conversation_history` llega vacío al backend

## Archivos Respaldados

### 1. `App.tsx`
- **Ubicación original:** `tauri-app/src/App.tsx`
- **Descripción:** Frontend de React/TypeScript para la aplicación Tauri
- **Contenido clave:** 
  - Estado de `conversationHistory` en el frontend
  - Lógica de envío de transcripciones al backend
  - Manejo de WebSocket para live caption

### 2. `server.py`
- **Ubicación original:** `python-core/api/server.py`
- **Descripción:** Backend FastAPI con endpoints WebSocket
- **Contenido clave:**
  -接收 `conversation_history` del frontend
  - Pipeline del coach
  - Manejo de mensajes WebSocket

## Bug a Arreglar

**Problema:** El `conversation_history` llega vacío al backend a pesar de que la UI muestra transcripciones.

**Síntomas observados:**
- La UI muestra correctamente las transcripciones en tiempo real
- El historial de conversación se visualiza en el panel lateral
- Al hacer una consulta manual al coach, el historial llega vacío

**Posibles causas (a investigar):**
1. El estado no se está persistiendo correctamente desde STT events
2. El `conversation_history` no se está enviando en el payload correcto
3. El backend no está interpretando correctamente el campo recibido

## Procedimiento de Rollback

Si los cambios para arreglar el bug fallan, ejecutar:

```bash
# Restaurar frontend
cp backup/v1.2/App.tsx tauri-app/src/App.tsx

# Restaurar backend
cp backup/v1.2/server.py python-core/api/server.py

# Reiniciar servicios
# (Reiniciar backend Python y frontend Tauri)
```

## Notas Adicionales

- Este backup es **CRÍTICO** porque los cambios pueden afectar la integridad del flujo de datos entre frontend y backend
- Antes de modificar, verificar que los archivos actuales tienen los cambios mencionados
- Documentar cualquier observación del estado actual de los archivos
