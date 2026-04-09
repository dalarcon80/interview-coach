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
        context_turn_limit: int = 4,
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
    
    def get_context_turns(self) -> list[Dict[str, Any]]:
        """
        Get the last N turns from conversation history for context.
        
        Uses the same get_last_n_turns method as the manual trigger
        to ensure consistent context.
        
        Returns:
            List of turn dictionaries
        """
        return self._tracker.get_last_n_turns(limit=self._context_turn_limit)
    
    def get_primary_question_from_context(self) -> str:
        """
        Get the primary question text from the conversation context.
        
        Returns the text of the most recent turn (which could be either
        interviewer or candidate, depending on the conversation flow).
        
        Returns:
            The text of the most recent turn, or empty string if no turns
        """
        turns = self.get_context_turns()
        if not turns:
            return ""
        
        last_turn = turns[-1]
        return last_turn.get("text", "")
    
    def build_suggestion_payload(self) -> Dict[str, Any]:
        """
        Build the payload for an automatic suggestion trigger.
        
        Returns:
            Dictionary with context_turns, turns, primary_question, and timestamp
        """
        turns = self.get_context_turns()
        primary_question = self.get_primary_question_from_context()
        
        return {
            "trigger": "silence",
            "context_turns": len(turns),
            "turns": turns,
            "primary_question": primary_question,
            "timestamp": time.time(),
        }
