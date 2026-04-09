"""
Interview Coach - Silence Detector for Auto-Triggered Suggestions

This module provides the SilenceDetector class that automatically triggers
suggestions when silence is detected after an interviewer turn.

Key features:
- Relaxed constraints vs. TurnAssembler (500ms vs 2000ms, 2 words vs 5)
- Cooldown tracking to prevent spam
- Integration with ConversationTracker for context
"""

import time
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from conversation.tracker import ConversationTracker


def resolve_realtime_context_bundle(turns: list[dict[str, Any]]) -> Dict[str, Any]:
    """Resolve the latest interviewer question block from a turn list."""
    primary_question = ""
    primary_question_index: Optional[int] = None
    primary_question_source = "none"

    interviewer_block: list[str] = []
    interviewer_block_start: Optional[int] = None
    interviewer_block_seen = False

    for idx in range(len(turns) - 1, -1, -1):
        text = str(turns[idx].get("text", "")).strip()
        if not text:
            continue
        speaker = turns[idx].get("speaker")

        if speaker == "interviewer":
            interviewer_block_seen = True
            interviewer_block.append(text)
            interviewer_block_start = idx
            continue

        if interviewer_block_seen:
            break

    if interviewer_block:
        primary_question = "\n".join(reversed(interviewer_block))
        primary_question_index = interviewer_block_start
        primary_question_source = (
            "latest_interviewer_block"
            if len(interviewer_block) > 1
            else "latest_interviewer_turn"
        )

    if not primary_question:
        for idx in range(len(turns) - 1, -1, -1):
            text = str(turns[idx].get("text", "")).strip()
            if text:
                primary_question = text
                primary_question_index = idx
                primary_question_source = "latest_non_empty_turn"
                break

    return {
        "turns": turns,
        "context_turns": len(turns),
        "primary_question": primary_question,
        "primary_question_index": primary_question_index,
        "interviewer_question_index": primary_question_index if primary_question_source == "latest_interviewer_turn" else None,
        "primary_question_source": primary_question_source,
    }


def build_realtime_context_bundle(conversation_tracker: "ConversationTracker", limit: int = 5) -> Dict[str, Any]:
    """Resolve the latest interviewer question block from the last N turns."""
    turns = conversation_tracker.get_last_n_turns(limit=limit)
    return resolve_realtime_context_bundle(turns)


class SilenceDetector:
    """
    Detects interviewer silence and triggers suggestion generation.
    
    Uses relaxed constraints compared to TurnAssembler to allow faster
    auto-triggering of suggestions:
    - min_turn_duration_ms: 500 (vs 2000 in TurnAssembler)
    - min_word_count: 2 (vs 5 in TurnAssembler)
    - cooldown_sec: 5.0 (same as suggestion cooldown)
    """
    
    def __init__(
        self,
        conversation_tracker: "ConversationTracker",
        cooldown_sec: float = 5.0,
        min_turn_duration_ms: int = 500,
        min_word_count: int = 2,
        context_turn_limit: int = 5,
    ):
        """
        Initialize the SilenceDetector.
        
        Args:
            conversation_tracker: The conversation tracker for context
            cooldown_sec: Minimum seconds between auto-triggered suggestions
            min_turn_duration_ms: Minimum turn duration (relaxed from TurnAssembler's 2000)
            min_word_count: Minimum word count (relaxed from TurnAssembler's 5)
            context_turn_limit: Number of turns to include in context
        """
        self._tracker = conversation_tracker
        self._cooldown_sec = cooldown_sec
        self._min_turn_duration_ms = min_turn_duration_ms
        self._min_word_count = min_word_count
        self._context_turn_limit = context_turn_limit
        
        self._last_suggestion_at: Optional[float] = None
        self._suggestion_in_progress: bool = False
    
    @property
    def cooldown_sec(self) -> float:
        """Get the cooldown period in seconds."""
        return self._cooldown_sec
    
    @property
    def min_turn_duration_ms(self) -> int:
        """Get the minimum turn duration in milliseconds."""
        return self._min_turn_duration_ms
    
    @property
    def min_word_count(self) -> int:
        """Get the minimum word count."""
        return self._min_word_count
    
    def should_trigger_suggestion(self, turn_data: Dict[str, Any]) -> bool:
        """
        Check if we should trigger an automatic suggestion based on the turn data.
        
        Uses relaxed constraints:
        - Minimum turn duration (500ms vs 2000ms in TurnAssembler)
        - Minimum word count (2 vs 5 in TurnAssembler)
        - Cooldown check
        
        Args:
            turn_data: Dictionary with turn information including:
                - speaker: str - The speaker type ("interviewer" or other)
                - duration_ms: int - Turn duration in milliseconds
                - text: str - The turn text
                
        Returns:
            True if suggestion should be triggered, False otherwise
        """
        # Only trigger on interviewer turns
        speaker = turn_data.get("speaker", "")
        if speaker != "interviewer":
            return False
        
        # Check if a suggestion is already in progress
        if self._suggestion_in_progress:
            return False
        
        # Check cooldown
        if not self._is_cooldown_expired():
            return False
        
        # Check relaxed duration constraint (500ms vs 2000ms)
        duration_ms = turn_data.get("duration_ms", 0)
        if duration_ms < self._min_turn_duration_ms:
            return False
        
        # Check relaxed word count constraint (2 vs 5)
        text = turn_data.get("text", "")
        word_count = len(str(text).split())
        if word_count < self._min_word_count:
            return False
        
        return True
    
    def _is_cooldown_expired(self) -> bool:
        """Check if cooldown period has expired since last suggestion."""
        if self._last_suggestion_at is None:
            return True
        
        elapsed = time.time() - self._last_suggestion_at
        return elapsed >= self._cooldown_sec
    
    def get_remaining_cooldown(self) -> float:
        """
        Get remaining cooldown time in seconds.
        
        Returns:
            Seconds remaining until next auto-trigger allowed, or 0 if no cooldown active
        """
        if self._last_suggestion_at is None:
            return 0.0
        
        elapsed = time.time() - self._last_suggestion_at
        remaining = self._cooldown_sec - elapsed
        return max(0.0, remaining)
    
    def record_trigger(self) -> None:
        """
        Record that a suggestion has been triggered.
        This starts the cooldown timer.
        """
        self._suggestion_in_progress = True
        self._last_suggestion_at = time.time()
    
    def record_completion(self) -> None:
        """
        Record that a suggestion generation has completed.
        This marks the suggestion as no longer in progress.
        """
        self._suggestion_in_progress = False
    
    def build_context_bundle(self) -> Dict[str, Any]:
        """Return the current realtime context bundle for auto or manual triggers."""
        return build_realtime_context_bundle(self._tracker, limit=self._context_turn_limit)

    def get_context_turns(self) -> list[Dict[str, Any]]:
        return self.build_context_bundle().get("turns", [])

    def get_primary_question_from_context(self) -> str:
        return self.build_context_bundle().get("primary_question", "")

    def build_suggestion_payload(self) -> Dict[str, Any]:
        bundle = self.build_context_bundle()
        return {
            "trigger": "silence",
            **bundle,
            "timestamp": time.time(),
        }
