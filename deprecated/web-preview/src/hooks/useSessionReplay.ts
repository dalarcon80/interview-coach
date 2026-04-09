/**
 * Interview Coach - Session Replay Hook
 * 
 * Provides functionality to replay interview sessions
 * and track question/answer history
 */

import { useState, useCallback, useEffect } from 'react';

export interface ReplayExchange {
  id: string;
  timestamp: string;
  question: string;
  answer: string;
  style: string;
  latency_ms: number;
}

export interface SessionReplay {
  id: string;
  name: string;
  createdAt: string;
  profile: {
    name: string;
    role: string;
    company: string;
    targetCompany: string;
    targetPosition: string;
  };
  exchanges: ReplayExchange[];
}

interface UseSessionReplayReturn {
  currentReplay: SessionReplay | null;
  currentExchangeIndex: number;
  isReplaying: boolean;
  startReplay: (session: SessionReplay) => void;
  stopReplay: () => void;
  nextExchange: () => void;
  prevExchange: () => void;
  goToExchange: (index: number) => void;
  currentExchange: ReplayExchange | null;
  progress: number;
  totalExchanges: number;
}

const REPLAY_STORAGE_KEY = 'interview-replay-history';

export function useSessionReplay(): UseSessionReplayReturn {
  const [currentReplay, setCurrentReplay] = useState<SessionReplay | null>(null);
  const [currentExchangeIndex, setCurrentExchangeIndex] = useState(0);
  const [isReplaying, setIsReplaying] = useState(false);
  
  const startReplay = useCallback((session: SessionReplay) => {
    // Build replay from session
    const replay: SessionReplay = {
      id: session.id,
      name: session.name,
      createdAt: session.createdAt,
      profile: {
        name: session.profile?.name || '',
        role: session.profile?.role || '',
        company: session.profile?.company || '',
        targetCompany: session.profile?.targetCompany || '',
        targetPosition: session.profile?.targetPosition || '',
      },
      exchanges: session.exchanges || [],
    };
    
    setCurrentReplay(replay);
    setCurrentExchangeIndex(0);
    setIsReplaying(true);
  }, []);
  
  const stopReplay = useCallback(() => {
    setCurrentReplay(null);
    setCurrentExchangeIndex(0);
    setIsReplaying(false);
  }, []);
  
  const nextExchange = useCallback(() => {
    if (!currentReplay) return;
    
    if (currentExchangeIndex < currentReplay.exchanges.length - 1) {
      setCurrentExchangeIndex(prev => prev + 1);
    }
  }, [currentReplay, currentExchangeIndex]);
  
  const prevExchange = useCallback(() => {
    if (currentExchangeIndex > 0) {
      setCurrentExchangeIndex(prev => prev - 1);
    }
  }, [currentExchangeIndex]);
  
  const goToExchange = useCallback((index: number) => {
    if (!currentReplay) return;
    
    if (index >= 0 && index < currentReplay.exchanges.length) {
      setCurrentExchangeIndex(index);
    }
  }, [currentReplay]);
  
  const currentExchange = currentReplay?.exchanges[currentExchangeIndex] || null;
  const progress = currentReplay 
    ? ((currentExchangeIndex + 1) / currentReplay.exchanges.length) * 100 
    : 0;
  const totalExchanges = currentReplay?.exchanges.length || 0;
  
  return {
    currentReplay,
    currentExchangeIndex,
    isReplaying,
    startReplay,
    stopReplay,
    nextExchange,
    prevExchange,
    goToExchange,
    currentExchange,
    progress,
    totalExchanges,
  };
}

// Helper to record exchanges during a live interview
export function useExchangeRecorder() {
  const [exchanges, setExchanges] = useState<ReplayExchange[]>([]);
  
  const recordExchange = useCallback((question: string, answer: string, style: string, latency_ms: number) => {
    const exchange: ReplayExchange = {
      id: Date.now().toString(),
      timestamp: new Date().toISOString(),
      question,
      answer,
      style,
      latency_ms,
    };
    
    setExchanges(prev => [...prev, exchange]);
    return exchange;
  }, []);
  
  const clearExchanges = useCallback(() => {
    setExchanges([]);
  }, []);
  
  const getExchanges = useCallback(() => exchanges, [exchanges]);
  
  return {
    exchanges,
    recordExchange,
    clearExchanges,
    getExchanges,
  };
}
