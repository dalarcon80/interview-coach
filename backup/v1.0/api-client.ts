import type {
  BackendHealth,
  CoachingStyle,
  CVAnalysisRequest,
  CVAnalysisResponse,
  SessionInfo,
  SuggestionRequest,
  SuggestionResponse,
} from "@/types";
import type { RuntimeConfig } from "./persistence";

const DEFAULT_BACKEND_URL = "http://localhost:8000";

interface RawHealthResponse {
  status: string;
  timestamp: string;
  db_connected: boolean;
  pgvector_ready: boolean;
  api_keys_configured: boolean;
  effective_mode: "real" | "demo";
  mode_source: string;
  version: string;
  providers_loaded: boolean;
}

interface RawSuggestResponse {
  success: boolean;
  mode: "real" | "demo" | "fallback" | "error";
  suggestion_id?: string;
  full_response?: string;
  bullets?: string[];
  confidence?: number;
  quality_score?: number;
  suggestion?: {
    full_response?: string;
    suggestedAnswer: string;
    bullets: string[];
    key_metrics?: string[];
    keyMetrics: string[];
    confidence: number;
    style: string;
    questionType: string;
    isCompound: boolean;
    subQuestions: Array<{
      text: string;
      priority: string;
      weight: number;
    }>;
    underlyingIntent: string[];
    redFlags: string[];
  };
  language?: {
    detected: string;
    confidence: number;
  };
  quality?: {
    passed: boolean;
    score: number;
    issues: string[];
  };
  llm?: {
    provider: string | null;
    model: string | null;
  };
  latency_ms?: number;
  error?: string;
}

interface RawCVAnalysisResponse {
  success: boolean;
  mode: "real" | "demo" | "fallback" | "unavailable";
  profile: {
    name: string;
    email?: string;
    currentRole?: string;
    company?: string;
    summary?: string;
    yearsExperience?: number;
    skills?: string[];
    achievements?: string[];
    leadershipRoles?: string[];
    technicalStack?: string[];
    metrics?: string[];
  };
  highlights?: string[];
  analysis_summary?: string;
  strengths?: string[];
  gaps?: string[];
  recommendations?: string[];
  suggestedTalkingPoints?: string[];
  confidence?: number;
  error?: string | null;
  note?: string;
}

class InterviewCoachAPI {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl || DEFAULT_BACKEND_URL;
  }

  setBaseUrl(url: string) {
    this.baseUrl = url;
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });

    if (!response.ok) {
      const errorBody = await response.text().catch(() => "Unknown error");
      throw new Error(`API error ${response.status}: ${errorBody}`);
    }

    return response.json() as Promise<T>;
  }

  async health(): Promise<BackendHealth> {
    const response = await this.request<RawHealthResponse>("/health");

    return {
      status: response.status,
      mode: response.effective_mode,
      mode_source: response.mode_source,
      version: response.version,
      providers: {
        database: response.db_connected,
        pgvector: response.pgvector_ready,
        api_keys: response.api_keys_configured,
        config_loaded: response.providers_loaded,
      },
    };
  }

  async suggest(req: SuggestionRequest): Promise<SuggestionResponse> {
    // DEBUG: Log cv_text being sent
    const cvTextLength = req.candidate_profile?.cv_text?.length || 0;
    console.log(`[API Client] Sending suggest request with cv_text: ${cvTextLength} chars`);
    if (cvTextLength > 0) {
      console.log(`[API Client] cv_text preview: ${req.candidate_profile?.cv_text?.substring(0, 100)}...`);
    }
    
      const response = await this.request<RawSuggestResponse>("/api/suggest", {
      method: "POST",
      body: JSON.stringify({
        question: req.question,
        session_id: req.session_id,
        candidate_profile: req.candidate_profile,
        company_info: req.company_info,
        style_id: req.style_id,
        language: req.language,
        mode: req.mode,
        // Profile ID for filtering evidence retrieval
        profile_id: req.profile_id,
        // Number of history messages to consult
        history_count: req.history_count,
        // Legacy compatibility fields still accepted by backend
        style: req.style_id,
        candidate: req.candidate_profile
          ? {
              name: req.candidate_profile.name,
              summary: req.candidate_profile.summary,
              skills: req.candidate_profile.skills,
              achievements: req.candidate_profile.achievements,
              certifications: req.candidate_profile.certifications,
            }
          : undefined,
        company: req.company_info
          ? {
              companyName: req.company_info.name,
              industry: req.company_info.industry,
              companyCulture: req.company_info.culture,
              roleTitle: req.company_info.role_title,
              roleRequirements: req.company_info.role_requirements,
              jobDescription: req.company_info.job_description,
            }
          : undefined,
      }),
    });

    if (!response.success || !response.suggestion) {
      throw new Error(response.error || "Suggestion request failed");
    }

    const fullResponse =
      response.full_response ??
      response.suggestion.full_response ??
      response.suggestion.suggestedAnswer ??
      "";

    const bullets =
      response.bullets ??
      response.suggestion.bullets ??
      [];

    const confidence =
      response.confidence ??
      response.suggestion.confidence ??
      0;

    return {
      suggestion_id:
        response.suggestion_id ??
        globalThis.crypto?.randomUUID?.() ??
        `suggestion-${Date.now()}`,
      question: req.question ?? "",
      full_response: fullResponse,
      bullets,
      confidence,
      quality_score: response.quality_score ?? response.quality?.score ?? 0,
      mode:
        response.mode === "real"
          ? "real"
          : response.mode === "fallback"
          ? "fallback"
          : "demo",
      latency_ms: response.latency_ms ?? 0,
      language: response.language?.detected ?? req.language ?? "en",
      metadata: {
        llm: response.llm,
        quality: response.quality,
        raw_mode: response.mode,
        mode_source: (response as { mode_source?: string }).mode_source,
      },
    };
  }

  async analyzeCV(req: CVAnalysisRequest): Promise<CVAnalysisResponse> {
    const response = await this.request<RawCVAnalysisResponse>(
      "/api/analyze-cv",
      {
        method: "POST",
        body: JSON.stringify({
          cv_text: req.cv_text,
          language: req.language,
        }),
      }
    );

    if (!response.success) {
      throw new Error(response.error || "CV analysis request failed");
    }

    return {
      profile: {
        name: response.profile.name,
        current_role: response.profile.currentRole ?? "",
        years_experience: response.profile.yearsExperience ?? 0,
        skills: response.profile.skills ?? [],
        education: "",
        languages: [],
        certifications: [],
        summary: response.profile.summary ?? "",
        achievements: response.profile.achievements ?? [],
        target_role: "",
        industry: "",
        location: "",
        cv_text: req.cv_text,
      },
      mode: response.mode,
      analysis_summary:
        response.analysis_summary ??
        (response.highlights ?? []).join(" "),
      strengths: response.strengths ?? response.highlights ?? [],
      gaps: response.gaps ?? [],
      recommendations:
        response.recommendations ?? response.suggestedTalkingPoints ?? [],
      note: response.note,
    };
  }

  async createSession(mode?: "real" | "demo"): Promise<SessionInfo> {
    return this.request("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ mode: mode || "real" }),
    });
  }

  async getSession(sessionId: string): Promise<SessionInfo> {
    return this.request(`/api/sessions/${sessionId}`);
  }

  async listStyles(): Promise<CoachingStyle[]> {
    return this.request("/api/styles");
  }

  createWebSocketUrl(sessionId: string): string {
    const wsBase = this.baseUrl.replace(/^http/, "ws");
    return `${wsBase}/ws/pipeline?session_id=${encodeURIComponent(sessionId)}`;
  }

  async getRuntimeConfig(): Promise<RuntimeConfig> {
    return this.request<RuntimeConfig>("/api/runtime-config");
  }

  async updateRuntimeConfig(config: RuntimeConfig): Promise<RuntimeConfig> {
    return this.request<RuntimeConfig>("/api/runtime-config", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  }

  // =============================================================================
  // Profile Reindex - For re-indexing after profile edits
  // =============================================================================

  async reindexProfile(profile: {
    profile_id?: string;
    name?: string;
    current_role?: string;
    years_experience?: number;
    skills?: string[];
    achievements?: string[];
    summary?: string;
    cv_text?: string;
  }): Promise<{
    success: boolean;
    profile_id?: string;
    deleted?: { achievements: number; document_chunks: number };
    indexed?: { achievements: number; document_chunks: number };
    message?: string;
    error?: string;
  }> {
    const response = await this.request<{
      success: boolean;
      profile_id?: string;
      deleted?: { achievements: number; document_chunks: number };
      indexed?: { achievements: number; document_chunks: number };
      message?: string;
      error?: string;
    }>("/api/profile/reindex", {
      method: "POST",
      body: JSON.stringify(profile),
    });

    return response;
  }

  // =============================================================================
  // Debug Retrieve Evidence - For verifying evidence retrieval
  // =============================================================================

  async debugRetrieveEvidence(question: string, profile_id?: string): Promise<{
    success: boolean;
    question?: string;
    evidence?: Array<{
      source: string;
      text: string;
      similarity_score: number;
      profile_id?: string;
      metadata?: Record<string, unknown>;
    }>;
    total_found?: number;
    achievements_found?: number;
    chunks_found?: number;
    error?: string;
  }> {
    const response = await this.request<{
      success: boolean;
      question?: string;
      evidence?: Array<{
        source: string;
        text: string;
        similarity_score: number;
        profile_id?: string;
        metadata?: Record<string, unknown>;
      }>;
      total_found?: number;
      achievements_found?: number;
      chunks_found?: number;
      error?: string;
    }>("/api/debug/retrieve-evidence", {
      method: "POST",
      body: JSON.stringify({
        question,
        profile_id,
      }),
    });

    return response;
  }
}

export const api = new InterviewCoachAPI();
export default api;
