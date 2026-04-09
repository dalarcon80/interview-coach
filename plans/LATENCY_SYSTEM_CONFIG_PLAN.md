# Plan: Habilitar STT Local desde Settings (Sin Romper Configuración Actual)

## Resumen del Requerimiento

1. **Agregar en Settings del app** - Nueva opción para STT local
2. **No afectar configuración actual** - Mantener todo como está por defecto
3. **Configurable manualmente desde Settings** - Toggle para habilitar/deshabilitar
4. **Mantener configuraciones actuales** - Deepgram sigue siendo el default

---

## Arquitectura de la Solución

```
┌─────────────────────────────────────────────────────────────────┐
│                     FRONTEND (Tauri App)                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ SettingsPanel.tsx                                         │  │
│  │   - Toggle: "Usar STT Local (Whisper)"                    │  │
│  │   - Slider: Modelo (base/small/medium)                    │  │
│  │   - Solo visible/habilitable si dependencies instaladas    │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     BACKEND (FastAPI)                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Runtime Config (persisted)                                 │  │
│  │   - stt.provider: "deepgram" | "whisper_local"           │  │
│  │   - stt.local_model: "base" | "small" | "medium"         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ STT Adapter Factory                                       │  │
│  │   Lee provider de config → crea el adapter apropiado     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementación por Componente

### 1. Extender RuntimeConfig

**Archivo**: [`python-core/api/server.py`](python-core/api/server.py)

```python
class LatencyConfig(BaseModel):
    """Latency configuration for real-time processing"""
    utterance_end_ms: int = 2000
    silence_threshold_ms: int = 500
    min_utterance_duration_ms: int = 300
    suggestion_cooldown_sec: int = 3

# NUEVO: Agregar configuración de STT local
class STTConfig(BaseModel):
    provider: str = "deepgram"  # "deepgram" | "whisper_local"
    model: str = "nova-3"
    api_key: str = ""
    enabled: bool = True
    # NUEVO: Configuración local
    local_model: str = "base"  # "base" | "small" | "medium"
    local_enabled: bool = False  # Toggle para STT local
```

### 2. Modificar STT Adapter Factory

**Archivo**: [`python-core/adapters/stt_adapter.py`](python-core/adapters/stt_adapter.py)

```python
def STTAdapterFactory.create(config: dict = None):
    # Leer provider de config (no de entorno, sino de runtime config)
    provider = (config or {}).get("provider", "deepgram").lower()
    
    if provider == "deepgram":
        return DeepgramSTTAdapter(api_key=config.get("api_key"))
    elif provider == "whisper_local":
        return WhisperLocalSTTAdapter(
            model_size=config.get("local_model", "base")
        )
    # ... resto sin cambios
```

### 3. Implementar WhisperLocalSTTAdapter

**Archivo**: [`python-core/adapters/stt_adapter.py`](python-core/adapters/stt_adapter.py)

Nueva clase:

```python
class WhisperLocalSTTAdapter(STTAdapter):
    """
    Local Whisper STT usando faster-whisper.
    Funciona offline sin API externa.
    """
    
    def __init__(self, model_size: str = "base"):
        self._model_size = model_size
        self._model = None
        self._session_id = "unknown"
    
    async def connect(self, config: dict, session_id: Optional[str] = None) -> None:
        """Cargar modelo Whisper"""
        from faster_whisper import WhisperModel
        # CPU con int8 para velocidad
        self._model = WhisperModel(
            self._model_size, 
            device="cpu", 
            compute_type="int8"
        )
    
    async def open_stream(self, session_id: Optional[str] = None) -> None:
        self._session_id = str(session_id or "unknown")
    
    async def stream_audio(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[TranscriptionEvent, None]:
        """Procesar audio chunks con modelo local"""
        # Implementar streaming con faster-whisper
        # Mantiene misma interfaz que DeepgramSTTAdapter
        audio_buffer = b""
        
        async for chunk in audio_chunks:
            audio_buffer += chunk
            # Transcribir cuando haya suficiente audio
            if len(audio_buffer) > 16000 * 2:  # 1 segundo
                segments, info = self._model.transcribe(
                    audio_buffer,
                    language="auto",
                    beam_size=1,  # Más rápido
                )
                
                for segment in segments:
                    yield TranscriptionEvent(
                        text=segment.text,
                        is_final=not segment.end,  # Último segmento = final
                        confidence=info.language_probability,
                        language=info.language,
                        speaker="unknown",
                    )
                audio_buffer = b""
    
    async def close_stream(self, session_id: Optional[str] = None) -> None:
        pass
    
    async def disconnect(self, session_id: Optional[str] = None) -> None:
        self._model = None
```

### 4. Actualizar SettingsPanel.tsx

**Archivo**: [`tauri-app/src/components/settings/SettingsPanel.tsx`](tauri-app/src/components/settings/SettingsPanel.tsx)

Agregar nueva sección:

```tsx
// En persistence.ts - agregar a RuntimeConfig
export interface LocalSTTConfig {
  enabled: boolean;
  model: "base" | "small" | "medium";
}

// En SettingsPanel.tsx
<Card>
  <CardHeader>
    <CardTitle>STT Local (Opcional)</CardTitle>
    <CardDescription>
      Usar Whisper local en lugar de Deepgram.
      Requiere instalación de faster-whisper.
    </CardDescription>
  </CardHeader>
  <CardContent className="space-y-4">
    <div className="flex items-center justify-between">
      <Label>Usar STT Local</Label>
      <Switch
        checked={localSTTConfig.enabled}
        onCheckedChange={(checked) => 
          updateSTTConfig({ ...localSTTConfig, enabled: checked })
        }
      />
    </div>
    
    {localSTTConfig.enabled && (
      <div className="space-y-2">
        <Label>Modelo</Label>
        <Select
          value={localSTTConfig.model}
          onValueChange={(value: "base" | "small" | "medium") =>
            updateSTTConfig({ ...localSTTConfig, model: value })
          }
        >
          <SelectItem value="base">Base (más rápido)</SelectItem>
          <SelectItem value="small">Small</SelectItem>
          <SelectItem value="medium">Medium (más preciso)</SelectItem>
        </Select>
      </div>
    )}
  </CardContent>
</Card>
```

### 5. Crear Requirements

**Archivo nuevo**: `requirements-whisper.txt`

```
faster-whisper>=0.10.0
```

---

## Flujo de Usuario

### Caso 1: Usuario Normal (sin cambios)

1. Abre Settings
2. Ve configuración de Deepgram como siempre
3. No toca nada → usa Deepgram normalmente ✅

### Caso 2: Usuario quiere STT Local

1. Instala dependencias: `pip install faster-whisper`
2. Abre Settings
3. Ve nueva sección "STT Local"
4. Toggle "Usar STT Local" → ON
5. Selecciona modelo (base/small/medium)
6. Guarda configuración
7. App usa Whisper local ✅

### Caso 3: Volver a Deepgram

1. Toggle "Usar STT Local" → OFF
2. Guarda
3. Vuelve a usar Deepgram ✅

---

## Archivos a Modificar

| Archivo | Cambio | ¿Rompimiento? |
|---------|--------|---------------|
| `python-core/api/server.py` | Agregar local_enabled y local_model a STTConfig | NO |
| `python-core/adapters/stt_adapter.py` | Agregar WhisperLocalSTTAdapter + factory | NO |
| `python-core/runtime_config.json` | Agregar defaults (no necesario) | NO |
| `tauri-app/src/lib/persistence.ts` | Agregar LocalSTTConfig interface | NO |
| `tauri-app/src/lib/api-client.ts` | Agregar update método si needed | NO |
| `tauri-app/src/components/settings/SettingsPanel.tsx` | Agregar UI toggle | NO |
| `requirements-whisper.txt` | Nuevo archivo | NO |

---

## Pendiente

1. **¿Qué modelo de Whisper por defecto?** (base/small/medium)
2. **¿Tienes GPU NVIDIA?** (para optimizar el modelo)
3. **¿Quieres que agregue validación de dependencies?** (mostrar warning si no está instalado faster-whisper)

¿Procedemos con la implementación?
