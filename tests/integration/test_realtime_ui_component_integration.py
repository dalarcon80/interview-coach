"""
Test Realtime UI Component Integration

Validates that:
1. page.tsx imports and uses the official realtime UI components
2. page.tsx does NOT contain inline rendering of transcript/suggestion/session UI
3. The page is a thin orchestrator that wires hooks to components

This test should FAIL if anyone revives inline rendering in page.tsx.
"""
import pytest
import re
from pathlib import Path


# ============================================
# Official Components that MUST be used
# ============================================

REQUIRED_COMPONENTS = {
    'SessionControlPanel',
    'AudioSettingsPanel',
    'LiveTranscriptPanel',
    'RealtimeSuggestionPanel',
}

# Components must be imported from this directory
COMPONENT_IMPORT_PATH = '@/components/realtime'

# ============================================
# Inline patterns that MUST NOT exist in page.tsx
# ============================================

FORBIDDEN_INLINE_PATTERNS = [
    # Inline transcript rendering (in JSX context)
    r'transcripts\.map\s*\(',
    r'\.transcripts\.map',
    r'{transcripts\.map',
    
    # Inline suggestion rendering in JSX (curly braces before)
    r'\{suggestion\.bullets\.map',
    r'\{suggestion\.full_response\}',
    r'\{realtime\.suggestion\.full_response\}',
    r'\{suggestion\s*&&\s*\(',
    
    # Inline session info rendering in JSX
    r'\{session\.active\s*&&\s*\(',
    r'Session Active',
    r'\{sessionDuration\}',
    
    # Manual transcript display blocks (class names, not types)
    r'class="Transcript Display"',
    r'class="TranscriptEntry"',
    
    # Manual suggestion display blocks
    r'class="Suggested Response"',
    r'class="Key Points"',
]

# Allowed inline patterns (status cards, architecture info, etc)
ALLOWED_INLINE_PATTERNS = [
    'Backend',
    'Database', 
    'WebSocket',
    'Audio',
    'Architecture',
    'Platform',
    'Providers',
    'Storage',
    'Status Summary',
]


class TestPageUsesOfficialComponents:
    """Tests that page.tsx uses the official realtime components."""

    def test_page_file_exists(self):
        """page.tsx must exist."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        assert page_path.exists(), "page.tsx not found"

    def test_page_imports_session_control_panel(self):
        """page.tsx must import SessionControlPanel."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert 'SessionControlPanel' in content, \
            "page.tsx does not import SessionControlPanel"

    def test_page_imports_audio_settings_panel(self):
        """page.tsx must import AudioSettingsPanel."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert 'AudioSettingsPanel' in content, \
            "page.tsx does not import AudioSettingsPanel"

    def test_page_imports_live_transcript_panel(self):
        """page.tsx must import LiveTranscriptPanel."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert 'LiveTranscriptPanel' in content, \
            "page.tsx does not import LiveTranscriptPanel"

    def test_page_imports_realtime_suggestion_panel(self):
        """page.tsx must import RealtimeSuggestionPanel."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert 'RealtimeSuggestionPanel' in content, \
            "page.tsx does not import RealtimeSuggestionPanel"

    def test_page_imports_from_components_realtime(self):
        """page.tsx must import from @/components/realtime."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        # Check for import from the official components directory
        import_patterns = [
            f"from '{COMPONENT_IMPORT_PATH}'",
            f'from "{COMPONENT_IMPORT_PATH}"',
            f"from '{COMPONENT_IMPORT_PATH}/",
            f'from "{COMPONENT_IMPORT_PATH}/',
        ]
        
        found = any(pattern in content for pattern in import_patterns)
        assert found, \
            f"page.tsx must import from {COMPONENT_IMPORT_PATH}"

    def test_page_uses_session_control_panel_as_jsx(self):
        """page.tsx must render SessionControlPanel as JSX."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        # Check for JSX usage (not just import)
        assert '<SessionControlPanel' in content, \
            "page.tsx imports SessionControlPanel but doesn't render it"

    def test_page_uses_audio_settings_panel_as_jsx(self):
        """page.tsx must render AudioSettingsPanel as JSX."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert '<AudioSettingsPanel' in content, \
            "page.tsx imports AudioSettingsPanel but doesn't render it"

    def test_page_uses_live_transcript_panel_as_jsx(self):
        """page.tsx must render LiveTranscriptPanel as JSX."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert '<LiveTranscriptPanel' in content, \
            "page.tsx imports LiveTranscriptPanel but doesn't render it"

    def test_page_uses_realtime_suggestion_panel_as_jsx(self):
        """page.tsx must render RealtimeSuggestionPanel as JSX."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert '<RealtimeSuggestionPanel' in content, \
            "page.tsx imports RealtimeSuggestionPanel but doesn't render it"


class TestNoInlineRealtimeUI:
    """Tests that page.tsx does NOT contain inline realtime UI rendering."""

    def test_no_inline_transcript_rendering(self):
        """page.tsx must not contain inline transcript rendering loops."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        # Remove comments for cleaner check
        # Strip single-line comments
        content_no_comments = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        # Strip multi-line comments
        content_no_comments = re.sub(r'/\*.*?\*/', '', content_no_comments, flags=re.DOTALL)
        
        # Check for forbidden patterns
        for pattern in FORBIDDEN_INLINE_PATTERNS:
            # Allow if it's inside a component usage (passing as prop)
            # e.g., transcripts={transcriptsForPanel} is OK
            # but {transcripts.map(...)} inside JSX is not OK
            
            matches = list(re.finditer(pattern, content_no_comments))
            for match in matches:
                # Check if this is inside a component prop assignment
                start = match.start()
                # Look backwards for the nearest '<' or '={'
                before = content_no_comments[max(0, start-100):start]
                
                # If it's a prop assignment like transcripts={...}, that's OK
                if '={' in before:
                    continue
                    
                # If it's actually just in a comment we missed, skip
                if '//' in before.split('\n')[-1] or '/*' in before:
                    continue
                    
                # Otherwise, this is forbidden inline rendering
                pytest.fail(
                    f"Found forbidden inline pattern '{pattern}' in page.tsx at position {start}. "
                    f"Use official components instead."
                )

    def test_no_manual_question_input_inline_render(self):
        """Manual question input should be minimal, not a full inline component."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        # Manual input is allowed but should be minimal
        # Check that it's not a huge inline block
        manual_input_blocks = content.count('Manual Question Input')
        
        # Should have exactly one manual input section (for audio stub)
        assert manual_input_blocks <= 1, \
            f"page.tsx has {manual_input_blocks} manual input sections, should be 0 or 1"


class TestPageIsThinOrchestrator:
    """Tests that page.tsx is a thin orchestrator."""

    def test_page_imports_official_hook(self):
        """page.tsx must import useRealtimeWebSocket."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert 'useRealtimeWebSocket' in content, \
            "page.tsx must import useRealtimeWebSocket hook"

    def test_page_uses_hook_not_direct_websocket(self):
        """page.tsx must use the hook, not create WebSocket directly."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        # Must not create WebSocket directly
        assert 'new WebSocket(' not in content, \
            "page.tsx creates WebSocket directly - use useRealtimeWebSocket hook instead"

    def test_page_passes_hook_state_to_components(self):
        """page.tsx must pass hook state to components as props."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        # Check that components receive props
        assert 'connected={' in content or 'connected=' in content, \
            "SessionControlPanel should receive connected prop from hook"
        
        assert 'sessionActive={' in content or 'sessionActive=' in content, \
            "SessionControlPanel should receive sessionActive prop from hook"

    def test_page_has_health_check(self):
        """page.tsx should have backend health check (orchestrator responsibility)."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        assert '/api/coach/backend-health' in content or '/health' in content, \
            "page.tsx should have backend health check"

    def test_page_has_layout_structure(self):
        """page.tsx should define layout structure (orchestrator responsibility)."""
        project_root = Path(__file__).parent.parent.parent
        page_path = project_root / 'src/app/page.tsx'
        content = page_path.read_text()
        
        # Check for layout elements
        assert '<header' in content, "page.tsx should have header layout"
        assert '<main' in content, "page.tsx should have main layout"
        assert '<footer' in content, "page.tsx should have footer layout"


class TestComponentIntegrationSummary:
    """Summary test that documents the integration."""

    def test_integration_is_documented(self):
        """Document the expected component integration."""
        integration = {
            "page_role": "thin_orchestrator",
            "required_components": sorted(list(REQUIRED_COMPONENTS)),
            "import_path": COMPONENT_IMPORT_PATH,
            "forbidden_patterns": [
                "Inline transcript rendering",
                "Inline suggestion rendering", 
                "Inline session info rendering",
                "Direct WebSocket creation"
            ]
        }
        
        print("\n" + "=" * 60)
        print("REALTIME UI COMPONENT INTEGRATION")
        print("=" * 60)
        print(f"\nPage Role: {integration['page_role']}")
        print(f"\nRequired Components (from {integration['import_path']}):")
        for component in integration['required_components']:
            print(f"  - {component}")
        print(f"\nForbidden Inline Patterns:")
        for pattern in integration['forbidden_patterns']:
            print(f"  - {pattern}")
        print("=" * 60 + "\n")
        
        assert True  # Always pass, this is documentation
