"use client";

import { useState, useEffect, useRef, useCallback } from "react";

// Types for transcript entries
interface TranscriptEntry {
  id: string;
  speaker: "interviewer" | "candidate" | "system";
  text: string;
  timestamp: number;
  isFinal: boolean;
}

// Live entry that updates in real-time with partials
interface LiveEntry {
  speaker: "interviewer" | "candidate" | "system";
  finalText: string;
  partialText: string;
  timestamp: number;
}

interface SuggestionData {
  full_response: string;
  bullets_preview: string[];
  mode: "real" | "demo" | "fallback";
  latency_ms?: number;
}

export default function HomePage() {
  // WebSocket state
  const [wsConnected, setWsConnected] = useState(false);
  const [wsConnecting, setWsConnecting] = useState(false);
  const [wsError, setWsError] = useState<string | null>(null);
  
  // Transcript state - frozen finalized entries
  const [transcriptEntries, setTranscriptEntries] = useState<TranscriptEntry[]>([]);
  
  // Live entry - updates in real-time with partials
  const [liveEntry, setLiveEntry] = useState<LiveEntry | null>(null);
  
  // Ref to track the previous live entry for atomic updates
  const prevLiveEntryRef = useRef<LiveEntry | null>(null);
  
  // Suggestion state
  const [suggestion, setSuggestion] = useState<SuggestionData | null>(null);
  
  // Session state
  const [sessionActive, setSessionActive] = useState(false);
  const [backendUrl, setBackendUrl] = useState("http://localhost:8000");
  
  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);

  // Helper to convert backend URL to WebSocket URL
  const wsUrlFromBackendUrl = (url: string) => {
    const wsUrl = url.replace(/^http/, "ws").replace(/\/$/, "");
    return `${wsUrl}/ws/realtime`;
  };

  // WebSocket message handler with transcript consolidation
  const handleWsMessage = useCallback((event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      const eventType = data.type;

      if (eventType === "transcript") {
        const text = typeof data.text === "string" ? data.text.trim() : "";
        if (!text) return;

        const rawSpeaker =
          typeof data.speaker === "string" ? data.speaker.toLowerCase() : "unknown";
        const speaker: TranscriptEntry["speaker"] =
          rawSpeaker === "interviewer" ? "interviewer" :
          rawSpeaker === "candidate" ? "candidate" :
          rawSpeaker === "system" ? "system" : "system";

        const isFinal = data.is_final === true;
        const utteranceComplete = data.utterance_complete === true;
        const now = Date.now();

        // Two-layer transcript handling:
        // 1. Live entry updates in real-time with partials
        // 2. Frozen entries are finalized when speaker stops or changes
        
        // Get the current live entry from ref for decision making
        const prevLive = prevLiveEntryRef.current;
        
        // Check if we need to start a new entry (speaker change or utterance complete)
        const needsNewEntry = 
          !prevLive || 
          prevLive.speaker !== speaker ||
          utteranceComplete;

        let frozenEntriesToAdd: TranscriptEntry[] = [];
        
        if (needsNewEntry && prevLive) {
          // Freeze the current live entry
          const frozenText = prevLive.finalText.trim();
          if (frozenText) {
            frozenEntriesToAdd = [{
              id: `transcript-${prevLive.timestamp}`,
              text: frozenText,
              timestamp: prevLive.timestamp,
              speaker: prevLive.speaker,
              isFinal: true,
            }];
          }
        }

        // Create or update the live entry
        const liveEntrySpeaker = needsNewEntry ? speaker : (prevLive?.speaker || speaker);
        const liveEntryTimestamp = needsNewEntry ? now : (prevLive?.timestamp || now);
        
        let newLiveEntry: LiveEntry;
        
        if (isFinal) {
          // Final text: append to finalText, clear partial
          const newFinalText = prevLive 
            ? prevLive.finalText + " " + text 
            : text;
          newLiveEntry = {
            speaker: liveEntrySpeaker,
            finalText: newFinalText.trim(),
            partialText: "",
            timestamp: liveEntryTimestamp,
          };
        } else {
          // Partial text: replace (Deepgram partials contain full interim text)
          const currentFinalText = prevLive?.finalText || "";
          newLiveEntry = {
            speaker: liveEntrySpeaker,
            finalText: currentFinalText,
            partialText: text,
            timestamp: liveEntryTimestamp,
          };
        }

        // Update both states
        prevLiveEntryRef.current = newLiveEntry;
        setLiveEntry(newLiveEntry);
        
        if (frozenEntriesToAdd.length > 0) {
          setTranscriptEntries((prev) => [...prev, ...frozenEntriesToAdd]);
        }
        
        return;
      }

      if (eventType === "suggestion") {
        const fullResponse =
          typeof data.full_response === "string"
            ? data.full_response
            : typeof data.fullResponse === "string"
            ? data.fullResponse
            : "";
        const bulletsPreview = Array.isArray(data.bullets_preview)
          ? data.bullets_preview.filter((v: unknown): v is string => typeof v === "string")
          : Array.isArray(data.bullets)
          ? data.bullets.filter((v: unknown): v is string => typeof v === "string")
          : [];

        setSuggestion({
          full_response: fullResponse,
          bullets_preview: bulletsPreview,
          mode: data.mode === "real" || data.mode === "fallback" ? data.mode : "demo",
          latency_ms: typeof data.latency_ms === "number" ? data.latency_ms : undefined,
        });
        return;
      }

      if (eventType === "error") {
        setWsError(typeof data.message === "string" ? data.message : "Unknown error");
        return;
      }
    } catch (err) {
      console.error("WebSocket message parse error:", err);
    }
  }, []);

  // Connect to WebSocket
  const connectWebSocket = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    setWsConnecting(true);
    setWsError(null);

    try {
      const socket = new WebSocket(wsUrlFromBackendUrl(backendUrl));
      wsRef.current = socket;

      socket.onopen = () => {
        setWsConnected(true);
        setWsConnecting(false);
        console.log("WebSocket connected");
      };

      socket.onclose = () => {
        setWsConnected(false);
        setWsConnecting(false);
        console.log("WebSocket disconnected");
      };

      socket.onerror = () => {
        setWsConnecting(false);
        setWsError("WebSocket connection error");
      };

      socket.onmessage = handleWsMessage;
    } catch (error) {
      setWsConnecting(false);
      const message = error instanceof Error ? error.message : "Failed to connect WebSocket";
      setWsError(message);
    }
  }, [backendUrl, handleWsMessage]);

  // Disconnect WebSocket
  const disconnectWebSocket = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setWsConnected(false);
  }, []);

  // Send message via WebSocket
  const sendWs = useCallback((type: string, payload: Record<string, unknown> = {}) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
    wsRef.current.send(JSON.stringify({ type, ...payload }));
    return true;
  }, []);

  // Start live session
  const startSession = useCallback(() => {
    if (!wsConnected) {
      setWsError("Connect WebSocket before starting a live session");
      return;
    }

    setTranscriptEntries([]);
    setLiveEntry(null);
    prevLiveEntryRef.current = null;
    setSuggestion(null);
    setSessionActive(true);

    sendWs("start_session", {
      mode: "real",
    });
  }, [wsConnected, sendWs]);

  // Stop session
  const stopSession = useCallback(() => {
    sendWs("stop_session", {});
    setSessionActive(false);
  }, [sendWs]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnectWebSocket();
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, [disconnectWebSocket]);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <h1 className="text-2xl font-bold text-gray-900">Interview Coach - Web Preview</h1>
          <p className="text-sm text-gray-500">Real-time interview coaching</p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        {/* Connection Controls */}
        <div className="bg-white rounded-lg shadow p-4 mb-6">
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Backend URL
              </label>
              <input
                type="text"
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md"
                placeholder="http://localhost:8000"
              />
            </div>

            <div className="flex items-end gap-2">
              {!wsConnected ? (
                <button
                  onClick={connectWebSocket}
                  disabled={wsConnecting}
                  className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
                >
                  {wsConnecting ? "Connecting..." : "Connect WebSocket"}
                </button>
              ) : (
                <button
                  onClick={disconnectWebSocket}
                  className="px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50"
                >
                  Disconnect
                </button>
              )}

              {!sessionActive ? (
                <button
                  onClick={startSession}
                  disabled={!wsConnected}
                  className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
                >
                  Start Session
                </button>
              ) : (
                <button
                  onClick={stopSession}
                  className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700"
                >
                  Stop Session
                </button>
              )}
            </div>
          </div>

          {wsError && (
            <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-md">
              <p className="text-sm text-red-600">{wsError}</p>
            </div>
          )}
        </div>

        {/* Live Transcript Panel */}
        <div className="bg-white rounded-lg shadow mb-6">
          <div className="px-4 py-3 border-b">
            <h2 className="text-lg font-semibold">Live Transcript</h2>
          </div>
          <div className="p-4 max-h-96 overflow-y-auto">
            {transcriptEntries.length === 0 && !liveEntry ? (
              <p className="text-sm text-gray-500">No transcript entries yet.</p>
            ) : (
              <div className="space-y-3">
                {/* Frozen transcript entries */}
                {transcriptEntries.map((entry) => (
                  <div
                    key={entry.id}
                    className={`p-3 rounded-lg ${
                      entry.speaker === "interviewer"
                        ? "bg-blue-50 ml-8"
                        : entry.speaker === "candidate"
                        ? "bg-green-50 mr-8"
                        : "bg-gray-50"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium capitalize">
                        {entry.speaker}
                      </span>
                      <span className="text-xs text-gray-400">
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-sm">{entry.text}</p>
                  </div>
                ))}

                {/* Live entry - updates in real-time */}
                {liveEntry && (
                  <div
                    className={`p-3 rounded-lg border-2 ${
                      liveEntry.speaker === "interviewer"
                        ? "bg-blue-50 ml-8 border-blue-300"
                        : liveEntry.speaker === "candidate"
                        ? "bg-green-50 mr-8 border-green-300"
                        : "bg-gray-50 border-gray-300"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium capitalize flex items-center gap-2">
                        {liveEntry.speaker}
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 animate-pulse">
                          LIVE
                        </span>
                      </span>
                      <span className="text-xs text-gray-400">
                        {new Date(liveEntry.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-sm">
                      {liveEntry.finalText}
                      {liveEntry.partialText && (
                        <span className="italic text-gray-500"> {liveEntry.partialText}</span>
                      )}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Suggestion Panel */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-4 py-3 border-b">
            <h2 className="text-lg font-semibold">Coach Suggestion</h2>
            {suggestion?.latency_ms && (
              <span className="text-xs text-gray-500">
                Latency: {suggestion.latency_ms}ms
              </span>
            )}
          </div>
          <div className="p-4">
            {suggestion ? (
              <div>
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Full Response</h3>
                  <p className="text-sm text-gray-900 whitespace-pre-wrap">
                    {suggestion.full_response}
                  </p>
                </div>
                {suggestion.bullets_preview.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-gray-700 mb-2">Key Points</h3>
                    <ul className="list-disc list-inside text-sm text-gray-600">
                      {suggestion.bullets_preview.map((bullet, index) => (
                        <li key={index}>{bullet}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500">No suggestions yet. Start a session to receive coaching.</p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
