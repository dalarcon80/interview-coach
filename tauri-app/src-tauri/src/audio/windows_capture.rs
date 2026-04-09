//! Windows System Audio Capture
//!
//! Uses WASAPI loopback to capture system audio (what the interviewer says).
//! Planned for V1.5.
//!
//! # Implementation Plan (V1.5)
//! - Use WASAPI (Windows Audio Session API) with loopback mode
//! - Capture audio from default audio endpoint
//! - Support for both shared and exclusive mode
//!
//! # Requirements
//! - Windows 10+ (WASAPI available since Windows Vista)
//! - No special permissions needed for loopback capture
//!
//! # Example (V1.5)
//! ```ignore
//! let mut capture = WindowsSystemAudioCapture::new(Default::default());
//! capture.start()?;
//! // ... receive audio frames via callback
//! capture.stop()?;
//! ```

use crate::audio::types::AudioConfig;
use crate::audio::{AudioCapture, AudioError};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

/// Windows system audio capture using WASAPI loopback
///
/// This is a STUB for V1. Windows support is planned for V1.5.
#[cfg(target_os = "windows")]
pub struct WindowsSystemAudioCapture {
    config: AudioConfig,
    is_capturing: Arc<AtomicBool>,
}

#[cfg(target_os = "windows")]
impl WindowsSystemAudioCapture {
    pub fn new(config: AudioConfig) -> Self {
        Self {
            config,
            is_capturing: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Check if audio loopback is available
    /// On Windows, this should always be true for the default endpoint
    pub fn check_availability() -> Result<bool, AudioError> {
        // In V1.5, this would:
        // 1. Initialize COM
        // 2. Get default audio endpoint
        // 3. Check if loopback is supported
        Ok(true)
    }

    /// Get list of available audio endpoints
    pub fn get_endpoints() -> Result<Vec<String>, AudioError> {
        // In V1.5, this would enumerate audio endpoints using:
        // IMMDeviceEnumerator::EnumAudioEndpoints
        Ok(vec!["Default Audio Device".to_string()])
    }
}

#[cfg(target_os = "windows")]
impl AudioCapture for WindowsSystemAudioCapture {
    fn start(&mut self) -> Result<(), AudioError> {
        if self.is_capturing.load(Ordering::SeqCst) {
            return Ok(());
        }

        // V1.5 Implementation:
        // 1. Initialize COM (CoInitializeEx)
        // 2. Create IMMDeviceEnumerator
        // 3. Get default audio endpoint (eRender, eConsole)
        // 4. Activate IAudioClient
        // 5. Set format (16kHz mono PCM)
        // 6. Initialize with AUDCLNT_STREAMFLAGS_LOOPBACK
        // 7. Get IAudioCaptureClient
        // 8. Start capture

        self.is_capturing.store(true, Ordering::SeqCst);
        Ok(())
    }

    fn stop(&mut self) -> Result<(), AudioError> {
        self.is_capturing.store(false, Ordering::SeqCst);
        Ok(())
    }

    fn is_capturing(&self) -> bool {
        self.is_capturing.load(Ordering::SeqCst)
    }
}

/// Stub for non-Windows platforms
#[cfg(not(target_os = "windows"))]
pub struct WindowsSystemAudioCapture;

#[cfg(not(target_os = "windows"))]
impl WindowsSystemAudioCapture {
    pub fn new(_config: AudioConfig) -> Self {
        Self
    }

    /// Returns error on non-Windows platforms
    pub fn check_availability() -> Result<bool, AudioError> {
        Err(AudioError::PlatformNotSupported)
    }
}

#[cfg(target_os = "windows")]
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_capture_lifecycle() {
        let mut capture = WindowsSystemAudioCapture::new(AudioConfig::default());
        assert!(!capture.is_capturing());

        capture.start().expect("Should start");
        assert!(capture.is_capturing());

        capture.stop().expect("Should stop");
        assert!(!capture.is_capturing());
    }

    #[test]
    fn test_availability_check() {
        let available = WindowsSystemAudioCapture::check_availability();
        assert!(available.is_ok());
    }
}
