//! Audio Capture Module
//!
//! Platform-specific implementations for audio capture.
//!
//! V1 (Current):
//! - macOS: ScreenCaptureKit for system audio + cpal for microphone
//!
//! V1.5 (Planned):
//! - Windows: WASAPI loopback
//! - Linux: PipeWire

pub mod mic_capture;
pub mod permissions;
pub mod router;
pub mod types;

// macOS-specific modules (only compile on macOS)
#[cfg(target_os = "macos")]
pub mod macos_capture;

// Windows-specific modules (only compile on Windows)
#[cfg(target_os = "windows")]
pub mod windows_capture;

// Linux-specific modules (only compile on Linux)
#[cfg(target_os = "linux")]
pub mod linux_capture;

use serde::{Deserialize, Serialize};

/// Audio capture trait - platform implementations must conform
pub trait AudioCapture {
    /// Start capturing audio
    fn start(&mut self) -> Result<(), AudioError>;

    /// Stop capturing audio
    fn stop(&mut self) -> Result<(), AudioError>;

    /// Check if capture is active
    fn is_capturing(&self) -> bool;
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum AudioError {
    PermissionDenied,
    DeviceUnavailable,
    PlatformNotSupported,
    InternalError(String),
}

impl std::fmt::Display for AudioError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AudioError::PermissionDenied => write!(f, "Audio permission denied"),
            AudioError::DeviceUnavailable => write!(f, "Audio device unavailable"),
            AudioError::PlatformNotSupported => write!(f, "Platform not supported in V1"),
            AudioError::InternalError(msg) => write!(f, "Internal error: {}", msg),
        }
    }
}

impl std::error::Error for AudioError {}

/// Platform support status
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlatformSupport {
    pub os: String,
    pub supported: bool,
    pub message: String,
}

/// Get platform support status for audio capture
pub fn get_platform_support() -> PlatformSupport {
    #[cfg(target_os = "macos")]
    {
        PlatformSupport {
            os: "macOS".to_string(),
            supported: true,
            message: "System audio and microphone capture supported via ScreenCaptureKit"
                .to_string(),
        }
    }

    #[cfg(target_os = "windows")]
    {
        PlatformSupport {
            os: "Windows".to_string(),
            supported: true,
            message: "System audio capture via WASAPI loopback (V1.5 stub ready). Microphone capture supported.".to_string(),
        }
    }

    #[cfg(target_os = "linux")]
    {
        PlatformSupport {
            os: "Linux".to_string(),
            supported: true,
            message:
                "System audio capture via PipeWire (V1.5 stub ready). Microphone capture supported."
                    .to_string(),
        }
    }

    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    {
        PlatformSupport {
            os: "Unknown".to_string(),
            supported: false,
            message: "Unsupported platform".to_string(),
        }
    }
}

pub use mic_capture::{default_mic_device_name, list_mic_devices, MicrophoneCapture};
pub use permissions::{
    all_permissions_granted, check_permission, request_permission, PermissionStatus, PermissionType,
};
/// Re-export commonly used types
pub use types::{AudioConfig, AudioFrame, AudioSource};
