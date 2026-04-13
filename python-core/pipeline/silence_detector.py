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
from datetime import datetime
from hashlib import sha1
from typing import Optional, Dict, Any, TYPE_CHECKING

from contracts.models import ActiveAskState, NormalizedRealtimeContextBundle

if TYPE_CHECKING:
    from conversation.tracker import ConversationTracker


DEFAULT_ACTIVE_ASK_IDLE_CLOSE_SEC = 5.0


def _normalize_turn_text(text: Any) -> str:
    return " ".join(str(text or "").split()).strip()


def _normalize_realtime_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for turn in list(turns or []):
        text = _normalize_turn_text(turn.get("text", ""))
        if not text:
            continue
        normalized.append(
            {
                **turn,
                "speaker": str(turn.get("speaker", "") or "").strip().lower() or "unknown",
                "text": text,
            }
        )
    return normalized


def _sort_realtime_turns_by_time(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort turns chronologically when time metadata exists."""
    ordered: list[tuple[float, int, dict[str, Any]]] = []
    for index, turn in enumerate(list(turns or [])):
        turn_time = _turn_event_time(turn)
        sort_time = float(turn_time) if turn_time is not None else float("inf")
        ordered.append((sort_time, index, turn))
    ordered.sort(key=lambda item: (item[0], item[1]))
    return [turn for _, _, turn in ordered]


def _parse_turn_timestamp(raw_value: Any) -> Optional[float]:
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    if not raw_value:
        return None
    try:
        normalized = str(raw_value).strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return None


def _turn_event_time(turn: dict[str, Any]) -> Optional[float]:
    for key in ("end_time", "start_time", "timestamp"):
        value = _parse_turn_timestamp(turn.get(key))
        if value is not None:
            return value
    timestamp_ms = turn.get("timestamp_ms")
    if isinstance(timestamp_ms, (int, float)):
        return float(timestamp_ms) / 1000.0
    if isinstance(timestamp_ms, str):
        try:
            return float(timestamp_ms) / 1000.0
        except Exception:
            return None
    return None


def _build_realtime_context_signature(turns: list[dict[str, Any]]) -> str:
    payload = [
        {
            "speaker": str(turn.get("speaker") or "").strip().lower(),
            "text": _normalize_turn_text(turn.get("text") or ""),
            "timestamp": turn.get("timestamp"),
            "timestamp_ms": turn.get("timestamp_ms"),
            "start_time": turn.get("start_time"),
            "end_time": turn.get("end_time"),
        }
        for turn in list(turns or [])
        if _normalize_turn_text(turn.get("text") or "")
    ]
    return sha1(str(payload).encode("utf-8")).hexdigest()


def _find_latest_interviewer_block_range(
    turns: list[dict[str, Any]],
    *,
    idle_close_sec: float,
) -> tuple[Optional[int], Optional[int]]:
    block_start: Optional[int] = None
    block_end: Optional[int] = None
    next_turn_time: Optional[float] = None
    block_seen = False

    for idx in range(len(turns) - 1, -1, -1):
        turn = turns[idx]
        speaker = str(turn.get("speaker") or "").strip().lower()
        text = _normalize_turn_text(turn.get("text") or "")
        if not text:
            continue

        if speaker == "interviewer":
            current_turn_time = _turn_event_time(turn)
            if (
                block_seen
                and next_turn_time is not None
                and current_turn_time is not None
                and (next_turn_time - current_turn_time) > max(idle_close_sec, 0.0)
            ):
                break
            block_seen = True
            block_start = idx
            if block_end is None:
                block_end = idx
            next_turn_time = current_turn_time
            continue

        if block_seen:
            break

    return block_start, block_end


def _select_historical_turns(
    turns: list[dict[str, Any]],
    *,
    active_start: int,
    active_end: int,
    historical_turn_limit: int,
) -> list[dict[str, Any]]:
    if historical_turn_limit <= 0:
        return list(turns[:active_start]) + list(turns[active_end + 1 :])

    historical_turns = list(turns[:active_start]) + list(turns[active_end + 1 :])
    if len(historical_turns) <= historical_turn_limit:
        return historical_turns
    return historical_turns[-historical_turn_limit:]


def resolve_realtime_context_bundle(
    turns: list[dict[str, Any]],
    *,
    last_answer_committed_at: Optional[float] = None,
    last_answer_committed_question_key: str = "",
    current_interviewer_generation: Optional[int] = None,
    frozen_at: Optional[float] = None,
    frozen_question_key: str = "",
    frozen_interviewer_generation: Optional[int] = None,
    idle_close_sec: float = DEFAULT_ACTIVE_ASK_IDLE_CLOSE_SEC,
    selected_turn_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Resolve the latest active interviewer block from a turn list."""
    normalized_turns = _sort_realtime_turns_by_time(_normalize_realtime_turns(turns))
    source_signature = _build_realtime_context_signature(normalized_turns)

    if not normalized_turns:
        bundle = NormalizedRealtimeContextBundle(source_signature=source_signature)
        return bundle.model_dump(mode="json")

    boundary_at = frozen_at if frozen_at is not None else last_answer_committed_at
    candidate_turns = list(normalized_turns)
    candidate_offset = 0
    if boundary_at is not None:
        boundary_index = len(normalized_turns)
        for idx, turn in enumerate(normalized_turns):
            turn_time = _turn_event_time(turn)
            if turn_time is not None and turn_time > float(boundary_at):
                boundary_index = idx
                break
        if boundary_index < len(normalized_turns):
            candidate_turns = list(normalized_turns[boundary_index:])
            candidate_offset = boundary_index
        elif last_answer_committed_at is not None and frozen_at is None:
            candidate_turns = []
            candidate_offset = len(normalized_turns)

    block_start, block_end = _find_latest_interviewer_block_range(
        candidate_turns,
        idle_close_sec=idle_close_sec,
    )

    active_turns: list[dict[str, Any]] = []
    active_turn_start_index: Optional[int] = None
    active_turn_end_index: Optional[int] = None
    primary_question = ""
    primary_question_source = "none"
    carry_forward_reason = ""

    if block_start is not None and block_end is not None:
        active_turn_start_index = candidate_offset + block_start
        active_turn_end_index = candidate_offset + block_end
        active_turns = [dict(turn) for turn in candidate_turns[block_start : block_end + 1]]
        primary_question = "\n".join(turn["text"] for turn in active_turns)
        if frozen_at is not None and candidate_offset > 0:
            primary_question_source = "post_freeze_interviewer_turns"
            carry_forward_reason = "new_interviewer_after_frozen_answer"
        elif last_answer_committed_at is not None and candidate_offset > 0:
            primary_question_source = "post_commit_interviewer_turns"
            carry_forward_reason = "new_interviewer_after_committed_answer"
        else:
            primary_question_source = (
                "latest_interviewer_block"
                if len(active_turns) > 1
                else "latest_interviewer_turn"
            )
    elif frozen_at is None and last_answer_committed_at is None:
        last_idx = len(normalized_turns) - 1
        active_turn_start_index = last_idx
        active_turn_end_index = last_idx
        active_turns = [dict(normalized_turns[last_idx])]
        primary_question = active_turns[0]["text"]
        primary_question_source = "latest_non_empty_turn"

    active_turn_count = len(active_turns)
    active_question_key = _normalize_turn_text(primary_question).lower()

    historical_turn_limit = max(
        0,
        (selected_turn_limit - active_turn_count)
        if isinstance(selected_turn_limit, int) and selected_turn_limit > 0
        else 0,
    )
    historical_turns = (
        _select_historical_turns(
            normalized_turns,
            active_start=active_turn_start_index if active_turn_start_index is not None else len(normalized_turns),
            active_end=active_turn_end_index if active_turn_end_index is not None else len(normalized_turns) - 1,
            historical_turn_limit=historical_turn_limit,
        )
        if active_turn_count > 0
        else list(normalized_turns)
    )

    active_ask_state = ActiveAskState(
        ask_key=active_question_key,
        question_text=primary_question,
        status="open" if active_turn_count > 0 else ("closed" if boundary_at is not None else "open"),
        source=primary_question_source,
        carry_forward_reason=carry_forward_reason,
        interviewer_generation=int(current_interviewer_generation or 0),
        source_turn_start_index=active_turn_start_index,
        source_turn_end_index=active_turn_end_index,
        opened_at=_turn_event_time(active_turns[0]) if active_turns else None,
        updated_at=_turn_event_time(active_turns[-1]) if active_turns else None,
        last_active_ask_frozen_at=frozen_at,
        last_active_ask_frozen_question_key=_normalize_turn_text(frozen_question_key).lower(),
        last_active_ask_frozen_interviewer_generation=(
            int(frozen_interviewer_generation)
            if frozen_interviewer_generation is not None
            else None
        ),
        last_answer_committed_at=last_answer_committed_at,
        last_answer_committed_question_key=_normalize_turn_text(last_answer_committed_question_key).lower(),
        last_answer_committed_interviewer_generation=(
            int(current_interviewer_generation or 0)
            if last_answer_committed_at is not None and current_interviewer_generation is not None
            else None
        ),
        idle_close_threshold_sec=float(idle_close_sec),
    )

    bundle = NormalizedRealtimeContextBundle(
        turns=active_turns,
        active_turns=active_turns,
        historical_turns=historical_turns,
        source_turns=normalized_turns,
        context_turns=len(active_turns),
        source_turn_count=len(normalized_turns),
        active_turn_count=len(active_turns),
        historical_turn_count=len(historical_turns),
        primary_question=primary_question,
        primary_question_index=0 if active_turns else None,
        interviewer_question_index=0 if active_turns else None,
        primary_question_source=primary_question_source,
        carry_forward_reason=carry_forward_reason,
        source_signature=source_signature,
        active_ask_state=active_ask_state,
    )
    return bundle.model_dump(mode="json")


def select_realtime_active_turn_window(
    turns: list[dict[str, Any]],
    *,
    idle_close_sec: float = DEFAULT_ACTIVE_ASK_IDLE_CLOSE_SEC,
    selected_turn_limit: Optional[int] = None,
) -> tuple[list[dict[str, Any]], Dict[str, Any]]:
    """Resolve a turn window and return the latest active interviewer block.

    The returned turns preserve the original timing metadata so downstream
    consumers can keep using the same deterministic silence boundary logic.
    """
    resolved_bundle = resolve_realtime_context_bundle(
        turns,
        idle_close_sec=idle_close_sec,
        selected_turn_limit=selected_turn_limit,
    )
    active_turns = resolved_bundle.get("turns") or resolved_bundle.get("active_turns") or []
    if active_turns:
        return [dict(turn) for turn in active_turns], resolved_bundle
    active_state = resolved_bundle.get("active_ask_state") or {}
    boundary_closed = False
    if isinstance(active_state, dict):
        boundary_closed = bool(
            active_state.get("last_active_ask_frozen_at") is not None
            or active_state.get("last_answer_committed_at") is not None
            or str(active_state.get("status") or "").strip().lower() == "closed"
        )
    if boundary_closed:
        return [], resolved_bundle
    return _sort_realtime_turns_by_time(_normalize_realtime_turns(turns)), resolved_bundle


def build_realtime_context_bundle(conversation_tracker: "ConversationTracker", limit: int = 5) -> Dict[str, Any]:
    """Resolve the latest interviewer question block from the tracker-aware live window."""
    if conversation_tracker is None:
        return resolve_realtime_context_bundle([])

    builder = getattr(conversation_tracker, "build_normalized_realtime_context_bundle", None)
    if callable(builder):
        bundle = builder(limit=limit)
        if bundle is not None:
            if hasattr(bundle, "model_dump"):
                return bundle.model_dump(mode="json")
            if isinstance(bundle, dict):
                return bundle

    turns = conversation_tracker.get_last_n_turns(limit=limit)
    resolved = resolve_realtime_context_bundle(turns)
    resolved.update(
        {
            "active_turns": resolved.get("turns", []),
            "historical_turns": [],
            "source_turns": turns,
            "source_turn_count": len(turns),
            "active_turn_count": len(resolved.get("turns", [])),
            "historical_turn_count": 0,
            "carry_forward_reason": "",
            "source_signature": "",
        }
    )
    return resolved


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
        speaker = turn_data.get("speaker", "")
        if speaker != "interviewer":
            return False

        if self._suggestion_in_progress:
            return False

        if not self._is_cooldown_expired():
            return False

        duration_ms = turn_data.get("duration_ms", 0)
        if duration_ms < self._min_turn_duration_ms:
            return False

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
