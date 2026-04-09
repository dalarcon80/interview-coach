# CV Text Flow Diagnosis - Ready for Testing

## Status: Logging Added, Ready for User Testing

## What Was Verified

### 1. Frontend Code is Correct ✅
- **File**: [`tauri-app/src/App.tsx`](tauri-app/src/App.tsx:1229)
- **Line 1229-1230**: Code correctly merges cv_text into candidate profile:
  ```typescript
  const candidateWithCv = candidateProfile
    ? { ...candidateProfile, cv_text: cvText || candidateProfile.cv_text }
    : undefined;
  ```

### 2. API Client Sends candidate_profile ✅
- **File**: [`tauri-app/src/lib/api-client.ts`](tauri-app/src/lib/api-client.ts:148)
- **Line 148**: Sends `candidate_profile: req.candidate_profile` which should include cv_text

### 3. Backend Extracts cv_text ✅
- **File**: [`python-core/api/server.py`](python-core/api/server.py:1449)
- **Line 1449**: Backend extracts: `candidate_cv_text = candidate.get("cv_text") or candidate.get("cvText") or ""`

## Logging Added for Diagnosis

### Frontend Logging (api-client.ts)
Added at line 144-149:
```typescript
const cvTextLength = req.candidate_profile?.cv_text?.length || 0;
console.log(`[API Client] Sending suggest request with cv_text: ${cvTextLength} chars`);
if (cvTextLength > 0) {
  console.log(`[API Client] cv_text preview: ${req.candidate_profile?.cv_text?.substring(0, 100)}...`);
}
```

### Backend Logging (server.py)
Added at line 1451-1457:
```python
print(f"[/api/suggest] Received cv_text: {len(candidate_cv_text)} chars")
if len(candidate_cv_text) > 0:
    print(f"[/api/suggest] cv_text preview: {candidate_cv_text[:100]}...")
else:
    print(f"[/api/suggest] WARNING: No cv_text received!")
    print(f"[/api/suggest] candidate keys: {list(candidate.keys())}")
```

## Current State

### Backend: ✅ Running with new logging
- Port 8000
- Uvicorn with --reload
- Will show cv_text logs on each /api/suggest request

### Frontend: ⚠️ Needs Vite Hot Reload
- Tauri app is running on port 5174
- TypeScript changes will hot-reload automatically when you interact with the app
- No rebuild needed - Vite will pick up changes

## How to Test

### Step 1: Open Browser DevTools
1. In the Tauri app window, open DevTools (Cmd+Option+I on Mac)
2. Go to the Console tab
3. Clear the console

### Step 2: Upload CV and Get Coaching
1. Upload your CV file (CV_Daniel_Alarcon-26.docx)
2. Click "Get Coaching" or ask a question
3. Watch BOTH:
   - **Browser Console**: Should show `[API Client] Sending suggest request with cv_text: XXXX chars`
   - **Backend Terminal**: Should show `[/api/suggest] Received cv_text: XXXX chars`

### Step 3: Analyze the Logs

#### ✅ SUCCESS Pattern:
```
# Browser Console:
[API Client] Sending suggest request with cv_text: 12543 chars
[API Client] cv_text preview: Daniel Alarcon
Senior Technology Executive...

# Backend Terminal:
[/api/suggest] Received cv_text: 12543 chars
[/api/suggest] cv_text preview: Daniel Alarcon
Senior Technology Executive...
```

#### ❌ FAILURE Pattern 1: Frontend Not Sending
```
# Browser Console:
[API Client] Sending suggest request with cv_text: 0 chars

# Backend Terminal:
[/api/suggest] Received cv_text: 0 chars
[/api/suggest] WARNING: No cv_text received!
[/api/suggest] candidate keys: ['name', 'summary', 'skills', ...]
```
**Diagnosis**: cvText state is empty in App.tsx

#### ❌ FAILURE Pattern 2: Backend Not Receiving
```
# Browser Console:
[API Client] Sending suggest request with cv_text: 12543 chars
[API Client] cv_text preview: Daniel Alarcon...

# Backend Terminal:
[/api/suggest] Received cv_text: 0 chars
[/api/suggest] WARNING: No cv_text received!
```
**Diagnosis**: Network issue or JSON serialization problem

## Possible Root Causes

### 1. cvText State Not Set (Most Likely)
**Symptom**: Frontend logs show 0 chars
**Cause**: The CV upload might not be setting the cvText state
**Check**: Look at [`CVIntake.tsx`](tauri-app/src/components/coach/CVIntake.tsx) - does it call `onCVTextExtracted`?

### 2. candidateProfile Doesn't Include cvText
**Symptom**: Frontend logs show chars, but backend shows 0
**Cause**: The merge at line 1229 might not be working
**Check**: Add `console.log('candidateWithCv:', candidateWithCv)` after line 1230

### 3. Cached Old Data
**Symptom**: Response mentions "Globant" and "345 indirect reports"
**Cause**: Backend is using cached profile from database instead of cv_text
**Check**: Backend should prioritize cv_text over cached data

### 4. Wrong Frontend Running
**Symptom**: No logs appear at all
**Cause**: User might be on localhost:3000 (Next.js) instead of Tauri
**Check**: Verify the URL - Tauri shows `tauri://localhost` or similar

## Next Steps After Testing

### If cv_text is 0 chars in frontend logs:
1. Check CVIntake component
2. Verify file upload is working
3. Check if onCVTextExtracted callback is called

### If cv_text is sent but not received:
1. Check network tab for the actual request payload
2. Verify JSON serialization
3. Check for middleware stripping the field

### If cv_text is received but response is still cached:
1. Check if backend is using cv_text in the pipeline
2. Verify retrieval logic prioritizes cv_text
3. Check if there's a profile_id causing database lookup instead

## Files Modified

1. [`tauri-app/src/lib/api-client.ts`](tauri-app/src/lib/api-client.ts) - Added frontend logging
2. [`python-core/api/server.py`](python-core/api/server.py) - Added backend logging

## Commands Run

```bash
# Killed old backend
lsof -ti:8000 | xargs kill -9

# Started backend with new logging
cd python-core && ../.venv/bin/python -m uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
```

## What to Report Back

Please provide:
1. **Browser console logs** (screenshot or copy/paste)
2. **Backend terminal logs** (copy/paste the cv_text lines)
3. **The response you received** (does it still mention Globant?)
4. **Which app you're using** (Tauri window or localhost:3000?)

This will definitively show where the cv_text is being lost in the flow.
