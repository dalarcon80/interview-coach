export interface CandidateProfile {
  name: string;
  current_role: string;
  years_experience: number;
  skills: string[];
  education: string;
  languages: string[];
  certifications: string[];
  summary: string;
  achievements: string[];
  target_role: string;
  industry: string;
  location: string;
  cv_text?: string;
  // Profile ID from database (set after indexing)
  profile_id?: string;
}

export interface CompanyInfo {
  name: string;
  industry: string;
  size: string;
  culture: string;
  mission: string;
  values: string[];
  tech_stack: string[];
  role_title: string;
  role_level: string;
  role_requirements: string[];
  role_responsibilities: string[];
  interview_type: string;
  interview_focus: string[];
  job_description: string;
}

export interface CoachingStyle {
  id: string;
  name: string;
  description: string;
}

export interface SuggestionRequest {
  question?: string;  // Optional when session_id is provided - backend gets from history
  session_id?: string;
  candidate_profile?: CandidateProfile;
  company_info?: CompanyInfo;
  style_id?: string;
  language?: string;
  mode?: "real" | "demo";
  // Profile ID for filtering evidence retrieval (from reindexed profile)
  profile_id?: string;
  // Number of history messages to consult (default: 4, range: 1-20)
  history_count?: number;
}

export interface SuggestionResponse {
  suggestion_id: string;
  question: string;
  full_response: string;
  bullets: string[];
  confidence: number;
  quality_score: number;
  mode: "real" | "demo" | "fallback";
  latency_ms: number;
  language: string;
  metadata?: Record<string, unknown>;
}

export interface CVAnalysisRequest {
  cv_text: string;
  language?: string;
}

export interface CVAnalysisResponse {
  profile: CandidateProfile;
  mode?: "real" | "demo" | "fallback" | "unavailable";
  analysis_summary: string;
  strengths: string[];
  gaps: string[];
  recommendations: string[];
  note?: string;
}

export interface SessionInfo {
  session_id: string;
  status: "idle" | "active" | "paused" | "ended";
  start_time?: string;
  questions_count: number;
  mode: "real" | "demo";
}

export interface BackendHealth {
  status: string;
  mode: "real" | "demo";
  mode_source?: string;
  version: string;
  providers: {
    database: boolean;
    pgvector: boolean;
    api_keys: boolean;
    config_loaded: boolean;
  };
}
