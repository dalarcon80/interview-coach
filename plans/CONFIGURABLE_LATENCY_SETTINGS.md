# Design: Configurable Latency Parameters in Settings

## Objective
Allow users to configure latency-related parameters from the Settings UI in the Tauri desktop app, instead of having them hardcoded. Keep current default values, but allow testing different configurations.

## Current Architecture

### Existing Settings Infrastructure
- **Frontend**: `tauri-app/src/lib/persistence.ts` has `RuntimeConfig` interface with `llm` and `stt` properties
- **API Client**: `tauri-app/src/lib/api-client.ts` already has `getRuntimeConfig()` and `updateRuntimeConfig()` methods
- **Settings Panel**: `tauri-app/src/components/settings/SettingsPanel.tsx` - existing settings UI
- **Backend**: `python-core/api/server.py` has runtime config endpoints

### Current Latency Parameters (Hardcoded)

| Parameter | File | Current Value | Description |
|-----------|------|---------------|-------------|
| `utterance_end_ms` | `python-core/adapters/stt_adapter.py` | 2500 | Deepgram waits this ms of silence before finalizing transcript |
| `silence_threshold_ms` | `python-core/pipeline/steps/turn_assembler.py` | 2000 | Minimum silence to detect end of speaker turn |
| `silence_threshold_ms` | `python-core/pipeline/realtime_pipeline.py` | 2500 | Pipeline-level silence threshold |
| `_min_utterance_duration_ms` | `python-core/api/server.py` | 2000 | Minimum utterance duration to process |
| `_suggestion_cooldown_sec` | `python-core/api/server.py` | 5.0 | Cooldown between suggestions |

## Proposed Design

### 1. Extended RuntimeConfig Interface

```typescript
// tauri-app/src/lib/persistence.ts

export interface STTConfig {
  provider: "deepgram";
  model: string;
  api_key: string;
  enabled: boolean;
  // NEW: Latency parameters
  utterance_end_ms?: number;      // Deepgram: 100-3000ms
  min_utterance_duration_ms?: number; // Min audio before processing
}

export interface PipelineConfig {
  silence_threshold_ms?: number;  // Turn detection threshold
  suggestion_cooldown_sec?: number; // Between suggestions
}
```

### 2. Backend API Changes

#### New Endpoint: GET /api/config/runtime
Returns current runtime configuration including latency params.

#### New Endpoint: PATCH /api/config/runtime
Allows partial updates to runtime configuration.

```python
# python-core/api/server.py additions

@router.patch("/api/config/runtime")
async def update_runtime_config(config: RuntimeConfigUpdate):
    """Update runtime configuration including latency parameters"""
    # Validates and applies new settings
    # Returns updated config
```

### 3. Settings Panel UI

Add new "Latency" section in SettingsPanel.tsx:

```tsx
// New section in SettingsPanel.tsx
<Card>
  <CardHeader>
    <CardTitle>Latency Settings</CardTitle>
    <CardDescription>
      Configure transcription and response timing parameters
    </CardDescription>
  </CardHeader>
  <CardContent className="space-y-4">
    <div className="space-y-2">
      <Label>Utterance End Delay (ms)</Label>
      <Slider 
        value={[sttConfig.utterance_end_ms]} 
        onValueChange={(v) => updateSttConfig({ utterance_end_ms: v[0] })}
        min={100}
        max={3000}
        step={100}
      />
      <p className="text-sm text-muted-foreground">
        How long Deepgram waits for silence before finalizing transcript.
        Lower = faster but may cut off speech. Current: {sttConfig.utterance_end_ms}ms
      </p>
    </div>

    <div className="space-y-2">
      <Label>Turn Detection Threshold (ms)</Label>
      <Slider 
        value={[pipelineConfig.silence_threshold_ms]}
        onValueChange={(v) => updatePipelineConfig({ silence_threshold_ms: v[0] })}
        min={500}
        max={5000}
        step={100}
      />
      <p className="text-sm text-muted-foreground">
        Minimum silence to detect end of speaker turn.
        Current: {pipelineConfig.silence_threshold_ms}ms
      </p>
    </div>

    <div className="space-y-2">
      <Label>Suggestion Cooldown (seconds)</Label>
      <Slider 
        value={[pipelineConfig.suggestion_cooldown_sec]}
        onValueChange={(v) => updatePipelineConfig({ suggestion_cooldown_sec: v[0] })}
        min={1}
        max={15}
        step={0.5}
      />
      <p className="text-sm text-muted-foreground">
        Minimum time between suggestions.
        Current: {pipelineConfig.suggestion_cooldown_sec}s
      </p>
    </div>

    <Button onClick={saveConfig}>Apply Changes</Button>
  </CardContent>
</Card>
```

### 4. Backend Parameter Integration

Modify components to read from runtime config instead of hardcoded values:

```python
# python-core/adapters/stt_adapter.py
class DeepgramAdapter:
    def __init__(self, config: dict = None):
        self.utterance_end_ms = config.get("utterance_end_ms", 2500)  # Read from runtime config
        
    def _get_deepgram_options(self) -> dict:
        return {
            "encoding": "linear16",
            "sample_rate": 16000,
            "channels": 1,
            "endpointing": str(self.utterance_end_ms),  # Use configurable value
            # ... other options
        }
```

```python
# python-core/pipeline/steps/turn_assembler.py
class TurnAssembler:
    def __init__(self, config: dict = None):
        self.silence_threshold_ms = config.get("silence_threshold_ms", 2000)
```

### 5. Configuration Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Settings UI    │────▶│  API Client      │────▶│  Backend API    │
│  (Tauri App)    │     │  (api-client)    │     │  (FastAPI)      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                                                │
        │                                                ▼
        │                                       ┌─────────────────┐
        │                                       │  Runtime Config │
        │                                       │  (in-memory)    │
        │                                       └─────────────────┘
        │                                                │
        ▼                                                ▼
┌─────────────────┐                            ┌─────────────────┐
│  Persist to     │                            │  Components     │
│  localStorage   │                            │  (STT, Turn,    │
└─────────────────┘                            │   Pipeline)     │
                                               └─────────────────┘
```

## Implementation Steps

### Phase 1: Backend API
1. Extend `RuntimeConfig` model to include latency params
2. Add PATCH endpoint for runtime config updates
3. Modify STT adapter to accept config injection
4. Modify TurnAssembler to accept config injection

### Phase 2: Frontend Integration
1. Update `persistence.ts` interfaces
2. Update `api-client.ts` methods
3. Add latency section to SettingsPanel.tsx

### Phase 3: Testing
1. Test parameter changes take effect
2. Verify default values preserved
3. Test persistence across app restarts

## Default Values (To Be Preserved)

| Parameter | Default | Min | Max | Recommended for Testing |
|-----------|---------|-----|-----|------------------------|
| `utterance_end_ms` | 2500 | 100 | 3000 | 1000, 1500, 2000 |
| `silence_threshold_ms` | 2000 | 500 | 5000 | 1000, 1500 |
| `suggestion_cooldown_sec` | 5.0 | 1.0 | 15.0 | 3.0, 4.0 |

## Trade-offs to Document for Users

- **Lower utterance_end_ms**: Faster transcription but may truncate speech
- **Lower silence_threshold_ms**: Faster turn detection but may misinterpret pauses
- **Lower suggestion_cooldown_sec**: More frequent suggestions but may overwhelm

## Files to Modify

1. `python-core/api/server.py` - Add PATCH endpoint
2. `python-core/adapters/stt_adapter.py` - Accept runtime config
3. `python-core/pipeline/steps/turn_assembler.py` - Accept runtime config  
4. `python-core/pipeline/realtime_pipeline.py` - Accept runtime config
5. `tauri-app/src/lib/persistence.ts` - Extend interfaces
6. `tauri-app/src/lib/api-client.ts` - Add update methods
7. `tauri-app/src/components/settings/SettingsPanel.tsx` - Add UI section

---
*Design v1.0 - Pending User Approval*
