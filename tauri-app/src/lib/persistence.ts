import type { CandidateProfile, CompanyInfo, InterviewerProfile } from "@/types";
import {
  readProfileStorageItem,
  removeProfileStorageItem,
  writeProfileStorageItem,
} from "@/lib/storageProfile";

const DEFAULT_STYLE = "professional";
const DEFAULT_LANGUAGE = "en";
const DEFAULT_BACKEND_URL = "http://localhost:8000";

// Keys for localStorage
const STORAGE_KEYS = {
  CANDIDATE_PROFILE: "ic_candidate_profile",
  COMPANY_INFO: "ic_company_info",
  INTERVIEWER_PROFILE: "ic_interviewer_profile",
  STYLE: "ic_style",
  LANGUAGE: "ic_language",
  CV_TEXT: "ic_cv_text",
  BACKEND_URL: "ic_backend_url",
  SETTINGS: "ic_settings",
  RUNTIME_CONFIG: "ic_runtime_config",
} as const;

export interface LLMConfig {
  provider: "anthropic" | "openai" | "ollama";
  model: string;
  api_key: string;
  enabled: boolean;
  base_url?: string;  // For Ollama
}

export interface STTConfig {
  provider: "deepgram";
  model: string;
  api_key: string;
  enabled: boolean;
}

// Latency configuration parameters
export interface LatencyConfig {
  // STT (Speech-to-Text) parameters
  utterance_end_ms: number;      // How long to wait for speech to end before processing (Deepgram)
  // Turn detection parameters
  silence_threshold_ms: number;  // How long of silence to wait before considering a turn complete
  min_utterance_duration_ms: number; // Minimum speech duration to process
  // Response pipeline parameters
  suggestion_cooldown_sec: number; // Cooldown between suggestions
}

// Auto-suggestion configuration parameters
export interface AutoSuggestionConfig {
  enabled: boolean;  // Enable/disable automatic suggestion triggering
  silence_threshold_ms: number;  // Silence duration before auto-trigger
  cooldown_sec: number;  // Minimum time between auto-suggestions
  min_turn_duration_ms: number;  // Minimum turn duration for auto-trigger
  min_word_count: number;  // Minimum words for auto-trigger
  context_turn_limit: number;  // Number of turns for context
}

export interface RuntimeConfig {
  llm: LLMConfig;
  stt: STTConfig;
  latency?: LatencyConfig;
  auto_suggestion?: AutoSuggestionConfig;
}

export interface InterviewContext {
  candidateProfile: CandidateProfile | null;
  companyInfo: CompanyInfo | null;
  interviewerProfile: InterviewerProfile | null;
  style: string;
  language: string;
  cvText: string;
  backendUrl: string;
}

function safeSetItem(key: string, value: string): void {
  writeProfileStorageItem(key, value);
}

function safeGetItem(key: string): string | null {
  return readProfileStorageItem(key);
}

function safeRemoveItem(key: string): void {
  removeProfileStorageItem(key);
}

function parseJson<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

function isCandidateProfile(value: unknown): value is CandidateProfile {
  if (!value || typeof value !== "object") return false;
  const profile = value as CandidateProfile;
  return (
    typeof profile.name === "string" &&
    typeof profile.current_role === "string" &&
    (typeof profile.company === "undefined" || typeof profile.company === "string") &&
    typeof profile.years_experience === "number" &&
    isStringArray(profile.skills) &&
    typeof profile.education === "string" &&
    isStringArray(profile.languages) &&
    isStringArray(profile.certifications) &&
    typeof profile.summary === "string" &&
    isStringArray(profile.achievements) &&
    typeof profile.target_role === "string" &&
    typeof profile.industry === "string" &&
    typeof profile.location === "string"
  );
}

function isCompanyInfo(value: unknown): value is CompanyInfo {
  if (!value || typeof value !== "object") return false;
  const company = value as CompanyInfo;
  return (
    typeof company.name === "string" &&
    typeof company.industry === "string" &&
    typeof company.size === "string" &&
    typeof company.culture === "string" &&
    typeof company.mission === "string" &&
    isStringArray(company.values) &&
    isStringArray(company.tech_stack) &&
    typeof company.role_title === "string" &&
    typeof company.role_level === "string" &&
    isStringArray(company.role_requirements) &&
    isStringArray(company.role_responsibilities) &&
    typeof company.interview_type === "string" &&
    isStringArray(company.interview_focus) &&
    typeof company.job_description === "string" &&
    (typeof company.company_summary === "undefined" || typeof company.company_summary === "string") &&
    (typeof company.products_services === "undefined" || isStringArray(company.products_services)) &&
    (typeof company.recent_focus === "undefined" || isStringArray(company.recent_focus)) &&
    (typeof company.source_urls === "undefined" || isStringArray(company.source_urls)) &&
    (typeof company.research_notes === "undefined" || typeof company.research_notes === "string") &&
    (typeof company.context_id === "undefined" || typeof company.context_id === "string")
  );
}

function isInterviewerProfile(value: unknown): value is InterviewerProfile {
  if (!value || typeof value !== "object") return false;
  const profile = value as InterviewerProfile;
  return (
    typeof profile.name === "string" &&
    typeof profile.role_title === "string" &&
    typeof profile.company === "string" &&
    typeof profile.background_summary === "string" &&
    isStringArray(profile.expertise) &&
    isStringArray(profile.career_highlights) &&
    isStringArray(profile.likely_focus_areas) &&
    typeof profile.communication_style === "string" &&
    typeof profile.notes === "string" &&
    (typeof profile.source_urls === "undefined" || isStringArray(profile.source_urls)) &&
    (typeof profile.context_id === "undefined" || typeof profile.context_id === "string")
  );
}

export function saveCandidateProfile(profile: CandidateProfile | null): void {
  if (!profile) {
    safeRemoveItem(STORAGE_KEYS.CANDIDATE_PROFILE);
    return;
  }
  safeSetItem(STORAGE_KEYS.CANDIDATE_PROFILE, JSON.stringify(profile));
}

export function loadCandidateProfile(): CandidateProfile | null {
  const parsed = parseJson<unknown>(safeGetItem(STORAGE_KEYS.CANDIDATE_PROFILE));
  return isCandidateProfile(parsed) ? parsed : null;
}

export function saveCompanyInfo(info: CompanyInfo | null): void {
  if (!info) {
    safeRemoveItem(STORAGE_KEYS.COMPANY_INFO);
    return;
  }
  safeSetItem(STORAGE_KEYS.COMPANY_INFO, JSON.stringify(info));
}

export function loadCompanyInfo(): CompanyInfo | null {
  const parsed = parseJson<unknown>(safeGetItem(STORAGE_KEYS.COMPANY_INFO));
  return isCompanyInfo(parsed) ? parsed : null;
}

export function saveInterviewerProfile(profile: InterviewerProfile | null): void {
  if (!profile) {
    safeRemoveItem(STORAGE_KEYS.INTERVIEWER_PROFILE);
    return;
  }
  safeSetItem(STORAGE_KEYS.INTERVIEWER_PROFILE, JSON.stringify(profile));
}

export function loadInterviewerProfile(): InterviewerProfile | null {
  const parsed = parseJson<unknown>(safeGetItem(STORAGE_KEYS.INTERVIEWER_PROFILE));
  return isInterviewerProfile(parsed) ? parsed : null;
}

export function saveStyle(style: string): void {
  safeSetItem(STORAGE_KEYS.STYLE, style);
}

export function loadStyle(): string {
  const value = safeGetItem(STORAGE_KEYS.STYLE);
  if (!value || !value.trim()) return DEFAULT_STYLE;
  return value;
}

export function saveLanguage(lang: string): void {
  safeSetItem(STORAGE_KEYS.LANGUAGE, lang);
}

export function loadLanguage(): string {
  const value = safeGetItem(STORAGE_KEYS.LANGUAGE);
  if (!value || !value.trim()) return DEFAULT_LANGUAGE;
  return value;
}

export function saveCvText(text: string): void {
  safeSetItem(STORAGE_KEYS.CV_TEXT, text);
}

export function loadCvText(): string {
  return safeGetItem(STORAGE_KEYS.CV_TEXT) ?? "";
}

export function saveBackendUrl(url: string): void {
  safeSetItem(STORAGE_KEYS.BACKEND_URL, url);
}

export function loadBackendUrl(): string {
  const value = safeGetItem(STORAGE_KEYS.BACKEND_URL);
  if (!value || !value.trim()) return DEFAULT_BACKEND_URL;
  return value;
}

// Save/load entire context at once
export function saveContext(ctx: InterviewContext): void {
  saveCandidateProfile(ctx.candidateProfile);
  saveCompanyInfo(ctx.companyInfo);
  saveInterviewerProfile(ctx.interviewerProfile);
  saveStyle(ctx.style);
  saveLanguage(ctx.language);
  saveCvText(ctx.cvText);
  saveBackendUrl(ctx.backendUrl);

  safeSetItem(STORAGE_KEYS.SETTINGS, JSON.stringify(ctx));
}

export function loadContext(): InterviewContext {
  const settingsRaw = safeGetItem(STORAGE_KEYS.SETTINGS);
  const parsedSettings = parseJson<Partial<InterviewContext>>(settingsRaw);
  const settings = parsedSettings as Partial<InterviewContext> & {
    interviewerProfile?: unknown;
  } | null;

  return {
    candidateProfile:
      settings && isCandidateProfile(settings.candidateProfile)
        ? settings.candidateProfile
        : loadCandidateProfile(),
    companyInfo:
      settings && isCompanyInfo(settings.companyInfo)
        ? settings.companyInfo
        : loadCompanyInfo(),
    interviewerProfile:
      settings && isInterviewerProfile(settings.interviewerProfile)
        ? settings.interviewerProfile
        : loadInterviewerProfile(),
    style:
      settings && typeof settings.style === "string"
        ? settings.style
        : loadStyle(),
    language:
      settings && typeof settings.language === "string"
        ? settings.language
        : loadLanguage(),
    cvText:
      settings && typeof settings.cvText === "string"
        ? settings.cvText
        : loadCvText(),
    backendUrl:
      settings && typeof settings.backendUrl === "string"
        ? settings.backendUrl
        : loadBackendUrl(),
  };
}

// Clear all persisted data
export function clearContext(): void {
  Object.values(STORAGE_KEYS).forEach((key) => safeRemoveItem(key));
}

// Check if context has been saved before
export function hasPersistedContext(): boolean {
  return Object.values(STORAGE_KEYS).some((key) => {
    const raw = safeGetItem(key);
    return raw !== null && raw !== "";
  });
}

// Default runtime config
export const DEFAULT_RUNTIME_CONFIG: RuntimeConfig = {
  llm: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    api_key: "",
    enabled: false,
    base_url: "",
  },
  stt: {
    provider: "deepgram",
    model: "nova-3",
    api_key: "",
    enabled: false,
  },
  latency: {
    utterance_end_ms: 2000,
    silence_threshold_ms: 500,
    min_utterance_duration_ms: 300,
    suggestion_cooldown_sec: 3,
  },
};

function pickString(primary: string | undefined, fallback: string): string {
  const value = typeof primary === "string" ? primary.trim() : "";
  return value ? value : fallback;
}

function normalizeBaseUrl(
  provider: RuntimeConfig["llm"]["provider"],
  baseUrl: string | undefined,
  fallbackBaseUrl = ""
): string {
  const resolvedBaseUrl = pickString(baseUrl, fallbackBaseUrl);
  if (provider === "ollama") {
    return resolvedBaseUrl || "http://localhost:11434";
  }

  return resolvedBaseUrl === "http://localhost:11434" ? "" : resolvedBaseUrl;
}

export function normalizeRuntimeConfig(config: RuntimeConfig): RuntimeConfig {
  const provider = config.llm.provider;

  return {
    ...config,
    llm: {
      ...config.llm,
      base_url: normalizeBaseUrl(provider, config.llm.base_url),
    },
  };
}

function isRuntimeConfig(value: unknown): value is RuntimeConfig {
  if (!value || typeof value !== "object") return false;
  const config = value as RuntimeConfig;
  return (
    typeof config.llm === "object" &&
    typeof config.llm.provider === "string" &&
    typeof config.llm.model === "string" &&
    typeof config.llm.api_key === "string" &&
    typeof config.llm.enabled === "boolean" &&
    (typeof config.llm.base_url === "undefined" || typeof config.llm.base_url === "string") &&
    typeof config.stt === "object" &&
    typeof config.stt.provider === "string" &&
    typeof config.stt.model === "string" &&
    typeof config.stt.api_key === "string" &&
    typeof config.stt.enabled === "boolean" &&
    (typeof config.latency === "undefined" || (
      typeof config.latency === "object" &&
      typeof config.latency.utterance_end_ms === "number" &&
      typeof config.latency.silence_threshold_ms === "number" &&
      typeof config.latency.min_utterance_duration_ms === "number" &&
      typeof config.latency.suggestion_cooldown_sec === "number"
    ))
  );
}

export function mergeRuntimeConfig(primary: RuntimeConfig, fallback: RuntimeConfig): RuntimeConfig {
  const provider = pickString(primary.llm.provider, fallback.llm.provider) as RuntimeConfig["llm"]["provider"];
  return {
    llm: {
      provider,
      model: pickString(primary.llm.model, fallback.llm.model),
      api_key: pickString(primary.llm.api_key, fallback.llm.api_key),
      enabled: primary.llm.enabled,
      base_url: normalizeBaseUrl(
        provider,
        primary.llm.base_url,
        fallback.llm.provider === provider ? fallback.llm.base_url : ""
      ),
    },
    stt: {
      provider: pickString(primary.stt.provider, fallback.stt.provider) as RuntimeConfig["stt"]["provider"],
      model: pickString(primary.stt.model, fallback.stt.model),
      api_key: pickString(primary.stt.api_key, fallback.stt.api_key),
      enabled: primary.stt.enabled,
    },
    latency: primary.latency ?? fallback.latency,
    auto_suggestion: primary.auto_suggestion ?? fallback.auto_suggestion,
  };
}

export function saveRuntimeConfig(config: RuntimeConfig): void {
  if (!config) {
    safeRemoveItem(STORAGE_KEYS.RUNTIME_CONFIG);
    return;
  }
  safeSetItem(STORAGE_KEYS.RUNTIME_CONFIG, JSON.stringify(normalizeRuntimeConfig(config)));
}

export function loadRuntimeConfig(): RuntimeConfig {
  const parsed = parseJson<unknown>(safeGetItem(STORAGE_KEYS.RUNTIME_CONFIG));
  if (isRuntimeConfig(parsed)) {
    return normalizeRuntimeConfig(parsed);
  }
  return DEFAULT_RUNTIME_CONFIG;
}

export function hasRuntimeConfig(): boolean {
  const config = loadRuntimeConfig();
  return (
    (config.llm.enabled && config.llm.api_key !== "") ||
    (config.stt.enabled && config.stt.api_key !== "")
  );
}
