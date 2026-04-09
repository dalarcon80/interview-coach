//! Audio Types
//!
//! Shared types for audio processing across capture implementations.

use serde::{Deserialize, Serialize};

/// Normalized audio frame - all capture sources output this format
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioFrame {
    /// PCM 16-bit samples at 16kHz mono
    pub samples: Vec<i16>,
    /// Timestamp in milliseconds from start of capture
    pub timestamp_ms: u64,
    /// Source of this frame
    pub source: AudioSource,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AudioSource {
    Microphone,
    SystemAudio,
}

/// Configuration for audio capture
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioConfig {
    /// Sample rate (always 16000 for output)
    pub sample_rate: u32,
    /// Channels (always 1 for output)
    pub channels: u16,
    /// Chunk duration in milliseconds
    pub chunk_ms: u32,
}

impl Default for AudioConfig {
    fn default() -> Self {
        Self {
            sample_rate: 16000,
            channels: 1,
            chunk_ms: 100,
        }
    }
}

impl AudioConfig {
    /// Number of samples per chunk
    pub fn samples_per_chunk(&self) -> usize {
        (self.sample_rate as usize * self.chunk_ms as usize) / 1000
    }
}
