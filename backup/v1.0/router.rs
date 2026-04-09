//! Audio Router
//!
//! Normalizes audio from different sources to a standard format:
//! - PCM 16-bit signed little-endian
//! - 16kHz sample rate
//! - Mono channel
//!
//! Emits stable frame format chunks every 100ms.

use crate::audio::types::{AudioConfig, AudioFrame, AudioSource};
use std::time::{Duration, Instant};

/// Audio router that normalizes input audio to standard format
pub struct AudioRouter {
    config: AudioConfig,
    buffer: Vec<i16>,
    emitted_frames: u64,
    last_emit_at: Option<Instant>,
    created_at: Instant,
    next_emit_at: Instant,
}

impl AudioRouter {
    pub fn new(config: AudioConfig) -> Self {
        let buffer_capacity = config.samples_per_chunk() * 2;
        let created_at = Instant::now();
        Self {
            config,
            buffer: Vec::with_capacity(buffer_capacity),
            emitted_frames: 0,
            last_emit_at: None,
            created_at,
            next_emit_at: created_at,
        }
    }

    /// Process incoming audio samples and emit complete frames
    pub fn process(&mut self, samples: &[i16], source: AudioSource) -> Vec<AudioFrame> {
        self.buffer.extend_from_slice(samples);

        let chunk_size = self.config.samples_per_chunk();
        let mut frames = Vec::new();

        while self.buffer.len() >= chunk_size {
            // Emit chunks immediately - no cadence hold wait
            // This eliminates the 30+ second latency from buffering
            let now = Instant::now();
            let chunk: Vec<i16> = self.buffer.drain(..chunk_size).collect();
            let interval_since_prev_ms = self
                .last_emit_at
                .map(|prev| now.duration_since(prev).as_millis() as u64)
                .unwrap_or(0);
            self.last_emit_at = Some(now);
            self.emitted_frames += 1;
            let router_elapsed_ms = now.duration_since(self.created_at).as_millis() as u64;
            let cadence_drift_ms = if interval_since_prev_ms == 0 {
                0
            } else {
                interval_since_prev_ms as i64 - self.config.chunk_ms as i64
            };
            self.next_emit_at = now + Duration::from_millis(self.config.chunk_ms as u64);
            let next_emit_in_ms = self.next_emit_at.duration_since(now).as_millis() as u64;

            println!(
                "[AUDIO][ROUTER] chunk_ready seq={} source={:?} chunk_samples={} chunk_bytes={} buffer_remaining_samples={} expected_chunk_ms={} interval_since_prev_ms={} cadence_drift_ms={} next_emit_in_ms={} router_elapsed_ms={}",
                self.emitted_frames,
                source,
                chunk_size,
                chunk_size * std::mem::size_of::<i16>(),
                self.buffer.len(),
                self.config.chunk_ms,
                interval_since_prev_ms,
                cadence_drift_ms,
                next_emit_in_ms,
                router_elapsed_ms
            );

            let timestamp_ms = 0; // Will be set by caller with actual timing

            frames.push(AudioFrame {
                samples: chunk,
                timestamp_ms,
                source,
            });
        }

        frames
    }

    /// Flush any remaining samples in buffer
    pub fn flush(&mut self, source: AudioSource) -> Option<AudioFrame> {
        if self.buffer.is_empty() {
            return None;
        }

        // Pad with zeros if needed
        let chunk_size = self.config.samples_per_chunk();
        while self.buffer.len() < chunk_size {
            self.buffer.push(0);
        }

        let samples = std::mem::take(&mut self.buffer);
        let now = Instant::now();
        let interval_since_prev_ms = self
            .last_emit_at
            .map(|prev| now.duration_since(prev).as_millis() as u64)
            .unwrap_or(0);
        self.last_emit_at = Some(now);
        self.emitted_frames += 1;
        let router_elapsed_ms = now.duration_since(self.created_at).as_millis() as u64;
        self.next_emit_at = now + Duration::from_millis(self.config.chunk_ms as u64);
        let cadence_drift_ms = if interval_since_prev_ms == 0 {
            0
        } else {
            interval_since_prev_ms as i64 - self.config.chunk_ms as i64
        };
        let next_emit_in_ms = self.next_emit_at.duration_since(now).as_millis() as u64;

        println!(
            "[AUDIO][ROUTER] flush_chunk_ready seq={} source={:?} chunk_samples={} chunk_bytes={} expected_chunk_ms={} interval_since_prev_ms={} cadence_drift_ms={} next_emit_in_ms={} router_elapsed_ms={}",
            self.emitted_frames,
            source,
            samples.len(),
            samples.len() * std::mem::size_of::<i16>(),
            self.config.chunk_ms,
            interval_since_prev_ms,
            cadence_drift_ms,
            next_emit_in_ms,
            router_elapsed_ms
        );

        Some(AudioFrame {
            samples,
            timestamp_ms: 0,
            source,
        })
    }
}

impl Default for AudioRouter {
    fn default() -> Self {
        Self::new(AudioConfig::default())
    }
}

/// Normalize audio to 16kHz mono PCM
pub fn normalize_to_16khz_mono(samples: &[f32], original_rate: u32) -> Vec<i16> {
    let target_rate = 16000u32;

    // Resample if needed
    let resampled = if original_rate != target_rate {
        resample(samples, original_rate, target_rate)
    } else {
        samples.to_vec()
    };

    // Convert f32 [-1.0, 1.0] to i16 [-32768, 32767]
    resampled
        .iter()
        .map(|&s| (s * 32767.0).clamp(-32768.0, 32767.0) as i16)
        .collect()
}

/// Simple linear interpolation resampling
fn resample(samples: &[f32], from_rate: u32, to_rate: u32) -> Vec<f32> {
    if from_rate == to_rate {
        return samples.to_vec();
    }

    let ratio = from_rate as f64 / to_rate as f64;
    let output_len = (samples.len() as f64 / ratio) as usize;
    let mut output = Vec::with_capacity(output_len);

    for i in 0..output_len {
        let src_idx = (i as f64 * ratio) as usize;
        let src_idx_next = (src_idx + 1).min(samples.len() - 1);

        let t = (i as f64 * ratio) - src_idx as f64;
        let sample = samples[src_idx] * (1.0 - t as f32) + samples[src_idx_next] * t as f32;
        output.push(sample);
    }

    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_router_emits_correct_chunk_size() {
        let config = AudioConfig::default();
        let mut router = AudioRouter::new(config.clone());

        // Give exactly 100ms of samples
        let samples = vec![100i16; config.samples_per_chunk()];
        let frames = router.process(&samples, AudioSource::Microphone);

        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].samples.len(), config.samples_per_chunk());
    }

    #[test]
    fn test_normalize_preserves_signal() {
        let input = vec![0.5, -0.5, 0.0, 0.25];
        let output = normalize_to_16khz_mono(&input, 16000);

        assert_eq!(output.len(), 4);
        assert!((output[0] as f32 / 32767.0 - 0.5).abs() < 0.01);
        assert!((output[1] as f32 / 32767.0 + 0.5).abs() < 0.01);
    }
}
