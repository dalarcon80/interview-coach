"""
Interview Coach - Turn Assembler
Assembles partial transcripts into complete speaker turns
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any
from enum import Enum

from contracts.models import LanguageDecision


class TurnState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    COMPLETE = "complete"


@dataclass
class SpeakerTurn:
    """A complete speaker turn"""
    speaker: str  # "interviewer" | "candidate"
    text: str
    start_time: float
    end_time: Optional[float] = None
    utterances: list[str] = field(default_factory=list)
    language_decision: Optional[LanguageDecision] = None
    language: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    completion_reason: Optional[str] = None
    is_complete: bool = False
    
    @property
    def duration_ms(self) -> int:
        if self.end_time:
            return int((self.end_time - self.start_time) * 1000)
        return 0

    @property
    def utterance_count(self) -> int:
        return len(self.utterances)


@dataclass
class TurnAssemblerState:
    """State for the turn assembler"""
    current_turn: Optional[SpeakerTurn] = None
    partial_text: str = ""
    last_activity_time: float = field(default_factory=time.time)
    last_utterance_time: Optional[float] = None
    last_speaker: Optional[str] = None
    silence_threshold_ms: int = 2000


class TurnAssembler:
    """
    Assembles partial transcripts into complete speaker turns.
    
    A turn is considered complete when:
    1. The speaker changes OR
    2. Silence exceeds the threshold
    3. Utterance end event arrives
    4. Interrogative punctuation indicates a question
    """
    
    def __init__(self, silence_threshold_ms: int = 2000):
        self.state = TurnAssemblerState(silence_threshold_ms=silence_threshold_ms)
        self.completed_turns: list[SpeakerTurn] = []

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text or "").split()).strip()

    @classmethod
    def _is_question_boundary(cls, text: str, speaker: str) -> bool:
        if speaker != "interviewer":
            return False
        normalized = cls._normalize_text(text)
        return bool(normalized) and normalized.endswith("?")

    def _update_turn_metadata(
        self,
        turn: SpeakerTurn,
        *,
        language: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        if language:
            turn.language = language
        if metadata:
            turn.metadata = {**(turn.metadata or {}), **metadata}

    def _append_utterance(self, turn: SpeakerTurn, text: str) -> None:
        normalized = self._normalize_text(text)
        if not normalized:
            return
        if not turn.utterances:
            turn.utterances = [normalized]
        else:
            last = turn.utterances[-1]
            if normalized == last:
                return
            if normalized.startswith(last):
                turn.utterances[-1] = normalized
            elif last.startswith(normalized):
                return
            else:
                turn.utterances.append(normalized)
        if turn.utterances:
            turn.text = turn.utterances[-1]
        else:
            turn.text = normalized
        self.state.partial_text = turn.text

    def _start_turn(
        self,
        *,
        speaker: str,
        text: str,
        event_time: float,
        language: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        normalized = self._normalize_text(text)
        new_turn = SpeakerTurn(
            speaker=speaker,
            text=normalized,
            start_time=event_time,
            utterances=[normalized] if normalized else [],
            language=language,
            metadata=metadata or {},
        )
        self.state.current_turn = new_turn
        self.state.partial_text = new_turn.text
        self.state.last_speaker = speaker

    @staticmethod
    def _format_timestamp(timestamp: Optional[float]) -> str:
        if timestamp is None:
            return "n/a"
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        except Exception:
            return str(timestamp)

    def _log_turn_complete(self, turn: SpeakerTurn) -> None:
        print(
            "[TURN][ASSEMBLY] turn_complete "
            f"speaker={turn.speaker} utterances={turn.utterance_count} "
            f"duration_ms={turn.duration_ms} "
            f"start_ts={self._format_timestamp(turn.start_time)} "
            f"end_ts={self._format_timestamp(turn.end_time)} "
            f"reason={turn.completion_reason or 'unknown'} "
            f"text='{(turn.text or '')[:60]}...'"
        )

    def _log_turn_boundary(self, turn: SpeakerTurn) -> None:
        print(
            "[TURN][BOUNDARY] "
            f"reason={turn.completion_reason or 'unknown'} "
            f"duration_ms={turn.duration_ms}"
        )

    def _complete_current_turn(
        self,
        *,
        end_time: float,
        reason: str,
    ) -> Optional[SpeakerTurn]:
        if self.state.current_turn is None:
            return None
        turn = self.state.current_turn
        if not turn.utterances and turn.text:
            turn.utterances = [self._normalize_text(turn.text)]
        turn.end_time = end_time
        turn.is_complete = True
        turn.completion_reason = reason
        self._log_turn_boundary(turn)
        self._log_turn_complete(turn)

        self.state.current_turn = None
        self.state.partial_text = ""
        self.state.last_utterance_time = None
        self.state.last_speaker = None

        self.completed_turns.append(turn)
        return turn

    def force_complete(
        self,
        *,
        reason: str = "forced",
        end_time: Optional[float] = None,
    ) -> Optional[SpeakerTurn]:
        """Force completion of the current turn regardless of pause threshold."""
        if self.state.current_turn is None:
            return None
        return self._complete_current_turn(
            end_time=end_time or time.time(),
            reason=reason,
        )

    def process_utterance(
        self,
        text: str,
        speaker: str = "interviewer",
        *,
        event_time: Optional[float] = None,
        language: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        allow_completion: bool = True,
    ) -> Optional[SpeakerTurn]:
        """
        Process a finalized utterance for turn assembly.
        Returns a completed turn when boundaries are detected.
        """
        event_time = event_time or time.time()
        normalized = self._normalize_text(text)
        if not normalized:
            return None

        self.state.last_activity_time = event_time
        completed_turn: Optional[SpeakerTurn] = None

        if self.state.current_turn is None:
            if allow_completion:
                self._start_turn(
                    speaker=speaker,
                    text=normalized,
                    event_time=event_time,
                    language=language,
                    metadata=metadata,
                )
                if self._is_question_boundary(normalized, speaker):
                    completed_turn = self._complete_current_turn(
                        end_time=event_time,
                        reason="question",
                    )
                    self.state.last_utterance_time = event_time
                    self.state.last_speaker = speaker
                    return completed_turn
            else:
                self._start_turn(
                    speaker=speaker,
                    text=normalized,
                    event_time=event_time,
                    language=language,
                    metadata=metadata,
                )
                self.state.last_utterance_time = event_time
                self.state.last_speaker = speaker
                return None
        else:
            current_turn = self.state.current_turn
            if allow_completion:
                pause_ms = None
                if self.state.last_utterance_time is not None:
                    pause_ms = (event_time - self.state.last_utterance_time) * 1000

                if speaker != current_turn.speaker:
                    completed_turn = self._complete_current_turn(
                        end_time=self.state.last_utterance_time or event_time,
                        reason="speaker_change",
                    )
                    self._start_turn(
                        speaker=speaker,
                        text=normalized,
                        event_time=event_time,
                        language=language,
                        metadata=metadata,
                    )
                elif pause_ms is not None and pause_ms >= self.state.silence_threshold_ms:
                    completed_turn = self._complete_current_turn(
                        end_time=self.state.last_utterance_time or event_time,
                        reason="pause",
                    )
                    self._start_turn(
                        speaker=speaker,
                        text=normalized,
                        event_time=event_time,
                        language=language,
                        metadata=metadata,
                    )
                else:
                    self._append_utterance(current_turn, normalized)
                    self._update_turn_metadata(current_turn, language=language, metadata=metadata)
                    if self._is_question_boundary(normalized, speaker):
                        completed_turn = self._complete_current_turn(
                            end_time=event_time,
                            reason="question",
                        )
            else:
                self._append_utterance(current_turn, normalized)
                self._update_turn_metadata(current_turn, language=language, metadata=metadata)

        self.state.last_utterance_time = event_time
        self.state.last_speaker = speaker
        return completed_turn
    
    def process_partial(self, text: str, speaker: str = "interviewer") -> Optional[SpeakerTurn]:
        """
        Process a partial transcript.
        Returns None (turn not complete) or a complete turn.
        """
        event_time = time.time()
        self.state.last_activity_time = event_time

        if self.state.current_turn is None:
            self._start_turn(speaker=speaker, text=text, event_time=event_time)
        else:
            self.state.current_turn.text = text
            if not self.state.current_turn.utterances:
                self.state.current_turn.utterances = [self._normalize_text(text)]
        self.state.last_utterance_time = event_time
        self.state.last_speaker = speaker
        self.state.partial_text = text
        return None  # Turn not complete yet
    
    def process_final(self, text: str, speaker: str = "interviewer") -> SpeakerTurn:
        """
        Process a final transcript.
        Returns the complete turn.
        """
        event_time = time.time()
        self.state.last_activity_time = event_time

        if self.state.current_turn is None or self.state.current_turn.speaker != speaker:
            self._start_turn(speaker=speaker, text=text, event_time=event_time)
        else:
            self._append_utterance(self.state.current_turn, text)

        turn = self._complete_current_turn(end_time=event_time, reason="final")
        if turn is None:
            raise RuntimeError("Failed to complete turn")
        return turn
    
    def check_silence_timeout(self) -> Optional[SpeakerTurn]:
        """
        Check if silence has exceeded threshold.
        Returns the turn if it should be forced complete.
        """
        return self.flush_if_idle(reason="pause")

    def flush_if_idle(
        self,
        current_time: Optional[float] = None,
        *,
        reason: str = "pause",
    ) -> Optional[SpeakerTurn]:
        if self.state.current_turn is None:
            return None
        current_time = current_time or time.time()
        last_activity = self.state.last_utterance_time or self.state.last_activity_time
        if last_activity is None:
            return None
        elapsed_ms = (current_time - last_activity) * 1000
        if elapsed_ms >= self.state.silence_threshold_ms:
            return self._complete_current_turn(
                end_time=last_activity,
                reason=reason,
            )
        return None
    
    def reset(self):
        """Reset the assembler state"""
        self.state = TurnAssemblerState(
            silence_threshold_ms=self.state.silence_threshold_ms
        )
        self.completed_turns = []
    
    def get_current_partial(self) -> str:
        """Get the current partial text"""
        return self.state.partial_text

    def get_current_turn(self) -> Optional[SpeakerTurn]:
        """Get the current in-progress turn"""
        return self.state.current_turn
    
    def get_turn_count(self) -> int:
        """Get the number of completed turns"""
        return len(self.completed_turns)


# Unit tests
if __name__ == "__main__":
    assembler = TurnAssembler()
    
    # Test partial processing
    assert assembler.process_partial("Hello") is None
    assert assembler.get_current_partial() == "Hello"
    
    # Test final processing
    turn = assembler.process_final("Hello, how are you?")
    assert turn.is_complete
    assert turn.text == "Hello, how are you?"
    assert assembler.get_turn_count() == 1
    
    print("TurnAssembler tests passed!")
