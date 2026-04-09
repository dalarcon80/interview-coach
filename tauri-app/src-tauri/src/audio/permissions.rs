//! Audio Permissions
//!
//! Handles permission requests for audio capture on different platforms.
//! - macOS: Screen Recording permission for system audio, Microphone for mic
//! - Windows: (V1.5) Similar permission handling
//! - Linux: (V1.5) PipeWire permissions

use serde::{Deserialize, Serialize};

/// Permission status for audio capture
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PermissionStatus {
    /// Permission granted
    Granted,
    /// Permission denied by user
    Denied,
    /// Permission not yet requested
    NotDetermined,
    /// Permission restricted (e.g., parental controls)
    Restricted,
}

/// Permission type required for audio capture
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PermissionType {
    /// Microphone access
    Microphone,
    /// Screen Recording (macOS) for system audio
    ScreenRecording,
}

/// Check current permission status for a permission type
pub fn check_permission(permission_type: PermissionType) -> PermissionStatus {
    #[cfg(target_os = "macos")]
    {
        check_permission_macos(permission_type)
    }

    #[cfg(target_os = "windows")]
    {
        // V1.5: Windows permission handling
        PermissionStatus::Granted // Windows doesn't require explicit permission for mic
    }

    #[cfg(target_os = "linux")]
    {
        // V1.5: Linux permission handling via PipeWire
        PermissionStatus::NotDetermined
    }

    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    {
        PermissionStatus::NotDetermined
    }
}

/// Request permission for a specific type
/// This may show a system dialog to the user
pub fn request_permission(permission_type: PermissionType) -> Result<PermissionStatus, String> {
    #[cfg(target_os = "macos")]
    {
        request_permission_macos(permission_type)
    }

    #[cfg(not(target_os = "macos"))]
    {
        let _ = permission_type;
        Ok(PermissionStatus::Granted)
    }
}

/// Get all required permissions for audio capture
pub fn get_required_permissions() -> Vec<(PermissionType, PermissionStatus)> {
    let mut permissions = Vec::new();

    // Microphone is always needed
    permissions.push((
        PermissionType::Microphone,
        check_permission(PermissionType::Microphone),
    ));

    // System audio requires Screen Recording on macOS
    #[cfg(target_os = "macos")]
    {
        permissions.push((
            PermissionType::ScreenRecording,
            check_permission(PermissionType::ScreenRecording),
        ));
    }

    permissions
}

/// Check if all required permissions are granted
pub fn all_permissions_granted() -> bool {
    get_required_permissions()
        .iter()
        .all(|(_, status)| *status == PermissionStatus::Granted)
}

// ============================================================================
// macOS-specific implementation
// ============================================================================

#[cfg(target_os = "macos")]
fn check_permission_macos(permission_type: PermissionType) -> PermissionStatus {
    // In production, this would use CoreFoundation/AVFoundation APIs:
    // - AVCaptureDevice.authorizationStatus(for: .audio) for microphone
    // - CGWindowListCopyWindowInfo for screen recording

    match permission_type {
        PermissionType::Microphone => {
            // Placeholder - in production would use AVFoundation
            PermissionStatus::NotDetermined
        }
        PermissionType::ScreenRecording => {
            // Placeholder - in production would check screen capture capability
            PermissionStatus::NotDetermined
        }
    }
}

#[cfg(target_os = "macos")]
fn request_permission_macos(permission_type: PermissionType) -> Result<PermissionStatus, String> {
    // In production, this would show system permission dialogs
    // using AVFoundation APIs

    match permission_type {
        PermissionType::Microphone => {
            // AVCaptureDevice.requestAccess(for: .audio)
            Ok(PermissionStatus::Granted)
        }
        PermissionType::ScreenRecording => {
            // Screen Recording permission is requested automatically
            // when attempting to capture screen content
            Ok(PermissionStatus::Granted)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_permission_types_exist() {
        let _ = PermissionType::Microphone;
        let _ = PermissionType::ScreenRecording;
    }

    #[test]
    fn test_permission_status_variants() {
        assert_ne!(PermissionStatus::Granted, PermissionStatus::Denied);
        assert_ne!(
            PermissionStatus::NotDetermined,
            PermissionStatus::Restricted
        );
    }

    #[test]
    fn test_get_required_permissions() {
        let permissions = get_required_permissions();
        assert!(!permissions.is_empty());
        assert!(permissions
            .iter()
            .any(|(t, _)| *t == PermissionType::Microphone));
    }
}
