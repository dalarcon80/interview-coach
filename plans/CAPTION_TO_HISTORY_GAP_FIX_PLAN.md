# Plan: Fix Live Caption → Conversation History Gap

## Problem Analysis

When a partial transcript becomes final, there's a visible gap where:
1. Live Caption clears (is_final=True received)
2. Conversation History hasn't received the transcript yet
3. User sees no text for 1-3 seconds

## Root Cause

- Backend sends `live_caption` with `is_final=True` → frontend clears partial
- Backend sends `transcript` separately → frontend adds to history
- These are separate async events with potential timing gap

## Solution: Delayed Clear with Handoff Confirmation

### Option A: Keep Final Visible (Recommended)
When `live_caption` receives `is_final=True`, keep the text visible for 2-3 seconds before clearing, OR wait for confirmation that transcript was added to history.

### Option B: Immediate Mirror in History
When `live_caption` receives final, immediately add to history (optimistic), then update when transcript arrives.

### Option C: Unified State
Merge Live Captions and Conversation History into one scrolling transcript with different styling for partial vs final.

## Implementation Plan (Option A)

### Step 1: Add Delay State
```typescript
// Add to App.tsx state
const [pendingFinal, setPendingFinal] = useState<{
  text: string;
  timestamp: number;
  confirmed: boolean;
} | null>(null);
```

### Step 2: Modify live_caption Handler
```typescript
if (eventType === "live_caption") {
  const isFinal = event.is_partial === false;
  
  if (isFinal) {
    // Set pending final instead of clearing immediately
    setPendingFinal({
      text: event.text,
      timestamp: Date.now(),
      confirmed: false
    });
  }
  // ... rest of handler
}
```

### Step 3: Modify transcript Handler
```typescript
if (eventType === "transcript") {
  // Add to history
  addToHistory(event.text);
  // Mark pending final as confirmed
  setPendingFinal(prev => prev ? { ...prev, confirmed: true } : null);
}
```

### Step 4: Add Cleanup Effect
```typescript
useEffect(() => {
  if (!pendingFinal) return;
  
  const timer = setTimeout(() => {
    if (pendingFinal.confirmed) {
      // Clear after delay if confirmed
      clearLiveCaption();
      setPendingFinal(null);
    }
  }, 2000); // 2 second delay
  
  return () => clearTimeout(timer);
}, [pendingFinal]);
```

## Rollback Strategy

### Current State = v1.0 Stable
Current code (without gap fix) is stable and working partially.

### Git Tags
```bash
git tag v1.0-stable  # Current state
# After implementing fix:
git tag v1.1-gap-fix
```

### Files to Backup
- `tauri-app/src/App.tsx` (WebSocket handlers)
- `python-core/runtime_config.json` (STT config)

### Rollback Commands
```bash
# If fix breaks:
git checkout v1.0-stable -- tauri-app/src/App.tsx
# Restore config if needed:
git checkout v1.0-stable -- python-core/runtime_config.json
```

### Testing Checklist
- [ ] Partial updates work normally
- [ ] Final text stays visible 2+ seconds
- [ ] No gap between caption clearing and history showing
- [ ] Transcript consolidation still works
- [ ] No duplicate entries
- [ ] Performance not degraded

## Files to Modify
1. `tauri-app/src/App.tsx` - Add pending final state and delayed clear logic
2. No backend changes needed

## Risk Assessment
- **Low Risk**: Frontend-only change
- **Rollback Time**: < 1 minute (single file revert)
- **Testing Needed**: 5-10 minutes of live session testing

## Decision
Proceed with Option A (Keep Final Visible with 2-second delay) for minimal risk and good UX.
