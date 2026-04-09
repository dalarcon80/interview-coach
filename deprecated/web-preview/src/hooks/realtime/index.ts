/**
 * Realtime Hooks Exports
 * 
 * Unified WebSocket connection using native WebSocket.
 * Matches Python backend protocol exactly.
 */

export { useRealtime } from './useRealtime';
export type {
  TranscriptEvent,
  SuggestionEvent,
  SessionConfig,
  RealtimeState,
  UseRealtimeOptions
} from './useRealtime';

export { useRealtimeWebSocket } from './useRealtimeWebSocket';
export type {
  WebSocketConfig,
  WebSocketState,
  WebSocketEventHandlers,
  EventCallback
} from './useRealtimeWebSocket';
