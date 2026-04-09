"""
Speaker fallback correction heuristics.

Applies lightweight, non-blocking rules to resolve unknown speaker labels
in realtime STT events.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Optional


UNKNOWN_SPEAKERS = {"unknown", "unattributed", ""}


@dataclass
class SpeakerFallbackDecision:
    speaker: str
    confidence: float
    reason: str
    method: str = "fallback"
    used_fallback: bool = True


class SpeakerFallbackCorrector:
    """Heuristic speaker resolver for unknown diarization labels."""

    def __init__(
        self,
        *,
        session_id: Optional[str] = None,
        long_pause_ms: int = 1200,
        short_pause_ms: int = 400,
    ) -> None:
        self._session_id = session_id or "unknown"
        self._long_pause_ms = long_pause_ms
        self._short_pause_ms = short_pause_ms
        self._last_speaker: Optional[str] = None
        self._last_turn_speaker: Optional[str] = None
        self._last_activity_at: Optional[float] = None
        self._last_turn_completed_at: Optional[float] = None
        self._last_text: str = ""
        self._turn_index = 0

    def resolve(
        self,
        raw_speaker: Optional[str],
        text: str,
        *,
        event_timestamp: Optional[float] = None,
        is_final: bool = False,
        utterance_complete: bool = False,
        source_hint: Optional[str] = None,
    ) -> SpeakerFallbackDecision:
        """Resolve speaker using STT label or fallback heuristics."""
        normalized = self._normalize_speaker(raw_speaker)
        event_time = event_timestamp if event_timestamp is not None else perf_counter()

        if normalized not in UNKNOWN_SPEAKERS:
            decision = SpeakerFallbackDecision(
                speaker=normalized,
                confidence=1.0,
                reason="stt_label",
                method="stt",
                used_fallback=False,
            )
            self._update_state(decision, text, event_time, is_final, utterance_complete)
            return decision

        source_decision = self._source_hint_decision(source_hint)
        if source_decision is not None:
            decision = source_decision
        else:
            decision = self._fallback_decision(text, event_time)
        self._update_state(decision, text, event_time, is_final, utterance_complete)
        return decision

    @staticmethod
    def _source_hint_decision(source_hint: Optional[str]) -> Optional[SpeakerFallbackDecision]:
        normalized_source = str(source_hint or "").strip().lower()
        if not normalized_source:
            return None

        interviewer_sources = {"system", "loopback", "speaker", "desktop", "output"}
        candidate_sources = {"mic", "microphone", "input", "user"}

        if normalized_source in interviewer_sources:
            return SpeakerFallbackDecision(
                speaker="interviewer",
                confidence=0.93,
                reason="audio_source_system",
            )

        if normalized_source in candidate_sources:
            return SpeakerFallbackDecision(
                speaker="candidate",
                confidence=0.93,
                reason="audio_source_mic",
            )

        return None

    def _fallback_decision(self, text: str, event_time: float) -> SpeakerFallbackDecision:
        """
        Make a fallback decision when STT diarization is unavailable.
        
        Strategy:
        - First utterance: unknown (let context decide)
        - Short pauses: continue with same speaker
        - Long pauses: alternate speakers (natural conversation flow)
        - Alternating pattern: switch speakers each turn
        """
        pause_ms = self._pause_ms(event_time)
        continuation = self._is_continuation(text)
        
        # If this is a continuation of the same text, keep the same speaker
        if continuation and self._last_speaker is not None:
            return SpeakerFallbackDecision(
                speaker=self._last_speaker,
                confidence=0.75,
                reason="text_continuation",
            )

        # Very short pause - likely same speaker continuing
        if pause_ms is not None and pause_ms <= self._short_pause_ms:
            if self._last_speaker is not None:
                return SpeakerFallbackDecision(
                    speaker=self._last_speaker,
                    confidence=0.7,
                    reason="short_pause_continuation",
                )
            # No prior speaker, default to interviewer (they usually start)
            return SpeakerFallbackDecision(
                speaker="interviewer",
                confidence=0.6,
                reason="short_pause_no_prior",
            )

        # Long pause - likely speaker change, alternate from last speaker
        if pause_ms is not None and pause_ms >= self._long_pause_ms:
            if self._last_speaker is not None:
                next_speaker = "candidate" if self._last_speaker == "interviewer" else "interviewer"
                return SpeakerFallbackDecision(
                    speaker=next_speaker,
                    confidence=0.72,
                    reason="long_pause_speaker_change",
                )
            # No prior speaker on long pause, could be either
            return SpeakerFallbackDecision(
                speaker="unknown",
                confidence=0.5,
                reason="long_pause_no_prior",
            )

        # Default: alternate speakers if we have a last speaker
        if self._last_speaker is not None:
            next_speaker = "candidate" if self._last_speaker == "interviewer" else "interviewer"
            return SpeakerFallbackDecision(
                speaker=next_speaker,
                confidence=0.65,
                reason="alternating_pattern",
            )
        
        # Truly first utterance with no context - mark as unknown
        # The pipeline will treat this as interviewer by default
        return SpeakerFallbackDecision(
            speaker="unknown",
            confidence=0.5,
            reason="first_utterance_unknown",
        )

    def _pause_ms(self, event_time: float) -> Optional[int]:
        anchor = self._last_turn_completed_at or self._last_activity_at
        if anchor is None:
            return None
        return int(max(0.0, (event_time - anchor) * 1000))

    def _is_continuation(self, text: str) -> bool:
        prior = self._normalize_text(self._last_text)
        current = self._normalize_text(text)
        if not prior or not current:
            return False
        return current.startswith(prior) or prior.startswith(current) or prior in current

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text or "").split()).strip()

    @staticmethod
    def _normalize_speaker(raw_speaker: Optional[str]) -> str:
        if raw_speaker is None:
            return "unknown"
        speaker = str(raw_speaker).strip().lower()
        if not speaker:
            return "unknown"
        if speaker in {"interviewer", "candidate", "unknown", "unattributed"}:
            return speaker
        return "unknown"

    def _update_state(
        self,
        decision: SpeakerFallbackDecision,
        text: str,
        event_time: float,
        is_final: bool,
        utterance_complete: bool,
    ) -> None:
        normalized_text = self._normalize_text(text)
        self._last_activity_at = event_time
        if normalized_text:
            self._last_text = normalized_text
        self._last_speaker = decision.speaker

        if is_final and utterance_complete:
            self._turn_index += 1
            self._last_turn_completed_at = event_time
            self._last_turn_speaker = decision.speaker
