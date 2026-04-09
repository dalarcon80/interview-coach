//! Interview Coach - Tauri 2.0 Desktop Application
//!
//! macOS-first desktop app that captures audio from video conferences,
//! transcribes via streaming STT, and provides AI-powered response suggestions.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;

/// Audio capture module
mod audio;

/// IPC commands for frontend communication
mod commands;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(commands::AppState::default())
        .setup(|app| {
            #[cfg(debug_assertions)]
            {
                let window = app.get_webview_window("main").unwrap();
                window.open_devtools();
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_audio_devices,
            commands::start_capture,
            commands::stop_capture,
            commands::pause_capture,
            commands::resume_capture,
            commands::get_capture_state,
            commands::get_platform_info,
            commands::check_permissions,
            commands::request_permission,
            commands::get_capture_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn main() {
    run();
}
