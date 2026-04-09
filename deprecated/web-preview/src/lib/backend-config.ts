/**
 * Backend Configuration
 * 
 * Single source of truth for backend URL.
 * All API routes must import from here.
 * 
 * Architecture compliance:
 * - Python FastAPI backend runs on port 8000
 * - No hardcoded URLs in individual routes
 */

// Backend base URL - Python/FastAPI server
export const BACKEND_URL = 'http://localhost:8000';

// WebSocket URL
export const WS_URL = 'ws://localhost:8000';

// Available endpoints in the backend
export const BACKEND_ENDPOINTS = {
  health: '/health',
  providers: '/providers',
  suggest: '/api/suggest',
  analyzeCV: '/api/analyze-cv',
  wsPipeline: '/ws/pipeline',
} as const;

// Full URLs for convenience
export const BACKEND = {
  health: `${BACKEND_URL}${BACKEND_ENDPOINTS.health}`,
  providers: `${BACKEND_URL}${BACKEND_ENDPOINTS.providers}`,
  suggest: `${BACKEND_URL}${BACKEND_ENDPOINTS.suggest}`,
  analyzeCV: `${BACKEND_URL}${BACKEND_ENDPOINTS.analyzeCV}`,
  wsPipeline: `${WS_URL}${BACKEND_ENDPOINTS.wsPipeline}`,
} as const;
