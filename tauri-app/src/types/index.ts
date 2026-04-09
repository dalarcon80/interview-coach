export interface CandidateProfile {
  name: string;
  current_role: string;
  company?: string;
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
  insights_context_summary?: string;
  insights_focus_areas?: string[];
  insights_reusable_evidence?: string[];
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
  company_summary?: string;
  products_services?: string[];
  recent_focus?: string[];
  source_urls?: string[];
  research_notes?: string;
  context_id?: string;
  // NEW: Length control for coach responses
  max_words?: number;
}

export interface InterviewerProfile {
  name: string;
  role_title: string;
  company: string;
  background_summary: string;
  expertise: string[];
  career_highlights: string[];
  likely_focus_areas: string[];
  communication_style: string;
  notes: string;
  source_urls?: string[];
  context_id?: string;
}

export interface TargetCompanyContext {
  name: string;
  industry?: string;
  size?: string;
  culture?: string;
  mission?: string;
  values?: string[];
  tech_stack?: string[];
  summary?: string;
  products_services?: string[];
  recent_focus?: string[];
  source_urls?: string[];
  research_notes?: string;
  context_id?: string;
}

export interface TargetRoleContext {
  title: string;
  level?: string;
  description?: string;
  requirements?: string[];
  responsibilities?: string[];
  interview_type?: string;
  interview_focus?: string[];
  max_words?: number;
}

export interface TargetContext {
  company: TargetCompanyContext;
  role: TargetRoleContext;
  interviewer?: InterviewerProfile;
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
  target_company_info?: TargetCompanyContext;
  target_role_info?: TargetRoleContext;
  interviewer_profile?: InterviewerProfile;
  target_context?: TargetContext;
  style_id?: string;
  language?: string;
  mode?: "real" | "demo";
  // Profile ID for filtering evidence retrieval (from reindexed profile)
  profile_id?: string;
  company_context_id?: string;
  interviewer_context_id?: string;
  // Number of history messages to consult (default: 4, range: 1-20)
  history_count?: number;
  // NEW: Length control for coach responses (50-500 words)
  max_words?: number;
  conversation_history?: Array<{ speaker: string; text: string }>;
  preserve_question_text?: boolean;
}

export interface ContextAnalyzeRequest {
  kind: "company" | "interviewer";
  urls?: string[];
  manual_text?: string;
  language?: string;
}

export interface ContextAnalyzeResponse<T = Record<string, unknown>> {
  success: boolean;
  kind: "company" | "interviewer";
  mode: "real" | "demo" | "fallback" | "unavailable";
  extracted_text?: string;
  source_urls?: string[];
  warnings?: string[];
  analyzed?: T;
  suggested_values?: T;
  note?: string;
  error?: string;
}

export interface ContextIndexRequest {
  kind: "company" | "interviewer";
  context_id?: string;
  payload: Record<string, unknown>;
  raw_text?: string;
  source_urls?: string[];
}

export interface ContextIndexResponse {
  success: boolean;
  kind: "company" | "interviewer";
  context_id?: string;
  context?: Record<string, unknown>;
  deleted?: { document_chunks: number };
  indexed?: { document_chunks: number };
  warnings?: string[];
  message?: string;
  error?: string;
}

export interface DebugInfo {
  history_count: number;
  conversation_history: Array<{ speaker: string; text: string }>;
  question: string;
  system_prompt: string;
  user_prompt: string;
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
  debug?: DebugInfo;
}

export interface CVAnalysisRequest {
  cv_text: string;
  language?: string;
}

export interface CVAnalysisResponse {
  profile: CandidateProfile;
  mode?: "real" | "unavailable";
  analysis_summary: string;
  strengths: string[];
  gaps: string[];
  recommendations: string[];
  note?: string;
}

export interface InsightCard {
  id: string;
  title: string;
  summary: string;
  tone: "positive" | "watch" | "neutral";
  bullets: string[];
}

export interface InsightQuestion {
  id: string;
  title: string;
  question: string;
  rationale: string;
  why_it_matters?: string;
  placeholder: string;
  category: string;
  status: "pending" | "answered";
  priority?: "high" | "medium" | "low";
  expected_impact?: "high" | "medium" | "low";
  dimension?: string;
  question_type?: string;
  benchmark_signal?: string;
  role_targets?: string[];
  improves_dimensions?: string[];
  estimated_delta?: {
    global?: number;
    roleFit?: number;
    proofStrength?: number;
    cvRepresentationQuality?: number;
  };
  answer_schema?: {
    fields: string[];
    format_hint: string;
  };
  answer_guidance?: string;
  example_answer?: string;
}

export interface ProposedChange {
  id: string;
  title: string;
  category: string;
  target: "candidate_profile" | "cv_text" | "insights_context";
  field?: keyof CandidateProfile | string;
  reason: string;
  current_value?: unknown;
  proposed_value?: unknown;
}

export type SupportLevel = "curated" | "derived" | "unsupported";

export interface InsightsBenchmarkSource {
  target_role: string;
  normalized_target_role: string;
  family: string;
  family_pack_id: string;
  archetype: string;
  archetype_pack_id: string;
  seniority: string;
  seniority_pack_id: string;
  specialty_ids: string[];
  support_level: SupportLevel;
  versions: {
    global_rubric_version: string;
    archetype_pack_version: string;
    role_family_pack_version: string;
    seniority_pack_version: string;
    resolver_version: string;
  };
  benchmark_source_fingerprint: string;
}

export interface PrimaryScores {
  profile_strength: number;
  role_fit: number;
  proof_strength: number;
  cv_representation_quality: number;
}

export interface BenchmarkDimensionState {
  id: string;
  label: string;
  score: number;
  weight?: number;
  coverage: number;
  confidence: number;
  status: "strong" | "partial" | "weak" | "not_applicable";
  summary: string;
  signals_found: string[];
  signals_missing: string[];
  why_score_is_not_higher?: string;
  next_best_action?: string;
  supporting_evidence_ids?: string[];
}

export interface EvidenceGap {
  id: string;
  title: string;
  dimension: string;
  severity: "high" | "medium" | "low";
  impact: "high" | "medium" | "low";
  why_it_matters: string;
  evidence_needed: string;
  follow_up_hint: string;
  benchmark_signal: string;
  question_ids: string[];
}

export interface EvidenceCard {
  id: string;
  type:
    | "impact_evidence"
    | "leadership_evidence"
    | "project_evidence"
    | "architecture_evidence"
    | "delivery_evidence"
    | "advisory_evidence"
    | "career_progression_evidence"
    | "cv_quality_evidence";
  state: "draft" | "inferred" | "needs_confirmation" | "approved" | "rejected" | "superseded" | "indexed";
  source: "cv" | "user_answer" | "imported_profile" | "system_extraction" | "generated_rewrite";
  summary: string;
  raw_evidence: string;
  dimensions: string[];
  signal_ids: string[];
  role_relevance: {
    archetype: string[];
    family: string[];
    seniority: string[];
  };
  proof: {
    metrics_present: boolean;
    scope_present: boolean;
    ownership_present: boolean;
    recency_present: boolean;
  };
  strength: "weak" | "moderate" | "strong";
  confidence?: "low" | "medium" | "high";
  approval_status?: "draft" | "needs_follow_up" | "approved" | "rejected";
  estimated_delta?: {
    global?: number;
    roleFit?: number;
    proofStrength?: number;
    cvRepresentationQuality?: number;
  };
  support_level: SupportLevel;
}

export interface InsightsActionStep {
  step_id: string;
  title: string;
  type: "question" | "approve_evidence" | "apply_rewrite" | "add_project" | "regenerate_variant";
  why_it_matters: string;
  improves_dimensions: string[];
  estimated_delta: {
    global?: number;
    roleFit?: number;
    proofStrength?: number;
    cvRepresentationQuality?: number;
  };
  effort: "low" | "medium" | "high";
  blocking_dependencies: string[];
  status: string;
}

export interface ImprovementPlan {
  id: string;
  role_target: string;
  current_global_score: number;
  target_score: number;
  steps: InsightsActionStep[];
  open_gap_count: number;
}

export interface ScoreHistoryEvent {
  event_id: string;
  source: "initial_analysis" | "question_answer" | "evidence_approval" | "rewrite_apply";
  label: string;
  score_before: number;
  score_after: number;
  delta: number;
  dimension_deltas: {
    profile_strength: number;
    role_fit: number;
    proof_strength: number;
    cv_representation_quality: number;
  };
  created_at: string;
}

export interface SignalState {
  id: string;
  label: string;
  dimension: string;
  tier: "required" | "supporting" | "differentiator" | "anti";
  coverage: number;
  confidence: number;
  status: "covered" | "partial" | "missing" | "active" | "clear";
  question_family: string;
  question_template: string;
  expected_evidence: string;
}

export interface ApprovedContextPreview {
  summary: string;
  focus_areas: string[];
  reusable_evidence: string[];
  project_evidence: string[];
  top_role_signals: string[];
  benchmark_headline: string;
  approved_change_titles: string[];
  support_level?: SupportLevel;
}

export interface CVVariantSection {
  id: string;
  title: string;
  content: string;
  items: string[];
}

export interface CVVariantPreview {
  variant_id: "master_cv" | "role_variant_cv";
  title: string;
  description: string;
  source_benchmark_fingerprint: string;
  evidence_card_ids_used: string[];
  unresolved_gap_ids: string[];
  change_summary: string;
  approval_state: string;
  export_state: string;
  structured_document_model: CVVariantSection[];
  rendered_text: string;
  sections: CVVariantSection[];
}

export interface InsightsAnalysisResponse {
  workspace_id: string;
  run_id: string;
  mode?: "real" | "demo" | "fallback" | "unavailable";
  analysis_summary: string;
  benchmark_source: InsightsBenchmarkSource;
  support_level: SupportLevel;
  workspace_state: "active" | "stale" | "draft" | "approved" | "outdated_by_pack_change" | "archived";
  primary_scores: PrimaryScores;
  global_score?: number;
  overall_match: number;
  score_history?: ScoreHistoryEvent[];
  coverage_pct: number;
  confidence: {
    label: "High" | "Medium" | "Low";
    score: number;
  };
  score_delta_available?: number;
  top_strengths?: string[];
  top_gaps?: string[];
  interpretation?: string;
  next_actions?: InsightsActionStep[];
  improvement_plan?: ImprovementPlan;
  dimension_states: BenchmarkDimensionState[];
  required_signals: SignalState[];
  supporting_signals: SignalState[];
  differentiator_signals: SignalState[];
  anti_signals: SignalState[];
  not_applicable_signals: SignalState[];
  gap_map: EvidenceGap[];
  evidence_cards: EvidenceCard[];
  questions: InsightQuestion[];
  proposed_changes: ProposedChange[];
  recommended_profile: CandidateProfile;
  approved_context_preview: ApprovedContextPreview;
  insights_context_summary: string;
  cv_health: string;
  role_match_summary: string;
  cv_variants: {
    master_cv: CVVariantPreview;
    role_variant_cv: CVVariantPreview;
  };
  answers: Record<string, string>;
  input_snapshot?: Record<string, unknown>;
  ui_state?: Record<string, unknown>;
  last_generated_at?: string | null;
  workspace_last_active_at?: string | null;
  context_index_status?: {
    saved: boolean;
    deleted: { document_chunks: number };
    indexed: { document_chunks: number };
  };
}

export interface InsightsAnalyzeRequest {
  workspace_id?: string | null;
  candidate_profile?: CandidateProfile | null;
  company_info?: CompanyInfo | null;
  interviewer_profile?: InterviewerProfile | null;
  cv_text: string;
  language?: string;
  target_role_override?: string | null;
  archetype_override?: string | null;
  seniority_override?: string | null;
  specialty_ids?: string[];
}

export interface InsightsWorkspaceStatus {
  workspace_id: string;
  workspace_state: "active" | "stale" | "draft" | "approved" | "outdated_by_pack_change" | "archived";
  current_run_id: string | null;
  ui_state_saved: boolean;
  last_active_at: string | null;
}

export interface InsightsApplyResponse extends InsightsAnalysisResponse {
  candidate_profile: CandidateProfile;
  cv_text: string;
  applied_change_ids: string[];
  approved_evidence_ids: string[];
  variant_applied?: "master_cv" | "role_variant_cv" | null;
  approved_context_preview: ApprovedContextPreview;
  context_index_status: {
    saved: boolean;
    deleted: { document_chunks: number };
    indexed: { document_chunks: number };
  };
}

export interface InsightsExportResponse {
  workspace_id: string;
  run_id: string;
  filename: string;
  mime_type: string;
  content_base64: string;
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
