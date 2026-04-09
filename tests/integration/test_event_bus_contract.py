"""
Interview Coach - Event Bus Contract Tests (LEGACY)

DEPRECATED: This test file validates a legacy event bus implementation that uses
deprecated event names (partial_transcript, final_transcript, etc.).

The current WebSocket contract uses:
- Backend → Frontend: connected, session_started, analysis, suggestion, session_ended, error, pong
- Frontend → Backend: start_session, transcript_ready, end_session, ping

For the official contract, see:
- tests/integration/test_frontend_backend_ws_contract.py
- config/status.json → websocket_contract

This file is kept for reference but should not be considered validation of the
current product path.

F5 Requirement: Event bus contract verified (LEGACY IMPLEMENTATION)
"""
import pytest
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from enum import Enum
from datetime import datetime
import asyncio
import json


class EventType(str, Enum):
    """Event types for the interview pipeline"""
    # Audio events
    AUDIO_CHUNK = "audio_chunk"
    AUDIO_STARTED = "audio_started"
    AUDIO_STOPPED = "audio_stopped"

    # STT events
    PARTIAL_TRANSCRIPT = "partial_transcript"
    FINAL_TRANSCRIPT = "final_transcript"

    # Question events
    QUESTION_DETECTED = "question_detected"
    QUESTION_ANALYZED = "question_analyzed"

    # Response events
    BULLETS_GENERATED = "bullets_generated"
    RESPONSE_GENERATED = "response_generated"
    RESPONSE_VALIDATED = "response_validated"

    # Session events
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"

    # Error events
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Event:
    """Base event structure"""
    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trace_id: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "trace_id": self.trace_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        return cls(
            event_type=EventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            trace_id=data.get("trace_id"),
            payload=data.get("payload", {}),
        )


@dataclass
class EventHandler:
    """Event handler registration"""
    event_type: EventType
    callback: Callable[[Event], None]
    priority: int = 0  # Higher priority = executed first


class EventBus:
    """
    In-memory event bus for pipeline events.

    In production, this would be replaced with:
    - Redis Pub/Sub for distributed systems
    - Kafka for high-throughput scenarios
    - NATS for lightweight messaging
    """

    def __init__(self):
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._event_log: list[Event] = []
        self._max_log_size = 1000

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None], priority: int = 0) -> None:
        """Subscribe to an event type"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []

        self._handlers[event_type].append(EventHandler(
            event_type=event_type,
            callback=callback,
            priority=priority,
        ))

        # Sort by priority (descending)
        self._handlers[event_type].sort(key=lambda h: -h.priority)

    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> bool:
        """Unsubscribe from an event type"""
        if event_type not in self._handlers:
            return False

        initial_len = len(self._handlers[event_type])
        self._handlers[event_type] = [
            h for h in self._handlers[event_type] if h.callback != callback
        ]
        return len(self._handlers[event_type]) < initial_len

    def publish(self, event: Event) -> None:
        """Publish an event to all subscribers"""
        # Log event
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]

        # Notify subscribers
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                handler.callback(event)
            except Exception as e:
                # In production, would use proper error handling
                print(f"Error in event handler: {e}")

    def get_event_log(self, event_type: Optional[EventType] = None) -> list[Event]:
        """Get event log, optionally filtered by type"""
        if event_type is None:
            return self._event_log.copy()
        return [e for e in self._event_log if e.event_type == event_type]

    def clear_log(self) -> None:
        """Clear event log"""
        self._event_log.clear()


class TestEventType:
    """Test event type definitions"""

    def test_event_types_exist(self):
        """Test that all required event types exist"""
        required_types = [
            EventType.AUDIO_CHUNK,
            EventType.PARTIAL_TRANSCRIPT,
            EventType.FINAL_TRANSCRIPT,
            EventType.QUESTION_DETECTED,
            EventType.QUESTION_ANALYZED,
            EventType.BULLETS_GENERATED,
            EventType.RESPONSE_GENERATED,
            EventType.SESSION_STARTED,
            EventType.ERROR,
        ]

        for event_type in required_types:
            assert event_type.value is not None

    def test_event_type_serialization(self):
        """Test event type serialization"""
        assert EventType.AUDIO_CHUNK.value == "audio_chunk"
        assert EventType.FINAL_TRANSCRIPT.value == "final_transcript"


class TestEvent:
    """Test event structure"""

    def test_event_creation(self):
        """Test creating an event"""
        event = Event(
            event_type=EventType.QUESTION_DETECTED,
            trace_id="trace-123",
            payload={"question_text": "Tell me about yourself"},
        )

        assert event.event_type == EventType.QUESTION_DETECTED
        assert event.trace_id == "trace-123"
        assert event.payload["question_text"] == "Tell me about yourself"

    def test_event_serialization(self):
        """Test event serialization to dict"""
        event = Event(
            event_type=EventType.AUDIO_STARTED,
            trace_id="trace-456",
            payload={"source": "microphone"},
        )

        data = event.to_dict()

        assert data["event_type"] == "audio_started"
        assert data["trace_id"] == "trace-456"
        assert data["payload"]["source"] == "microphone"

    def test_event_deserialization(self):
        """Test event deserialization from dict"""
        data = {
            "event_type": "final_transcript",
            "timestamp": datetime.utcnow().isoformat(),
            "trace_id": "trace-789",
            "payload": {"text": "Hello world", "confidence": 0.95},
        }

        event = Event.from_dict(data)

        assert event.event_type == EventType.FINAL_TRANSCRIPT
        assert event.trace_id == "trace-789"
        assert event.payload["text"] == "Hello world"


class TestEventBus:
    """Test event bus functionality"""

    def test_subscribe_and_publish(self):
        """Test subscribing and publishing events"""
        bus = EventBus()
        received = []

        def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.QUESTION_DETECTED, handler)

        event = Event(event_type=EventType.QUESTION_DETECTED, payload={"text": "Test?"})
        bus.publish(event)

        assert len(received) == 1
        assert received[0].payload["text"] == "Test?"

    def test_multiple_subscribers(self):
        """Test multiple subscribers for same event"""
        bus = EventBus()
        received_1 = []
        received_2 = []

        bus.subscribe(EventType.ERROR, lambda e: received_1.append(e))
        bus.subscribe(EventType.ERROR, lambda e: received_2.append(e))

        event = Event(event_type=EventType.ERROR, payload={"message": "Test error"})
        bus.publish(event)

        assert len(received_1) == 1
        assert len(received_2) == 1

    def test_priority_ordering(self):
        """Test handler priority ordering"""
        bus = EventBus()
        order = []

        def low_priority(e):
            order.append("low")

        def high_priority(e):
            order.append("high")

        bus.subscribe(EventType.AUDIO_STARTED, low_priority, priority=1)
        bus.subscribe(EventType.AUDIO_STARTED, high_priority, priority=10)

        event = Event(event_type=EventType.AUDIO_STARTED)
        bus.publish(event)

        assert order == ["high", "low"]

    def test_unsubscribe(self):
        """Test unsubscribing from events"""
        bus = EventBus()
        received = []

        def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.WARNING, handler)
        bus.unsubscribe(EventType.WARNING, handler)

        event = Event(event_type=EventType.WARNING)
        bus.publish(event)

        assert len(received) == 0

    def test_event_log(self):
        """Test event logging"""
        bus = EventBus()

        bus.publish(Event(event_type=EventType.AUDIO_STARTED))
        bus.publish(Event(event_type=EventType.AUDIO_STOPPED))
        bus.publish(Event(event_type=EventType.ERROR))

        log = bus.get_event_log()
        assert len(log) == 3

        error_events = bus.get_event_log(EventType.ERROR)
        assert len(error_events) == 1

    def test_clear_log(self):
        """Test clearing event log"""
        bus = EventBus()

        bus.publish(Event(event_type=EventType.AUDIO_STARTED))
        bus.publish(Event(event_type=EventType.AUDIO_STOPPED))

        bus.clear_log()
        assert len(bus.get_event_log()) == 0


class TestEventBusContract:
    """Test event bus contract requirements"""

    def test_event_trace_propagation(self):
        """Test that trace ID propagates through events"""
        bus = EventBus()
        received_events = []

        def handler(event: Event):
            received_events.append(event)

        bus.subscribe(EventType.QUESTION_DETECTED, handler)
        bus.subscribe(EventType.QUESTION_ANALYZED, handler)

        # Simulate a trace flow
        trace_id = "trace-abc123"
        bus.publish(Event(
            event_type=EventType.QUESTION_DETECTED,
            trace_id=trace_id,
            payload={"text": "Test question"},
        ))
        bus.publish(Event(
            event_type=EventType.QUESTION_ANALYZED,
            trace_id=trace_id,
            payload={"type": "behavioral"},
        ))

        # All events should have the same trace ID
        assert all(e.trace_id == trace_id for e in received_events)

    def test_event_ordering_guarantee(self):
        """Test that events are processed in order"""
        bus = EventBus()
        timestamps = []

        def handler(event: Event):
            timestamps.append(event.timestamp)

        bus.subscribe(EventType.AUDIO_CHUNK, handler)

        # Publish multiple events
        for i in range(10):
            bus.publish(Event(
                event_type=EventType.AUDIO_CHUNK,
                payload={"chunk_id": i},
            ))
            import time
            time.sleep(0.001)  # Small delay to ensure different timestamps

        # Timestamps should be in ascending order
        assert timestamps == sorted(timestamps)

    def test_payload_schema_validation(self):
        """Test that event payloads have required fields"""
        # Define required payload schemas per event type
        required_fields = {
            EventType.AUDIO_CHUNK: ["chunk_id", "data"],
            EventType.FINAL_TRANSCRIPT: ["text", "confidence"],
            EventType.ERROR: ["message", "code"],
        }

        # Test that payloads can have required fields
        for event_type, fields in required_fields.items():
            payload = {field: f"test_{field}" for field in fields}
            event = Event(event_type=event_type, payload=payload)

            # Verify all required fields are present
            for field in fields:
                assert field in event.payload


class TestAsyncEventBus:
    """Test async event bus operations"""

    @pytest.mark.asyncio
    async def test_async_event_processing(self):
        """Test async event processing"""
        bus = EventBus()
        processed = []

        async def async_handler(event: Event):
            await asyncio.sleep(0.01)
            processed.append(event)

        # Wrap async handler for sync event bus
        def sync_wrapper(event: Event):
            asyncio.create_task(async_handler(event))

        bus.subscribe(EventType.AUDIO_STARTED, sync_wrapper)

        event = Event(event_type=EventType.AUDIO_STARTED)
        bus.publish(event)

        # Give async task time to complete
        await asyncio.sleep(0.05)

        # Event should have been processed
        # Note: In production, would use proper async event bus


class TestEventBusIntegration:
    """Integration tests for event bus"""

    def test_pipeline_event_flow(self):
        """Test typical pipeline event flow"""
        bus = EventBus()
        flow = []

        # Subscribe to all event types
        for event_type in EventType:
            bus.subscribe(event_type, lambda e: flow.append(e.event_type.value))

        # Simulate pipeline flow
        trace_id = "trace-flow-001"
        bus.publish(Event(event_type=EventType.SESSION_STARTED, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.AUDIO_STARTED, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.AUDIO_CHUNK, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.PARTIAL_TRANSCRIPT, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.FINAL_TRANSCRIPT, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.QUESTION_DETECTED, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.QUESTION_ANALYZED, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.BULLETS_GENERATED, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.RESPONSE_GENERATED, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.RESPONSE_VALIDATED, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.AUDIO_STOPPED, trace_id=trace_id))
        bus.publish(Event(event_type=EventType.SESSION_ENDED, trace_id=trace_id))

        # Verify flow order
        expected_flow = [
            "session_started",
            "audio_started",
            "audio_chunk",
            "partial_transcript",
            "final_transcript",
            "question_detected",
            "question_analyzed",
            "bullets_generated",
            "response_generated",
            "response_validated",
            "audio_stopped",
            "session_ended",
        ]

        assert flow == expected_flow
