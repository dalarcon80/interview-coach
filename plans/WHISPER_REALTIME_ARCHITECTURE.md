# WhisperLocal Real-Time Architecture Plan

## Problem

The current WhisperLocal implementation has fundamental limitations:
- faster-whisper is designed for batch transcription, not real-time streaming
- Each transcription returns results for the entire audio buffer (cumulative)
- This causes fragmented text display and latency

## User Requirement

1. **Real-time display**: Show transcription on screen as speaker talks (like Deepgram does)
2. **Consolidated for coach**: Behind the scenes, consolidate complete messages for the coach

## Solution Architecture

### Option A: Two-Stage Processing (Recommended)

```
Audio Input → [Small Buffer (1s)] → Real-time Display (partial)
                ↓
           [Accumulate + Silence Detection]
                ↓
           Consolidated Text → Coach
```

**Implementation:**
1. **Real-time path**: Process small chunks (1 second) independently, show partial results immediately
2. **Consolidated path**: Use silence detection (via audio energy) to determine when speaker finished, then send consolidated text to coach

### Option B: Use config to switch behavior

Add configuration options:
- `whisper_realtime_enabled`: Show partial in real-time
- `whisper_consolidate_for_coach`: Send consolidated to coach

## Key Changes Needed

### 1. WhisperLocalSTTAdapter changes:

```python
# Real-time: process each chunk independently (no accumulation)
# Show partial results immediately for display

# Consolidated: detect silence, then send complete message to coach
# Use audio energy detection to find silence boundaries
```

### 2. Server-side changes:

- Handle partial vs final differently
- Only trigger coach processing on final (consolidated) transcripts

### 3. Configuration:

Add to runtime_config.json:
```json
{
  "stt": {
    "local_enabled": true,
    "local_model": "small",
    "realtime_buffer_ms": 1000,
    "silence_threshold_ms": 1500
  }
}
```

## Implementation Priority

1. First: Fix real-time display (show partial every ~1 second)
2. Second: Add silence detection for coach consolidation
3. Third: Add configuration options for tuning

## Current Status

- Real-time display is partially working (shows text every ~1 second)
- Fragmentation is the main issue - text appears as short phrases
- Coach consolidation not yet implemented separately
