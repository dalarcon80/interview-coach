"""
Interview Coach - Latency Tracking
"""
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from typing import Optional
from dataclasses import dataclass
import time

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class LatencyMetric:
    """A single latency measurement"""
    step_name: str
    duration_ms: float
    timestamp: str


class LatencyTracker:
    """
    Track latency metrics for pipeline steps.
    
    Measures:
    - P50, P95, P99 latency per step
    - Total pipeline latency
    """
    
    def __init__(self, max_samples: int = 1000):
        self._metrics: dict[str, list[float]] = {}
        self._max_samples = max_samples
        self._start_times: dict[str, float] = {}
    
    def start_timer(self, step_name: str) -> str:
        """Start a timer for a step"""
        timer_id = f"{step_name}_{time.time_ns()}"
        self._start_times[timer_id] = time.time()
        return timer_id
    
    def stop_timer(self, timer_id: str) -> Optional[float]:
        """Stop a timer and record the duration"""
        if timer_id not in self._start_times:
            return None
        
        start_time = self._start_times.pop(timer_id)
        duration_ms = (time.time() - start_time) * 1000
        
        step_name = timer_id.rsplit("_", 1)[0]
        self.record(step_name, duration_ms)
        
        return duration_ms
    
    def record(self, step_name: str, duration_ms: float) -> None:
        """Record a latency measurement"""
        if step_name not in self._metrics:
            self._metrics[step_name] = []
        
        if len(self._metrics[step_name]) >= self._max_samples:
            self._metrics[step_name] = self._metrics[step_name][-self._max_samples + 1:]
        
        self._metrics[step_name].append(duration_ms)
    
    def get_stats(self, step_name: str) -> dict:
        """Get statistics for a step"""
        values = self._metrics.get(step_name, [])
        
        if not values:
            return {
                "count": 0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
            }
        
        sorted_values = sorted(values)
        count = len(sorted_values)
        
        def percentile(p: float) -> float:
            idx = int(count * p)
            idx = min(idx, count - 1)
            return sorted_values[idx]
        
        return {
            "count": count,
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "mean": sum(sorted_values) / count,
        }
    
    def get_all_stats(self) -> dict:
        """Get statistics for all steps"""
        return {name: self.get_stats(name) for name in self._metrics}


class LatencyContext:
    """Context manager for timing a code block"""
    
    def __init__(self, tracker: LatencyTracker, step_name: str):
        self.tracker = tracker
        self.step_name = step_name
        self.timer_id: Optional[str] = None
        self.duration_ms: Optional[float] = None
    
    def __enter__(self):
        self.timer_id = self.tracker.start_timer(self.step_name)
        return self
    
    def __exit__(self, *args):
        if self.timer_id:
            self.duration_ms = self.tracker.stop_timer(self.timer_id)
    
    async def __aenter__(self):
        self.timer_id = self.tracker.start_timer(self.step_name)
        return self
    
    async def __aexit__(self, *args):
        if self.timer_id:
            self.duration_ms = self.tracker.stop_timer(self.timer_id)


# Global tracker
_tracker: Optional[LatencyTracker] = None


class PipelineLatency:
    """
    Tracks pipeline latency with stage-level granularity.
    
    Supports concurrent stages (some can run in parallel).
    Tracks first_bullet_time and full_response_time per exchange.
    Provides session-level summary statistics.
    
    Latency targets:
    - Bullets visible in < 8 seconds (8000ms)
    - Full response in < 15 seconds (15000ms)
    """
    
    # Target thresholds in milliseconds
    BULLETS_TARGET_MS = 8000
    FULL_RESPONSE_TARGET_MS = 15000
    
    def __init__(self):
        # Stage timings: stage_name -> list of durations in ms
        self._stage_timings: dict[str, list[float]] = {}
        # Active stage start times: stage_name -> start_time (perf_counter)
        self._active_stages: dict[str, float] = {}
        # Exchange-level metrics
        self._first_bullet_times: list[float] = []
        self._full_response_times: list[float] = []
        # Overall exchange start time
        self._exchange_start_time: Optional[float] = None
    
    def start_exchange(self) -> None:
        """Mark the start of a new exchange"""
        self._exchange_start_time = time.perf_counter()
    
    def start_stage(self, stage_name: str) -> None:
        """Start timing a pipeline stage"""
        self._active_stages[stage_name] = time.perf_counter()
    
    def end_stage(self, stage_name: str) -> Optional[float]:
        """End timing a pipeline stage and return duration in ms"""
        if stage_name not in self._active_stages:
            return None
        
        start_time = self._active_stages.pop(stage_name)
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        if stage_name not in self._stage_timings:
            self._stage_timings[stage_name] = []
        self._stage_timings[stage_name].append(duration_ms)
        
        return duration_ms
    
    def record_first_bullet(self, latency_ms: float) -> None:
        """Record time to first bullet emission"""
        self._first_bullet_times.append(latency_ms)
    
    def record_full_response(self, latency_ms: float) -> None:
        """Record time to full response emission"""
        self._full_response_times.append(latency_ms)
    
    def get_stage_timing(self, stage_name: str) -> Optional[float]:
        """Get the most recent timing for a stage"""
        timings = self._stage_timings.get(stage_name, [])
        return timings[-1] if timings else None
    
    def get_all_stage_timings(self) -> dict[str, float]:
        """Get the most recent timing for each stage"""
        return {
            name: timings[-1] 
            for name, timings in self._stage_timings.items() 
            if timings
        }
    
    def get_summary(self) -> dict:
        """Get session-level latency summary"""
        def calc_stats(timings: list[float]) -> dict:
            if not timings:
                return {"count": 0, "min": 0, "max": 0, "avg": 0}
            return {
                "count": len(timings),
                "min": min(timings),
                "max": max(timings),
                "avg": sum(timings) / len(timings),
            }
        
        # Calculate target achievement rates
        bullets_under_8s = sum(1 for t in self._first_bullet_times if t < self.BULLETS_TARGET_MS)
        full_under_15s = sum(1 for t in self._full_response_times if t < self.FULL_RESPONSE_TARGET_MS)
        
        bullets_pct = (bullets_under_8s / len(self._first_bullet_times) * 100) if self._first_bullet_times else 0
        full_pct = (full_under_15s / len(self._full_response_times) * 100) if self._full_response_times else 0
        
        # Stage statistics
        stage_stats = {}
        for stage, timings in self._stage_timings.items():
            stage_stats[stage] = calc_stats(timings)
        
        return {
            "stages": stage_stats,
            "first_bullet": calc_stats(self._first_bullet_times),
            "full_response": calc_stats(self._full_response_times),
            "targets": {
                "bullets_under_8s_pct": bullets_pct,
                "full_under_15s_pct": full_pct,
                "bullets_target_ms": self.BULLETS_TARGET_MS,
                "full_target_ms": self.FULL_RESPONSE_TARGET_MS,
            },
            "total_exchanges": len(self._full_response_times),
        }
    
    def get_current_stage_timings(self) -> dict[str, float]:
        """Get timing info for currently active stages"""
        current_time = time.perf_counter()
        return {
            name: (current_time - start_time) * 1000
            for name, start_time in self._active_stages.items()
        }
    
    def reset(self) -> None:
        """Reset all latency tracking"""
        self._stage_timings.clear()
        self._active_stages.clear()
        self._first_bullet_times.clear()
        self._full_response_times.clear()
        self._exchange_start_time = None


def get_latency_tracker() -> LatencyTracker:
    """Get or create the global latency tracker"""
    global _tracker
    if _tracker is None:
        _tracker = LatencyTracker()
    return _tracker


def time_step(step_name: str) -> LatencyContext:
    """Create a context manager for timing a step"""
    return LatencyContext(get_latency_tracker(), step_name)
