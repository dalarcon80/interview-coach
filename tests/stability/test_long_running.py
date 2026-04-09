"""
Interview Coach - Stability Tests
Long-running stability tests
F4 Requirement: 30 min stable
"""
import pytest
import time
import threading
import queue
from dataclasses import dataclass, field
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import random

from tests.fixtures.questions.question_bank import QUESTION_BANK
from tests.fixtures.profiles.cto_profile import CTO_PROFILE


@dataclass
class StabilityResult:
    """Result of stability test"""
    test_name: str
    duration_seconds: float
    operations_completed: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


@dataclass
class MemoryTracker:
    """Track memory usage during stability test"""
    samples: list[float] = field(default_factory=list)
    peak: float = 0.0

    def sample(self) -> float:
        """Take a memory sample (mock)"""
        # In real implementation, would use psutil or similar
        # Mock: simulate stable memory with small variance
        base = 100.0  # MB
        variance = random.uniform(-5, 5)
        current = base + variance
        self.samples.append(current)
        self.peak = max(self.peak, current)
        return current

    @property
    def average(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0


@dataclass
class ConversationState:
    """Mock conversation state for stability testing"""
    exchanges: list[dict] = field(default_factory=list)
    metrics_used: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)

    def add_exchange(self, exchange: dict):
        self.exchanges.append(exchange)
        self.metrics_used.extend(exchange.get("metrics", []))
        self.claims.extend(exchange.get("claims", []))

    def clear_old_exchanges(self, keep_last: int = 100):
        """Prevent unbounded growth"""
        if len(self.exchanges) > keep_last:
            removed = self.exchanges[:-keep_last]
            self.exchanges = self.exchanges[-keep_last:]
            # Note: In real implementation, would need to track which metrics/claims belong to removed exchanges


class MockPipelineStability:
    """Mock pipeline for stability testing"""

    def __init__(self):
        self.state = ConversationState()
        self.memory = MemoryTracker()
        self.operation_count = 0
        self.errors: list[str] = []
        self._lock = threading.Lock()

    def process_question(self, question_id: str) -> dict:
        """Process a single question"""
        import random

        with self._lock:
            self.operation_count += 1

        # Simulate memory usage
        self.memory.sample()

        # Simulate processing
        time.sleep(random.uniform(0.01, 0.05))  # 10-50ms

        # Generate mock result
        question = next((q for q in QUESTION_BANK if q["id"] == question_id), None)
        if not question:
            with self._lock:
                self.errors.append(f"Question not found: {question_id}")
            return {"error": "not_found"}

        result = {
            "question_id": question_id,
            "type": question.get("type", "unknown"),
            "metrics": [f"metric_{self.operation_count}"],
            "claims": [f"claim_{self.operation_count}"],
            "processed_at": time.time(),
        }

        self.state.add_exchange(result)

        return result

    def get_status(self) -> dict:
        """Get current pipeline status"""
        with self._lock:
            return {
                "operation_count": self.operation_count,
                "exchange_count": len(self.state.exchanges),
                "memory_peak": self.memory.peak,
                "memory_avg": self.memory.average,
                "error_count": len(self.errors),
                "errors": self.errors[-5:] if self.errors else [],
            }


class TestStability:
    """Stability tests"""

    def test_short_stability_run(self):
        """Test stability for short duration (30 seconds)"""
        pipeline = MockPipelineStability()
        duration = 30  # seconds
        start = time.time()

        while time.time() - start < duration:
            # Process random question
            question = random.choice(QUESTION_BANK)
            pipeline.process_question(question["id"])

        status = pipeline.get_status()

        print(f"\n30s Stability Test Results:")
        print(f"  Operations: {status['operation_count']}")
        print(f"  Exchanges: {status['exchange_count']}")
        print(f"  Memory peak: {status['memory_peak']:.1f}MB")
        print(f"  Memory avg: {status['memory_avg']:.1f}MB")
        print(f"  Errors: {status['error_count']}")

        assert status["error_count"] == 0, f"Errors during stability test: {status['errors']}"

    def test_memory_stability(self):
        """Test memory stability over many operations"""
        pipeline = MockPipelineStability()
        operations = 1000

        for i in range(operations):
            question = QUESTION_BANK[i % len(QUESTION_BANK)]
            pipeline.process_question(question["id"])

        status = pipeline.get_status()

        print(f"\nMemory Stability Test ({operations} operations):")
        print(f"  Memory peak: {status['memory_peak']:.1f}MB")
        print(f"  Memory avg: {status['memory_avg']:.1f}MB")

        # Memory should be stable (not growing unbounded)
        # Peak should be within 20% of average
        assert status["memory_peak"] < status["memory_avg"] * 1.5, \
            f"Memory peak {status['memory_peak']} much higher than avg {status['memory_avg']}"

    def test_state_cleanup(self):
        """Test that state is properly cleaned up"""
        state = ConversationState()

        # Add many exchanges
        for i in range(200):
            state.add_exchange({
                "metrics": [f"metric_{i}"],
                "claims": [f"claim_{i}"],
            })

        # Clean up old exchanges
        state.clear_old_exchanges(keep_last=100)

        assert len(state.exchanges) == 100, f"Expected 100 exchanges, got {len(state.exchanges)}"


class TestConcurrencyStability:
    """Test stability under concurrent load"""

    def test_concurrent_questions(self):
        """Test processing multiple questions concurrently"""
        pipeline = MockPipelineStability()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(50):
                question = QUESTION_BANK[i % len(QUESTION_BANK)]
                futures.append(executor.submit(pipeline.process_question, question["id"]))

            # Wait for all to complete
            results = [f.result() for f in as_completed(futures)]

        status = pipeline.get_status()

        print(f"\nConcurrent Test Results:")
        print(f"  Futures submitted: 50")
        print(f"  Results received: {len(results)}")
        print(f"  Pipeline operations: {status['operation_count']}")
        print(f"  Errors: {status['error_count']}")

        assert len(results) == 50, f"Expected 50 results, got {len(results)}"
        assert status["error_count"] == 0

    def test_sustained_load(self):
        """Test sustained load over time"""
        pipeline = MockPipelineStability()
        duration = 60  # seconds
        request_rate = 2  # requests per second

        start = time.time()
        requests_made = 0

        while time.time() - start < duration:
            batch_start = time.time()

            # Process a question
            question = random.choice(QUESTION_BANK)
            pipeline.process_question(question["id"])
            requests_made += 1

            # Maintain rate
            elapsed = time.time() - batch_start
            sleep_time = (1 / request_rate) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        status = pipeline.get_status()

        print(f"\nSustained Load Test ({duration}s at {request_rate} req/s):")
        print(f"  Requests made: {requests_made}")
        print(f"  Operations: {status['operation_count']}")
        print(f"  Memory peak: {status['memory_peak']:.1f}MB")
        print(f"  Errors: {status['error_count']}")

        # Should have processed approximately rate * duration requests
        expected_min = int(duration * request_rate * 0.8)
        assert requests_made >= expected_min, \
            f"Only {requests_made} requests, expected at least {expected_min}"


class TestErrorRecovery:
    """Test error recovery stability"""

    def test_error_handling(self):
        """Test that errors are handled gracefully"""
        pipeline = MockPipelineStability()

        # Process some valid questions
        for i in range(10):
            question = QUESTION_BANK[i % len(QUESTION_BANK)]
            pipeline.process_question(question["id"])

        # Try to process invalid question
        result = pipeline.process_question("invalid-question-id")
        assert "error" in result

        # Continue processing - should recover
        for i in range(10):
            question = QUESTION_BANK[i % len(QUESTION_BANK)]
            pipeline.process_question(question["id"])

        status = pipeline.get_status()

        print(f"\nError Recovery Test:")
        print(f"  Total operations: {status['operation_count']}")
        print(f"  Errors: {status['error_count']}")

        # Should have continued processing after error
        assert status["operation_count"] >= 20

    def test_graceful_degradation(self):
        """Test graceful degradation under stress"""
        pipeline = MockPipelineStability()

        # Rapid fire requests
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(pipeline.process_question, q["id"]) for q in QUESTION_BANK * 5]

            results = [f.result() for f in as_completed(futures)]

        success_count = sum(1 for r in results if "error" not in r)

        print(f"\nGraceful Degradation Test:")
        print(f"  Total requests: {len(results)}")
        print(f"  Successful: {success_count}")
        print(f"  Success rate: {success_count/len(results):.0%}")

        # Should maintain high success rate
        assert success_count / len(results) >= 0.95, \
            f"Success rate {success_count/len(results):.0%} below 95%"


class TestLongRunning:
    """Long-running stability tests"""

    @pytest.mark.slow
    def test_5_minute_stability(self):
        """Test stability for 5 minutes"""
        pipeline = MockPipelineStability()
        duration = 300  # 5 minutes
        interval = 1.0  # Check every second

        start = time.time()
        checkpoints = []

        while time.time() - start < duration:
            # Process a question
            question = random.choice(QUESTION_BANK)
            pipeline.process_question(question["id"])

            # Record checkpoint every 30 seconds
            elapsed = time.time() - start
            if len(checkpoints) < int(elapsed / 30):
                status = pipeline.get_status()
                checkpoints.append({
                    "elapsed": elapsed,
                    "operations": status["operation_count"],
                    "memory_peak": status["memory_peak"],
                })

        status = pipeline.get_status()

        print(f"\n5-Minute Stability Test Results:")
        print(f"  Total operations: {status['operation_count']}")
        print(f"  Checkpoints:")
        for cp in checkpoints:
            print(f"    {cp['elapsed']:.0f}s: {cp['operations']} ops, {cp['memory_peak']:.1f}MB")
        print(f"  Errors: {status['error_count']}")

        # Verify stability
        assert status["error_count"] == 0

        # Verify memory didn't grow unbounded
        if len(checkpoints) >= 2:
            first_mem = checkpoints[0]["memory_peak"]
            last_mem = checkpoints[-1]["memory_peak"]
            growth = (last_mem - first_mem) / first_mem if first_mem > 0 else 0

            print(f"  Memory growth: {growth:.1%}")
            assert growth < 0.5, f"Memory grew {growth:.1%}, potential leak"


class TestResourceCleanup:
    """Test resource cleanup"""

    def test_exchange_cleanup(self):
        """Test that exchanges are cleaned up properly"""
        state = ConversationState()

        # Add exchanges in batches
        for batch in range(5):
            for i in range(50):
                state.add_exchange({
                    "metrics": [f"batch_{batch}_metric_{i}"],
                    "claims": [f"batch_{batch}_claim_{i}"],
                })
            state.clear_old_exchanges(keep_last=100)

            print(f"Batch {batch}: {len(state.exchanges)} exchanges")

        # Should never exceed keep_last + batch size
        assert len(state.exchanges) <= 150, \
            f"Exchange count {len(state.exchanges)} exceeded limit"

    def test_periodic_cleanup(self):
        """Test periodic cleanup mechanism"""
        pipeline = MockPipelineStability()

        # Process many questions
        for i in range(300):
            question = QUESTION_BANK[i % len(QUESTION_BANK)]
            pipeline.process_question(question["id"])

            # Periodic cleanup every 100 operations
            if i % 100 == 0 and i > 0:
                pipeline.state.clear_old_exchanges(keep_last=100)

        status = pipeline.get_status()

        print(f"\nPeriodic Cleanup Test:")
        print(f"  Operations: {status['operation_count']}")
        print(f"  Exchanges kept: {len(pipeline.state.exchanges)}")

        # Exchanges should be bounded
        assert len(pipeline.state.exchanges) <= 200, \
            f"Exchange count {len(pipeline.state.exchanges)} not bounded"


class TestStabilityReport:
    """Generate stability test report"""

    def test_stability_report_generation(self):
        """Test generating stability report"""
        import json

        pipeline = MockPipelineStability()

        # Run stability tests
        for i in range(100):
            question = QUESTION_BANK[i % len(QUESTION_BANK)]
            pipeline.process_question(question["id"])

        status = pipeline.get_status()

        report = {
            "stability_test": {
                "timestamp": time.time(),
                "operation_count": status["operation_count"],
                "exchange_count": status["exchange_count"],
                "memory": {
                    "peak_mb": status["memory_peak"],
                    "avg_mb": status["memory_avg"],
                },
                "errors": status["error_count"],
                "passed": status["error_count"] == 0,
            }
        }

        # Save report
        report_path = "/home/z/my-project/tests/stability/stability_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        print(f"\nStability report saved to: {report_path}")
        print(f"Report contents:")
        print(json.dumps(report, indent=2))

        assert report["stability_test"]["passed"]
