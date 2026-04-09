#!/usr/bin/env python3
"""
Aggressive Profile Testing Script for Interview Coach

This script performs comprehensive testing of the profile editing, reindexing,
and context retrieval flow to ensure the system correctly uses updated profile
information when generating responses.

Usage:
    cd /Users/dalarcon/projects/dev/interview-coach
    python tests/aggressive_profile_testing.py

Test Scenarios:
    1. Profile Creation - Create initial profile with specific details
    2. Profile Update - Modify profile and verify reindex works
    3. Context Verification - Ask questions and verify context is used
    4. Rapid Changes - Multiple rapid profile updates
    5. Edge Cases - Empty fields, special characters, large text
"""

import asyncio
import json
import sys
from datetime import datetime
from typing import Dict, Any, Optional
import httpx

# Configuration
BASE_URL = "http://localhost:8000"
API_PREFIX = "/api"
TIMEOUT = 30.0

# Test Profiles
TEST_PROFILES = {
    "initial": {
        "name": "Test User",
        "current_role": "Software Engineer",
        "target_role": "Senior Software Engineer",
        "years_experience": 5,
        "skills": ["Python", "JavaScript", "React", "FastAPI"],
        "industry": "Technology",
        "cv_text": """
        Software Engineer with 5 years of experience in web development.
        Specialized in Python backends and React frontends.
        Led a team of 3 developers on a major e-commerce platform.
        Experience with microservices architecture and cloud deployment on AWS.
        """
    },
    "updated_1": {
        "name": "Test User Updated",
        "current_role": "Senior Software Engineer",
        "target_role": "Staff Engineer",
        "years_experience": 7,
        "skills": ["Python", "TypeScript", "React", "FastAPI", "Kubernetes", "AWS"],
        "industry": "Fintech",
        "cv_text": """
        Senior Software Engineer with 7 years of experience in fintech.
        Expert in building high-performance trading systems.
        Led architecture redesign that reduced latency by 40%.
        Managed a team of 8 engineers across 3 time zones.
        Deep expertise in Kubernetes, AWS, and distributed systems.
        """
    },
    "updated_2": {
        "name": "Test User - CTO Track",
        "current_role": "Staff Engineer",
        "target_role": "CTO",
        "years_experience": 10,
        "skills": ["System Design", "Team Leadership", "Strategy", "Python", "Go"],
        "industry": "Enterprise SaaS",
        "cv_text": """
        Staff Engineer with 10 years of experience building enterprise SaaS products.
        Previously VP of Engineering at a Series B startup that was acquired.
        Managed engineering teams of 50+ people.
        Expert in scaling engineering organizations and technical strategy.
        Strong background in distributed systems and cloud-native architectures.
        """
    }
}

# Test Questions designed to trigger specific context usage
TEST_QUESTIONS = [
    {
        "question": "Tell me about your experience with team leadership",
        "expected_keywords": ["team", "led", "developers", "e-commerce"],
        "min_matches": 2,
        "description": "Leadership experience verification"
    },
    {
        "question": "What is your technical expertise?",
        "expected_keywords": ["Python", "JavaScript", "React", "AWS"],
        "min_matches": 2,
        "description": "Technical skills verification"
    },
    {
        "question": "Why are you interested in moving into a Senior Software Engineer role?",
        "expected_keywords": ["Senior Software Engineer", "growth", "next step", "opportunity"],
        "min_matches": 1,
        "description": "Career goals verification"
    },
    {
        "question": "Tell me about a challenging project you worked on",
        "expected_keywords": ["project", "architecture", "system", "platform"],
        "min_matches": 2,
        "description": "Project experience verification"
    }
]


class ProfileTester:
    """Test harness for profile and context testing."""
    
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)
        self.test_results: list[Dict[str, Any]] = []
        self.current_profile: Optional[Dict] = None
        self.profile_id: Optional[str] = None
        
    async def health_check(self) -> bool:
        """Verify backend is running."""
        try:
            response = await self.client.get("/health")
            if response.status_code == 200:
                print("✓ Backend is healthy")
                return True
            else:
                print(f"✗ Backend health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ Cannot connect to backend: {e}")
            return False
    
    async def set_profile(self, profile: Dict[str, Any]) -> bool:
        """Set profile via the suggest endpoint (simulates frontend)."""
        try:
            response = await self.client.post(
                f"{API_PREFIX}/suggest",
                json={
                    "question": "Initialize profile",
                    **profile
                }
            )
            if response.status_code == 200:
                self.current_profile = profile
                print(f"✓ Profile set: {profile['name']} - {profile['current_role']}")
                return True
            else:
                print(f"✗ Failed to set profile: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"✗ Error setting profile: {e}")
            return False
    
    async def reindex_profile(self) -> bool:
        """Trigger profile reindexing."""
        try:
            response = await self.client.post(
                f"{API_PREFIX}/profile/reindex",
                json=self.current_profile or {}
            )
            if response.status_code == 200:
                result = response.json()
                self.profile_id = result.get("profile_id") or self.profile_id
                indexed = result.get("indexed", {}) if isinstance(result.get("indexed"), dict) else {}
                chunk_count = indexed.get("document_chunks", 0)
                achievement_count = indexed.get("achievements", 0)
                print(
                    f"✓ Reindex successful: profile_id={self.profile_id} "
                    f"chunks={chunk_count} achievements={achievement_count}"
                )
                return True
            else:
                print(f"✗ Reindex failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"✗ Error during reindex: {e}")
            return False
    
    async def get_evidence(self, query: str) -> Dict[str, Any]:
        """Retrieve evidence for a query to verify context."""
        try:
            response = await self.client.post(
                f"{API_PREFIX}/debug/retrieve-evidence",
                json={
                    "question": query,
                    "query": query,
                    "profile_id": self.profile_id,
                }
            )
            if response.status_code == 200:
                return response.json()
            else:
                print(f"✗ Evidence retrieval failed: {response.status_code}")
                return {}
        except Exception as e:
            print(f"✗ Error retrieving evidence: {e}")
            return {}
    
    async def ask_question(self, question: str, mode: str = "manual") -> Dict[str, Any]:
        """Ask a question and get a response."""
        try:
            response = await self.client.post(
                f"{API_PREFIX}/suggest",
                json={
                    "question": question,
                    "profile_id": self.profile_id,
                    **(self.current_profile or {})
                }
            )
            if response.status_code == 200:
                return response.json()
            else:
                print(f"✗ Question failed: {response.status_code} - {response.text}")
                return {}
        except Exception as e:
            print(f"✗ Error asking question: {e}")
            return {}
    
    def verify_keywords(
        self,
        text: str,
        keywords: list[str],
        min_matches: Optional[int] = None,
    ) -> tuple[bool, list[str], list[str]]:
        """Check if enough keywords are present in text."""
        text_lower = text.lower()
        found = []
        missing = []
        for keyword in keywords:
            if keyword.lower() in text_lower:
                found.append(keyword)
            else:
                missing.append(keyword)
        required_matches = min_matches if min_matches is not None else len(keywords)
        return len(found) >= required_matches, missing, found
    
    async def run_test_scenario_1(self) -> bool:
        """
        Scenario 1: Basic profile creation and question answering.
        """
        print("\n" + "="*60)
        print("SCENARIO 1: Basic Profile Creation and Question Answering")
        print("="*60)
        
        # Set initial profile
        if not await self.set_profile(TEST_PROFILES["initial"]):
            return False
        
        # Reindex
        if not await self.reindex_profile():
            return False
        
        # Ask questions and verify responses
        all_passed = True
        for test_q in TEST_QUESTIONS:
            print(f"\n  Testing: {test_q['description']}")
            print(f"  Question: {test_q['question']}")
            
            # Get evidence first
            evidence = await self.get_evidence(test_q['question'])
            print(f"  Evidence chunks: {len(evidence.get('chunks', []))}")
            
            # Ask question
            response = await self.ask_question(test_q['question'])
            full_response = response.get('full_response', '')
            
            # Verify keywords
            passed, missing, found = self.verify_keywords(
                full_response,
                test_q['expected_keywords'],
                min_matches=test_q.get('min_matches'),
            )
            if passed:
                print(f"  ✓ Found keywords: {found}")
            else:
                print(f"  ✗ Found keywords: {found} | Missing keywords: {missing}")
                all_passed = False
            
            # Show response preview
            preview = full_response[:150] + "..." if len(full_response) > 150 else full_response
            print(f"  Response preview: {preview}")
        
        return all_passed
    
    async def run_test_scenario_2(self) -> bool:
        """
        Scenario 2: Profile update and verify context changes.
        """
        print("\n" + "="*60)
        print("SCENARIO 2: Profile Update and Context Verification")
        print("="*60)
        
        # First, set initial profile
        if not await self.set_profile(TEST_PROFILES["initial"]):
            return False
        await self.reindex_profile()
        
        # Ask question about experience
        print("\n  Before update:")
        response1 = await self.ask_question("How many years of experience do you have?")
        print(f"  Response: {response1.get('full_response', '')[:200]}...")
        
        # Now update profile
        print("\n  Updating profile...")
        if not await self.set_profile(TEST_PROFILES["updated_1"]):
            return False
        await self.reindex_profile()
        
        # Ask same question
        print("\n  After update:")
        response2 = await self.ask_question("How many years of experience do you have?")
        print(f"  Response: {response2.get('full_response', '')[:200]}...")
        
        # Verify the response mentions the new experience level
        passed, missing, found = self.verify_keywords(
            response2.get('full_response', ''),
            ['7', 'seven', 'Senior', 'fintech', 'trading'],
            min_matches=2,
        )
        
        if passed:
            print(f"  ✓ Profile update correctly reflected in responses (found: {found})")
            return True
        else:
            print(f"  ✗ Updated profile not reflected. Found: {found} Missing: {missing}")
            return False
    
    async def run_test_scenario_3(self) -> bool:
        """
        Scenario 3: Rapid profile changes.
        """
        print("\n" + "="*60)
        print("SCENARIO 3: Rapid Profile Changes")
        print("="*60)
        
        profiles = [
            TEST_PROFILES["initial"],
            TEST_PROFILES["updated_1"],
            TEST_PROFILES["updated_2"],
            TEST_PROFILES["initial"]  # Back to initial
        ]
        
        all_passed = True
        for i, profile in enumerate(profiles):
            print(f"\n  Change {i+1}: {profile['name']} - {profile['current_role']}")
            
            if not await self.set_profile(profile):
                all_passed = False
                continue
            
            if not await self.reindex_profile():
                all_passed = False
                continue
            
            # Quick verification
            response = await self.ask_question("What is your current role?")
            response_text = response.get('full_response', '').lower()
            
            if profile['current_role'].lower() in response_text:
                print(f"  ✓ Context correctly updated")
            else:
                print(f"  ✗ Context not updated. Expected mention of: {profile['current_role']}")
                all_passed = False
        
        return all_passed
    
    async def run_test_scenario_4(self) -> bool:
        """
        Scenario 4: Edge cases - empty fields, special characters.
        """
        print("\n" + "="*60)
        print("SCENARIO 4: Edge Cases")
        print("="*60)
        
        edge_case_profiles = [
            {
                "name": "Test Special Chars: ñáéíóú & <script>alert('xss')</script>",
                "current_role": "Engineer @ Company™",
                "target_role": "Senior Engineer",
                "years_experience": 0,
                "skills": [],
                "industry": "",
                "cv_text": "Short CV with special chars: $100k, 50%, emoji 🚀"
            },
            {
                "name": "",
                "current_role": "",
                "target_role": "",
                "years_experience": 0,
                "skills": [],
                "industry": "",
                "cv_text": ""
            },
            {
                "name": "A" * 500,  # Very long name
                "current_role": "B" * 1000,  # Very long role
                "target_role": "C" * 500,
                "years_experience": 100,
                "skills": ["skill" + str(i) for i in range(100)],
                "industry": "D" * 200,
                "cv_text": "Word " * 10000  # Very long CV
            }
        ]
        
        all_passed = True
        for i, profile in enumerate(edge_case_profiles):
            print(f"\n  Edge case {i+1}...")
            try:
                if await self.set_profile(profile):
                    if await self.reindex_profile():
                        print(f"  ✓ Edge case handled correctly")
                    else:
                        print(f"  ✗ Reindex failed for edge case")
                        all_passed = False
                else:
                    print(f"  ✗ Set profile failed for edge case")
                    all_passed = False
            except Exception as e:
                print(f"  ✗ Exception for edge case: {e}")
                all_passed = False
        
        return all_passed
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all test scenarios."""
        print("\n" + "="*60)
        print("AGGRESSIVE PROFILE TESTING - Interview Coach")
        print(f"Started at: {datetime.now().isoformat()}")
        print("="*60)
        
        # Health check
        if not await self.health_check():
            return {"success": False, "error": "Backend not available"}
        
        results = {
            "scenario_1": False,
            "scenario_2": False,
            "scenario_3": False,
            "scenario_4": False,
            "timestamp": datetime.now().isoformat()
        }
        
        # Run scenarios
        try:
            results["scenario_1"] = await self.run_test_scenario_1()
        except Exception as e:
            print(f"Scenario 1 failed with exception: {e}")
        
        try:
            results["scenario_2"] = await self.run_test_scenario_2()
        except Exception as e:
            print(f"Scenario 2 failed with exception: {e}")
        
        try:
            results["scenario_3"] = await self.run_test_scenario_3()
        except Exception as e:
            print(f"Scenario 3 failed with exception: {e}")
        
        try:
            results["scenario_4"] = await self.run_test_scenario_4()
        except Exception as e:
            print(f"Scenario 4 failed with exception: {e}")
        
        # Summary
        results["success"] = all([
            results["scenario_1"],
            results["scenario_2"],
            results["scenario_3"],
            results["scenario_4"]
        ])
        
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Scenario 1 (Basic): {'✓ PASS' if results['scenario_1'] else '✗ FAIL'}")
        print(f"Scenario 2 (Update): {'✓ PASS' if results['scenario_2'] else '✗ FAIL'}")
        print(f"Scenario 3 (Rapid): {'✓ PASS' if results['scenario_3'] else '✗ FAIL'}")
        print(f"Scenario 4 (Edge): {'✓ PASS' if results['scenario_4'] else '✗ FAIL'}")
        print(f"\nOverall: {'✓ ALL TESTS PASSED' if results['success'] else '✗ SOME TESTS FAILED'}")
        print("="*60)
        
        return results
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


async def main():
    """Main entry point."""
    tester = ProfileTester()
    try:
        results = await tester.run_all_tests()
        
        # Save results to file
        output_file = f"tests/test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {output_file}")
        
        # Exit with appropriate code
        sys.exit(0 if results["success"] else 1)
    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
