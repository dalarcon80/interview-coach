# Worklog — Interview Coach Baseline
**Date**: 2026-03-15
**Phase**: P0-T3 (Truth Reconciliation)

## Test Collection
Timestamp (UTC): 2026-03-15T16:47:14Z
```
tests/integration/test_event_bus_contract.py::TestEventType::test_event_types_exist
tests/integration/test_event_bus_contract.py::TestEventType::test_event_type_serialization
tests/integration/test_event_bus_contract.py::TestEvent::test_event_creation
tests/integration/test_event_bus_contract.py::TestEvent::test_event_serialization
tests/integration/test_event_bus_contract.py::TestEvent::test_event_deserialization
tests/integration/test_event_bus_contract.py::TestEventBus::test_subscribe_and_publish
tests/integration/test_event_bus_contract.py::TestEventBus::test_multiple_subscribers
tests/integration/test_event_bus_contract.py::TestEventBus::test_priority_ordering
tests/integration/test_event_bus_contract.py::TestEventBus::test_unsubscribe
tests/integration/test_event_bus_contract.py::TestEventBus::test_event_log
tests/integration/test_event_bus_contract.py::TestEventBus::test_clear_log
tests/integration/test_event_bus_contract.py::TestEventBusContract::test_event_trace_propagation
tests/integration/test_event_bus_contract.py::TestEventBusContract::test_event_ordering_guarantee
tests/integration/test_event_bus_contract.py::TestEventBusContract::test_payload_schema_validation
tests/integration/test_event_bus_contract.py::TestAsyncEventBus::test_async_event_processing
tests/integration/test_event_bus_contract.py::TestEventBusIntegration::test_pipeline_event_flow
tests/integration/test_frontend_backend_ws_contract.py::TestWebSocketEventContract::test_backend_events_are_defined
tests/integration/test_frontend_backend_ws_contract.py::TestWebSocketEventContract::test_no_overlap_between_event_directions
tests/integration/test_frontend_backend_ws_contract.py::TestWebSocketEventContract::test_deprecated_events_list_is_complete
tests/integration/test_frontend_backend_ws_contract.py::TestWebSocketEventContract::test_no_deprecated_events_in_active_frontend_files
tests/integration/test_frontend_backend_ws_contract.py::TestWebSocketEventContract::test_frontend_hook_uses_official_events
tests/integration/test_frontend_backend_ws_contract.py::TestWebSocketEventContract::test_backend_suggestion_payload_matches_frontend
tests/integration/test_frontend_backend_ws_contract.py::TestNoDuplicateFrontendWebsocketPaths::test_only_one_websocket_hook_in_realtime_folder
tests/integration/test_frontend_backend_ws_contract.py::TestNoDuplicateFrontendWebsocketPaths::test_page_tsx_does_not_create_websocket_directly
tests/integration/test_frontend_backend_ws_contract.py::TestNoDuplicateFrontendWebsocketPaths::test_page_tsx_uses_websocket_hook
tests/integration/test_frontend_backend_ws_contract.py::TestEventNameConsistency::test_server_py_uses_official_events
tests/integration/test_frontend_backend_ws_contract.py::TestEventNameConsistency::test_index_ts_exports_official_hook_only
tests/integration/test_frontend_backend_ws_contract.py::TestIntegrationContractSummary::test_contract_is_documented
tests/integration/test_health_real.py::TestHealthRealDB::test_health_returns_healthy_when_db_connected
tests/integration/test_health_real.py::TestHealthRealDB::test_health_returns_degraded_when_db_not_connected
tests/integration/test_health_real.py::TestHealthRealDB::test_health_returns_degraded_on_db_exception
tests/integration/test_health_real.py::TestHealthRealDB::test_health_includes_version_and_providers
tests/integration/test_health_real.py::TestHealthRealDB::test_health_endpoint_exposes_mode
tests/integration/test_health_real.py::TestHealthDBIntegration::test_health_with_real_database
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_file_exists
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_imports_session_control_panel
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_imports_audio_settings_panel
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_imports_live_transcript_panel
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_imports_realtime_suggestion_panel
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_imports_from_components_realtime
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_uses_session_control_panel_as_jsx
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_uses_audio_settings_panel_as_jsx
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_uses_live_transcript_panel_as_jsx
tests/integration/test_realtime_ui_component_integration.py::TestPageUsesOfficialComponents::test_page_uses_realtime_suggestion_panel_as_jsx
tests/integration/test_realtime_ui_component_integration.py::TestNoInlineRealtimeUI::test_no_inline_transcript_rendering
tests/integration/test_realtime_ui_component_integration.py::TestNoInlineRealtimeUI::test_no_manual_question_input_inline_render
tests/integration/test_realtime_ui_component_integration.py::TestPageIsThinOrchestrator::test_page_imports_official_hook
tests/integration/test_realtime_ui_component_integration.py::TestPageIsThinOrchestrator::test_page_uses_hook_not_direct_websocket
tests/integration/test_realtime_ui_component_integration.py::TestPageIsThinOrchestrator::test_page_passes_hook_state_to_components
tests/integration/test_realtime_ui_component_integration.py::TestPageIsThinOrchestrator::test_page_has_health_check
tests/integration/test_realtime_ui_component_integration.py::TestPageIsThinOrchestrator::test_page_has_layout_structure
tests/integration/test_realtime_ui_component_integration.py::TestComponentIntegrationSummary::test_integration_is_documented
tests/integration/test_ws_realtime_flow.py::TestWebSocketRealtimeFlow::test_websocket_sends_session_started_with_mode
tests/integration/test_ws_realtime_flow.py::TestWebSocketRealtimeFlow::test_websocket_sends_real_events_on_transcript
tests/integration/test_ws_realtime_flow.py::TestWebSocketRealtimeFlow::test_websocket_includes_mode_in_suggestion
tests/integration/test_ws_realtime_flow.py::TestWebSocketRealtimeFlow::test_websocket_handles_partial_transcript
tests/integration/test_ws_realtime_flow.py::TestWebSocketRealtimeFlow::test_websocket_sends_session_error_on_no_session
tests/integration/test_ws_realtime_flow.py::TestWebSocketRealtimeFlow::test_websocket_session_end_includes_summary
tests/integration/test_ws_realtime_flow.py::TestWebSocketEventTypes::test_analysis_includes_question_type
tests/integration/test_ws_realtime_flow.py::TestWebSocketEventTypes::test_suggestion_response_includes_quality
tests/integration/test_ws_realtime_flow.py::TestWebSocketAudioStreamingPersistence::test_audio_data_reuses_single_stt_stream_and_cleans_up_on_end_session
tests/unit/test_contracts.py::TestEnums::test_question_type_values
tests/unit/test_contracts.py::TestEnums::test_response_style_values
tests/unit/test_contracts.py::TestEnums::test_priority_values
tests/unit/test_contracts.py::TestSubQuestion::test_subquestion_creation
tests/unit/test_contracts.py::TestSubQuestion::test_subquestion_default_weight
tests/unit/test_contracts.py::TestSubQuestion::test_subquestion_weight_validation
tests/unit/test_contracts.py::TestQuestionAnalysis::test_question_analysis_creation
tests/unit/test_contracts.py::TestQuestionAnalysis::test_question_analysis_defaults
tests/unit/test_contracts.py::TestEvidenceChunk::test_evidence_chunk_creation
tests/unit/test_contracts.py::TestEvidenceChunk::test_evidence_chunk_score_validation
tests/unit/test_contracts.py::TestGeneratedResponse::test_generated_response_creation
tests/unit/test_contracts.py::TestQualityResult::test_quality_result_pass
tests/unit/test_contracts.py::TestQualityResult::test_quality_result_fail
tests/unit/test_contracts.py::TestLanguageDecision::test_language_decision_spanish
tests/unit/test_contracts.py::TestLanguageDecision::test_language_decision_english
tests/unit/test_contracts.py::TestExchange::test_exchange_creation
tests/unit/test_contracts.py::TestSessionState::test_session_state_creation
tests/unit/test_contracts.py::TestSessionState::test_session_state_with_exchanges
tests/unit/test_contracts.py::TestProviderConfig::test_provider_config_creation
tests/unit/test_contracts.py::TestInterviewConfig::test_interview_config_creation
tests/unit/test_contracts.py::TestInterviewConfig::test_interview_config_defaults
tests/unit/test_contracts.py::TestUserProfile::test_user_profile_creation
tests/unit/test_language_policy.py::TestLanguageDecision::test_spanish_decision
tests/unit/test_language_policy.py::TestLanguageDecision::test_english_decision
tests/unit/test_language_policy.py::TestLanguageDecision::test_low_confidence_fallback
tests/unit/test_language_policy.py::TestLanguagePolicyCases::test_user_preference_takes_priority
tests/unit/test_language_policy.py::TestLanguagePolicyCases::test_dominant_language_detection
tests/unit/test_language_policy.py::TestLanguagePolicyCases::test_bilingual_uses_last_sentence
tests/unit/test_language_policy.py::TestLanguagePolicyCases::test_low_confidence_session_fallback
tests/unit/test_language_policy.py::TestLanguagePolicyCases::test_absolute_fallback_is_spanish
tests/unit/test_language_policy.py::TestLanguagePolicyCasesFromBank::test_mixed_english_spanish
tests/unit/test_language_policy.py::TestLanguagePolicyCasesFromBank::test_spanish_with_technical_terms
tests/unit/test_language_policy.py::TestLanguagePolicyCasesFromBank::test_code_switching_mid_sentence
tests/unit/test_language_policy.py::TestLanguagePolicyConfidence::test_high_confidence
tests/unit/test_language_policy.py::TestLanguagePolicyConfidence::test_medium_confidence
tests/unit/test_language_policy.py::TestLanguagePolicyConfidence::test_low_confidence
tests/unit/test_language_policy.py::TestLanguagePolicyExceptions::test_proper_names_exception
tests/unit/test_language_policy.py::TestLanguagePolicyExceptions::test_technical_terms_exception
tests/unit/test_provider_registry.py::TestProviderRegistryService::test_registry_initialization
tests/unit/test_provider_registry.py::TestProviderRegistryService::test_resolve_llm_config
tests/unit/test_provider_registry.py::TestProviderRegistryService::test_resolve_stt_config
tests/unit/test_provider_registry.py::TestProviderRegistryService::test_resolve_embedding_config
tests/unit/test_provider_registry.py::TestProviderRegistryService::test_resolve_unknown_alias_raises_error
tests/unit/test_provider_registry.py::TestProviderRegistryService::test_get_llm_config_shortcut
tests/unit/test_provider_registry.py::TestProviderRegistryService::test_get_stt_config_shortcut
tests/unit/test_provider_registry.py::TestProviderRegistryService::test_get_embedding_config_shortcut
tests/unit/test_provider_registry.py::TestProviderRegistryEnvOverrides::test_model_override
tests/unit/test_provider_registry.py::TestProviderRegistryEnvOverrides::test_provider_override
tests/unit/test_provider_registry.py::TestGlobalRegistry::test_get_registry_singleton
tests/unit/test_provider_registry.py::TestProviderConfigFromFile::test_load_from_providers_yaml
tests/unit/test_quality_gate.py::TestQualityResult::test_passing_result
tests/unit/test_quality_gate.py::TestQualityResult::test_failing_result
tests/unit/test_quality_gate.py::TestQualityResult::test_result_with_contradictions
tests/unit/test_quality_gate.py::TestQualityGateCases::test_response_too_long_fails
tests/unit/test_quality_gate.py::TestQualityGateCases::test_metric_repetition_fails
tests/unit/test_quality_gate.py::TestQualityGateCases::test_contradiction_fails
tests/unit/test_quality_gate.py::TestQualityGateCases::test_missing_must_answer_fails
tests/unit/test_quality_gate.py::TestQualityGateCases::test_language_mismatch_fails
tests/unit/test_quality_gate.py::TestQualityGatePass::test_valid_response_passes
tests/unit/test_quality_gate.py::TestQualityGatePass::test_response_with_unique_metrics_passes
tests/unit/test_quality_gate.py::TestQualityGateScoreThresholds::test_score_above_0_8_passes
tests/unit/test_quality_gate.py::TestQualityGateScoreThresholds::test_score_below_0_6_fails
tests/unit/test_quality_gate.py::TestConversationMapValidation::test_empty_conversation_map
tests/unit/test_quality_gate.py::TestConversationMapValidation::test_conversation_map_with_history
tests/unit/test_question_bank.py::TestQuestionBank::test_question_bank_not_empty
tests/unit/test_question_bank.py::TestQuestionBank::test_all_questions_have_required_fields
tests/unit/test_question_bank.py::TestQuestionBank::test_get_question_by_id
tests/unit/test_question_bank.py::TestQuestionBank::test_get_question_by_id_not_found
tests/unit/test_question_bank.py::TestQuestionBank::test_get_questions_by_type
tests/unit/test_question_bank.py::TestQuestionBank::test_get_questions_by_language
tests/unit/test_question_bank.py::TestQuestionBank::test_get_quality_gate_fail_cases
tests/unit/test_question_bank.py::TestQuestionBank::test_get_language_policy_cases
tests/unit/test_question_bank.py::TestQuestionTypes::test_has_behavioral_questions
tests/unit/test_question_bank.py::TestQuestionTypes::test_has_technical_questions
tests/unit/test_question_bank.py::TestQuestionTypes::test_has_compound_questions
tests/unit/test_question_bank.py::TestQuestionLanguages::test_has_spanish_questions
tests/unit/test_question_bank.py::TestQuestionLanguages::test_has_english_questions
tests/unit/test_question_bank.py::TestQuestionLanguages::test_has_mixed_language_questions
tests/unit/test_stt_speaker_mapping.py::test_map_speaker_returns_unknown_when_diarization_missing
tests/unit/test_stt_speaker_mapping.py::test_map_speaker_uses_diarization_when_available

==================================== ERRORS ====================================
_________ ERROR collecting tests/benchmarks/test_latency_benchmarks.py _________
tests/benchmarks/test_latency_benchmarks.py:13: in <module>
    from tests.fixtures.profiles.cto_profile import CTO_PROFILE
tests/fixtures/profiles/cto_profile.py:135: in <module>
    def get_achievement_by_id(achievement_id: str) -> dict | None:
E   TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
_______ ERROR collecting tests/integration/test_pipeline_integration.py ________
tests/integration/test_pipeline_integration.py:31: in <module>
    from pipeline.steps.response_composer import ResponseComposer, ComposerMode
python-core/pipeline/steps/response_composer.py:72: in <module>
    class ResponseComposer:
python-core/pipeline/steps/response_composer.py:181: in ResponseComposer
    on_bullets: Optional[Callable[[GeneratedResponse], Awaitable[None] | None]] = None,
E   TypeError: unsupported operand type(s) for |: '_GenericAlias' and 'NoneType'
_______ ERROR collecting tests/integration/test_realtime_session_e2e.py ________
ImportError while importing test module '/Users/dalarcon/projects/dev/interview-coach/tests/integration/test_realtime_session_e2e.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/importlib/__init__.py:127: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/integration/test_realtime_session_e2e.py:10: in <module>
    from fastapi.testclient import TestClient
E   ModuleNotFoundError: No module named 'fastapi'
___________ ERROR collecting tests/integration/test_suggest_mode.py ____________
ImportError while importing test module '/Users/dalarcon/projects/dev/interview-coach/tests/integration/test_suggest_mode.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/importlib/__init__.py:127: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/integration/test_suggest_mode.py:9: in <module>
    from fastapi.testclient import TestClient
E   ModuleNotFoundError: No module named 'fastapi'
_________ ERROR collecting tests/simulations/test_simulation_runner.py _________
tests/simulations/test_simulation_runner.py:10: in <module>
    from tests.fixtures.profiles.cto_profile import CTO_PROFILE, CTO_INTERVIEW_CONFIG
tests/fixtures/profiles/cto_profile.py:135: in <module>
    def get_achievement_by_id(achievement_id: str) -> dict | None:
E   TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
____________ ERROR collecting tests/stability/test_long_running.py _____________
tests/stability/test_long_running.py:16: in <module>
    from tests.fixtures.profiles.cto_profile import CTO_PROFILE
tests/fixtures/profiles/cto_profile.py:135: in <module>
    def get_achievement_by_id(achievement_id: str) -> dict | None:
E   TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
_________ ERROR collecting tests/unit/test_ws_audio_stt_forwarding.py __________
ImportError while importing test module '/Users/dalarcon/projects/dev/interview-coach/tests/unit/test_ws_audio_stt_forwarding.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/importlib/__init__.py:127: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/unit/test_ws_audio_stt_forwarding.py:13: in <module>
    from api.server import _process_audio_for_stt
python-core/api/server.py:24: in <module>
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
E   ModuleNotFoundError: No module named 'fastapi'
__________ ERROR collecting tests/unit/test_ws_session_stt_manager.py __________
ImportError while importing test module '/Users/dalarcon/projects/dev/interview-coach/tests/unit/test_ws_session_stt_manager.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/importlib/__init__.py:127: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/unit/test_ws_session_stt_manager.py:8: in <module>
    from api.server import SessionSTTStreamManager
python-core/api/server.py:24: in <module>
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
E   ModuleNotFoundError: No module named 'fastapi'
=============================== warnings summary ===============================
tests/integration/test_event_bus_contract.py:398
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_event_bus_contract.py:398: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_health_real.py:15
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_health_real.py:15: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_health_real.py:33
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_health_real.py:33: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_health_real.py:51
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_health_real.py:51: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_health_real.py:69
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_health_real.py:69: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_health_real.py:86
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_health_real.py:86: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_health_real.py:105
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_health_real.py:105: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:48
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:48: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:84
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:84: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:124
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:124: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:167
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:167: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:203
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:203: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:227
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:227: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:295
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:295: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:330
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:330: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

tests/integration/test_ws_realtime_flow.py:453
  /Users/dalarcon/projects/dev/interview-coach/tests/integration/test_ws_realtime_flow.py:453: PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    @pytest.mark.asyncio

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
ERROR tests/benchmarks/test_latency_benchmarks.py - TypeError: unsupported op...
ERROR tests/integration/test_pipeline_integration.py - TypeError: unsupported...
ERROR tests/integration/test_realtime_session_e2e.py
ERROR tests/integration/test_suggest_mode.py
ERROR tests/simulations/test_simulation_runner.py - TypeError: unsupported op...
ERROR tests/stability/test_long_running.py - TypeError: unsupported operand t...
ERROR tests/unit/test_ws_audio_stt_forwarding.py
ERROR tests/unit/test_ws_session_stt_manager.py
!!!!!!!!!!!!!!!!!!! Interrupted: 8 errors during collection !!!!!!!!!!!!!!!!!!!!
141 tests collected, 8 errors in 0.84s
```

## Quick Tests
Timestamp (UTC): 2026-03-15T16:47:15Z
```
[0;34m==========================================
Interview Coach - Package Smoke Test
Mode: quick
==========================================[0m

[1;33mChecking prerequisites...[0m
  [0;32m✓[0m Python found: Python 3.14.3
  [0;32m✓[0m pytest found

[1;33mRunning QUICK validation (unit tests only)[0m

[0;34m▶ Unit Tests[0m
........................................................................ [ 84%]
.............                                                            [100%]
85 passed in 0.34s
  [0;32m✓ PASSED[0m

[0;34m==========================================
Results: \033[0;32m1 passed\033[0m, \033[0;31m0 failed\033[0m
==========================================[0m
```

## Smoke Tests
Timestamp (UTC): 2026-03-15T16:47:16Z
```
[0;34m==========================================
Interview Coach - Package Smoke Test
Mode: smoke
==========================================[0m

[1;33mChecking prerequisites...[0m
  [0;32m✓[0m Python found: Python 3.14.3
  [0;32m✓[0m pytest found

[1;33mRunning SMOKE validation[0m

[0;34m▶ Test Collection[0m
  [0;32m✓ PASSED[0m (all tests collect)
[0;34m▶ Unit Tests[0m
........................................................................ [ 84%]
.............                                                            [100%]
85 passed in 0.27s
  [0;32m✓ PASSED[0m
[0;34m▶ WebSocket Contract[0m
............                                                             [100%]
12 passed in 0.01s
  [0;32m✓ PASSED[0m
[0;34m▶ UI Component Integration[0m
..................                                                       [100%]
18 passed in 0.01s
  [0;32m✓ PASSED[0m

[0;34m==========================================
Results: \033[0;32m4 passed\033[0m, \033[0;31m0 failed\033[0m
==========================================[0m
```

## Full Verification
Timestamp (UTC): 2026-03-15T16:47:18Z
```
[0;34m==========================================
Interview Coach - Package Verification
==========================================[0m

[0;34m▶ 1. Test Collection[0m
  [0;32m✓ PASSED[0m - 225 tests collected in 0.21s
[0;34m▶ 2. Unit Tests[0m
  [0;32m✓ PASSED[0m - 85 passed in 0.19s
[0;34m▶ 3. Smoke Test[0m
  [0;32m✓ PASSED[0m - 4 suites (collection, unit, contract, integration)
[0;34m▶ 4. Lint Check[0m
  [0;32m✓ PASSED[0m -  errors,  warnings

[0;34m==========================================
Package Status: [0;32mHEALTHY[0m
==========================================[0m

All verifications passed. Package is ready.
```

## Summary
- Tests collected: 141
- Quick tests: PASS
- Smoke tests: PASS
- Full verification: PASS
- Blockers for P1: `python3 -m pytest tests --collect-only -q` failed with 8 collection errors (Python 3.9 type-hint incompatibilities and missing `fastapi` in the system interpreter)
