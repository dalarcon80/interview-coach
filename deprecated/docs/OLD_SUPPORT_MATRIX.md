# Interview Coach - Platform Support Matrix

Truth labels used in this document: **functional**, **partial**, **stub**.

## Platform truth (R1-R5 aligned)

| Platform | Web UI | Backend | Audio Capture | Desktop App |
|----------|--------|---------|---------------|-------------|
| macOS (Apple Silicon) | **functional** | **functional** | **partial** | **partial** |
| Linux | **functional** | **functional** | **stub** | **stub** |
| Windows | **functional** | **functional** | **stub** | **stub** |

## Tiering

### Tier 1: macOS (primary target)
- **Web UI**: functional
- **Backend**: functional
- **Audio capture**: partial
  - Real ScreenCaptureKit capture path exists.
  - IPC bridge integration is still pending.
- **Desktop app (Tauri)**: partial
- **PostgreSQL + pgvector**: functional via Docker Desktop

### Tier 2: Linux / Windows
- **Web UI**: functional
- **Backend**: functional
- **Audio capture**: stub (V1.5 target)
- **Desktop app**: stub for product use in the current phase
- **PostgreSQL + pgvector**: functional via Docker (native PostgreSQL optional on Linux)

## Audio capture status detail

| Platform | Technology | Status | Notes |
|----------|------------|--------|-------|
| macOS | ScreenCaptureKit | **partial** | Native capture path exists; end-to-end desktop wiring still incomplete (IPC bridge pending). |
| Windows | WASAPI | **stub** | Planned for V1.5. |
| Linux | PipeWire | **stub** | Planned for V1.5. |

## Practical guidance

- For reliable current usage across all platforms, run **web preview + backend**.
- Treat desktop audio as **macOS partial** and **Linux/Windows stub**.

## Getting started by platform

### macOS
```bash
bash scripts/bootstrap_macos.sh
bash scripts/doctor_macos.sh
cd python-core && python main.py  # Terminal 1
bun dev                           # Terminal 2
```

### Linux
```bash
bash scripts/bootstrap_linux.sh
bash scripts/doctor_linux.sh
cd python-core && python main.py  # Terminal 1
bun dev                           # Terminal 2
```

### Windows (recommended: WSL2)
```powershell
wsl
bash scripts/bootstrap_linux.sh
bash scripts/doctor_linux.sh
cd python-core && python main.py
bun dev
```
