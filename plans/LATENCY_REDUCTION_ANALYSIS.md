# Latency Reduction Analysis & Implementation Plan

## Executive Summary

Current issue: **7-second delay** from interviewer speaking to seeing the message in the application. Target: **5 seconds or less**.

This document outlines the analysis and proposed solution to reduce transcription latency by optimizing silence detection parameters across the audio pipeline.

---

## Current Latency Analysis

### Identified Bottlenecks

| Component | File | Parameter | Current Value | Latency Contribution |
|-----------|------|-----------|---------------|---------------------|
| **Deepgram STT** | `python-core/adapters/stt_adapter.py` | `utterance_end_ms` | 2500ms | **PRIMARY: ~2000-2500ms** |
| Turn Assembler | `python-core/pipeline/steps/turn_assembler.py` | `silence_threshold_ms` | 2000ms | 0-2000ms |
| Realtime Pipeline | `python-core/pipeline/realtime_pipeline.py` | `silence_threshold_ms` | 2500ms | 0-2500ms |
| Server | `python-core/api/server.py` | `_min_utterance_duration_ms` | 2000ms | 0-2000ms |
| Server | `python-core/api/server.py` | `_suggestion_cooldown_sec` | 5.0s | 0-5000ms |

### Root Cause

The **primary latency source** is Deepgram's `utterance_end_ms = 2500` parameter. This tells Deepgram to wait 2.5 seconds of **silence** before considering an utterance complete and sending the final transcript.

---

## Provider Evaluation

**Question: Should we use Deepgram or switch to another provider?**

### Answer: **Deepgram is already optimal**

Deepgram is the correct choice because:
- Already integrated and working
- Provides real-time streaming with low latency
- The `nova-3` model is fast and accurate
- **Improvements come from tuning parameters, NOT switching providers**

Other providers (Google Speech-to-Text, AWS Transcribe, Whisper) would either:
- Not improve latency meaningfully
- Require significant integration work
- Not support real-time streaming as well as Deepgram

---

## Solution: Optimized Parameters

### Proposed Changes

| Component | Parameter | Current | Proposed | Est. Reduction |
|-----------|-----------|---------|----------|-----------------|
| **Deepgram STT** | `utterance_end_ms` | 2500 | **800** | ~1700ms |
| Turn Assembler | `silence_threshold_ms` | 2000 | **1000** | ~1000ms |
| Realtime Pipeline | `silence_threshold_ms` | 2500 | **1000** | ~1500ms |
| Server | `_min_utterance_duration_ms` | 2000 | **1000** | ~1000ms |
| Server | `_suggestion_cooldown_sec` | 5.0 | **2.0** | ~3000ms |

### Total Estimated Reduction
**~4700ms to 5700ms reduction** → Target of 5s or less is achievable

---

## Implementation Steps

### Step 1: Modify Deepgram STT Adapter
**File**: `python-core/adapters/stt_adapter.py`

Change `utterance_end_ms` from 2500 to 800:
```python
# Line 107, 191
self._utterance_end_ms = 800  # Reduced from 2500ms for faster transcription
```

### Step 2: Modify Turn Assembler
**File**: `python-core/pipeline/steps/turn_assembler.py`

Change `silence_threshold_ms` from 2000 to 1000:
```python
# Line 53, 67
silence_threshold_ms: int = 1000  # Reduced from 2000ms
```

### Step 3: Modify Realtime Pipeline Config
**File**: `python-core/pipeline/realtime_pipeline.py`

Change `silence_threshold_ms` from 2500 to 1000:
```python
# Line 51
silence_threshold_ms: int = 1000  # Reduced from 2500ms
```

### Step 4: Modify Server Settings
**File**: `python-core/api/server.py`

Change minimum utterance and cooldown:
```python
# Line 578-580
self._min_utterance_duration_ms = 1000  # Reduced from 2000ms
self._min_utterance_words = 5
self._suggestion_cooldown_sec = 2.0  # Reduced from 5.0s
```

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Very short utterances may be cut off | Low | 800ms is enough for most interview questions |
| More frequent suggestions | Medium | Cooldown of 2s prevents spam while allowing faster responses |
| Turn boundaries less stable | Low | 1000ms silence threshold is still conservative |

---

## Next Steps After Approval

1. Apply the 5 parameter changes above
2. Restart the backend server
3. Run a live session test
4. Measure actual latency improvement
5. Fine-tune if needed

---

## Request for Approval

**Please approve the implementation plan above to proceed with the latency optimizations.**

The changes are:
- ✅ Non-breaking (no response format changes)
- ✅ Preserve current answer quality
- ✅ Use existing Deepgram integration
- ✅ Achievable target: 5 seconds or less
