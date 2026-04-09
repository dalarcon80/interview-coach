//! Tauri IPC Commands
//!
//! Commands exposed to the frontend for audio capture and control.

#[cfg(target_os = "macos")]
use crate::audio::macos_capture::{MacOSSystemAudioCapture, ScreenRecordingPermissionState};
use crate::audio::permissions::{self, PermissionStatus, PermissionType};
use crate::audio::{
    get_platform_support, list_mic_devices, AudioCapture, AudioConfig, AudioError, AudioFrame,
    MicrophoneCapture,
};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager};

/// Global state for audio capture
/// Note: Microphone capture runs in a dedicated thread to avoid Send+Sync issues with cpal Stream
pub struct AppState {
    pub system_audio_capture: Arc<Mutex<Option<MacOSSystemAudioCapture>>>,
    pub capture_state: Arc<Mutex<CaptureState>>,
    pub is_capturing: Arc<Mutex<bool>>,
    pub capture_start_time: Arc<Mutex<Option<std::time::Instant>>>,
    pub capture_type: Arc<Mutex<Option<CaptureType>>>,
    pub capture_session_id: Arc<Mutex<Option<String>>>,
    pub capture_session_counter: Arc<Mutex<u64>>,
    // Thread handle for microphone capture (to stop it)
    pub mic_capture_stop_flag: Arc<Mutex<bool>>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            system_audio_capture: Arc::new(Mutex::new(None)),
            capture_state: Arc::new(Mutex::new(CaptureState::Idle)),
            is_capturing: Arc::new(Mutex::new(false)),
            capture_start_time: Arc::new(Mutex::new(None)),
            capture_type: Arc::new(Mutex::new(None)),
            capture_session_id: Arc::new(Mutex::new(None)),
            capture_session_counter: Arc::new(Mutex::new(0)),
            mic_capture_stop_flag: Arc::new(Mutex::new(false)),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum CaptureState {
    Idle,
    Capturing,
    Paused,
}

/// Audio data event payload sent to frontend
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioDataEvent {
    /// Base64-encoded PCM 16-bit audio data
    pub data: String,
    /// Timestamp in milliseconds from capture start
    pub timestamp_ms: u64,
    /// Sample rate (always 16000)
    pub sample_rate: u32,
    /// Number of channels (always 1 for mono)
    pub channels: u16,
    /// Audio source (system or mic)
    pub source: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CaptureAction {
    Start,
    Stop,
    Pause,
    Resume,
}

fn capture_state_name(state: &CaptureState) -> &'static str {
    match state {
        CaptureState::Idle => "idle",
        CaptureState::Capturing => "capturing",
        CaptureState::Paused => "paused",
    }
}

fn capture_action_name(action: CaptureAction) -> &'static str {
    match action {
        CaptureAction::Start => "start_capture",
        CaptureAction::Stop => "stop_capture",
        CaptureAction::Pause => "pause_capture",
        CaptureAction::Resume => "resume_capture",
    }
}

fn capture_type_name(capture_type: &CaptureType) -> &'static str {
    match capture_type {
        CaptureType::Microphone => "Microphone",
        CaptureType::SystemAudio => "SystemAudio",
        CaptureType::Both => "Both",
    }
}

fn next_capture_state(
    current: &CaptureState,
    action: CaptureAction,
) -> Result<CaptureState, String> {
    match (current, action) {
        (CaptureState::Idle, CaptureAction::Start) => Ok(CaptureState::Capturing),
        (CaptureState::Capturing, CaptureAction::Pause) => Ok(CaptureState::Paused),
        (CaptureState::Paused, CaptureAction::Resume) => Ok(CaptureState::Capturing),
        (CaptureState::Capturing, CaptureAction::Stop) => Ok(CaptureState::Idle),
        (CaptureState::Paused, CaptureAction::Stop) => Ok(CaptureState::Idle),
        _ => Err(format!(
            "Invalid transition: {} from {}",
            capture_action_name(action),
            capture_state_name(current)
        )),
    }
}

fn timestamp_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0)
}

fn log_capture_transition(
    session_id: Option<&str>,
    from: &CaptureState,
    to: &CaptureState,
    action: CaptureAction,
) {
    eprintln!(
        "[AUDIO][CAPTURE][STATE_TRANSITION] {}",
        json!({
            "timestamp_ms": timestamp_ms(),
            "session_id": session_id,
            "action": capture_action_name(action),
            "from": capture_state_name(from),
            "to": capture_state_name(to),
        })
    );
}

fn log_capture_invalid_transition(
    session_id: Option<&str>,
    current: &CaptureState,
    action: CaptureAction,
) {
    eprintln!(
        "[AUDIO][CAPTURE][STATE_INVALID] {}",
        json!({
            "timestamp_ms": timestamp_ms(),
            "session_id": session_id,
            "action": capture_action_name(action),
            "state": capture_state_name(current),
        })
    );
}

/// Start the audio frame emission task
fn start_audio_emitter(app_handle: AppHandle, state: tauri::State<'_, AppState>) {
    let capture_state = Arc::clone(&state.capture_state);
    let capture_data = Arc::clone(&state.system_audio_capture);

    std::thread::spawn(move || {
        loop {
            // Check if we should continue
            let current_state = {
                match capture_state.lock() {
                    Ok(guard) => guard.clone(),
                    Err(_) => CaptureState::Idle,
                }
            };

            if current_state == CaptureState::Idle {
                break;
            }

            if current_state == CaptureState::Paused {
                std::thread::sleep(std::time::Duration::from_millis(50));
                continue;
            }

            // Take frames from system audio capture
            let frames: Vec<AudioFrame> = {
                match capture_data.lock() {
                    Ok(mut capture_guard) => {
                        if let Some(ref mut sys_capture) = *capture_guard {
                            sys_capture.take_frames()
                        } else {
                            Vec::new()
                        }
                    }
                    Err(_) => Vec::new(),
                }
            };

            // Emit each frame
            for frame in frames {
                // Convert i16 samples to bytes for base64 encoding
                let bytes: Vec<u8> = frame
                    .samples
                    .iter()
                    .flat_map(|&s| s.to_le_bytes())
                    .collect();
                let audio_data = BASE64.encode(&bytes);

                let event = AudioDataEvent {
                    data: audio_data,
                    timestamp_ms: frame.timestamp_ms,
                    sample_rate: 16000,
                    channels: 1,
                    source: match frame.source {
                        crate::audio::AudioSource::SystemAudio => "system".to_string(),
                        crate::audio::AudioSource::Microphone => "mic".to_string(),
                    },
                };

                if let Err(e) = app_handle.emit("audio-data", event) {
                    eprintln!("Failed to emit audio-data event: {}", e);
                }
            }

            // Small sleep to prevent busy loop (100ms = one frame at 100ms chunk)
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
    });
}

#[cfg(target_os = "macos")]
fn screen_recording_guidance_message() -> String {
    "Screen Recording permission required for system audio capture. Open System Settings → Privacy & Security → Screen Recording → Enable Interview Coach. You can also use microphone-only mode instead.".to_string()
}

#[cfg(target_os = "macos")]
fn screen_recording_restricted_message() -> String {
    "Screen Recording access is restricted by parental controls or system policy. Please contact your administrator.".to_string()
}

#[cfg(target_os = "macos")]
fn map_screen_permission_state_to_status(
    state: ScreenRecordingPermissionState,
) -> PermissionStatus {
    match state {
        ScreenRecordingPermissionState::Unknown => PermissionStatus::NotDetermined,
        ScreenRecordingPermissionState::Granted => PermissionStatus::Granted,
        ScreenRecordingPermissionState::Denied => PermissionStatus::Denied,
        ScreenRecordingPermissionState::Restricted => PermissionStatus::Restricted,
    }
}

#[cfg(target_os = "macos")]
fn map_screen_permission_state_to_error(state: ScreenRecordingPermissionState) -> Option<String> {
    match state {
        ScreenRecordingPermissionState::Granted => None,
        ScreenRecordingPermissionState::Unknown => Some(screen_recording_guidance_message()),
        ScreenRecordingPermissionState::Denied => Some(screen_recording_guidance_message()),
        ScreenRecordingPermissionState::Restricted => Some(screen_recording_restricted_message()),
    }
}

#[cfg(target_os = "macos")]
fn map_start_capture_error(error: AudioError) -> String {
    match error {
        AudioError::PermissionDenied => screen_recording_guidance_message(),
        AudioError::DeviceUnavailable => {
            "Audio device unavailable. Please check your microphone and try again.".to_string()
        }
        AudioError::PlatformNotSupported => {
            "System audio capture is only supported on macOS in V1".to_string()
        }
        AudioError::InternalError(message) => {
            let lower = message.to_ascii_lowercase();
            if lower.contains("sample rate") {
                "Sample rate mismatch. Restarting capture...".to_string()
            } else if lower.contains("restricted")
                || lower.contains("parental")
                || lower.contains("policy")
            {
                screen_recording_restricted_message()
            } else if lower.contains("permission")
                || lower.contains("authorization")
                || lower.contains("not authorized")
                || lower.contains("not permitted")
            {
                screen_recording_guidance_message()
            } else if lower.contains("device") || lower.contains("unavailable") {
                "Audio device unavailable. Please check your microphone and try again.".to_string()
            } else {
                format!("Failed to start capture: {message}")
            }
        }
    }
}

/// Get available audio devices
#[tauri::command]
pub fn get_audio_devices() -> Vec<AudioDeviceInfo> {
    match list_mic_devices() {
        Ok(devices) => devices
            .into_iter()
            .enumerate()
            .map(|(i, name)| AudioDeviceInfo {
                id: i.to_string(),
                name,
                is_input: true,
                is_system: false,
            })
            .collect(),
        Err(_) => vec![AudioDeviceInfo {
            id: "default".to_string(),
            name: "Default Input".to_string(),
            is_input: true,
            is_system: false,
        }],
    }
}

/// Start audio capture
#[allow(non_snake_case)]
#[tauri::command]
pub async fn start_capture(
    app_handle: AppHandle,
    deviceId: String,
    captureType: CaptureType,
) -> Result<(), String> {
    let _ = deviceId; // Device selection to be implemented

    // Get app state
    let app_handle_for_state = app_handle.clone();
    let state = app_handle_for_state.state::<AppState>();

    let current_state = state
        .capture_state
        .lock()
        .map_err(|e| e.to_string())?
        .clone();
    let current_session_id = state
        .capture_session_id
        .lock()
        .map_err(|e| e.to_string())?
        .clone();

    let next_state = match next_capture_state(&current_state, CaptureAction::Start) {
        Ok(next) => next,
        Err(error) => {
            log_capture_invalid_transition(
                current_session_id.as_deref(),
                &current_state,
                CaptureAction::Start,
            );
            return Err(error);
        }
    };

    let session_id = {
        let mut session_counter = state
            .capture_session_counter
            .lock()
            .map_err(|e| e.to_string())?;
        *session_counter += 1;
        format!("capture-{}-{}", timestamp_ms(), *session_counter)
    };

    let mut should_start_audio_emitter = false;

    match &captureType {
        CaptureType::Microphone => {
            // Spawn a dedicated thread for microphone capture
            // This avoids Send+Sync issues with cpal Stream
            let app_handle_clone = app_handle.clone();
            let capture_state = Arc::clone(&state.capture_state);
            let stop_flag = Arc::clone(&state.mic_capture_stop_flag);
            
            // Reset stop flag
            {
                let mut stop = stop_flag.lock().map_err(|e| e.to_string())?;
                *stop = false;
            }
            
            // Spawn microphone capture thread
            std::thread::spawn(move || {
                let config = AudioConfig::default();
                let mut mic_capture = MicrophoneCapture::new(config);
                
                // Start the capture
                if let Err(e) = mic_capture.start() {
                    eprintln!("[MIC] Failed to start microphone capture: {}", e);
                    return;
                }
                
                println!("[MIC] Microphone capture started successfully");

                // Run the capture loop
                loop {
                    // Check if we should stop
                    let should_stop = stop_flag
                        .lock()
                        .map(|guard| *guard)
                        .unwrap_or(true);
                    
                    if should_stop {
                        println!("[MIC] Stop flag detected, exiting capture loop");
                        break;
                    }

                    // Check capture state
                    let current_state = capture_state
                        .lock()
                        .map(|guard| guard.clone())
                        .unwrap_or(CaptureState::Idle);

                    if current_state == CaptureState::Idle {
                        break;
                    }

                    if current_state == CaptureState::Paused {
                        std::thread::sleep(std::time::Duration::from_millis(50));
                        continue;
                    }

                    // Get frames from microphone
                    let frames = mic_capture.get_frames();
                    
                    for frame in frames {
                        // Convert i16 samples to bytes for base64 encoding
                        let bytes: Vec<u8> = frame
                            .samples
                            .iter()
                            .flat_map(|&s| s.to_le_bytes())
                            .collect();
                        let audio_data = BASE64.encode(&bytes);

                        let event = AudioDataEvent {
                            data: audio_data,
                            timestamp_ms: frame.timestamp_ms,
                            sample_rate: 16000,
                            channels: 1,
                            source: "mic".to_string(),
                        };

                        if let Err(e) = app_handle_clone.emit("audio-data", event) {
                            eprintln!("[MIC] Failed to emit audio-data event: {}", e);
                        }
                    }

                    std::thread::sleep(std::time::Duration::from_millis(50));
                }

                // Stop capture on exit
                let _ = mic_capture.stop();
                println!("[MIC] Microphone capture stopped");
            });

            should_start_audio_emitter = true;
        }
        CaptureType::SystemAudio | CaptureType::Both => {
            // System audio only works on macOS
            #[cfg(target_os = "macos")]
            {
                // First, check the permission status
                let mut permission_state = MacOSSystemAudioCapture::permission_status();
                eprintln!("[DEBUG] Initial permission state: {:?}", permission_state);

                // If permission is Unknown, try to request it (this triggers the system dialog)
                // If it's Denied or Restricted, we should not try again without user intervention
                if matches!(permission_state, ScreenRecordingPermissionState::Unknown) {
                    eprintln!("[DEBUG] Permission unknown, requesting...");
                    // Requesting permission triggers the system dialog
                    permission_state = MacOSSystemAudioCapture::request_permission()
                        .map_err(map_start_capture_error)?;
                    eprintln!("[DEBUG] Permission state after request: {:?}", permission_state);
                }

                // Check if permission was granted after the request
                if let Some(permission_error) =
                    map_screen_permission_state_to_error(permission_state)
                {
                    eprintln!("[DEBUG] Permission error: {}", permission_error);
                    return Err(permission_error);
                }

                let config = AudioConfig::default();
                let mut capture = MacOSSystemAudioCapture::new(config);

                // Start the capture - this is where the actual ScreenCaptureKit call happens
                eprintln!("[DEBUG] Starting capture...");
                capture.start().map_err(|e| {
                    eprintln!("[DEBUG] Capture start error: {:?}", e);
                    map_start_capture_error(e)
                })?;

                // Store capture
                {
                    let mut sys_capture = state
                        .system_audio_capture
                        .lock()
                        .map_err(|e| e.to_string())?;
                    *sys_capture = Some(capture);
                }

                should_start_audio_emitter = true;
            }
            #[cfg(not(target_os = "macos"))]
            {
                return Err("System audio capture is only supported on macOS in V1".to_string());
            }
        }
    }

    {
        let mut capture_state = state.capture_state.lock().map_err(|e| e.to_string())?;
        *capture_state = next_state.clone();
    }
    {
        let mut is_capturing = state.is_capturing.lock().map_err(|e| e.to_string())?;
        *is_capturing = true;
    }
    {
        let mut start_time = state.capture_start_time.lock().map_err(|e| e.to_string())?;
        *start_time = Some(std::time::Instant::now());
    }
    {
        let mut active_capture_type = state.capture_type.lock().map_err(|e| e.to_string())?;
        *active_capture_type = Some(captureType.clone());
    }
    {
        let mut active_session_id = state.capture_session_id.lock().map_err(|e| e.to_string())?;
        *active_session_id = Some(session_id.clone());
    }

    log_capture_transition(
        Some(session_id.as_str()),
        &current_state,
        &next_state,
        CaptureAction::Start,
    );

    if should_start_audio_emitter {
        // Start the shared audio emission thread
        start_audio_emitter(app_handle, state);
    }

    Ok(())
}

/// Stop audio capture
#[tauri::command]
pub async fn stop_capture(app_handle: AppHandle) -> Result<(), String> {
    // Get app state
    let state = app_handle.state::<AppState>();

    let current_state = state
        .capture_state
        .lock()
        .map_err(|e| e.to_string())?
        .clone();
    let session_id = state
        .capture_session_id
        .lock()
        .map_err(|e| e.to_string())?
        .clone();

    let next_state = match next_capture_state(&current_state, CaptureAction::Stop) {
        Ok(next) => next,
        Err(error) => {
            log_capture_invalid_transition(
                session_id.as_deref(),
                &current_state,
                CaptureAction::Stop,
            );
            return Err(error);
        }
    };

    // Stop system audio capture
    #[cfg(target_os = "macos")]
    {
        let mut capture = state
            .system_audio_capture
            .lock()
            .map_err(|e| e.to_string())?;
        if let Some(ref mut sys_capture) = *capture {
            let _ = sys_capture.stop();
        }
        *capture = None;
    }

    // Signal microphone capture thread to stop
    {
        let mut stop = state
            .mic_capture_stop_flag
            .lock()
            .map_err(|e| e.to_string())?;
        *stop = true;
    }

    // Mark as not capturing
    {
        let mut is_capturing = state.is_capturing.lock().map_err(|e| e.to_string())?;
        *is_capturing = false;
    }
    {
        let mut capture_state = state.capture_state.lock().map_err(|e| e.to_string())?;
        *capture_state = next_state.clone();
    }
    {
        let mut start_time = state.capture_start_time.lock().map_err(|e| e.to_string())?;
        *start_time = None;
    }
    {
        let mut active_capture_type = state.capture_type.lock().map_err(|e| e.to_string())?;
        *active_capture_type = None;
    }
    {
        let mut active_session_id = state.capture_session_id.lock().map_err(|e| e.to_string())?;
        *active_session_id = None;
    }

    log_capture_transition(
        session_id.as_deref(),
        &current_state,
        &next_state,
        CaptureAction::Stop,
    );

    Ok(())
}

/// Pause audio capture without tearing down resources
#[tauri::command]
pub async fn pause_capture(app_handle: AppHandle) -> Result<(), String> {
    let state = app_handle.state::<AppState>();

    let current_state = state
        .capture_state
        .lock()
        .map_err(|e| e.to_string())?
        .clone();
    let session_id = state
        .capture_session_id
        .lock()
        .map_err(|e| e.to_string())?
        .clone();

    let next_state = match next_capture_state(&current_state, CaptureAction::Pause) {
        Ok(next) => next,
        Err(error) => {
            log_capture_invalid_transition(
                session_id.as_deref(),
                &current_state,
                CaptureAction::Pause,
            );
            return Err(error);
        }
    };

    #[cfg(target_os = "macos")]
    {
        let active_capture_type = state
            .capture_type
            .lock()
            .map_err(|e| e.to_string())?
            .clone();
        if matches!(
            active_capture_type,
            Some(CaptureType::SystemAudio) | Some(CaptureType::Both)
        ) {
            let mut capture = state
                .system_audio_capture
                .lock()
                .map_err(|e| e.to_string())?;
            if let Some(ref mut sys_capture) = *capture {
                sys_capture
                    .pause()
                    .map_err(|error| format!("Failed to pause capture: {error}"))?;
            } else {
                return Err(
                    "Cannot pause system audio capture because stream is not initialized"
                        .to_string(),
                );
            }
        }
    }

    {
        let mut capturing = state.is_capturing.lock().map_err(|e| e.to_string())?;
        *capturing = false;
    }
    {
        let mut capture_state = state.capture_state.lock().map_err(|e| e.to_string())?;
        *capture_state = next_state.clone();
    }

    log_capture_transition(
        session_id.as_deref(),
        &current_state,
        &next_state,
        CaptureAction::Pause,
    );

    Ok(())
}

/// Resume a paused audio capture stream
#[tauri::command]
pub async fn resume_capture(app_handle: AppHandle) -> Result<(), String> {
    let state = app_handle.state::<AppState>();

    let current_state = state
        .capture_state
        .lock()
        .map_err(|e| e.to_string())?
        .clone();
    let session_id = state
        .capture_session_id
        .lock()
        .map_err(|e| e.to_string())?
        .clone();

    let next_state = match next_capture_state(&current_state, CaptureAction::Resume) {
        Ok(next) => next,
        Err(error) => {
            log_capture_invalid_transition(
                session_id.as_deref(),
                &current_state,
                CaptureAction::Resume,
            );
            return Err(error);
        }
    };

    #[cfg(target_os = "macos")]
    {
        let active_capture_type = state
            .capture_type
            .lock()
            .map_err(|e| e.to_string())?
            .clone();
        if matches!(
            active_capture_type,
            Some(CaptureType::SystemAudio) | Some(CaptureType::Both)
        ) {
            let mut capture = state
                .system_audio_capture
                .lock()
                .map_err(|e| e.to_string())?;
            if let Some(ref mut sys_capture) = *capture {
                sys_capture
                    .resume()
                    .map_err(|error| format!("Failed to resume capture: {error}"))?;
            } else {
                return Err(
                    "Cannot resume system audio capture because stream is not initialized"
                        .to_string(),
                );
            }
        }
    }

    {
        let mut capturing = state.is_capturing.lock().map_err(|e| e.to_string())?;
        *capturing = true;
    }
    {
        let mut capture_state = state.capture_state.lock().map_err(|e| e.to_string())?;
        *capture_state = next_state.clone();
    }

    log_capture_transition(
        session_id.as_deref(),
        &current_state,
        &next_state,
        CaptureAction::Resume,
    );

    Ok(())
}

/// Get capture lifecycle state
#[tauri::command]
pub fn get_capture_state(app_handle: AppHandle) -> CaptureStateInfo {
    let state = app_handle.state::<AppState>();

    let capture_state = state
        .capture_state
        .lock()
        .map(|guard| guard.clone())
        .unwrap_or(CaptureState::Idle);

    let capture_type = state
        .capture_type
        .lock()
        .ok()
        .and_then(|guard| (*guard).clone())
        .map(|capture| capture_type_name(&capture).to_string());

    let session_id = state
        .capture_session_id
        .lock()
        .ok()
        .and_then(|guard| (*guard).clone());

    CaptureStateInfo {
        state: capture_state,
        capture_type,
        session_id,
    }
}

/// Get platform information
#[tauri::command]
pub fn get_platform_info() -> PlatformInfo {
    let support = get_platform_support();
    PlatformInfo {
        os: support.os,
        arch: std::env::consts::ARCH.to_string(),
        supports_system_audio: support.supported,
        version: env!("CARGO_PKG_VERSION").to_string(),
    }
}

/// Check permission status for audio capture
#[tauri::command]
pub fn check_permissions() -> PermissionInfo {
    let mic_status = permissions::check_permission(PermissionType::Microphone);

    #[cfg(target_os = "macos")]
    let screen_status = Some(map_screen_permission_state_to_status(
        MacOSSystemAudioCapture::permission_status(),
    ));

    #[cfg(not(target_os = "macos"))]
    let screen_status: Option<PermissionStatus> = None;

    let all_granted = match &screen_status {
        Some(screen) => {
            mic_status == PermissionStatus::Granted && *screen == PermissionStatus::Granted
        }
        None => mic_status == PermissionStatus::Granted,
    };

    PermissionInfo {
        microphone: mic_status,
        screen_recording: screen_status,
        all_granted,
    }
}

/// Request permission for audio capture
#[tauri::command]
pub async fn request_permission(
    permission_type: PermissionTypeArg,
) -> Result<PermissionStatus, String> {
    let ptype = match permission_type {
        PermissionTypeArg::Microphone => PermissionType::Microphone,
        PermissionTypeArg::ScreenRecording => PermissionType::ScreenRecording,
    };

    #[cfg(target_os = "macos")]
    {
        if ptype == PermissionType::ScreenRecording {
            let status =
                MacOSSystemAudioCapture::request_permission().map_err(map_start_capture_error)?;
            return Ok(map_screen_permission_state_to_status(status));
        }
    }

    permissions::request_permission(ptype)
}

/// Get audio capture status
#[tauri::command]
pub fn get_capture_status(app_handle: AppHandle) -> CaptureStatus {
    let state = app_handle.state::<AppState>();

    let capture_state = state
        .capture_state
        .lock()
        .map(|guard| guard.clone())
        .unwrap_or(CaptureState::Idle);

    let is_capturing = capture_state == CaptureState::Capturing;

    let capture_type = state
        .capture_type
        .lock()
        .ok()
        .and_then(|guard| (*guard).clone())
        .map(|capture| capture_type_name(&capture).to_string());

    let duration_ms = if capture_state != CaptureState::Idle {
        state
            .capture_start_time
            .lock()
            .ok()
            .and_then(|guard| *guard)
            .map(|started_at| started_at.elapsed().as_millis() as u64)
            .unwrap_or(0)
    } else {
        0
    };

    let session_id = state
        .capture_session_id
        .lock()
        .ok()
        .and_then(|guard| (*guard).clone());

    CaptureStatus {
        is_capturing,
        capture_state,
        capture_type,
        duration_ms,
        session_id,
    }
}

// ============================================================================
// Data Types
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioDeviceInfo {
    pub id: String,
    pub name: String,
    pub is_input: bool,
    pub is_system: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum CaptureType {
    Microphone,
    SystemAudio,
    Both,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureStateInfo {
    pub state: CaptureState,
    pub capture_type: Option<String>,
    pub session_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlatformInfo {
    pub os: String,
    pub arch: String,
    pub supports_system_audio: bool,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PermissionInfo {
    pub microphone: PermissionStatus,
    pub screen_recording: Option<PermissionStatus>,
    pub all_granted: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum PermissionTypeArg {
    Microphone,
    ScreenRecording,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureStatus {
    pub is_capturing: bool,
    pub capture_state: CaptureState,
    pub capture_type: Option<String>,
    pub duration_ms: u64,
    pub session_id: Option<String>,
}

// Custom serialization for PermissionStatus
impl From<PermissionStatus> for String {
    fn from(status: PermissionStatus) -> String {
        match status {
            PermissionStatus::Granted => "granted".to_string(),
            PermissionStatus::Denied => "denied".to_string(),
            PermissionStatus::NotDetermined => "not_determined".to_string(),
            PermissionStatus::Restricted => "restricted".to_string(),
        }
    }
}

#[cfg(test)]
#[cfg(target_os = "macos")]
mod tests {
    use super::*;

    #[test]
    fn map_start_capture_error_permission_denied_returns_guidance() {
        assert_eq!(
            map_start_capture_error(AudioError::PermissionDenied),
            "Screen Recording permission required. Open System Settings → Privacy & Security → Screen Recording → Enable Interview Coach"
        );
    }

    #[test]
    fn map_start_capture_error_device_unavailable_returns_friendly_message() {
        assert_eq!(
            map_start_capture_error(AudioError::DeviceUnavailable),
            "Audio device unavailable. Please check your microphone and try again."
        );
    }

    #[test]
    fn map_start_capture_error_sample_rate_returns_restart_message() {
        assert_eq!(
            map_start_capture_error(AudioError::InternalError(
                "Sample rate mismatch in stream configuration".to_string(),
            )),
            "Sample rate mismatch. Restarting capture..."
        );
    }

    #[test]
    fn map_screen_permission_state_unknown_maps_to_not_determined() {
        assert_eq!(
            map_screen_permission_state_to_status(ScreenRecordingPermissionState::Unknown),
            PermissionStatus::NotDetermined
        );
    }

    #[test]
    fn capture_state_machine_allows_expected_transitions() {
        assert_eq!(
            next_capture_state(&CaptureState::Idle, CaptureAction::Start).unwrap(),
            CaptureState::Capturing
        );
        assert_eq!(
            next_capture_state(&CaptureState::Capturing, CaptureAction::Pause).unwrap(),
            CaptureState::Paused
        );
        assert_eq!(
            next_capture_state(&CaptureState::Paused, CaptureAction::Resume).unwrap(),
            CaptureState::Capturing
        );
        assert_eq!(
            next_capture_state(&CaptureState::Capturing, CaptureAction::Stop).unwrap(),
            CaptureState::Idle
        );
        assert_eq!(
            next_capture_state(&CaptureState::Paused, CaptureAction::Stop).unwrap(),
            CaptureState::Idle
        );
    }

    #[test]
    fn capture_state_machine_blocks_invalid_transitions() {
        assert!(next_capture_state(&CaptureState::Idle, CaptureAction::Pause).is_err());
        assert!(next_capture_state(&CaptureState::Idle, CaptureAction::Resume).is_err());
        assert!(next_capture_state(&CaptureState::Idle, CaptureAction::Stop).is_err());
        assert!(next_capture_state(&CaptureState::Capturing, CaptureAction::Start).is_err());
        assert!(next_capture_state(&CaptureState::Paused, CaptureAction::Pause).is_err());
    }

    #[test]
    fn capture_transition_logging_outputs_session_context() {
        log_capture_transition(
            Some("session-test-123"),
            &CaptureState::Idle,
            &CaptureState::Capturing,
            CaptureAction::Start,
        );
        log_capture_invalid_transition(
            Some("session-test-123"),
            &CaptureState::Idle,
            CaptureAction::Pause,
        );
    }
}
