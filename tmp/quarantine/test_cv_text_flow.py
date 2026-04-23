#!/usr/bin/env python3
"""
Test script to verify cv_text flows from frontend to LLM.
This simulates the exact payload the frontend sends after the fix.
"""
import requests
import json

# Sample CV text (shortened for testing)
CV_TEXT = """
Daniel Alarcon - CTO at Xertica

EXPERIENCE:
- CTO at Xertica (2018-2022)
  * Led digital transformation for enterprise clients
  * Managed team of 50+ engineers
  * Implemented cloud migration strategy
  * Reduced infrastructure costs by 30%

- VP Engineering at TechCorp (2015-2018)
  * Built engineering team from 10 to 40 people
  * Launched 3 major product lines
  * Established DevOps practices

SKILLS:
- Cloud Architecture (AWS, Azure, GCP)
- Team Leadership & Scaling
- Digital Transformation
- Agile/Scrum
"""

def test_suggest_with_cv_text():
    """Test /api/suggest with cv_text in candidate_profile"""
    
    url = "http://127.0.0.1:8000/api/suggest"
    
    payload = {
        "question": "What was your role in Xertica?",
        "candidate_profile": {
            "name": "Daniel Alarcon",
            "current_role": "CTO",
            "years_experience": 15,
            "skills": ["Cloud Architecture", "Team Leadership"],
            "education": "",
            "languages": ["en", "es"],
            "certifications": [],
            "summary": "Experienced CTO with 15+ years in tech leadership",
            "achievements": ["Led digital transformation", "Managed 50+ engineers"],
            "target_role": "CTO",
            "industry": "Technology",
            "location": "Remote",
            "cv_text": CV_TEXT  # THIS IS THE KEY FIX
        },
        "company_info": {
            "name": "TestCorp",
            "industry": "Technology",
            "role_title": "CTO",
            "job_description": "Lead engineering team"
        },
        "style_id": "professional",
        "language": "en",
        "mode": "real"
    }
    
    print("=" * 80)
    print("Testing /api/suggest with cv_text")
    print("=" * 80)
    print(f"\nQuestion: {payload['question']}")
    print(f"CV text length: {len(CV_TEXT)} chars")
    print(f"CV text preview: {CV_TEXT[:100]}...")
    print("\nSending request...")
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        print("\n" + "=" * 80)
        print("RESPONSE")
        print("=" * 80)
        print(f"Success: {result.get('success')}")
        print(f"Mode: {result.get('mode')}")
        
        if result.get('success'):
            suggestion = result.get('suggestion', {})
            full_response = result.get('full_response') or suggestion.get('full_response', '')
            
            print(f"\nFull Response ({len(full_response)} chars):")
            print("-" * 80)
            print(full_response)
            print("-" * 80)
            
            # Check if response mentions Xertica (from CV)
            if 'Xertica' in full_response:
                print("\n✅ SUCCESS: Response mentions 'Xertica' from CV!")
            else:
                print("\n❌ FAILURE: Response does NOT mention 'Xertica' from CV")
                print("   This suggests cv_text is still not reaching the LLM")
            
            # Check for hallucinations
            hallucinations = []
            if 'Globant' in full_response:
                hallucinations.append("Globant (not in CV)")
            if '40% OPEX' in full_response or '345 indirect' in full_response:
                hallucinations.append("Specific metrics not in CV")
            
            if hallucinations:
                print(f"\n⚠️  WARNING: Possible hallucinations detected:")
                for h in hallucinations:
                    print(f"   - {h}")
            else:
                print("\n✅ No obvious hallucinations detected")
                
        else:
            print(f"\nError: {result.get('error')}")
            
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to backend at http://127.0.0.1:8000")
        print("   Make sure the backend is running: cd python-core && python -m api.server")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    test_suggest_with_cv_text()
