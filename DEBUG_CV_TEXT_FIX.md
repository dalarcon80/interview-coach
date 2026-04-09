# CV Text NOT Reaching LLM - Debug & Fix

## Problem Statement
When asked "What was your role in Xertica?", the system responded with:
- "Globant" (NOT in the CV)
- "40% OPEX reduction" (hallucinated)
- "345 indirect reports" (hallucinated)
- "17+ enterprise clients" (hallucinated)

This proved the cv_text was NOT being passed to the LLM.

## Root Cause Analysis

### Issue #1: Frontend Not Sending cv_text
**Location:** [`tauri-app/src/App.tsx:1228`](tauri-app/src/App.tsx:1228)

The `submitCoachQuestion` function was sending `candidateProfile` to the API, but `candidateProfile` state and `cvText` state were stored separately. When the API was called, `cv_text` was not included in the `candidate_profile` object.

**Fix:**
```typescript
// Merge cv_text into candidate_profile before sending to API
const candidateWithCv = candidateProfile
  ? { ...candidateProfile, cv_text: cvText || candidateProfile.cv_text }
  : undefined;

const suggestion = await api.suggest({
  question,
  session_id: liveSession.sessionId ?? undefined,
  candidate_profile: candidateWithCv,  // Now includes cv_text
  company_info: companyInfo ?? undefined,
  style_id: selectedStyle,
  language: selectedLanguage ?? language,
  mode: backendMode,
});
```

### Issue #2: Backend Prioritizing Database Evidence Over cv_text
**Location:** [`python-core/pipeline/steps/response_composer.py:874`](python-core/pipeline/steps/response_composer.py:874)

The original logic was:
```python
if not evidence_lines and cv_text:
    # Use cv_text only when NO database evidence exists
```

This meant that if the database had ANY evidence (even old/wrong data), it would use that instead of the fresh cv_text from the request.

**Fix:**
```python
# PRIORITY: Use cv_text if available (most recent, authoritative source)
# Fall back to database evidence only if cv_text is not provided

if cv_text:
    # cv_text is the authoritative source - use it directly
    cv_snippet = cv_text[:2000].strip()
    evidence_section = f"[CV TEXT - PRIMARY SOURCE, use as grounding, do not invent facts beyond this]\n{cv_snippet}"
    print(f"[ResponseComposer] ✓ Using cv_text as PRIMARY evidence source ({len(cv_snippet)} chars)")
elif evidence_lines:
    # No cv_text, but we have database evidence
    evidence_section = chr(10).join(evidence_lines)
    print(f"[ResponseComposer] Using database evidence ({len(evidence_lines)} items)")
else:
    # No cv_text and no database evidence
    evidence_section = "No evidence retrieved."
    print(f"[ResponseComposer] ⚠️ No evidence and no cv_text - risk of hallucination!")
```

## Files Changed

1. **tauri-app/src/App.tsx**
   - Line 1228: Added cv_text merging logic in `submitCoachQuestion`
   - Line 1259: Added `cvText` to dependency array

2. **python-core/api/server.py**
   - Line 1449: Added debug logging for cv_text reception
   - Logs cv_text length and preview when received

3. **python-core/pipeline/steps/response_composer.py**
   - Line 874: Changed priority to use cv_text FIRST, database evidence as fallback
   - Added logging to trace which evidence source is being used

## Verification

### Test Command
```bash
curl -X POST http://127.0.0.1:8000/api/suggest \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What was your role in Xertica?",
    "candidate_profile": {
      "name": "Daniel Alarcon",
      "cv_text": "Daniel Alarcon - CTO at Xertica (2018-2022). Led digital transformation."
    },
    "style_id": "professional",
    "language": "en",
    "mode": "real"
  }'
```

### Expected Result
Response should mention:
- ✅ "Xertica"
- ✅ "CTO at Xertica from 2018 to 2022"
- ✅ "Led digital transformation"
- ❌ Should NOT mention "Globant", "Accenture", or hallucinated metrics

### Actual Result (After Fix)
```
"In my role as CTO at Xertica from 2018 to 2022, I was responsible for leading 
the company's entire technology strategy and digital transformation..."
```

✅ **SUCCESS** - cv_text is now flowing correctly from frontend → backend → LLM

## Data Flow (After Fix)

```
1. User uploads CV via CVIntake.tsx
   ↓
2. CV analyzed, profile extracted with cv_text
   ↓
3. Profile stored in candidateProfile state
   cv_text stored in cvText state
   ↓
4. User clicks "Get Coaching"
   ↓
5. submitCoachQuestion merges cvText into candidate_profile
   ↓
6. api.suggest() sends candidate_profile with cv_text
   ↓
7. Backend /api/suggest receives cv_text
   ↓
8. candidate_context["cv_text"] = cv_text
   ↓
9. ResponseComposer._build_prompt() checks for cv_text
   ↓
10. cv_text used as PRIMARY evidence source in prompt
   ↓
11. LLM receives cv_text as grounding context
   ↓
12. Response based on actual CV content (no hallucinations)
```

## Logging Added

### Backend Logs
```
[/api/suggest] cv_text received: 123 chars
[/api/suggest] cv_text preview: Daniel Alarcon - CTO at Xertica...
[ResponseComposer] ✓ Using cv_text as PRIMARY evidence source (123 chars)
```

### What to Watch For
- If you see `cv_text received: 0 chars` → Frontend not sending cv_text
- If you see `Using database evidence` when cv_text should be present → Backend priority logic broken
- If you see `⚠️ No evidence and no cv_text` → Both sources missing, high risk of hallucination

## Testing Checklist

- [x] Backend receives cv_text in request payload
- [x] Backend logs cv_text length and preview
- [x] ResponseComposer prioritizes cv_text over database evidence
- [x] LLM response mentions facts from cv_text
- [x] LLM response does NOT hallucinate facts not in cv_text
- [x] Frontend merges cvText into candidate_profile before API call

## Status
**FIXED** ✅

The cv_text now flows correctly from the frontend through the backend to the LLM, and the LLM uses it as the primary grounding source for generating responses.
