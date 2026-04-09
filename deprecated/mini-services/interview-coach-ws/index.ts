/**
 * Interview Coach WebSocket Service
 * Port: 3003
 * 
 * Real-time communication layer for interview coaching.
 * Handles transcript streaming, suggestions delivery, and session management.
 * 
 * Architecture compliance:
 * - Single WebSocket endpoint at root path "/"
 * - Uses XTransformPort query parameter for gateway routing
 * - Stateless connection handling
 */

import { Server } from "socket.io";

// ============================================
// Types
// ============================================
interface TranscriptEvent {
  type: 'partial' | 'final';
  text: string;
  language?: string;
  speaker?: 'interviewer' | 'candidate';
  timestamp: number;
}

interface SuggestionEvent {
  sessionId: string;
  bullets: string[];
  fullResponse?: string;
  confidence: number;
  latencyMs: number;
  timestamp: number;
}

interface SessionState {
  id: string;
  companyName: string;
  roleTitle: string;
  responseStyle: 'executive' | 'commercial' | 'technical' | 'mixed';
  languagePreference: string;
  exchanges: Exchange[];
  conversationMap: ConversationMap;
  createdAt: Date;
  updatedAt: Date;
}

interface Exchange {
  index: number;
  question: string;
  languageDetected: string;
  bullets: string[];
  suggestedResponse: string;
  userActualResponse?: string;
  latencyMs: number;
  timestamp: Date;
}

interface ConversationMap {
  claims: string[];
  metricsUsed: string[];
  achievementsReferenced: string[];
  uncoveredGaps: string[];
  interviewerValues: string[];
  warnings: string[];
}

// ============================================
// In-memory Session Storage
// ============================================
const sessions: Map<string, SessionState> = new Map();

// ============================================
// Socket.IO Server
// ============================================
const io = new Server(3003, {
  cors: {
    origin: "*",
    methods: ["GET", "POST"]
  },
  // Gateway compatibility - root path
  path: "/"
});

console.log('🚀 Interview Coach WebSocket Service running on port 3003');

// ============================================
// Connection Handling
// ============================================
io.on("connection", (socket) => {
  console.log(`Client connected: ${socket.id}`);
  
  let currentSessionId: string | null = null;

  // =====================
  // Session Management
  // =====================
  socket.on("session:start", (config: {
    companyName: string;
    roleTitle: string;
    responseStyle?: string;
    languagePreference?: string;
  }) => {
    const sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    const session: SessionState = {
      id: sessionId,
      companyName: config.companyName,
      roleTitle: config.roleTitle,
      responseStyle: (config.responseStyle as SessionState['responseStyle']) || 'mixed',
      languagePreference: config.languagePreference || 'auto',
      exchanges: [],
      conversationMap: {
        claims: [],
        metricsUsed: [],
        achievementsReferenced: [],
        uncoveredGaps: [],
        interviewerValues: [],
        warnings: []
      },
      createdAt: new Date(),
      updatedAt: new Date()
    };
    
    sessions.set(sessionId, session);
    currentSessionId = sessionId;
    socket.join(sessionId);
    
    socket.emit("session:started", {
      sessionId,
      config: {
        companyName: session.companyName,
        roleTitle: session.roleTitle,
        responseStyle: session.responseStyle,
        languagePreference: session.languagePreference
      }
    });
    
    console.log(`Session started: ${sessionId}`);
  });

  socket.on("session:join", (sessionId: string) => {
    const session = sessions.get(sessionId);
    if (session) {
      currentSessionId = sessionId;
      socket.join(sessionId);
      socket.emit("session:joined", { sessionId, session });
    } else {
      socket.emit("error", { message: "Session not found" });
    }
  });

  socket.on("session:end", () => {
    if (currentSessionId) {
      const session = sessions.get(currentSessionId);
      if (session) {
        session.updatedAt = new Date();
        socket.emit("session:ended", { 
          sessionId: currentSessionId,
          summary: {
            totalExchanges: session.exchanges.length,
            duration: Date.now() - session.createdAt.getTime()
          }
        });
      }
      socket.leave(currentSessionId);
      currentSessionId = null;
    }
  });

  // =====================
  // Transcript Handling
  // =====================
  socket.on("transcript:partial", (data: Omit<TranscriptEvent, 'type' | 'timestamp'>) => {
    if (!currentSessionId) return;
    
    const event: TranscriptEvent = {
      type: 'partial',
      text: data.text,
      language: data.language,
      speaker: data.speaker,
      timestamp: Date.now()
    };
    
    // Broadcast to session room (for potential multiple clients)
    io.to(currentSessionId).emit("transcript:partial", event);
    
    // TODO: Trigger speculative work (intent classification, evidence prefetch)
  });

  socket.on("transcript:final", async (data: Omit<TranscriptEvent, 'type' | 'timestamp'>) => {
    if (!currentSessionId) return;
    
    const session = sessions.get(currentSessionId);
    if (!session) return;
    
    const startTime = Date.now();
    
    const event: TranscriptEvent = {
      type: 'final',
      text: data.text,
      language: data.language,
      speaker: data.speaker,
      timestamp: startTime
    };
    
    // Notify processing started
    io.to(currentSessionId).emit("processing:started", {
      question: data.text,
      timestamp: startTime
    });
    
    // Call the coaching API for suggestion
    try {
      const response = await fetch('http://localhost:8001/api/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          questionText: data.text,
          style: session.responseStyle,
          language: data.language || session.languagePreference,
          company: {
            companyName: session.companyName,
            positionTitle: session.roleTitle
          }
        })
      });
      
      const result = await response.json();
      
      if (result.success && result.suggestion) {
        const latencyMs = Date.now() - startTime;
        
        // Create exchange record
        const exchange: Exchange = {
          index: session.exchanges.length,
          question: data.text,
          languageDetected: data.language || 'es',
          bullets: result.suggestion.bullets || [],
          suggestedResponse: result.suggestion.suggestedAnswer || '',
          latencyMs,
          timestamp: new Date()
        };
        
        session.exchanges.push(exchange);
        session.updatedAt = new Date();
        
        // Send bullets first (faster display)
        io.to(currentSessionId).emit("suggestion:bullets", {
          exchangeIndex: exchange.index,
          bullets: exchange.bullets,
          latencyMs
        });
        
        // Then send full response
        io.to(currentSessionId).emit("suggestion:response", {
          exchangeIndex: exchange.index,
          fullResponse: exchange.suggestedResponse,
          confidence: result.suggestion.confidence || 0.8,
          latencyMs
        });
      } else {
        io.to(currentSessionId).emit("error", {
          message: result.error || "Failed to generate suggestion"
        });
      }
    } catch (error) {
      console.error('Error calling coaching API:', error);
      io.to(currentSessionId).emit("error", {
        message: "Failed to process question"
      });
    }
  });

  // =====================
  // User Response Tracking
  // =====================
  socket.on("user:response", (data: { exchangeIndex: number; text: string }) => {
    if (!currentSessionId) return;
    
    const session = sessions.get(currentSessionId);
    if (!session) return;
    
    const exchange = session.exchanges[data.exchangeIndex];
    if (exchange) {
      exchange.userActualResponse = data.text;
      session.updatedAt = new Date();
      
      // TODO: Update conversation map with claims, metrics, etc.
      
      socket.emit("user:response:recorded", {
        exchangeIndex: data.exchangeIndex,
        recorded: true
      });
    }
  });

  // =====================
  // Ping/Pong
  // =====================
  socket.on("ping", () => {
    socket.emit("pong", { timestamp: Date.now() });
  });

  // =====================
  // Disconnect
  // =====================
  socket.on("disconnect", () => {
    console.log(`Client disconnected: ${socket.id}`);
    if (currentSessionId) {
      socket.leave(currentSessionId);
    }
  });
});

// ============================================
// Health Check HTTP Server
// ============================================
// Socket.IO doesn't expose HTTP directly, but we can use adapter
setInterval(() => {
  console.log(`📊 Active sessions: ${sessions.size}, Connections: ${io.sockets.sockets.size}`);
}, 60000);

export { io, sessions };
