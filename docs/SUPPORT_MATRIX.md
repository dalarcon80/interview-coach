# Interview Coach — Support Matrix

Truth labels: **functional**, **partial**, **stub**, **deprecated**.

## Canonical validation target
- **Canonical product target**: `tauri-desktop`
- **Forbidden validation targets**: `localhost:3000`, `web-preview-as-product`

## Platform truth

| Platform | Tauri Desktop | Backend | Live Audio Path | Notes |
|---|---|---|---|---|
| macOS Apple Silicon | **partial** | **functional** | **partial** | Primary target; canonical product path still not closed |
| Linux | **stub** | **functional** | **stub** | Not current closure target |
| Windows | **stub** | **functional** | **stub** | Not current closure target |

## What works today
- backend API and WebSocket core
- manual/prep coaching
- interview context persistence
- backend live STT runtime at backend scope

## What does not work yet
- live desktop session end-to-end on the canonical product path
- real system-audio capture wired into the canonical Tauri live flow (primary path)
- real microphone capture wired into the Tauri live flow (secondary/optional)
- session replay/history
- end-to-end latency truth

## Practical rule
If a test or demo does not go through the Tauri desktop path, it does not count as product-live closure.
