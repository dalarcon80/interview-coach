#!/usr/bin/env python3
"""Test script to diagnose LLM adapter issues"""
import os
import sys
import asyncio

# Add python-core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'python-core'))

print("=" * 60)
print("LLM Adapter Diagnostic Test")
print("=" * 60)

# Check environment
anthropic_key = os.getenv("ANTHROPIC_API_KEY")
print(f"\n1. Environment Check:")
print(f"   ANTHROPIC_API_KEY present: {bool(anthropic_key)}")
if anthropic_key:
    print(f"   Key length: {len(anthropic_key)}")
    print(f"   Key prefix: {anthropic_key[:20]}...")

# Check Python path
print(f"\n2. Python Path:")
print(f"   Executable: {sys.executable}")
print(f"   Version: {sys.version}")

# Check anthropic package
print(f"\n3. Package Check:")
try:
    import anthropic
    print(f"   anthropic package: INSTALLED (version: {anthropic.__version__})")
except ImportError as e:
    print(f"   anthropic package: NOT INSTALLED ({e})")

# Check runtime config
print(f"\n4. Runtime Config Check:")
try:
    import json
    from pathlib import Path
    config_path = Path(__file__).parent / "python-core" / "runtime_config.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        llm_cfg = config.get("llm", {})
        print(f"   Config file: FOUND")
        print(f"   Provider: {llm_cfg.get('provider')}")
        print(f"   Enabled: {llm_cfg.get('enabled')}")
        api_key = llm_cfg.get("api_key", "")
        print(f"   Config key length: {len(api_key)}")
        print(f"   Config key is placeholder: {api_key.startswith('sk-test') or len(api_key) < 20}")
    else:
        print(f"   Config file: NOT FOUND")
except Exception as e:
    print(f"   Config error: {e}")

# Test adapter creation
print(f"\n5. Adapter Creation Test:")
try:
    from adapters.llm_adapter import get_llm_adapter, get_llm_adapter_required, DemoLLMAdapter
    
    adapter = get_llm_adapter()
    if adapter is None:
        print("   Result: NO ADAPTER (None returned)")
    elif isinstance(adapter, DemoLLMAdapter):
        print("   Result: DEMO ADAPTER (fallback)")
    else:
        print(f"   Result: REAL ADAPTER ({adapter.__class__.__name__})")
        print(f"   Model: {getattr(adapter, 'model', 'N/A')}")
        print(f"   API Key source: {getattr(adapter, 'api_key', 'N/A')[:20]}...")
except Exception as e:
    print(f"   ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Test actual LLM call
print(f"\n6. LLM Call Test:")
async def test_llm_call():
    try:
        from adapters.llm_adapter import get_llm_adapter_required
        
        adapter = get_llm_adapter_required()
        print(f"   Adapter: {adapter.__class__.__name__}")
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Reply with only: 'TEST OK'"},
            {"role": "user", "content": "Say TEST OK"}
        ]
        config = {"max_tokens": 100, "temperature": 0}
        
        print("   Calling LLM...")
        response = await adapter.generate(messages, config)
        print(f"   Response: {response.strip()[:100]}")
        print("   SUCCESS!")
    except Exception as e:
        print(f"   ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return e
    return None

error = asyncio.run(test_llm_call())

print(f"\n{'=' * 60}")
if error:
    print("DIAGNOSIS: LLM call FAILED")
    print(f"Error type: {type(error).__name__}")
else:
    print("DIAGNOSIS: LLM call SUCCESS")
print("=" * 60)
