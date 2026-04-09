import json
from pathlib import Path
from unittest.mock import patch

import runtime_config_store
from adapters.stt_adapter import DeepgramSTTAdapter, STTAdapterFactory, WhisperLocalSTTAdapter


def test_load_runtime_config_skips_sanitized_legacy_migration(tmp_path, monkeypatch):
    legacy_path = tmp_path / "legacy_runtime_config.json"
    legacy_payload = {
        "llm": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "api_key": "",
            "enabled": True,
            "base_url": "",
        },
        "stt": {
            "provider": "deepgram",
            "model": "nova-3",
            "api_key": "",
            "enabled": True,
        },
    }
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    local_path = tmp_path / "runtime_config.json"
    monkeypatch.setenv("INTERVIEW_COACH_RUNTIME_CONFIG_PATH", str(local_path))
    monkeypatch.setattr(runtime_config_store, "_LEGACY_CONFIG_PATH", legacy_path)

    payload = runtime_config_store.load_runtime_config_payload()

    assert payload is None
    assert not local_path.exists()


def test_stt_adapter_factory_reads_local_settings_store():
    runtime_payload = {
        "stt": {
            "provider": "deepgram",
            "enabled": True,
            "api_key": "local-stt-key",
            "model": "nova-3",
            "local_enabled": False,
        }
    }

    with patch("adapters.stt_adapter.load_runtime_config_payload", return_value=runtime_payload):
        adapter = STTAdapterFactory.create()

    assert isinstance(adapter, DeepgramSTTAdapter)
    assert adapter._api_key == "local-stt-key"


def test_stt_adapter_factory_honors_local_whisper_flag():
    runtime_payload = {
        "stt": {
            "provider": "deepgram",
            "enabled": True,
            "api_key": "local-stt-key",
            "model": "nova-3",
            "local_enabled": True,
            "local_model": "small",
        }
    }

    with patch("adapters.stt_adapter.load_runtime_config_payload", return_value=runtime_payload):
        adapter = STTAdapterFactory.create()

    assert isinstance(adapter, WhisperLocalSTTAdapter)
