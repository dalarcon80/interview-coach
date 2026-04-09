"""Unit tests for truthful speaker attribution mapping in Deepgram STT adapter."""

from adapters.stt_adapter import DeepgramSTTAdapter


def test_map_speaker_returns_unknown_when_diarization_missing():
    adapter = DeepgramSTTAdapter(api_key="test")
    payload = {
        "type": "Results",
        "channel": {
            "alternatives": [
                {
                    "transcript": "Tell me about your architecture",
                    "confidence": 0.9,
                }
            ]
        },
    }

    speaker = adapter._map_speaker_from_payload(payload, payload["channel"]["alternatives"][0])

    assert speaker == "unknown"


def test_map_speaker_uses_diarization_when_available():
    adapter = DeepgramSTTAdapter(api_key="test")
    payload = {
        "type": "Results",
        "results": {
            "utterances": [
                {"speaker": 0, "transcript": "Can you describe a challenge?"},
                {"speaker": 1, "transcript": "Sure, I can."},
            ]
        },
    }

    speaker = adapter._map_speaker_from_payload(payload, {"transcript": "Can you describe a challenge?"})

    assert speaker == "interviewer"
