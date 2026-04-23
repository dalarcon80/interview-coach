# ADR-002 — STT: mantener Deepgram primary + Whisper local fallback

- **Status:** Accepted
- **Date:** 2026-04-22
- **Deciders:** architect, product owner

## Contexto

El repo ya tiene dos adapters STT:

- `python-core/adapters/stt_adapter.py::DeepgramSTTAdapter` — primary actual, nova-3 streaming.
- `python-core/adapters/stt_adapter.py::WhisperLocalSTTAdapter` — local CPU int8 con faster-whisper.

El síntoma reportado por el owner es: "la respuesta live no es buena; revisar si Deepgram sigue siendo lo correcto o cambiar a otro proveedor (AssemblyAI / Gladia / Speechmatics / OpenAI Realtime)."

La auditoría demostró que el síntoma **no** es causado por el STT:

- El blocker real es el desktop audio bridge (HR / `current_blocker` en `status.json`): el audio de Zoom/Meet no llega consistentemente a la pipeline de STT en todos los macs.
- La fragilidad de respuesta live está causada por CR-4 (brain/emit acoplados), CR-5 (historia en memoria) y CR-7 (silencio por parches), no por el proveedor STT.

## Decisión

Mantener **Deepgram Nova-3** como primary y **Whisper local** como fallback. No cambiar proveedor. Incorporar un `stt/router.py` con health checks + failover automático.

## Justificación (evidencia)

| Criterio | Deepgram Nova-3 | Whisper local (int8 CPU) | Ganador |
|---|---|---|---|
| Latencia streaming p95 | ~250–450 ms | 1–3 s | Deepgram |
| Partials útiles | Nativos | Batched | Deepgram |
| End-of-turn event (`UtteranceEnd`) | Sí | No | Deepgram |
| Diarization | Sí (nova-3) | Parcial | Deepgram |
| Mezcla ES+EN | Bien (probado en código actual) | Aceptable | Deepgram |
| Costo | ~$0.0043/min | $0 | Whisper |
| Offline | No | Sí | Whisper |
| Replay batch | Requiere API call | Ejecuta en CPU | Whisper |
| Bridge desktop es el blocker | Aplica igual | Aplica igual | Empate — no diferencia |

**Conclusión operativa**: cambiar proveedor STT no resuelve ninguno de los síntomas reales. El costo de migración (testing, latencia caps de nuevo proveedor, integración de endpointing distinto) superaría al beneficio marginal.

## Cuándo reabrir esta decisión

Reabrir sólo si se cumple **al menos uno** de los siguientes:

1. Deepgram cambia su precio a >2× actual.
2. Deepgram tiene un outage ≥30 minutos dos veces en un mismo trimestre.
3. Aparece un proveedor con **end-of-turn semántico nativo** (no basado solo en silencio), ej. OpenAI Realtime con VAD mejorado, y los tests comparativos muestran ≥20% de mejora en métricas de timing (`ic_emit_prematures_total`).
4. Los tests bilingües muestran WER >15% más alto que un competidor en ES+EN mezclado.

## Estrategia de failover

```
stt/router.py
  primary:    DeepgramSTTAdapter
  secondary:  WhisperLocalSTTAdapter  (lazy-loaded on first failover)
  policy:
    - If primary.connect() times out >3s -> secondary
    - If primary.stream emits >5 consecutive errors within 30s -> secondary
    - If primary recovers (health probe every 60s), migrate back
  health_endpoint: /health/stt exposes {provider, last_success_at, error_count}
```

## Implementación

Ver `TARGET_ARCHITECTURE.md` §4.2 (`stt/` módulo) e `IMPLEMENTATION_PLAN.md` F4 + F5.

## Rollback

No hay rollback necesario: esta ADR mantiene el status quo. El ADR está documentado para prevenir que cambios "por intuición" toquen el proveedor.

## Benchmarks futuros

Cuando se reabra (ver criterios), ejecutar `scripts/stt_benchmark.py` (a crear en F5 si se requiere) contra:

- Deepgram Nova-3 / Nova-2 (regression)
- AssemblyAI Universal-Streaming
- Gladia
- Speechmatics Enhanced
- OpenAI `gpt-4o-realtime-transcribe`

Criterios medibles:
- WER global y WER en ES/EN mezcla.
- Latencia p50 y p95 streaming.
- Estabilidad del evento end-of-turn.
- Costo por minuto.
- Tamaño del payload de eventos.

## Referencias

- `docs/audit/AUDIT_REPORT.md` §1 CR-5 y CR-7
- `docs/audit/TARGET_ARCHITECTURE.md` §4.2
- `config/providers.yaml`
- `python-core/adapters/stt_adapter.py` (existente)
