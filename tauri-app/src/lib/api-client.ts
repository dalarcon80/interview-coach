import type {
  BackendHealth,
  ContextAnalyzeRequest,
  ContextAnalyzeResponse,
  ContextIndexRequest,
  ContextIndexResponse,
  CoachingStyle,
  CVAnalysisRequest,
  CVAnalysisResponse,
  InsightsAnalysisResponse,
  InsightsAnalyzeRequest,
  InsightsApplyResponse,
  InsightsExportResponse,
  InsightsWorkspaceStatus,
  CVVariantPreview,
  SessionInfo,
  SuggestionRequest,
  SuggestionResponse,
  TargetContext,
} from "@/types";
import type { RuntimeConfig } from "./persistence";

export interface RuntimeConfigStatus {
  profile: string;
  config_path: string;
  config_exists: boolean;
  config_sha256: string | null;
}

const DEFAULT_BACKEND_URL = "http://localhost:8000";

function buildTargetContext(
  companyInfo?: SuggestionRequest["company_info"],
  interviewerProfile?: SuggestionRequest["interviewer_profile"]
): TargetContext | undefined {
  if (!companyInfo && !interviewerProfile) return undefined;

  const company = companyInfo
    ? {
        name: companyInfo.name,
        industry: companyInfo.industry,
        size: companyInfo.size,
        culture: companyInfo.culture,
        mission: companyInfo.mission,
        values: companyInfo.values,
        tech_stack: companyInfo.tech_stack,
        summary: companyInfo.company_summary,
        products_services: companyInfo.products_services,
        recent_focus: companyInfo.recent_focus,
        source_urls: companyInfo.source_urls,
        research_notes: companyInfo.research_notes,
        context_id: companyInfo.context_id,
      }
    : { name: "" };

  const role = companyInfo
    ? {
        title: companyInfo.role_title,
        level: companyInfo.role_level,
        description: companyInfo.job_description,
        requirements: companyInfo.role_requirements,
        responsibilities: companyInfo.role_responsibilities,
        interview_type: companyInfo.interview_type,
        interview_focus: companyInfo.interview_focus,
        max_words: companyInfo.max_words,
      }
    : { title: "" };

  return {
    company,
    role,
    interviewer: interviewerProfile,
  };
}

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
  mode: "real" | "unavailable";
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

  private async requestWithFallback<T>(paths: string[], options?: RequestInit): Promise<T> {
    let lastError: unknown = null;

    for (const path of paths) {
      try {
        return await this.request<T>(path, options);
      } catch (error) {
        lastError = error;
        const message = error instanceof Error ? error.message : "";
        if (!message.includes("API error 404")) {
          throw error;
        }
      }
    }

    if (lastError instanceof Error) {
      throw lastError;
    }
    throw new Error("Request failed");
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
        target_company_info: req.target_company_info,
        target_role_info: req.target_role_info,
        interviewer_profile: req.interviewer_profile,
        target_context: req.target_context ?? buildTargetContext(req.company_info, req.interviewer_profile),
        style_id: req.style_id,
        language: req.language,
        mode: req.mode,
        // Profile ID for filtering evidence retrieval
        profile_id: req.profile_id,
        company_context_id: req.company_context_id,
        interviewer_context_id: req.interviewer_context_id,
        // Number of history messages to consult
        history_count: req.history_count,
        conversation_history: req.conversation_history,
        preserve_question_text: req.preserve_question_text,
        // Legacy compatibility fields still accepted by backend
        style: req.style_id,
        candidate: req.candidate_profile
          ? {
              name: req.candidate_profile.name,
              current_role: req.candidate_profile.current_role,
              currentRole: req.candidate_profile.current_role,
              company: req.candidate_profile.company,
              years_experience: req.candidate_profile.years_experience,
              yearsExperience: req.candidate_profile.years_experience,
              summary: req.candidate_profile.summary,
              skills: req.candidate_profile.skills,
              achievements: req.candidate_profile.achievements,
              certifications: req.candidate_profile.certifications,
              cv_text: req.candidate_profile.cv_text,
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

  async analyzeContext<T extends Record<string, unknown> = Record<string, unknown>>(
    req: ContextAnalyzeRequest
  ): Promise<ContextAnalyzeResponse<T>> {
    return this.requestWithFallback<ContextAnalyzeResponse<T>>(
      ["/api/context/analyze", "/api/coach/context/analyze"],
      {
        method: "POST",
        body: JSON.stringify(req),
      }
    );
  }

  async indexContext(req: ContextIndexRequest): Promise<ContextIndexResponse> {
    return this.requestWithFallback<ContextIndexResponse>(
      ["/api/context/index", "/api/coach/context/index"],
      {
        method: "POST",
        body: JSON.stringify(req),
      }
    );
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
        company: response.profile.company ?? "",
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

  async analyzeInsights(req: InsightsAnalyzeRequest): Promise<InsightsAnalysisResponse> {
    const response = await this.request<InsightsAnalysisResponse & { success: boolean; error?: string }>(
      "/api/insights/analyze",
      {
        method: "POST",
        body: JSON.stringify(req),
      }
    );

    if (!response.success) {
      throw new Error(response.error || "Insights analysis request failed");
    }
    return response;
  }

  async getInsightsWorkspace(workspaceId: string, runId?: string): Promise<InsightsAnalysisResponse> {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    const response = await this.request<InsightsAnalysisResponse & { success: boolean; error?: string }>(
      `/api/insights/workspace/${encodeURIComponent(workspaceId)}${query}`
    );
    if (!response.success) {
      throw new Error(response.error || "Insights workspace request failed");
    }
    return response;
  }

  async getInsightsWorkspaceStatus(workspaceId: string): Promise<InsightsWorkspaceStatus> {
    const response = await this.request<InsightsWorkspaceStatus & { success: boolean; error?: string }>(
      `/api/insights/workspace/${encodeURIComponent(workspaceId)}/status`
    );
    if (!response.success) {
      throw new Error(response.error || "Insights workspace status request failed");
    }
    return response;
  }

  async findInsightsWorkspace(params: {
    profile_id?: string;
    target_role?: string;
  }): Promise<InsightsAnalysisResponse> {
    const search = new URLSearchParams();
    if (params.profile_id) search.set("profile_id", params.profile_id);
    if (params.target_role) search.set("target_role", params.target_role);
    const query = search.toString() ? `?${search.toString()}` : "";
    const response = await this.request<InsightsAnalysisResponse & { success: boolean; error?: string }>(
      `/api/insights/workspace${query}`
    );
    if (!response.success) {
      throw new Error(response.error || "Insights workspace lookup failed");
    }
    return response;
  }

  async autosaveInsightsWorkspace(params: {
    workspace_id: string;
    ui_state: Record<string, unknown>;
    workspace_state?: "active" | "stale" | "draft" | "approved";
  }): Promise<InsightsAnalysisResponse> {
    const response = await this.request<InsightsAnalysisResponse & { success: boolean; error?: string }>(
      `/api/insights/workspace/${encodeURIComponent(params.workspace_id)}`,
      {
        method: "PUT",
        body: JSON.stringify({
          ui_state: params.ui_state,
          workspace_state: params.workspace_state,
        }),
      }
    );
    if (!response.success) {
      throw new Error(response.error || "Insights autosave request failed");
    }
    return response;
  }

  async answerInsightQuestion(params: {
    workspace_id: string;
    run_id: string;
    question_id: string;
    answer: string;
  }): Promise<InsightsAnalysisResponse> {
    const response = await this.request<InsightsAnalysisResponse & { success: boolean; error?: string }>(
      "/api/insights/questions/answer",
      {
        method: "POST",
        body: JSON.stringify(params),
      }
    );
    if (!response.success) {
      throw new Error(response.error || "Insights answer request failed");
    }
    return response;
  }

  async previewInsightCv(params: {
    workspace_id: string;
    run_id: string;
    variant: "master_cv" | "role_variant_cv";
  }): Promise<CVVariantPreview> {
    const response = await this.request<{
      success: boolean;
      error?: string;
      variant: CVVariantPreview;
    }>("/api/insights/cv/preview", {
      method: "POST",
      body: JSON.stringify(params),
    });
    if (!response.success) {
      throw new Error(response.error || "Insights preview request failed");
    }
    return response.variant;
  }

  async applyInsightChanges(params: {
    workspace_id: string;
    run_id: string;
    approved_change_ids: string[];
    approved_evidence_ids: string[];
    targets: Array<"candidate_profile" | "cv_text">;
    variant?: "master_cv" | "role_variant_cv";
  }): Promise<InsightsApplyResponse> {
    const response = await this.request<InsightsApplyResponse & { success: boolean; error?: string }>(
      "/api/insights/apply",
      {
        method: "POST",
        body: JSON.stringify(params),
      }
    );
    if (!response.success) {
      throw new Error(response.error || "Insights apply request failed");
    }
    return response;
  }

  async exportInsightCv(params: {
    workspace_id: string;
    run_id: string;
    variant: "master_cv" | "role_variant_cv";
  }): Promise<InsightsExportResponse> {
    const response = await this.request<InsightsExportResponse & { success: boolean; error?: string }>(
      "/api/insights/cv/export",
      {
        method: "POST",
        body: JSON.stringify(params),
      }
    );
    if (!response.success) {
      throw new Error(response.error || "Insights export request failed");
    }
    return response;
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

  async getRuntimeConfigStatus(): Promise<RuntimeConfigStatus> {
    return this.request<RuntimeConfigStatus>("/api/runtime-config/status");
  }

  // =============================================================================
  // Model Discovery - For dynamic model selection
  // =============================================================================

  async listAvailableModels(provider?: string, ollamaBaseUrl?: string): Promise<{
    success: boolean;
    providers: Record<string, Array<{ id: string; name: string }>>;
  }> {
    const params = new URLSearchParams();
    if (provider) params.set("provider", provider);
    if (ollamaBaseUrl) params.set("ollama_base_url", ollamaBaseUrl);
    const query = params.toString() ? `?${params.toString()}` : "";
    return this.request<{ success: boolean; providers: Record<string, Array<{ id: string; name: string }>> }>(`/api/models${query}`);
  }

  async listProviderModels(provider: string, ollamaBaseUrl?: string): Promise<{
    success: boolean;
    provider: string;
    models: Array<{ id: string; name: string }>;
  }> {
    const params = new URLSearchParams();
    if (ollamaBaseUrl) params.set("ollama_base_url", ollamaBaseUrl);
    const query = params.toString() ? `?${params.toString()}` : "";
    return this.request<{ success: boolean; provider: string; models: Array<{ id: string; name: string }> }>(`/api/models/${provider}${query}`);
  }

  async checkOllamaStatus(ollamaBaseUrl?: string): Promise<{
    success: boolean;
    available: boolean;
    base_url: string;
  }> {
    const params = new URLSearchParams();
    if (ollamaBaseUrl) params.set("ollama_base_url", ollamaBaseUrl);
    const query = params.toString() ? `?${params.toString()}` : "";
    return this.request<{ success: boolean; available: boolean; base_url: string }>(`/api/ollama/status${query}`);
  }

  // =============================================================================
  // Profile Reindex - For re-indexing after profile edits
  // =============================================================================

  async reindexProfile(profile: {
    profile_id?: string;
    name?: string;
    current_role?: string;
    company?: string;
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
