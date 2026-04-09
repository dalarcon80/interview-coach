/**
 * Interview Coach - Session Store
 * 
 * File-based session persistence with in-memory cache.
 * Provides durable storage for interview sessions.
 * 
 * Architecture compliance:
 * - No database dependencies (file-based for V1)
 * - PostgreSQL migration path ready
 */

import fs from 'fs';
import path from 'path';

// ============================================
// Types
// ============================================
export interface Exchange {
  index: number;
  question: string;
  languageDetected: string;
  bullets: string[];
  suggestedResponse: string;
  userActualResponse?: string;
  qualityScore?: number;
  latencyMs: number;
  timestamp: string;
}

export interface ConversationMap {
  claims: string[];
  metricsUsed: string[];
  achievementsReferenced: string[];
  uncoveredGaps: string[];
  interviewerValues: string[];
  warnings: string[];
}

export interface InterviewSession {
  id: string;
  companyName: string;
  roleTitle: string;
  jobDescription?: string;
  responseStyle: 'executive' | 'commercial' | 'technical' | 'mixed';
  languagePreference: string;
  status: 'active' | 'paused' | 'completed';
  exchanges: Exchange[];
  conversationMap: ConversationMap;
  createdAt: string;
  updatedAt: string;
}

// ============================================
// Configuration
// ============================================
const SESSIONS_DIR = path.join(process.cwd(), 'data', 'sessions');

// Ensure directory exists
function ensureSessionsDir(): void {
  if (!fs.existsSync(SESSIONS_DIR)) {
    fs.mkdirSync(SESSIONS_DIR, { recursive: true });
  }
}

// ============================================
// In-memory Cache
// ============================================
const sessionCache: Map<string, InterviewSession> = new Map();

// ============================================
// Session Operations
// ============================================

/**
 * Create a new interview session
 */
export function createSession(config: {
  companyName: string;
  roleTitle: string;
  jobDescription?: string;
  responseStyle?: string;
  languagePreference?: string;
}): InterviewSession {
  ensureSessionsDir();
  
  const id = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  const now = new Date().toISOString();
  
  const session: InterviewSession = {
    id,
    companyName: config.companyName,
    roleTitle: config.roleTitle,
    jobDescription: config.jobDescription,
    responseStyle: (config.responseStyle as InterviewSession['responseStyle']) || 'mixed',
    languagePreference: config.languagePreference || 'auto',
    status: 'active',
    exchanges: [],
    conversationMap: {
      claims: [],
      metricsUsed: [],
      achievementsReferenced: [],
      uncoveredGaps: [],
      interviewerValues: [],
      warnings: []
    },
    createdAt: now,
    updatedAt: now
  };
  
  // Save to cache and file
  sessionCache.set(id, session);
  saveSessionToFile(session);
  
  return session;
}

/**
 * Get session by ID
 */
export function getSession(id: string): InterviewSession | null {
  // Check cache first
  if (sessionCache.has(id)) {
    return sessionCache.get(id) || null;
  }
  
  // Load from file
  const session = loadSessionFromFile(id);
  if (session) {
    sessionCache.set(id, session);
  }
  
  return session;
}

/**
 * Update session
 */
export function updateSession(id: string, updates: Partial<InterviewSession>): InterviewSession | null {
  const session = getSession(id);
  if (!session) return null;
  
  const updated: InterviewSession = {
    ...session,
    ...updates,
    updatedAt: new Date().toISOString()
  };
  
  sessionCache.set(id, updated);
  saveSessionToFile(updated);
  
  return updated;
}

/**
 * Delete session
 */
export function deleteSession(id: string): boolean {
  sessionCache.delete(id);
  
  const filePath = path.join(SESSIONS_DIR, `${id}.json`);
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
    return true;
  }
  
  return false;
}

/**
 * List all sessions
 */
export function listSessions(): InterviewSession[] {
  ensureSessionsDir();
  
  const files = fs.readdirSync(SESSIONS_DIR).filter(f => f.endsWith('.json'));
  const sessions: InterviewSession[] = [];
  
  for (const file of files) {
    const id = file.replace('.json', '');
    const session = getSession(id);
    if (session) {
      sessions.push(session);
    }
  }
  
  return sessions.sort((a, b) => 
    new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  );
}

// ============================================
// Exchange Operations
// ============================================

/**
 * Add exchange to session
 */
export function addExchange(sessionId: string, exchange: Omit<Exchange, 'index' | 'timestamp'>): Exchange | null {
  const session = getSession(sessionId);
  if (!session) return null;
  
  const newExchange: Exchange = {
    ...exchange,
    index: session.exchanges.length,
    timestamp: new Date().toISOString()
  };
  
  session.exchanges.push(newExchange);
  session.updatedAt = new Date().toISOString();
  
  saveSessionToFile(session);
  
  return newExchange;
}

/**
 * Update exchange in session
 */
export function updateExchange(sessionId: string, exchangeIndex: number, updates: Partial<Exchange>): boolean {
  const session = getSession(sessionId);
  if (!session) return false;
  
  if (exchangeIndex < 0 || exchangeIndex >= session.exchanges.length) return false;
  
  session.exchanges[exchangeIndex] = {
    ...session.exchanges[exchangeIndex],
    ...updates
  };
  session.updatedAt = new Date().toISOString();
  
  saveSessionToFile(session);
  
  return true;
}

// ============================================
// Conversation Map Operations
// ============================================

/**
 * Update conversation map
 */
export function updateConversationMap(sessionId: string, updates: Partial<ConversationMap>): boolean {
  const session = getSession(sessionId);
  if (!session) return false;
  
  session.conversationMap = {
    ...session.conversationMap,
    ...updates
  };
  session.updatedAt = new Date().toISOString();
  
  saveSessionToFile(session);
  
  return true;
}

// ============================================
// Export/Import
// ============================================

/**
 * Export session as JSON
 */
export function exportSession(id: string): string | null {
  const session = getSession(id);
  if (!session) return null;
  
  return JSON.stringify(session, null, 2);
}

/**
 * Import session from JSON
 */
export function importSession(json: string): InterviewSession | null {
  try {
    const session = JSON.parse(json) as InterviewSession;
    
    // Validate required fields
    if (!session.id || !session.companyName || !session.roleTitle) {
      throw new Error('Invalid session data');
    }
    
    // Generate new ID to avoid conflicts
    const newId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    session.id = newId;
    session.createdAt = new Date().toISOString();
    session.updatedAt = new Date().toISOString();
    
    sessionCache.set(newId, session);
    saveSessionToFile(session);
    
    return session;
  } catch (error) {
    console.error('Failed to import session:', error);
    return null;
  }
}

// ============================================
// File Operations
// ============================================

function saveSessionToFile(session: InterviewSession): void {
  ensureSessionsDir();
  
  const filePath = path.join(SESSIONS_DIR, `${session.id}.json`);
  fs.writeFileSync(filePath, JSON.stringify(session, null, 2));
}

function loadSessionFromFile(id: string): InterviewSession | null {
  try {
    const filePath = path.join(SESSIONS_DIR, `${id}.json`);
    if (!fs.existsSync(filePath)) return null;
    
    const content = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(content) as InterviewSession;
  } catch (error) {
    console.error(`Failed to load session ${id}:`, error);
    return null;
  }
}

// ============================================
// Cleanup
// ============================================

/**
 * Clean up old sessions (older than days)
 */
export function cleanupOldSessions(days: number = 30): number {
  ensureSessionsDir();
  
  const cutoff = Date.now() - (days * 24 * 60 * 60 * 1000);
  const files = fs.readdirSync(SESSIONS_DIR).filter(f => f.endsWith('.json'));
  let deleted = 0;
  
  for (const file of files) {
    const filePath = path.join(SESSIONS_DIR, file);
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      const session = JSON.parse(content) as InterviewSession;
      
      if (new Date(session.updatedAt).getTime() < cutoff) {
        fs.unlinkSync(filePath);
        sessionCache.delete(session.id);
        deleted++;
      }
    } catch {
      // Ignore parse errors
    }
  }
  
  return deleted;
}

// Initialize on module load
ensureSessionsDir();
