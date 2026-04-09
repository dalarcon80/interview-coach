//! macOS System Audio Capture
//!
//! Uses ScreenCaptureKit to capture system audio (what the interviewer says).
//! Requires Screen Recording permission on macOS 13+.
//!
//! Note: This module only compiles on macOS.
//!
//! ## IMPLEMENTATION STATUS (C5 Audit)
//!
//! **CURRENT STATE: PARTIAL IMPLEMENTATION**
//!
//! What works:
//! - Compiles on macOS
//! - ScreenCaptureKit stream setup (shareable content + filter + stream config)
//! - Real system-audio callback via SCStreamOutputType::Audio
//! - Audio normalization to 16kHz mono chunks through AudioRouter
//! - `start()` and `stop()` lifecycle management
//!
//! What doesn't work yet:
//! - IPC emission path is not wired in this module yet (frames are buffered)
//! - Permission probing remains best-effort and OS-dialog driven
//!
//! To complete:
//! 1. Wire buffered frames to IPC -> Python backend command path
//! 2. Add richer runtime diagnostics/metrics for dropped/invalid audio buffers

#[cfg(target_os = "macos")]
use crate::audio::router::AudioRouter;
#[cfg(target_os = "macos")]
use crate::audio::types::{AudioConfig, AudioFrame, AudioSource};
#[cfg(target_os = "macos")]
use crate::audio::{AudioCapture, AudioError};
#[cfg(target_os = "macos")]
use screencapturekit::prelude::{
    CMSampleBuffer, SCContentFilter, SCShareableContent, SCStream, SCStreamConfiguration,
    SCStreamOutputType,
};
#[cfg(target_os = "macos")]
use screencapturekit::stream::configuration::{AudioChannelCount, AudioSampleRate};
#[cfg(target_os = "macos")]
use std::sync::atomic::{AtomicBool, Ordering};
#[cfg(target_os = "macos")]
use std::sync::{Arc, Mutex};
#[cfg(target_os = "macos")]
use std::time::Instant;

#[cfg(target_os = "macos")]
type SCAudioCaptureConfiguration = SCStreamConfiguration;

/// Implementation status for macOS audio capture
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImplementationStatus {
    /// Partial - some components work
    Partial,
    /// Full - production ready
    Full,
}

/// Screen Recording permission state on macOS.
#[cfg(target_os = "macos")]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScreenRecordingPermissionState {
    /// Not yet determined (user has not explicitly granted/denied yet)
    Unknown,
    /// Permission explicitly granted
    Granted,
    /// Permission explicitly denied
    Denied,
    /// Permission restricted by parental controls/system policy
    Restricted,
}

#[cfg(target_os = "macos")]
struct CaptureCallbackContext {
    router: Mutex<AudioRouter>,
    frames: Mutex<Vec<AudioFrame>>,
    started_at: Instant,
}

#[cfg(target_os = "macos")]
impl CaptureCallbackContext {
    fn new(config: AudioConfig) -> Self {
        Self {
            router: Mutex::new(AudioRouter::new(config)),
            frames: Mutex::new(Vec::new()),
            started_at: Instant::now(),
        }
    }

    fn process_audio_sample(&self, sample: CMSampleBuffer) {
        let Some(format_description) = sample.format_description() else {
            return;
        };
        let input_rate = format_description
            .audio_sample_rate()
            .unwrap_or(16_000.0)
            .round() as u32;
        let channels = format_description.audio_channel_count().unwrap_or(1) as usize;
        let is_float = format_description.audio_is_float();

        let Some(audio_buffers) = sample.audio_buffer_list() else {
            return;
        };

        let mut mono_f32: Vec<f32> = Vec::new();
        for buffer in &audio_buffers {
            let data = buffer.data();
            if data.is_empty() {
                continue;
            }

            let mut decoded: Vec<f32> = if is_float {
                data.chunks_exact(4)
                    .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
                    .collect()
            } else {
                data.chunks_exact(2)
                    .map(|chunk| i16::from_le_bytes([chunk[0], chunk[1]]) as f32 / 32767.0)
                    .collect()
            };

            if channels > 1 {
                decoded = decoded
                    .chunks(channels)
                    .map(|frame| frame.iter().copied().sum::<f32>() / channels as f32)
                    .collect();
            }

            mono_f32.extend(decoded);
        }

        if mono_f32.is_empty() {
            return;
        }

        let normalized = crate::audio::router::normalize_to_16khz_mono(&mono_f32, input_rate);

        let mut router = match self.router.lock() {
            Ok(guard) => guard,
            Err(_) => return,
        };
        let mut frames = router.process(&normalized, AudioSource::SystemAudio);
        let elapsed_ms = self.started_at.elapsed().as_millis() as u64;
        for frame in &mut frames {
            frame.timestamp_ms = elapsed_ms;
        }

        if frames.is_empty() {
            return;
        }

        if let Ok(mut sink) = self.frames.lock() {
            sink.extend(frames);
        }
    }
}

/// macOS system audio capture using ScreenCaptureKit
///
/// **IMPLEMENTATION STATUS: Partial**
///
/// This module performs real ScreenCaptureKit stream setup and audio callback
/// processing. Audio is normalized to 16kHz mono and chunked into AudioFrame
/// instances using AudioRouter. Frame-to-IPC forwarding remains to be wired in
/// the command/application layer.
///
/// # Permissions
/// Requires Screen Recording permission. If denied, returns AudioError::PermissionDenied.
///
/// # Example
/// ```ignore
/// let mut capture = MacOSSystemAudioCapture::new(Default::default());
/// capture.start()?;
/// // ... collect normalized 16kHz mono frames via take_frames()
/// capture.stop()?;
/// ```
#[cfg(target_os = "macos")]
pub struct MacOSSystemAudioCapture {
    config: AudioConfig,
    is_capturing: Arc<AtomicBool>,
    is_paused: Arc<AtomicBool>,
    stream: Option<SCStream>,
    callback_ctx: Arc<CaptureCallbackContext>,
    /// Current implementation status
    status: ImplementationStatus,
}

#[cfg(target_os = "macos")]
impl MacOSSystemAudioCapture {
    pub fn new(config: AudioConfig) -> Self {
        let callback_ctx = Arc::new(CaptureCallbackContext::new(config.clone()));
        Self {
            config,
            is_capturing: Arc::new(AtomicBool::new(false)),
            is_paused: Arc::new(AtomicBool::new(false)),
            stream: None,
            callback_ctx,
            status: ImplementationStatus::Partial,
        }
    }

    /// Get the current implementation status
    pub fn implementation_status(&self) -> ImplementationStatus {
        self.status
    }

    /// Check if this is a real implementation or a stub
    pub fn is_functional(&self) -> bool {
        matches!(
            self.status,
            ImplementationStatus::Partial | ImplementationStatus::Full
        )
    }

    /// Drain captured normalized system-audio frames.
    ///
    /// This is a temporary in-memory handoff point until IPC wiring is added.
    pub fn take_frames(&self) -> Vec<AudioFrame> {
        if self.is_paused.load(Ordering::SeqCst) {
            return Vec::new();
        }

        match self.callback_ctx.frames.lock() {
            Ok(mut frames) => std::mem::take(&mut *frames),
            Err(_) => Vec::new(),
        }
    }

    /// Pause capture emission without stopping the underlying stream.
    pub fn pause(&mut self) -> Result<(), AudioError> {
        if !self.is_capturing.load(Ordering::SeqCst) {
            return Err(AudioError::InternalError(
                "Cannot pause capture when stream is not active".to_string(),
            ));
        }

        self.is_paused.store(true, Ordering::SeqCst);
        Ok(())
    }

    /// Resume capture emission after pause.
    pub fn resume(&mut self) -> Result<(), AudioError> {
        if !self.is_capturing.load(Ordering::SeqCst) {
            return Err(AudioError::InternalError(
                "Cannot resume capture when stream is not active".to_string(),
            ));
        }

        self.is_paused.store(false, Ordering::SeqCst);
        Ok(())
    }

    fn classify_permission_error(message: &str) -> ScreenRecordingPermissionState {
        let lower = message.to_ascii_lowercase();

        if lower.contains("restricted") || lower.contains("parental") || lower.contains("policy") {
            ScreenRecordingPermissionState::Restricted
        } else if lower.contains("denied")
            || lower.contains("permission")
            || lower.contains("not authorized")
            || lower.contains("not permitted")
            || lower.contains("authorization")
        {
            ScreenRecordingPermissionState::Denied
        } else {
            ScreenRecordingPermissionState::Unknown
        }
    }

    fn map_stream_error(message: &str) -> AudioError {
        let lower = message.to_ascii_lowercase();

        if lower.contains("restricted") || lower.contains("parental") || lower.contains("policy") {
            AudioError::InternalError(
                "Screen Recording permission is restricted by system policy".to_string(),
            )
        } else if lower.contains("denied")
            || lower.contains("permission")
            || lower.contains("not authorized")
            || lower.contains("not permitted")
            || lower.contains("authorization")
        {
            AudioError::PermissionDenied
        } else if lower.contains("sample rate") {
            AudioError::InternalError("Sample rate mismatch".to_string())
        } else if lower.contains("device")
            || lower.contains("display")
            || lower.contains("unavailable")
            || lower.contains("no such")
        {
            AudioError::DeviceUnavailable
        } else {
            AudioError::InternalError(format!(
                "Failed to start ScreenCaptureKit stream: {message}"
            ))
        }
    }

    /// Get Screen Recording permission status.
    pub fn permission_status() -> ScreenRecordingPermissionState {
        match SCShareableContent::get() {
            Ok(_) => ScreenRecordingPermissionState::Granted,
            Err(error) => {
                let error_str = error.to_string();
                eprintln!("[DEBUG] SCShareableContent::get() error: {}", error_str);
                Self::classify_permission_error(&error_str)
            }
        }
    }

    /// Check if Screen Recording permission is granted
    pub fn check_permission() -> Result<bool, AudioError> {
        Ok(matches!(
            Self::permission_status(),
            ScreenRecordingPermissionState::Granted
        ))
    }

    /// Request Screen Recording permission
    /// This will show a system dialog to the user
    pub fn request_permission() -> Result<ScreenRecordingPermissionState, AudioError> {
        // macOS shows the permission prompt when we attempt to read
        // shareable content / start capture.
        Ok(match SCShareableContent::get() {
            Ok(_) => ScreenRecordingPermissionState::Granted,
            Err(error) => Self::classify_permission_error(&error.to_string()),
        })
    }
}

#[cfg(target_os = "macos")]
impl AudioCapture for MacOSSystemAudioCapture {
    fn start(&mut self) -> Result<(), AudioError> {
        if self.is_capturing.load(Ordering::SeqCst) {
            return Ok(());
        }

        // Check permission first
        match Self::permission_status() {
            ScreenRecordingPermissionState::Granted => {}
            ScreenRecordingPermissionState::Denied => {
                return Err(AudioError::PermissionDenied);
            }
            ScreenRecordingPermissionState::Restricted => {
                return Err(AudioError::InternalError(
                    "Screen Recording permission is restricted by system policy".to_string(),
                ));
            }
            ScreenRecordingPermissionState::Unknown => {
                let requested = Self::request_permission()?;
                if !matches!(requested, ScreenRecordingPermissionState::Granted) {
                    return Err(match requested {
                        ScreenRecordingPermissionState::Denied => AudioError::PermissionDenied,
                        ScreenRecordingPermissionState::Restricted => AudioError::InternalError(
                            "Screen Recording permission is restricted by system policy"
                                .to_string(),
                        ),
                        ScreenRecordingPermissionState::Unknown => AudioError::PermissionDenied,
                        ScreenRecordingPermissionState::Granted => AudioError::PermissionDenied,
                    });
                }
            }
        }

        let content = SCShareableContent::get().map_err(|e| {
            let err_str = e.to_string();
            eprintln!("[DEBUG] SCShareableContent::get() in start() error: {}", err_str);
            Self::map_stream_error(&err_str)
        })?;
        let display = content
            .displays()
            .into_iter()
            .next()
            .ok_or(AudioError::DeviceUnavailable)?;

        let filter = SCContentFilter::create()
            .with_display(&display)
            .with_excluding_windows(&[])
            .build();

        let stream_config: SCAudioCaptureConfiguration = SCStreamConfiguration::new()
            .with_width(display.width())
            .with_height(display.height())
            .with_captures_audio(true)
            .with_sample_rate(AudioSampleRate::Rate16000)
            .with_channel_count(AudioChannelCount::Mono)
            .with_excludes_current_process_audio(true);

        self.callback_ctx = Arc::new(CaptureCallbackContext::new(self.config.clone()));
        let callback_ctx = Arc::clone(&self.callback_ctx);

        let mut stream = SCStream::new(&filter, &stream_config);
        let handler_added = stream.add_output_handler(
            move |sample: CMSampleBuffer, output_type| {
                if output_type == SCStreamOutputType::Audio {
                    callback_ctx.process_audio_sample(sample);
                }
            },
            SCStreamOutputType::Audio,
        );

        if handler_added.is_none() {
            return Err(AudioError::InternalError(
                "Failed to register ScreenCaptureKit audio output handler".to_string(),
            ));
        }

        stream.start_capture().map_err(|e| {
            let err_str = e.to_string();
            eprintln!("[DEBUG] SCStream::start_capture() error: {}", err_str);
            Self::map_stream_error(&err_str)
        })?;

        self.stream = Some(stream);
        self.is_paused.store(false, Ordering::SeqCst);
        self.is_capturing.store(true, Ordering::SeqCst);
        Ok(())
    }

    fn stop(&mut self) -> Result<(), AudioError> {
        if let Some(stream) = self.stream.take() {
            stream
                .stop_capture()
                .map_err(|e| AudioError::InternalError(format!("Failed to stop capture: {e}")))?;
        }

        if let Ok(mut router) = self.callback_ctx.router.lock() {
            if let Some(mut frame) = router.flush(AudioSource::SystemAudio) {
                frame.timestamp_ms = self.callback_ctx.started_at.elapsed().as_millis() as u64;
                if let Ok(mut sink) = self.callback_ctx.frames.lock() {
                    sink.push(frame);
                }
            }
        }

        self.is_capturing.store(false, Ordering::SeqCst);
        self.is_paused.store(false, Ordering::SeqCst);
        Ok(())
    }

    fn is_capturing(&self) -> bool {
        self.is_capturing.load(Ordering::SeqCst)
    }
}

/// Stub for non-macOS platforms
#[cfg(not(target_os = "macos"))]
pub struct MacOSSystemAudioCapture {
    status: ImplementationStatus,
}

#[cfg(not(target_os = "macos"))]
impl MacOSSystemAudioCapture {
    pub fn new(_config: AudioConfig) -> Self {
        Self {
            status: ImplementationStatus::Partial,
        }
    }

    pub fn implementation_status(&self) -> ImplementationStatus {
        self.status
    }

    pub fn is_functional(&self) -> bool {
        false
    }
}

#[cfg(test)]
#[cfg(target_os = "macos")]
mod tests {
    use super::*;

    #[test]
    fn test_capture_starts_and_stops() {
        let mut capture = MacOSSystemAudioCapture::new(AudioConfig::default());
        assert!(!capture.is_capturing());

        assert_eq!(
            capture.implementation_status(),
            ImplementationStatus::Partial,
            "Expected real ScreenCaptureKit-backed partial implementation"
        );

        match capture.start() {
            Ok(()) => {
                assert!(capture.is_capturing());

                capture.stop().expect("Should stop");
                assert!(!capture.is_capturing());
            }
            Err(AudioError::PermissionDenied) => {
                // CI/local environments may not grant screen recording permission.
                assert!(!capture.is_capturing());
            }
            Err(other) => panic!("Unexpected start error: {other}"),
        }
    }
}
