"""
Interview Coach - Observability Setup
OpenTelemetry configuration for traces, metrics, and logs
"""
import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

# OTLP exporter is optional - only needed for production/external collectors
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    HAS_OTLP_EXPORTER = True
except ImportError:
    OTLPSpanExporter = None  # type: ignore
    HAS_OTLP_EXPORTER = False


_tracer_provider: Optional[TracerProvider] = None


def setup_telemetry(service_name: str = "interview-coach") -> TracerProvider:
    """
    Set up OpenTelemetry tracing.

    Configures:
    - OTLP exporter (if OTEL_EXPORTER_OTLP_ENDPOINT is set and package available)
    - Console exporter (for development)
    """
    global _tracer_provider

    if _tracer_provider is not None:
        return _tracer_provider

    # Create tracer provider
    _tracer_provider = TracerProvider(
        resource={
            "service.name": service_name,
            "service.version": "0.1.0",
        }
    )

    # OTLP exporter (for production/external collectors) - optional
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint and HAS_OTLP_EXPORTER and OTLPSpanExporter is not None:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        _tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # Console exporter (for development)
    if os.getenv("APP_ENV", "development") == "development":
        console_exporter = ConsoleSpanExporter()
        _tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))

    # Set global tracer provider
    trace.set_tracer_provider(_tracer_provider)

    return _tracer_provider


def get_tracer(name: str = __name__) -> trace.Tracer:
    """Get a tracer for the given module"""
    return trace.get_tracer(name)


class LatencyTracker:
    """Track latency metrics for pipeline steps"""

    def __init__(self):
        self._metrics: dict[str, list[float]] = {}

    def record(self, step_name: str, duration_ms: float):
        """Record a latency measurement"""
        if step_name not in self._metrics:
            self._metrics[step_name] = []
        self._metrics[step_name].append(duration_ms)

    def get_stats(self, step_name: str) -> dict:
        """Get statistics for a step"""
        values = self._metrics.get(step_name, [])
        if not values:
            return {"count": 0, "p50": 0, "p95": 0, "p99": 0}

        sorted_values = sorted(values)
        count = len(sorted_values)

        return {
            "count": count,
            "p50": sorted_values[int(count * 0.5)],
            "p95": sorted_values[int(count * 0.95)],
            "p99": sorted_values[int(count * 0.99)],
            "min": sorted_values[0],
            "max": sorted_values[-1],
        }

    def get_all_stats(self) -> dict[str, dict]:
        """Get statistics for all steps"""
        return {name: self.get_stats(name) for name in self._metrics}


# Global latency tracker
_latency_tracker: Optional[LatencyTracker] = None


def get_latency_tracker() -> LatencyTracker:
    """Get the global latency tracker"""
    global _latency_tracker
    if _latency_tracker is None:
        _latency_tracker = LatencyTracker()
    return _latency_tracker
