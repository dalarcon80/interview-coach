"""Unit tests for source-aware speaker fallback behavior."""

from conversation.speaker_fallback import SpeakerFallbackCorrector


def test_unknown_speaker_uses_system_audio_source_as_interviewer():
    corrector = SpeakerFallbackCorrector(session_id="test-system")

    decision = corrector.resolve(
        None,
        "What roles did they have?",
        is_final=True,
        utterance_complete=True,
        source_hint="system",
    )

    assert decision.speaker == "interviewer"
    assert decision.reason == "audio_source_system"
    assert decision.confidence > 0.9


def test_unknown_speaker_uses_mic_audio_source_as_candidate():
    corrector = SpeakerFallbackCorrector(session_id="test-mic")

    decision = corrector.resolve(
        None,
        "I managed 20 direct managers.",
        is_final=True,
        utterance_complete=True,
        source_hint="mic",
    )

    assert decision.speaker == "candidate"
    assert decision.reason == "audio_source_mic"
    assert decision.confidence > 0.9
