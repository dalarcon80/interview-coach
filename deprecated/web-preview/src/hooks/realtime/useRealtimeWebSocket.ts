/**
 * useRealtimeWebSocket Hook
 * 
 * OFFICIAL frontend WebSocket hook for Interview Coach.
 * 
 * Architecture compliance:
 * - Native WebSocket against ws://localhost:8000/ws/pipeline
 * - Event protocol matches backend server.py EXACTLY
 * - Single source of truth for all realtime UI components
 * 
 * Backend Event Contract (from server.py):
 * 
 * Server -> Client events:
 * - connected: Initial connection confirmation
 * - session_started: {session_id, config, mode}
 * - analysis: {question_type, is_compound, sub_questions, underlying_intent, red_flags}
 * - suggestion: {mode, bullets, full_response, key_metrics, confidence, style, quality_passed, ...}
 * - session_ended: {summary}
 * - error: {message}
 * - pong: Heartbeat response
 * 
 * Client -> Server events:
 * - start_session: {config: {company_name, role_title, response_style, language_preference}}
 * - transcript_ready: {text, is_final, language}
 * - end_session: {}
 * - ping: {}
 */

'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { BACKEND } from '@/lib/backend-config';

// ============================================
// Types - Match backend server.py exactly
// ============================================

export interface WebSocketConfig {
  autoConnect?: boolean;
  maxReconnectAttempts?: number;
  reconnectBaseDelay?: number;
}

export interface CandidateContext {
  name: string;
  email?: string;
  phone?: string;
  currentRole?: string;
  currentCompany?: string;
  yearsExperience?: number;
  skills?: string[];
  achievements?: string[];
  education?: { degree: string; institution: string; year: string }[];
  languages?: string[];
  certifications?: string[];
  linkedinUrl?: string;
  portfolioUrl?: string;
  summary?: string;
  rawResume?: string;
}

export interface CompanyContext {
  companyName: string;
  industry?: string;
  companySize?: string;
  companyDescription?: string;
  companyValues?: string[];
  companyCulture?: string;
  positionTitle: string;
  positionLevel?: string;
  positionDepartment?: string;
  positionDescription?: string;
  positionRequirements?: string[];
  salaryRange?: string;
  location?: string;
  workMode?: string;
  jobPostingUrl?: string;
  notes?: string;
}

export interface SessionConfig {
  company_name: string;
  role_title: string;
  response_style?: 'executive' | 'commercial' | 'technical' | 'mixed';
  language_preference?: 'auto' | 'es' | 'en';
  // Full context objects for unified interview context flow
  candidate?: CandidateContext;
  company?: CompanyContext;
}

export interface AnalysisResult {
  question_type: string;
  is_compound: boolean;
  sub_questions: Array<{
    text: string;
    priority: string;
    weight: number;
  }>;
  underlying_intent: string[];
  red_flags: string[];
}

export interface SuggestionResult {
  stage?: 'bullets' | 'full';
  mode: 'demo' | 'real' | 'fallback';
  bullets: string[];
  full_response: string;
  key_metrics: string[];
  confidence: number;
  style: string;
  language: string;
  provider?: string;
  model?: string;
  quality_passed: boolean;
  quality_score: number;
  quality_issues: string[];
  latency_ms: number;
  processing_full_response?: boolean;
  bullets_latency_ms?: number;
  full_latency_ms?: number;
}

export interface TranscriptEntry {
  id: string;
  text: string;
  type: 'partial' | 'final';
  speaker?: 'interviewer' | 'candidate';
  language?: string;
  timestamp: number;
}

export interface SessionState {
  sessionId: string | null;
  mode: 'demo' | 'real' | null;
  active: boolean;
  config: SessionConfig | null;
  duration: number;
  exchangeCount: number;
}

export interface WebSocketState {
  connected: boolean;
  connecting: boolean;
  reconnecting: boolean;
  reconnectAttempts: number;
  error: string | null;
  lastHeartbeat: string | null;
}

export interface RealtimeState extends WebSocketState {
  session: SessionState;
  analysis: AnalysisResult | null;
  suggestion: SuggestionResult | null;
  transcripts: TranscriptEntry[];
  currentPartial: string | null;
  processing: boolean;
  averageLatency: number;
}

// ============================================
// Hook Implementation
// ============================================

export function useRealtimeWebSocket(config: WebSocketConfig = {}) {
  const {
    autoConnect = false,
    maxReconnectAttempts = 5,
    reconnectBaseDelay = 1000
  } = config;

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const sessionStartRef = useRef<Date | null>(null);
  const latencyHistoryRef = useRef<number[]>([]);

  const [state, setState] = useState<RealtimeState>({
    connected: false,
    connecting: false,
    reconnecting: false,
    reconnectAttempts: 0,
    error: null,
    lastHeartbeat: null,
    session: {
      sessionId: null,
      mode: null,
      active: false,
      config: null,
      duration: 0,
      exchangeCount: 0
    },
    analysis: null,
    suggestion: null,
    transcripts: [],
    currentPartial: null,
    processing: false,
    averageLatency: 0
  });

  // ============================================
  // Reconnection Logic
  // ============================================

  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (state.reconnectAttempts >= maxReconnectAttempts) {
      setState(prev => ({
        ...prev,
        reconnecting: false,
        error: 'Max reconnection attempts reached'
      }));
      return;
    }

    const delay = reconnectBaseDelay * Math.pow(2, state.reconnectAttempts);
    
    setState(prev => ({
      ...prev,
      reconnecting: true,
      reconnectAttempts: prev.reconnectAttempts + 1
    }));

    console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${state.reconnectAttempts + 1})`);

    reconnectTimeoutRef.current = setTimeout(() => {
      connect();
    }, delay);
  }, [state.reconnectAttempts, maxReconnectAttempts, reconnectBaseDelay]);

  // ============================================
  // Duration Timer
  // ============================================

  useEffect(() => {
    if (!state.session.active || !sessionStartRef.current) return;

    const interval = setInterval(() => {
      const duration = Math.floor((Date.now() - sessionStartRef.current!.getTime()) / 1000);
      setState(prev => ({
        ...prev,
        session: { ...prev.session, duration }
      }));
    }, 1000);

    return () => clearInterval(interval);
  }, [state.session.active]);

  // ============================================
  // Message Handler - Matches backend events
  // ============================================

  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      const eventType = data.type;

      console.log('[WebSocket] Received:', eventType);

      switch (eventType) {
        case 'connected':
          console.log('[WebSocket] Server confirmed connection');
          break;

        case 'pong':
        case 'heartbeat':
          setState(prev => ({
            ...prev,
            lastHeartbeat: new Date().toISOString()
          }));
          break;

        case 'session_started':
          sessionStartRef.current = new Date();
          setState(prev => ({
            ...prev,
            session: {
              sessionId: data.session_id,
              mode: data.mode,
              active: true,
              config: data.config,
              duration: 0,
              exchangeCount: 0
            },
            transcripts: [],
            currentPartial: null,
            analysis: null,
            suggestion: null,
            error: null
          }));
          break;

        case 'analysis':
          setState(prev => ({
            ...prev,
            analysis: {
              question_type: data.question_type,
              is_compound: data.is_compound,
              sub_questions: data.sub_questions || [],
              underlying_intent: data.underlying_intent || [],
              red_flags: data.red_flags || []
            },
            processing: true
          }));
          break;

        case 'suggestion':
          const isFullStage = (data.stage || 'full') === 'full';

          // Track latency for average (full-stage only)
          if (isFullStage && data.latency_ms) {
            latencyHistoryRef.current.push(data.latency_ms);
            if (latencyHistoryRef.current.length > 10) {
              latencyHistoryRef.current.shift();
            }
          }
          const avgLatency = latencyHistoryRef.current.length > 0
            ? Math.round(latencyHistoryRef.current.reduce((a, b) => a + b, 0) / latencyHistoryRef.current.length)
            : 0;

          setState(prev => ({
            ...prev,
            suggestion: {
              mode: data.mode,
              stage: data.stage || 'full',
              bullets: data.bullets || [],
              full_response: data.full_response || '',
              key_metrics: data.key_metrics || [],
              confidence: data.confidence || 0.5,
              style: data.style,
              language: data.language,
              provider: data.provider,
              model: data.model,
              quality_passed: data.quality_passed,
              quality_score: data.quality_score,
              quality_issues: data.quality_issues || [],
              latency_ms: data.latency_ms,
              processing_full_response: data.processing_full_response,
              bullets_latency_ms: data.bullets_latency_ms,
              full_latency_ms: data.full_latency_ms,
            },
            processing: data.processing_full_response ?? !isFullStage,
            averageLatency: avgLatency,
            session: {
              ...prev.session,
              exchangeCount: isFullStage ? prev.session.exchangeCount + 1 : prev.session.exchangeCount
            }
          }));
          break;

        case 'session_ended':
          sessionStartRef.current = null;
          setState(prev => ({
            ...prev,
            session: {
              sessionId: null,
              mode: null,
              active: false,
              config: null,
              duration: 0,
              exchangeCount: 0
            },
            analysis: null,
            suggestion: null,
            transcripts: [],
            currentPartial: null
          }));
          break;

        case 'error':
          setState(prev => ({
            ...prev,
            error: data.message || 'Unknown error',
            processing: false
          }));
          break;

        default:
          console.log('[WebSocket] Unknown event type:', eventType);
      }
    } catch (e) {
      console.error('[WebSocket] Failed to parse message:', e);
    }
  }, []);

  // ============================================
  // Connection Management
  // ============================================

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) return;

    setState(prev => ({ ...prev, connecting: true, error: null }));

    try {
      const socket = new WebSocket(BACKEND.wsPipeline);
      socketRef.current = socket;

      socket.onopen = () => {
        console.log('[WebSocket] Connected to', BACKEND.wsPipeline);
        clearReconnectTimeout();
        setState(prev => ({
          ...prev,
          connected: true,
          connecting: false,
          reconnecting: false,
          reconnectAttempts: 0,
          error: null
        }));
      };

      socket.onclose = (event) => {
        console.log('[WebSocket] Disconnected:', event.reason);
        setState(prev => ({
          ...prev,
          connected: false,
          connecting: false,
          session: { ...prev.session, active: false }
        }));

        if (event.code !== 1000) {
          scheduleReconnect();
        }
      };

      socket.onerror = () => {
        console.error('[WebSocket] Connection error');
        setState(prev => ({
          ...prev,
          connected: false,
          connecting: false,
          error: 'WebSocket connection error'
        }));
      };

      socket.onmessage = handleMessage;
    } catch (error) {
      console.error('[WebSocket] Failed to create connection:', error);
      setState(prev => ({
        ...prev,
        connected: false,
        connecting: false,
        error: error instanceof Error ? error.message : 'Connection failed'
      }));
      scheduleReconnect();
    }
  }, [handleMessage, clearReconnectTimeout, scheduleReconnect]);

  const disconnect = useCallback(() => {
    clearReconnectTimeout();
    
    if (socketRef.current) {
      socketRef.current.close(1000, 'Client disconnect');
      socketRef.current = null;
    }
    
    setState({
      connected: false,
      connecting: false,
      reconnecting: false,
      reconnectAttempts: 0,
      error: null,
      lastHeartbeat: null,
      session: { sessionId: null, mode: null, active: false, config: null, duration: 0, exchangeCount: 0 },
      analysis: null,
      suggestion: null,
      transcripts: [],
      currentPartial: null,
      processing: false,
      averageLatency: 0
    });
  }, [clearReconnectTimeout]);

  // ============================================
  // Send Messages - Match backend protocol
  // ============================================

  const send = useCallback((type: string, payload: Record<string, unknown> = {}) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      console.warn(`[WebSocket] Cannot send "${type}": not connected`);
      return false;
    }
    
    const message = JSON.stringify({ type, ...payload });
    socketRef.current.send(message);
    return true;
  }, []);

  const startSession = useCallback((sessionConfig: SessionConfig) => {
    latencyHistoryRef.current = [];
    setState(prev => ({ 
      ...prev, 
      processing: false, 
      analysis: null, 
      suggestion: null,
      transcripts: [],
      session: {
        ...prev.session,
        config: sessionConfig
      }
    }));
    return send('start_session', { config: sessionConfig });
  }, [send]);

  const sendTranscript = useCallback((text: string, isFinal: boolean = true, language?: string) => {
    // Add to transcript history
    const entry: TranscriptEntry = {
      id: `transcript-${Date.now()}`,
      text,
      type: isFinal ? 'final' : 'partial',
      speaker: 'interviewer',
      language,
      timestamp: Date.now()
    };

    if (isFinal) {
      setState(prev => ({
        ...prev,
        transcripts: [...prev.transcripts, entry],
        currentPartial: null
      }));
    } else {
      setState(prev => ({
        ...prev,
        currentPartial: text
      }));
    }

    return send('transcript_ready', { 
      text, 
      is_final: isFinal,
      language 
    });
  }, [send]);

  const endSession = useCallback(() => {
    return send('end_session');
  }, [send]);

  const ping = useCallback(() => {
    return send('ping');
  }, [send]);

  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }));
  }, []);

  const clearSuggestion = useCallback(() => {
    setState(prev => ({ ...prev, suggestion: null, analysis: null }));
  }, []);

  // ============================================
  // Lifecycle
  // ============================================

  useEffect(() => {
    if (autoConnect) {
      const timeoutId = setTimeout(() => {
        connect();
      }, 0);
      
      return () => {
        clearTimeout(timeoutId);
        disconnect();
      };
    }
    
    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  // ============================================
  // Return
  // ============================================

  return {
    // Connection state
    connected: state.connected,
    connecting: state.connecting,
    reconnecting: state.reconnecting,
    error: state.error,
    lastHeartbeat: state.lastHeartbeat,
    
    // Session state
    session: state.session,
    
    // Realtime data
    analysis: state.analysis,
    suggestion: state.suggestion,
    transcripts: state.transcripts,
    currentPartial: state.currentPartial,
    processing: state.processing,
    averageLatency: state.averageLatency,
    
    // Connection actions
    connect,
    disconnect,
    ping,
    
    // Session actions
    startSession,
    endSession,
    sendTranscript,
    
    // Utility
    clearError,
    clearSuggestion
  };
}

export default useRealtimeWebSocket;
