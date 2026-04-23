#!/usr/bin/env python3
"""
Test to verify that conversation history is properly included in the prompt
"""
import asyncio
import sys
sys.path.insert(0, 'python-core')

from pipeline.steps.response_composer import ResponseComposer
from contracts.models import AssembledContext, ResponseStyle
from typing import Optional, List, Dict

# Mock conversation history
mock_history = [
    {"role": "interviewer", "content": "Tell me about your experience at Xertica"},
    {"role": "candidate", "content": "I worked there for 2 years as CTO"},
    {"role": "interviewer", "content": "What was your biggest achievement?"},
    {"role": "candidate", "content": "I grew the team from 5 to 50 engineers"}
]

# Create test context
context = AssembledContext(
    question="How did you handle the rapid growth?",
    conversation_summary="",  # Empty - should use history instead
    conversation_history=mock_history,  # HR-2: Full conversation history
    evidence=[],
    interview_config={
        "candidate_name": "Test Candidate",
        "candidate_summary": "Experienced CTO",
    }
)

# Create response composer
composer = ResponseComposer()

# Build prompt
prompt = composer._build_prompt(context, ResponseStyle.MIXED)

print("=" * 80)
print("PROMPT VERIFICATION TEST")
print("=" * 80)
print("\n--- PROMPT SECTIONS ---\n")

# Check that conversation history is in the prompt
if "PREVIOUS CONVERSATION" in prompt:
    print("✅ PASS: 'PREVIOUS CONVERSATION' section found in prompt")
else:
    print("❌ FAIL: 'PREVIOUS CONVERSATION' section NOT found in prompt")

if "INTERVIEWER:" in prompt and "CANDIDATE:" in prompt:
    print("✅ PASS: Conversation roles (INTERVIEWER/CANDIDATE) found in prompt")
    # Count occurrences
    interviewer_count = prompt.count("INTERVIEWER:")
    candidate_count = prompt.count("CANDIDATE:")
    print(f"   Found {interviewer_count} INTERVIEWER entries and {candidate_count} CANDIDATE entries")
else:
    print("❌ FAIL: Conversation roles NOT found in prompt")

if "Xertica" in prompt:
    print("✅ PASS: Conversation content (Xertica) found in prompt")
else:
    print("❌ FAIL: Conversation content NOT found in prompt")

if "grew the team from 5 to 50" in prompt:
    print("✅ PASS: Recent conversation context found in prompt")
else:
    print("❌ FAIL: Recent conversation context NOT found in prompt")

print("\n--- FULL PROMPT PREVIEW ---\n")
lines = prompt.split('\n')
for i, line in enumerate(lines[:60]):  # First 60 lines
    print(line)
if len(lines) > 60:
    print(f"\n... ({len(lines) - 60} more lines)")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
