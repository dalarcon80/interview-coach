"""Manual runtime validation for Deepgram-backed live STT websocket path.

L2-STT-05 validation script:
- opens websocket session
- streams multiple audio_data messages
- measures first partial/final transcript latency
- reports stream lifecycle and provider errors observed from server events/logs

Usage:
  python scripts/validate_live_stt_runtime.py --ws-url ws://127.0.0.1:8000/ws/pipeline
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import time
from pathlib import Path
import wave
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError

import websockets


def _load_audio_bytes(audio_file: str | None) -> bytes:
    if not audio_file:
        # 2s synthetic PCM16 mono @16kHz (non-empty, speech-like tone burst)
        # to satisfy Deepgram realtime raw-audio framing expectations in
        # environments where no external file is provided.
        import math

        sample_rate = 16000
        duration_s = 2.0
        total_samples = int(sample_rate * duration_s)
        freq_hz = 440.0
        amplitude = 0.25 * 32767
        pcm = bytearray()
        for n in range(total_samples):
            value = int(amplitude * math.sin(2.0 * math.pi * freq_hz * (n / sample_rate)))
            pcm.extend(int(value).to_bytes(2, byteorder="little", signed=True))
        return bytes(pcm)

    path = Path(audio_file)
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as wav:
            return wav.readframes(wav.getnframes())
    return path.read_bytes()


def _chunk_audio(audio_bytes: bytes, chunk_size: int = 32000) -> list[bytes]:
    if not audio_bytes:
        return []
    return [audio_bytes[i:i + chunk_size] for i in range(0, len(audio_bytes), chunk_size)]


async def run_validation(ws_url: str, timeout_s: float = 15.0, audio_file: str | None = None) -> int:
    started_at = time.perf_counter()
    first_partial_latency_ms = None
    first_final_latency_ms = None
    first_non_error_final_latency_ms = None
    provider_errors: list[str] = []
    transcript_events: list[dict] = []
    stream_open_observed = False
    stream_close_observed = False
    analysis_observed = False
    suggestion_observed = False
    suggestion_timestamp_ms = None
    analysis_timestamp_ms = None
    transcript_timestamp_ms = None
    finalize_sent_ms = None
    close_stream_sent_ms = None
    keepalive_count = 0
    keepalive_observed = False
    teardown_timestamp_ms = None
    teardown_cancel_ms = None

    async with websockets.connect(ws_url) as ws:
        connected = json.loads(await ws.recv())
        if connected.get("type") != "connected":
            print(f"[validate_live_stt] Unexpected first event: {connected}")
            return 2

        await ws.send(json.dumps({
            "type": "start_session",
            "config": {
                "company_name": "Runtime Validation Co",
                "role_title": "Senior Engineer",
                "mode": "real",
            },
        }))

        session_started = json.loads(await ws.recv())
        if session_started.get("type") != "session_started":
            print(f"[validate_live_stt] Unexpected session event: {session_started}")
            return 2

        audio_bytes = _load_audio_bytes(audio_file)
        audio_chunks = _chunk_audio(audio_bytes)
        if not audio_chunks:
            print("[validate_live_stt] No audio chunks available")
            return 2

        print(f"audio_source={audio_file or 'synthetic'} total_audio_bytes={len(audio_bytes)} chunks={len(audio_chunks)}")
        for index, chunk in enumerate(audio_chunks, start=1):
            await ws.send(json.dumps({
                "type": "audio_data",
                "audio": base64.b64encode(chunk).decode("ascii"),
                "timestamp": index * 600,
                "sample_rate": 16000,
                "channels": 1,
                "source": "system",
            }))

        deadline = time.perf_counter() + timeout_s
        timed_out = False
        while time.perf_counter() < deadline:
            remaining = max(0.1, deadline - time.perf_counter())
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                timed_out = True
                break
            except (ConnectionClosedOK, ConnectionClosedError):
                break

            event = json.loads(raw)
            etype = event.get("type")

            if etype == "audio_received":
                stream_open_observed = True
            elif etype == "transcript":
                transcript_events.append(event)
                now_ms = int((time.perf_counter() - started_at) * 1000)
                if transcript_timestamp_ms is None:
                    transcript_timestamp_ms = now_ms
                if not event.get("is_final") and first_partial_latency_ms is None:
                    first_partial_latency_ms = now_ms
                if event.get("is_final") and first_final_latency_ms is None:
                    first_final_latency_ms = now_ms
                    if str(event.get("text", "")).startswith("[STT Error:"):
                        provider_errors.append(str(event.get("text")))
                if event.get("is_final") and not str(event.get("text", "")).startswith("[STT Error:"):
                    if first_non_error_final_latency_ms is None:
                        first_non_error_final_latency_ms = now_ms

                provider_metadata = event.get("provider_metadata") or {}
                if isinstance(provider_metadata, dict):
                    keepalive_count = max(keepalive_count, int(provider_metadata.get("keepalive_count", 0) or 0))
                    if keepalive_count > 0:
                        keepalive_observed = True
                    if finalize_sent_ms is None and provider_metadata.get("finalize_sent_ms") is not None:
                        finalize_sent_ms = int(provider_metadata.get("finalize_sent_ms"))
                    if close_stream_sent_ms is None and provider_metadata.get("close_stream_sent_ms") is not None:
                        close_stream_sent_ms = int(provider_metadata.get("close_stream_sent_ms"))
            elif etype == "error":
                provider_errors.append(str(event.get("message", "")))
            elif etype == "analysis":
                analysis_observed = True
                if analysis_timestamp_ms is None:
                    analysis_timestamp_ms = int((time.perf_counter() - started_at) * 1000)
            elif etype == "suggestion":
                if event.get("stage") == "full":
                    suggestion_observed = True
                    if suggestion_timestamp_ms is None:
                        suggestion_timestamp_ms = int((time.perf_counter() - started_at) * 1000)
                    break

        with contextlib.suppress(Exception):
            await ws.send(json.dumps({"type": "end_session"}))
            close_deadline = time.perf_counter() + 30.0
            while time.perf_counter() < close_deadline:
                remaining = max(0.1, close_deadline - time.perf_counter())
                try:
                    end_raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except (asyncio.TimeoutError, ConnectionClosedOK, ConnectionClosedError):
                    break
                end_event = json.loads(end_raw)
                if end_event.get("type") == "session_ended":
                    stream_close_observed = True
                    break

        if timed_out:
            print(f"validation_loop_timeout_s={timeout_s}")

    print("\n=== LIVE STT RUNTIME VALIDATION ===")
    print(f"ws_url={ws_url}")
    print(f"first_partial_latency_ms={first_partial_latency_ms}")
    print(f"first_final_latency_ms={first_final_latency_ms}")
    print(f"first_non_error_final_latency_ms={first_non_error_final_latency_ms}")
    print(f"transcript_event_count={len(transcript_events)}")
    print(f"provider_errors={len(provider_errors)}")
    for idx, err in enumerate(provider_errors, start=1):
        print(f"  provider_error[{idx}]={err}")
    print(f"analysis_observed={analysis_observed}")
    print(f"suggestion_observed={suggestion_observed}")
    print(f"stream_open_observed={stream_open_observed}")
    print(f"stream_close_observed={stream_close_observed}")
    print(f"keepalive_count={keepalive_count}")
    print(f"keepalive_observed={keepalive_observed}")
    print(f"finalize_sent_ms={finalize_sent_ms}")
    print(f"close_stream_sent_ms={close_stream_sent_ms}")
    print(f"transcript_timestamp_ms={transcript_timestamp_ms}")
    print(f"analysis_timestamp_ms={analysis_timestamp_ms}")
    print(f"suggestion_timestamp_ms={suggestion_timestamp_ms}")
    print(f"teardown_timestamp_ms={teardown_timestamp_ms}")
    print(f"teardown_cancel_ms={teardown_cancel_ms}")

    if first_final_latency_ms is None:
        print("RESULT=FAILED (no final transcript observed)")
        return 1
    if first_non_error_final_latency_ms is None:
        print("RESULT=FAILED (no non-error final transcript observed)")
        return 1
    if first_final_latency_ms < first_partial_latency_ms:
        print("RESULT=FAILED (final transcript arrived before partial)")
        return 1
    if not analysis_observed:
        print("RESULT=FAILED (analysis event not observed)")
        return 1
    if not suggestion_observed:
        print("RESULT=FAILED (suggestion event not observed)")
        return 1
    if finalize_sent_ms is None:
        print("RESULT=FAILED (finalize timestamp not observed in transcript metadata)")
        return 1
    if close_stream_sent_ms is not None and close_stream_sent_ms < finalize_sent_ms:
        print("RESULT=FAILED (close_stream occurred before finalize)")
        return 1
    if transcript_timestamp_ms is None or analysis_timestamp_ms is None or suggestion_timestamp_ms is None:
        print("RESULT=FAILED (timeline timestamps missing)")
        return 1
    if not (transcript_timestamp_ms <= analysis_timestamp_ms <= suggestion_timestamp_ms):
        print("RESULT=FAILED (ordering violated: transcript -> analysis -> suggestion)")
        return 1
    if not stream_open_observed:
        print("RESULT=FAILED (stream_open not observed)")
        return 1

    print("RESULT=PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate live Deepgram STT runtime path")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8000/ws/pipeline")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--audio-file", default=None)
    args = parser.parse_args()
    return asyncio.run(run_validation(ws_url=args.ws_url, timeout_s=args.timeout, audio_file=args.audio_file))


if __name__ == "__main__":
    raise SystemExit(main())
