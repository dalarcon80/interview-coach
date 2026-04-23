from __future__ import annotations

import os


def _flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def audio_pipeline_tracing_enabled() -> bool:
    return _flag_enabled("INTERVIEW_COACH_TRACE_AUDIO_PIPELINE", default=False)


def caption_event_tracing_enabled() -> bool:
    return _flag_enabled("INTERVIEW_COACH_TRACE_CAPTIONS", default=False)
