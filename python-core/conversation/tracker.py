"""
Interview Coach - Conversation Tracker
Tracks the state of the conversation to ensure coherence

Maintains:
- Claims made by candidate (for contradiction detection)
- Metrics already used (for repetition avoidance)
- Achievements referenced (for not repeating same stories)
- Uncovered gaps (topics interviewer wanted but weren't addressed)
- Interviewer values (inferred from questions)
"""
import asyncio
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha1
from typing import Optional, Any

from contracts.models import (
    ActiveAskState,
    AskBrief,
    ConversationMap,
    QuestionAnalysis,
    GeneratedResponse,
    QualityResult,
    Exchange,
    LiveAskSummary,
    LivePreparedContext,
    NormalizedRealtimeContextBundle,
)


logger = logging.getLogger(__name__)


@dataclass
class TrackerState:
    """Internal state for the tracker"""
    claims: list[str] = field(default_factory=list)
    metrics_used: list[str] = field(default_factory=list)
    achievements_referenced: list[str] = field(default_factory=list)
    uncovered_gaps: list[str] = field(default_factory=list)
    interviewer_values: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    topics_covered: list[str] = field(default_factory=list)
    summary: str = ""
    exchange_count: int = 0
    speaker_history: list[dict] = field(default_factory=list)
    turn_history: list[dict] = field(default_factory=list)
    latest_ask_brief: Optional[AskBrief] = None
    latest_ask_primary_question: str = ""
    latest_live_ask_summary: Optional[LiveAskSummary] = None
    latest_live_prepared_context: Optional[LivePreparedContext] = None
    latest_active_ask_state: Optional[ActiveAskState] = None
    latest_normalized_realtime_context: Optional[NormalizedRealtimeContextBundle] = None
    last_answer_committed_at: Optional[float] = None
    last_answer_committed_question_key: str = ""
    last_answer_committed_interviewer_generation: Optional[int] = None


class ConversationTracker:
    """
    Tracks conversation state for coherence across exchanges.
    
    After each exchange:
    1. Extracts new claims from response
    2. Verifies against profile (if available)
    3. Detects if gaps were covered
    4. Extracts metrics mentioned
    5. Updates conversation summary
    """
    
    SHORT_TURN_SEC = 0.5
    RAPID_SWITCH_SEC = 1.0
    LONG_PAUSE_SEC = 5.0
    DEFAULT_MAX_TURNS = 100

    def __init__(self):
        self.state = TrackerState()
        self.exchanges: list[Exchange] = []
        self.max_turns = self.DEFAULT_MAX_TURNS
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        logger.debug("ConversationTracker initialized max_turns=%s", self.max_turns)

    @staticmethod
    def _normalize_text(text: Optional[str]) -> str:
        return " ".join(str(text or "").split()).strip()

    def _add_warning(self, warning: str) -> None:
        if warning and warning not in self.state.warnings:
            self.state.warnings.append(warning)

    def _build_map(self) -> ConversationMap:
        return ConversationMap(
            claims=self.state.claims.copy(),
            metrics_used=self.state.metrics_used.copy(),
            achievements_referenced=self.state.achievements_referenced.copy(),
            uncovered_gaps=self.state.uncovered_gaps.copy(),
            interviewer_values=self.state.interviewer_values.copy(),
            warnings=self.state.warnings.copy(),
            topics_covered=self.state.topics_covered.copy(),
            summary=self.state.summary,
        )
    
    def get_map(self) -> ConversationMap:
        """Get current conversation state as ConversationMap"""
        with self._sync_lock:
            return self._build_map()

    def get_conversation_summary(self) -> dict:
        """Return a debugging snapshot of conversation tracker state."""
        with self._sync_lock:
            last_exchange = self.exchanges[-1] if self.exchanges else None
            last_turn = self.state.turn_history[-1] if self.state.turn_history else None
            summary = {
                "exchange_count": self.state.exchange_count,
                "turn_count": len(self.state.turn_history),
                "speaker_event_count": len(self.state.speaker_history),
                "last_exchange_index": last_exchange.index if last_exchange else None,
                "last_question": last_exchange.interviewer_utterance if last_exchange else None,
                "last_turn": last_turn,
                "topics_covered": self.state.topics_covered[-5:],
                "metrics_used": self.state.metrics_used[-5:],
                "warnings": self.state.warnings[-5:],
                "summary": self.state.summary,
            }
        logger.debug("conversation_summary snapshot=%s", summary)
        return summary

    def get_last_interviewer_turn(self, max_age_seconds: float = 30.0) -> Optional[Dict[str, Any]]:
        """
        Get the most recent interviewer turn from conversation history.

        Args:
            max_age_seconds: Only return turns newer than this (prevents old suggestions)

        Returns:
            Dict with 'text', 'speaker', 'timestamp', 'start_time', 'end_time' or None if not found
        """
        import time

        with self._sync_lock:
            if not self.state.turn_history:
                logger.debug("get_last_interviewer_turn: no turn history")
                return None

            # DEBUG: Log all turns for diagnosis
            current_time = time.time()
            logger.debug("get_last_interviewer_turn: checking %d turns", len(self.state.turn_history))
            for i, turn in enumerate(self.state.turn_history):
                speaker = turn.get("speaker", "unknown")
                end_time = turn.get("end_time")
                age = current_time - end_time if end_time else None
                text_preview = turn.get("text", "")[:50]
                logger.debug("  turn[%d]: speaker=%s age=%.2fs text='%s...'", i, speaker, age, text_preview)
            
            # Search backwards through turn history for interviewer turns
            for turn in reversed(self.state.turn_history):
                speaker = turn.get("speaker", "")
                # Check if this is an interviewer turn
                if speaker != "interviewer":
                    continue
                
                # Check if within max age
                end_time = turn.get("end_time")
                if end_time is not None:
                    age_seconds = current_time - end_time
                    if age_seconds > max_age_seconds:
                        logger.debug(
                            "get_last_interviewer_turn: turn too old age_seconds=%.2f max=%.2f",
                            age_seconds,
                            max_age_seconds
                        )
                        continue
                
                # Return the turn data
                return {
                    "text": turn.get("text", ""),
                    "speaker": speaker,
                    "timestamp": turn.get("timestamp"),
                    "start_time": turn.get("start_time"),
                    "end_time": turn.get("end_time"),
                    "duration_ms": turn.get("duration_ms"),
                    "utterance_count": turn.get("utterance_count"),
                }
            
            logger.debug("get_last_interviewer_turn: no recent interviewer turn found")
            return None

    def get_recent_context(self, limit: int = 5) -> list[Dict[str, Any]]:
        """
        Get recent turns for context.
        
        Args:
            limit: Maximum number of turns to return
        
        Returns:
            List of recent turn dicts
        """
        with self._sync_lock:
            if not self.state.turn_history:
                return []
            
            # Get last N turns
            recent = self.state.turn_history[-limit:] if len(self.state.turn_history) >= limit else self.state.turn_history
            
            return [
                {
                    "text": turn.get("text", ""),
                    "speaker": turn.get("speaker", ""),
                    "timestamp": turn.get("timestamp"),
                    "start_time": turn.get("start_time"),
                    "end_time": turn.get("end_time"),
                }
                for turn in recent
            ]

    def get_last_n_turns(self, limit: int = 5) -> list[Dict[str, Any]]:
        """
        Get last N turns from conversation history.
        
        This is an alias for get_recent_context with a default limit of 4,
        as per HR-2: Use last 4 messages from Conversation History.
        
        Args:
            limit: Maximum number of turns to return (default 4)
        
        Returns:
            List of recent turn dicts
        """
        return self.get_recent_context(limit=limit)

    def cache_latest_ask_brief(
        self,
        *,
        primary_question: str,
        ask_brief: Optional[AskBrief],
    ) -> None:
        if ask_brief is None:
            return
        with self._sync_lock:
            self.state.latest_ask_brief = ask_brief
            self.state.latest_ask_primary_question = self._normalize_text(primary_question)

    def get_cached_ask_brief(self, primary_question: Optional[str] = None) -> Optional[AskBrief]:
        with self._sync_lock:
            cached = self.state.latest_ask_brief
            cached_primary = self.state.latest_ask_primary_question
            requested_primary = self._normalize_text(primary_question)
            if cached is None:
                return None
            if requested_primary and cached_primary and requested_primary != cached_primary:
                return None
            return cached

    def cache_live_ask_summary(self, summary: Optional[LiveAskSummary]) -> None:
        if summary is None:
            return
        with self._sync_lock:
            self.state.latest_live_ask_summary = summary

    def get_live_ask_summary(self) -> Optional[LiveAskSummary]:
        with self._sync_lock:
            return self.state.latest_live_ask_summary

    def cache_live_prepared_context(self, prepared_context: Optional[LivePreparedContext]) -> None:
        if prepared_context is None:
            return
        with self._sync_lock:
            self.state.latest_live_prepared_context = prepared_context

    def get_live_prepared_context(self) -> Optional[LivePreparedContext]:
        with self._sync_lock:
            return self.state.latest_live_prepared_context

    def cache_active_ask_state(self, active_ask_state: Optional[ActiveAskState]) -> None:
        if active_ask_state is None:
            return
        with self._sync_lock:
            self.state.latest_active_ask_state = active_ask_state

    def get_active_ask_state(self) -> Optional[ActiveAskState]:
        with self._sync_lock:
            return self.state.latest_active_ask_state

    def cache_normalized_realtime_context(
        self,
        normalized_context: Optional[NormalizedRealtimeContextBundle],
    ) -> None:
        if normalized_context is None:
            return
        with self._sync_lock:
            self.state.latest_normalized_realtime_context = normalized_context
            self.state.latest_active_ask_state = normalized_context.active_ask_state

    def get_normalized_realtime_context(self) -> Optional[NormalizedRealtimeContextBundle]:
        with self._sync_lock:
            return self.state.latest_normalized_realtime_context

    @staticmethod
    def _turn_event_time(turn: dict[str, Any]) -> Optional[float]:
        for key in ("end_time", "start_time"):
            value = turn.get(key)
            if isinstance(value, (int, float)):
                return float(value)

        timestamp = turn.get("timestamp")
        if isinstance(timestamp, (int, float)):
            return float(timestamp)
        if isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
            except Exception:
                return None
        return None

    @staticmethod
    def _turn_signature(turns: list[dict[str, Any]]) -> str:
        serialized: list[str] = []
        for turn in turns:
            speaker = str(turn.get("speaker", "")).strip().lower()
            text = " ".join(str(turn.get("text", "")).split()).strip().lower()
            if not speaker and not text:
                continue
            serialized.append(f"{speaker}::{text}")
        if not serialized:
            return ""
        return sha1("\n".join(serialized).encode("utf-8")).hexdigest()

    @staticmethod
    def _build_closed_active_ask_state(
        *,
        active_ask_state: Optional[ActiveAskState],
        primary_question: str,
        primary_question_source: str,
        carry_forward_reason: str,
        last_answer_committed_at: Optional[float],
        last_answer_committed_question_key: str,
        last_answer_committed_interviewer_generation: Optional[int],
        interviewer_generation: int,
        source_turn_start_index: Optional[int],
        source_turn_end_index: Optional[int],
        status: str,
    ) -> ActiveAskState:
        base_state = active_ask_state or ActiveAskState()
        normalized_question = " ".join(str(primary_question or "").split()).strip()
        normalized_question_key = normalized_question.lower()
        updated = base_state.model_copy(
            update={
                "ask_key": normalized_question_key or base_state.ask_key,
                "question_text": normalized_question or base_state.question_text,
                "status": status,
                "source": primary_question_source or base_state.source,
                "carry_forward_reason": carry_forward_reason,
                "interviewer_generation": interviewer_generation,
                "source_turn_start_index": source_turn_start_index,
                "source_turn_end_index": source_turn_end_index,
                "last_answer_committed_at": last_answer_committed_at,
                "last_answer_committed_question_key": last_answer_committed_question_key,
                "last_answer_committed_interviewer_generation": last_answer_committed_interviewer_generation,
                "updated_at": datetime.utcnow().timestamp(),
            }
        )
        return updated

    def build_normalized_realtime_context_bundle(
        self,
        *,
        turns: Optional[list[dict[str, Any]]] = None,
        limit: int = 5,
    ) -> NormalizedRealtimeContextBundle:
        source_turns = list(turns if turns is not None else self.get_last_n_turns(limit=limit))
        source_turn_count = len(source_turns)
        commit_at = self.state.last_answer_committed_at

        commit_boundary_index = 0
        if commit_at is not None:
            commit_boundary_index = source_turn_count
            for idx, turn in enumerate(source_turns):
                turn_time = self._turn_event_time(turn)
                if turn_time is not None and turn_time > float(commit_at):
                    commit_boundary_index = idx
                    break

        post_commit_turns = source_turns[commit_boundary_index:]
        active_block_start: Optional[int] = None
        active_block_end = len(post_commit_turns)
        interviewer_block_seen = False
        for idx in range(len(post_commit_turns) - 1, -1, -1):
            text = str(post_commit_turns[idx].get("text", "")).strip()
            if not text:
                continue
            speaker = post_commit_turns[idx].get("speaker")
            if speaker == "interviewer":
                interviewer_block_seen = True
                active_block_start = idx
                continue
            if interviewer_block_seen:
                break
            active_block_end = idx

        active_turns: list[dict[str, Any]] = []
        active_turn_start_index: Optional[int] = None
        active_turn_end_index: Optional[int] = None
        if interviewer_block_seen and active_block_start is not None:
            active_turn_start_index = commit_boundary_index + active_block_start
            active_turn_end_index = commit_boundary_index + active_block_end
            active_turns = list(source_turns[active_turn_start_index:active_turn_end_index])

        if active_turn_start_index is not None and active_turn_end_index is not None:
            historical_turns = list(source_turns[:active_turn_start_index]) + list(source_turns[active_turn_end_index:])
        else:
            historical_turns = list(source_turns)

        from pipeline.silence_detector import resolve_realtime_context_bundle

        active_context = resolve_realtime_context_bundle(active_turns)
        primary_question = str(active_context.get("primary_question", "") or "")
        primary_question_index = active_context.get("primary_question_index")
        interviewer_question_index = active_context.get("interviewer_question_index")
        primary_question_source = str(active_context.get("primary_question_source", "none") or "none")
        carry_forward_reason = ""

        if commit_at is not None:
            if active_turns and primary_question:
                primary_question_source = "post_commit_interviewer_turns"
                carry_forward_reason = "new_interviewer_after_committed_answer"
            else:
                primary_question_source = "none"
                primary_question = ""
                primary_question_index = None
                interviewer_question_index = None
                carry_forward_reason = "awaiting_new_interviewer_after_committed_answer"

        active_ask_state = self._build_closed_active_ask_state(
            active_ask_state=self.state.latest_active_ask_state,
            primary_question=primary_question,
            primary_question_source=primary_question_source,
            carry_forward_reason=carry_forward_reason,
            last_answer_committed_at=commit_at,
            last_answer_committed_question_key=self.state.last_answer_committed_question_key,
            last_answer_committed_interviewer_generation=self.state.last_answer_committed_interviewer_generation,
            interviewer_generation=int(self.state.last_answer_committed_interviewer_generation or 0),
            source_turn_start_index=active_turn_start_index,
            source_turn_end_index=(active_turn_end_index - 1) if active_turn_end_index is not None and active_turns else None,
            status="open" if active_turns else ("closed" if commit_at is not None else "open"),
        )

        source_signature = self._turn_signature(source_turns)
        normalized_context = NormalizedRealtimeContextBundle(
            turns=active_turns,
            active_turns=active_turns,
            historical_turns=historical_turns,
            source_turns=source_turns,
            context_turns=len(active_turns),
            source_turn_count=source_turn_count,
            active_turn_count=len(active_turns),
            historical_turn_count=len(historical_turns),
            primary_question=primary_question,
            primary_question_index=primary_question_index,
            interviewer_question_index=interviewer_question_index,
            primary_question_source=primary_question_source,
            carry_forward_reason=carry_forward_reason,
            source_signature=source_signature,
            active_ask_state=active_ask_state,
        )
        self.cache_normalized_realtime_context(normalized_context)
        return normalized_context

    def record_answer_committed(
        self,
        *,
        committed_at: float,
        question_key: str,
        interviewer_generation: Optional[int] = None,
    ) -> None:
        with self._sync_lock:
            normalized_question_key = self._normalize_text(question_key).lower()
            self.state.last_answer_committed_at = float(committed_at)
            self.state.last_answer_committed_question_key = normalized_question_key
            self.state.last_answer_committed_interviewer_generation = (
                int(interviewer_generation)
                if isinstance(interviewer_generation, int)
                else interviewer_generation
            )
            if self.state.latest_active_ask_state is not None:
                self.state.latest_active_ask_state = self.state.latest_active_ask_state.model_copy(
                    update={
                        "status": "closed",
                        "last_answer_committed_at": self.state.last_answer_committed_at,
                        "last_answer_committed_question_key": normalized_question_key,
                        "last_answer_committed_interviewer_generation": self.state.last_answer_committed_interviewer_generation,
                    }
                )
            if self.state.latest_normalized_realtime_context is not None:
                self.state.latest_normalized_realtime_context = self.state.latest_normalized_realtime_context.model_copy(
                    update={"active_ask_state": self.state.latest_active_ask_state}
                )

    def get_answer_commit_state(self) -> dict[str, Any]:
        with self._sync_lock:
            return {
                "last_answer_committed_at": self.state.last_answer_committed_at,
                "last_answer_committed_question_key": self.state.last_answer_committed_question_key,
                "last_answer_committed_interviewer_generation": self.state.last_answer_committed_interviewer_generation,
            }

    def record_speaker_event(
        self,
        *,
        speaker: str,
        confidence: float,
        reason: str,
        source: str,
        utterance_text: str,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Record speaker attribution decisions for debugging and continuity."""
        entry = {
            "timestamp": (timestamp or datetime.utcnow()).isoformat(),
            "speaker": speaker,
            "confidence": float(confidence),
            "reason": reason,
            "source": source,
            "utterance": (utterance_text or "")[:200],
            "metadata": metadata or {},
        }
        with self._sync_lock:
            self.state.speaker_history.append(entry)
            logger.debug(
                "speaker_event_recorded count=%s speaker=%s reason=%s",
                len(self.state.speaker_history),
                speaker,
                reason,
            )
    
    def record_exchange(
        self,
        exchange: Exchange,
        analysis: Optional[QuestionAnalysis] = None,
        profile_claims: Optional[list[str]] = None,
    ) -> ConversationMap:
        """
        Record an exchange and update conversation state.
        
        Args:
            exchange: The completed exchange
            analysis: Question analysis for context
            profile_claims: Valid claims from user's profile
        
        Returns:
            Updated ConversationMap
        """
        with self._sync_lock:
            return self._record_exchange_unlocked(
                exchange,
                analysis=analysis,
                profile_claims=profile_claims,
            )

    async def record_exchange_async(
        self,
        exchange: Exchange,
        analysis: Optional[QuestionAnalysis] = None,
        profile_claims: Optional[list[str]] = None,
    ) -> ConversationMap:
        """Async-safe variant of record_exchange using asyncio.Lock."""
        async with self._lock:
            return self._record_exchange_unlocked(
                exchange,
                analysis=analysis,
                profile_claims=profile_claims,
            )

    def _record_exchange_unlocked(
        self,
        exchange: Exchange,
        *,
        analysis: Optional[QuestionAnalysis] = None,
        profile_claims: Optional[list[str]] = None,
    ) -> ConversationMap:
        if exchange is None:
            warning = "record_exchange called with None exchange"
            logger.warning("record_exchange rejected: %s", warning)
            self._add_warning(warning)
            return self._build_map()

        analysis = analysis or exchange.analysis
        logger.debug("record_exchange start index=%s", exchange.index)

        self.exchanges.append(exchange)
        self.state.exchange_count = len(self.exchanges)
        logger.debug("exchange_count_updated count=%s", self.state.exchange_count)

        # Extract claims from response
        if exchange.suggested_response:
            new_claims = self._extract_claims(
                exchange.suggested_response.full_response
            )
            if new_claims:
                self.state.claims.extend(new_claims)
                logger.debug(
                    "claims_added count=%s total=%s",
                    len(new_claims),
                    len(self.state.claims),
                )

        # Extract metrics
        if exchange.suggested_response:
            added_metrics = 0
            for metric in exchange.suggested_response.key_metrics:
                if metric not in self.state.metrics_used:
                    self.state.metrics_used.append(metric)
                    added_metrics += 1
            if added_metrics:
                logger.debug(
                    "metrics_added count=%s total=%s",
                    added_metrics,
                    len(self.state.metrics_used),
                )

        # Check if topics were covered
        if analysis:
            added_topics = 0
            for topic in analysis.key_topics:
                if topic not in self.state.topics_covered:
                    self.state.topics_covered.append(topic)
                    added_topics += 1
            if added_topics:
                logger.debug(
                    "topics_added count=%s total=%s",
                    added_topics,
                    len(self.state.topics_covered),
                )

            # Check if must-answer questions were addressed
            if analysis.sub_questions:
                for sq in analysis.sub_questions:
                    if sq.priority.value == "must_answer":
                        if exchange.suggested_response:
                            if self._addresses_question(
                                exchange.suggested_response.full_response,
                                sq.text
                            ):
                                # Covered, remove from gaps if there
                                if sq.text in self.state.uncovered_gaps:
                                    self.state.uncovered_gaps.remove(sq.text)
                                    logger.debug("gap_resolved question=%s", sq.text)
                            else:
                                # Add to gaps
                                if sq.text not in self.state.uncovered_gaps:
                                    self.state.uncovered_gaps.append(sq.text)
                                    logger.debug("gap_added question=%s", sq.text)

        # Detect interviewer values
        if analysis and analysis.underlying_intent:
            added_values = 0
            for intent in analysis.underlying_intent:
                value = self._extract_value(intent)
                if value and value not in self.state.interviewer_values:
                    self.state.interviewer_values.append(value)
                    added_values += 1
            if added_values:
                logger.debug(
                    "interviewer_values_added count=%s total=%s",
                    added_values,
                    len(self.state.interviewer_values),
                )

        # Verify claims against profile if provided
        if profile_claims:
            for claim in self.state.claims:
                if not self._is_claim_supported(claim, profile_claims):
                    warning = f"Claim may not be supported by profile: {claim[:50]}..."
                    if warning not in self.state.warnings:
                        self.state.warnings.append(warning)
                        logger.debug("profile_warning_added warning=%s", warning)

        # Update summary
        self._update_summary()

        self._validate_state()
        return self._build_map()

    def record_turn_event(
        self,
        *,
        speaker: str,
        text: str,
        utterance_count: int,
        start_time: float,
        end_time: float,
        reason: str,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Record turn assembly events for audit/debugging."""
        accepted = self.add_turn(
            speaker=speaker,
            text=text,
            utterance_count=utterance_count,
            start_time=start_time,
            end_time=end_time,
            reason=reason,
            timestamp=timestamp,
            metadata=metadata,
        )
        if not accepted:
            logger.debug(
                "turn_event_rejected speaker=%s reason=%s start_time=%s end_time=%s",
                speaker,
                reason,
                start_time,
                end_time,
            )
            return
        logger.debug(
            "turn_event_recorded speaker=%s reason=%s count=%s",
            speaker,
            reason,
            len(self.state.turn_history),
        )

    def add_turn(
        self,
        *,
        speaker: str,
        text: Optional[str],
        utterance_count: int,
        start_time: float,
        end_time: float,
        reason: str,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        """Add a completed turn with defensive validation."""
        with self._sync_lock:
            return self._add_turn_unlocked(
                speaker=speaker,
                text=text,
                utterance_count=utterance_count,
                start_time=start_time,
                end_time=end_time,
                reason=reason,
                timestamp=timestamp,
                metadata=metadata,
            )

    async def add_turn_async(
        self,
        *,
        speaker: str,
        text: Optional[str],
        utterance_count: int,
        start_time: float,
        end_time: float,
        reason: str,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        """Async-safe variant of add_turn using asyncio.Lock."""
        async with self._lock:
            return self._add_turn_unlocked(
                speaker=speaker,
                text=text,
                utterance_count=utterance_count,
                start_time=start_time,
                end_time=end_time,
                reason=reason,
                timestamp=timestamp,
                metadata=metadata,
            )

    def _add_turn_unlocked(
        self,
        *,
        speaker: str,
        text: Optional[str],
        utterance_count: int,
        start_time: float,
        end_time: float,
        reason: str,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        normalized_text = self._normalize_text(text)
        if not normalized_text:
            warning = "empty_turn_rejected"
            logger.warning("turn_rejected_empty speaker=%s", speaker)
            self._add_warning(warning)
            return False

        if start_time is None or end_time is None:
            warning = "invalid_turn_timing missing_time"
            logger.warning("turn_rejected_invalid_timing speaker=%s", speaker)
            self._add_warning(warning)
            return False

        duration_sec = end_time - start_time
        if duration_sec < 0:
            warning = "invalid_turn_timing negative_duration"
            logger.warning(
                "turn_rejected_invalid_timing speaker=%s start=%s end=%s",
                speaker,
                start_time,
                end_time,
            )
            self._add_warning(warning)
            return False

        if duration_sec < self.SHORT_TURN_SEC:
            warning = f"short_turn_rejected duration_sec={duration_sec:.3f}"
            logger.warning(
                "turn_rejected_short speaker=%s duration_sec=%.3f",
                speaker,
                duration_sec,
            )
            self._add_warning(warning)
            return False

        last_turn = self.state.turn_history[-1] if self.state.turn_history else None
        last_speaker = last_turn.get("speaker") if last_turn else None
        last_text = last_turn.get("text") if last_turn else None
        last_end_time = last_turn.get("end_time") if last_turn else None

        if last_speaker == speaker and last_text == normalized_text:
            warning = "duplicate_turn_rejected"
            logger.debug("turn_rejected_duplicate speaker=%s", speaker)
            self._add_warning(warning)
            return False

        gap_sec: Optional[float] = None
        if last_end_time is not None:
            gap_sec = start_time - last_end_time
            if gap_sec < 0:
                warning = "turn_overlap_detected"
                logger.warning(
                    "turn_overlap speaker=%s gap_sec=%.3f",
                    speaker,
                    gap_sec,
                )
                self._add_warning(warning)
                gap_sec = 0.0

        metadata = {**(metadata or {})}
        if gap_sec is not None:
            metadata["gap_ms"] = int(gap_sec * 1000)

        if gap_sec is not None and last_speaker and last_speaker != speaker and gap_sec < self.RAPID_SWITCH_SEC:
            warning = f"rapid_speaker_switch gap_ms={int(gap_sec * 1000)}"
            logger.warning(
                "rapid_speaker_switch detected speaker=%s last_speaker=%s gap_ms=%s",
                speaker,
                last_speaker,
                int(gap_sec * 1000),
            )
            metadata["rapid_switch"] = True
            self._add_warning(warning)

        if gap_sec is not None and gap_sec >= self.LONG_PAUSE_SEC:
            metadata["long_pause_ms"] = int(gap_sec * 1000)
            logger.debug(
                "long_pause_detected speaker=%s gap_ms=%s",
                speaker,
                int(gap_sec * 1000),
            )

        entry = {
            "timestamp": (timestamp or datetime.utcnow()).isoformat(),
            "speaker": speaker,
            "utterance_count": int(utterance_count),
            "text": normalized_text[:400],
            "start_time": start_time,
            "end_time": end_time,
            "duration_ms": int(duration_sec * 1000),
            "reason": reason,
            "metadata": metadata,
        }
        self.state.turn_history.append(entry)
        logger.debug(
            "turn_added speaker=%s duration_ms=%s total_turns=%s",
            speaker,
            entry["duration_ms"],
            len(self.state.turn_history),
        )
        self._prune_turn_history()
        self._validate_state()
        return True
    
    def _extract_claims(self, text: str) -> list[str]:
        """Extract factual claims from response text"""
        if not text:
            return []
        claims = []
        text_lower = text.lower()
        
        # Pattern: "I [verb] [something]"
        claim_patterns = [
            r"i (led|built|created|scaled|achieved|reduced|increased|managed|hired) ([^.]+)",
            r"i have (\d+)(?:\+)? (?:years|people|engineers)",
            r"my (?:team|organization) (?:grew|scaled|increased) ([^.]+)",
        ]
        
        for pattern in claim_patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                if isinstance(match, tuple):
                    claim = " ".join(match)
                else:
                    claim = match
                if claim and len(claim) > 10:
                    claims.append(claim.strip())
        
        return claims
    
    def _extract_value(self, intent: str) -> Optional[str]:
        """Extract interviewer value from intent"""
        # Map intents to values
        value_map = {
            "seniority": "experience_level",
            "technical": "technical_depth",
            "leadership": "leadership_ability",
            "scaling": "growth_capability",
            "results": "outcome_focus",
            "strategic": "strategic_thinking",
        }
        
        intent_lower = intent.lower()
        for keyword, value in value_map.items():
            if keyword in intent_lower:
                return value
        
        return None
    
    def _addresses_question(self, response: str, question: str) -> bool:
        """Check if response addresses a question"""
        if not response or not question:
            return False
        response_lower = response.lower()
        question_words = set(question.lower().split())
        
        # Remove common words
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for"}
        question_words -= stop_words
        
        # Check overlap
        response_words = set(response_lower.split())
        overlap = len(question_words & response_words)
        
        return overlap >= 2
    
    def _is_claim_supported(self, claim: str, profile_claims: list[str]) -> bool:
        """Check if a claim is supported by profile"""
        claim_lower = claim.lower()
        
        for profile_claim in profile_claims:
            # Simple overlap check
            if self._addresses_question(profile_claim, claim):
                return True
        
        return False  # Conservative: assume unsupported
    
    def _update_summary(self):
        """Update conversation summary"""
        if not self.exchanges:
            self.state.summary = ""
            logger.debug("summary_reset no_exchanges")
            return
        
        # Build summary from last few exchanges
        summary_parts = []
        
        for exchange in self.exchanges[-3:]:
            if exchange.suggested_response:
                # Get first sentence of response
                sentences = exchange.suggested_response.full_response.split(". ")
                if sentences:
                    topic_label = "topic"
                    if exchange.analysis and exchange.analysis.key_topics:
                        topic_label = ", ".join(exchange.analysis.key_topics[:2])
                    summary_parts.append(f"Q{exchange.index + 1}: Discussed {topic_label}")

        self.state.summary = "; ".join(summary_parts)
        logger.debug("summary_updated entries=%s", len(summary_parts))
    
    def get_metrics_for_quality_gate(self) -> list[str]:
        """Get metrics already used for quality gate check"""
        with self._sync_lock:
            return self.state.metrics_used.copy()
    
    def get_claims_for_quality_gate(self) -> list[str]:
        """Get claims already made for quality gate check"""
        with self._sync_lock:
            return self.state.claims.copy()
    
    def get_gaps(self) -> list[str]:
        """Get uncovered gaps to prioritize"""
        with self._sync_lock:
            return self.state.uncovered_gaps.copy()
    
    def reset(self):
        """Reset the tracker"""
        with self._sync_lock:
            self.state = TrackerState()
            self.exchanges = []
            logger.debug("tracker_reset")
    
    def get_exchange_count(self) -> int:
        """Get number of exchanges"""
        with self._sync_lock:
            return self.state.exchange_count

    def _prune_turn_history(self) -> None:
        if self.max_turns <= 0:
            return
        excess = len(self.state.turn_history) - self.max_turns
        if excess > 0:
            self.state.turn_history = self.state.turn_history[excess:]
            logger.debug(
                "turn_history_pruned pruned=%s remaining=%s",
                excess,
                len(self.state.turn_history),
            )

    def _validate_state(self) -> list[str]:
        """Validate tracker state for consistency."""
        issues: list[str] = []
        if self.state.exchange_count != len(self.exchanges):
            issues.append(
                f"exchange_count_mismatch expected={len(self.exchanges)} actual={self.state.exchange_count}"
            )
        if len(self.state.turn_history) > self.max_turns:
            issues.append(
                f"turn_history_overflow count={len(self.state.turn_history)} max={self.max_turns}"
            )
        for idx, turn in enumerate(self.state.turn_history):
            start_time = turn.get("start_time")
            end_time = turn.get("end_time")
            if start_time is None or end_time is None:
                issues.append(f"turn_history[{idx}] missing_time")
            elif end_time < start_time:
                issues.append(f"turn_history[{idx}] negative_duration")
        if self.state.summary is None:
            issues.append("summary_missing")

        if issues:
            for issue in issues:
                self._add_warning(f"state_validation:{issue}")
            logger.warning("state_validation_failed issues=%s", issues)
        else:
            logger.debug("state_validation_ok")
        return issues


# Unit tests
if __name__ == "__main__":
    tracker = ConversationTracker()
    
    # Test initial state
    assert tracker.get_exchange_count() == 0
    assert len(tracker.get_map().claims) == 0
    
    # Test recording an exchange
    exchange = Exchange(
        index=0,
        interviewer_utterance="Tell me about your leadership experience",
        suggested_response=GeneratedResponse(
            bullets=["• Led team of 15 engineers"],
            full_response="I led a team of 15 engineers and scaled the organization from 5 to 50 people.",
            key_metrics=["15 engineers", "5 to 50"],
        ),
    )
    
    conv_map = tracker.record_exchange(exchange)
    assert tracker.get_exchange_count() == 1
    assert len(conv_map.metrics_used) == 2
    
    print("ConversationTracker tests passed!")
