import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, UnlistenFn } from "@tauri-apps/api/event";
import {
  AlertCircle,
  Bug,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Mic,
  Radio,
  Wifi,
  WifiOff,
} from "lucide-react";

import {
  CVIntake,
  CandidateProfileForm,
  CompanyInfoForm,
  ConversationHistory,
  InterviewerProfileForm,
  QuestionInput,
  ResearchContextIntake,
  StyleSelector,
  SuggestionDisplay,
} from "@/components/coach";
import { InsightsWorkspace } from "@/components/insights";
import { SettingsPanel } from "@/components/settings";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import api from "@/lib/api-client";
import {
  hasPersistedContext,
  loadBackendUrl,
  loadCandidateProfile,
  loadCompanyInfo,
  loadCvText,
  loadLanguage,
  loadInterviewerProfile,
  loadStyle,
  saveContext,
} from "@/lib/persistence";
import {
  readProfileStorageItem,
  removeProfileStorageItem,
  writeProfileStorageItem,
} from "@/lib/storageProfile";
import type {
  BackendHealth,
  ContextAnalyzeResponse,
  CVAnalysisResponse,
  CandidateProfile,
  CompanyInfo,
  InterviewerProfile,
  SuggestionResponse,
  TargetContext,
} from "@/types";

function modeBadgeClass(mode: "real" | "demo" | "fallback" | null | undefined): string {
  if (mode === "real") {
    return "status-badge-success";
  }
  if (mode === "fallback") {
    return "status-badge-warning";
  }
  return "border-surface-500/40 bg-surface-500/10 text-surface-600";
}

function modeLabel(mode: "real" | "demo" | "fallback" | null | undefined): string {
  if (mode === "real") return "REAL";
  if (mode === "fallback") return "FALLBACK";
  return "DEMO";
}

function captureStateBadgeClass(state: CaptureState | null | undefined): string {
  if (state === "capturing") {
    return "status-badge-success";
  }
  if (state === "paused") {
    return "status-badge-warning";
  }
  return "border-surface-500/40 bg-surface-500/10 text-surface-500";
}

function captureStateLabel(state: CaptureState | null | undefined): string {
  if (state === "capturing") return "capturing";
  if (state === "paused") return "paused";
  return "idle";
}

const DEFAULT_BACKEND_URL = "http://localhost:8000";
const DEFAULT_STYLE = "professional";
const DEFAULT_LANGUAGE = "en";
const CONVERSATION_HISTORY_STORAGE_KEY = "ic_conversation_history";
const MAX_PERSISTED_HISTORY = 20;
const AUDIO_SEND_INTERVAL_MS = 100;

type AppTab = "prepare" | "insights" | "coach" | "live" | "settings";
type InputMode = "system" | "mic" | "both";
type PermissionState = "granted" | "denied" | "restricted" | "prompt" | "unknown";
type Platform = "macos" | "windows" | "linux" | "unknown";
type CaptureType = "Microphone" | "SystemAudio" | "Both";
type CaptureState = "idle" | "capturing" | "paused";

type PrepareDraftFromInsights = {
  profile: CandidateProfile;
  sourceLabel: string;
  contextSummary?: string;
};

interface ConversationEntry {
  id: string;
  timestamp: string;
  question: string;
  suggestion: SuggestionResponse;
}

interface PlatformInfo {
  os: string;
  arch: string;
  supports_system_audio: boolean;
  version: string;
}

interface AudioDeviceInfo {
  id: string;
  name: string;
  is_input: boolean;
  is_system: boolean;
}

interface PermissionInfo {
  microphone: unknown;
  screen_recording: unknown;
  all_granted: boolean;
}

interface QueuedAudioPayload {
  tauriEventSeq: number;
  data: string;
  timestamp_ms: number;
  sample_rate: number;
  channels: number;
  source: string;
  payload_b64_len: number;
  estimated_pcm_bytes: number;
  queued_at_ms: number;
}

interface CaptureStatus {
  is_capturing: boolean;
  capture_state: CaptureState;
  capture_type: string | null;
  duration_ms: number;
  session_id: string | null;
}

interface LiveTranscriptEntry {
  id: string;
  text: string;
  timestamp: number;
  speaker: "interviewer" | "candidate" | "system" | "unknown";
  isFinal: boolean;
  utteranceComplete?: boolean;
}

interface LiveSuggestion {
  mode: "real" | "demo" | "fallback";
  bulletsPreview: string[];
  fullResponse: string;
  confidence: number;
  latencyMs?: number;
  bulletsLatencyMs?: number;
  fullLatencyMs?: number;
  provider?: string;
  model?: string;
  debug?: {
    history_count?: number;
    conversation_history?: Array<{ speaker: string; text: string }>;
    question?: string;
    resolved_question?: string;
    primary_ask?: string;
    secondary_asks?: string[];
    asks_in_order?: string[];
    response_structure?: string[];
    answer_focus?: string;
    answer_style_guidance?: string;
    draft_answer?: string;
    latest_display_caption?: string;
    pending_interviewer_candidate?: string;
    semantic_blocks_window?: Array<{ speaker: string; text: string }>;
    signature?: string;
    literal_question?: string;
    contextualized_question?: string;
    effective_turn_count?: number;
    latest_turn_included?: boolean;
    plan_stage?: string;
    planner_source?: string;
    planner_provider?: string;
    planner_model?: string;
    planner_reasoning_summary?: string;
    planner_confidence?: number;
    brain_status?: string;
    brain_failure_reason?: string | null;
    brain_duration_ms?: number | null;
    brain_started_at_ms?: number | null;
    brain_completed_at_ms?: number | null;
    path_used?: string;
    cache_hit?: boolean;
    cache_signature_matches_current?: boolean;
    draft_ready_at_silence?: boolean;
    silence_wait_ms?: number;
    time_to_prepare_ms?: number;
    time_to_base_plan_ms?: number;
    time_to_semantic_plan_ms?: number;
    time_from_silence_to_answer_ms?: number;
    fallback_used?: boolean;
    request_payload?: Record<string, unknown> | null;
    brain_contract?: {
      literal_question?: string;
      contextualized_question?: string;
      resolved_question?: string;
      asks_in_order?: string[];
      context_focus?: string[];
      interviewer_need?: {
        summary?: string;
      };
      answer_focus?: string;
      answer_style_guidance?: string;
    };
    system_prompt?: string;
    user_prompt?: string;
  };
}

function renderLiveSuggestionParagraphs(text: string): JSX.Element[] {
  return text
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map((paragraph, index) => (
      <p key={`live-suggestion-paragraph-${index}`} className="text-sm leading-6 md:text-base">
        {paragraph}
      </p>
    ));
}

interface WsEvent {
  type?: string;
  [key: string]: unknown;
}

interface LiveSessionState {
  sessionId: string | null;
  isActive: boolean;
  mode: "real" | "demo" | null;
  startedAt: number | null;
  durationSec: number;
  exchangeCount: number;
  averageLatencyMs: number;
}

function buildLatestInterviewerQuestionBlock(
  turns: Array<{ speaker: string; text: string; timestamp?: number; timestamp_ms?: number }>
): string {
  const block: string[] = [];
  let interviewerBlockSeen = false;
  let nextTurnTime: number | null = null;
  const INTERVIEWER_BLOCK_GAP_MS = 5000;

  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index];
    const text = String(turn?.text ?? '').trim();
    if (!text) continue;

    if (turn?.speaker === 'interviewer') {
      const currentTurnTime =
        typeof turn.timestamp_ms === 'number'
          ? turn.timestamp_ms
          : typeof turn.timestamp === 'number'
            ? turn.timestamp
            : null;
      if (
        interviewerBlockSeen &&
        currentTurnTime !== null &&
        nextTurnTime !== null &&
        nextTurnTime - currentTurnTime > INTERVIEWER_BLOCK_GAP_MS
      ) {
        break;
      }
      interviewerBlockSeen = true;
      block.push(text);
      nextTurnTime = currentTurnTime;
      continue;
    }

    if (interviewerBlockSeen) break;
  }

  if (block.length > 0) {
    return block.reverse().join('\n');
  }

  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const text = String(turns[index]?.text ?? '').trim();
    if (text) return text;
  }

  return '';
}

function isGenericFallbackCandidateProfile(profile: CandidateProfile | null | undefined): boolean {
  if (!profile) return false;
  const summary = (profile.summary || "").trim();
  const normalizedSkills = (profile.skills || []).map((item) => item.trim().toLowerCase());
  const normalizedAchievements = (profile.achievements || []).map((item) => item.trim().toLowerCase());
  return (
    /^Experienced professional with \d+\+ years in the industry\.?$/i.test(summary) &&
    normalizedSkills.join("|") === "leadership|strategy|team building" &&
    normalizedAchievements.join("|") === "led teams|delivered projects|drove growth"
  );
}

function normalizeProfileSourceText(value: string | null | undefined): string {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function hasLegacyExtractedListFormatting(values: string[]): boolean {
  return values.some((value) => /[\n\r\t]|^[▪•-]\s*/.test(String(value || "")));
}

function getCandidateProfileSyncIssue(
  profile: CandidateProfile | null | undefined,
  cvText: string
): string | null {
  const normalizedCvText = normalizeProfileSourceText(cvText);
  if (!normalizedCvText) return null;

  if (!profile) {
    return "No candidate profile has been extracted from the current CV yet.";
  }

  if (isGenericFallbackCandidateProfile(profile)) {
    return "The current candidate profile still matches the old generic fallback and cannot be used.";
  }

  const hasStructuredEvidence =
    Boolean(profile.summary.trim()) ||
    profile.skills.length > 0 ||
    profile.achievements.length > 0;
  if (!hasStructuredEvidence) {
    return "The current candidate profile is missing structured evidence extracted from the CV.";
  }

  if (
    hasLegacyExtractedListFormatting(profile.skills) ||
    hasLegacyExtractedListFormatting(profile.achievements)
  ) {
    return "The current candidate profile still uses an older CV extraction format and needs to be refreshed.";
  }

  const normalizedProfileCv = normalizeProfileSourceText(profile.cv_text);
  if (!normalizedProfileCv) {
    return "The current candidate profile is missing the CV source used to derive it.";
  }

  if (normalizedProfileCv !== normalizedCvText) {
    return "The current candidate profile was extracted from an older CV version.";
  }

  return null;
}

function getCandidateProfileReadinessIssue(
  profile: CandidateProfile | null | undefined,
  cvText: string
): string | null {
  if (!profile) {
    return "Complete the candidate profile in Prepare before continuing.";
  }

  if (!profile.name.trim()) {
    return "Complete the candidate name in Prepare before continuing.";
  }

  if (!profile.current_role.trim()) {
    return "Complete the candidate current role in Prepare before continuing.";
  }

  if (!(profile.company ?? "").trim()) {
    return "Complete the candidate current company in Prepare before continuing.";
  }

  const syncIssue = getCandidateProfileSyncIssue(profile, cvText);
  if (syncIssue) {
    return syncIssue;
  }

  const hasStructuredEvidence =
    Boolean(profile.summary.trim()) ||
    profile.skills.length > 0 ||
    profile.achievements.length > 0;

  if (!hasStructuredEvidence) {
    if (cvText.trim()) {
      return "The candidate profile is missing real evidence from the current CV. Refresh the extracted profile in Prepare.";
    }
    return "Paste the candidate CV in Prepare or complete the summary, skills, and achievements before continuing.";
  }

  return null;
}

function getTargetContextReadinessIssue(company: CompanyInfo): string | null {
  if (!company.name.trim()) {
    return "Complete the target company in Prepare before continuing.";
  }

  if (!company.role_title.trim()) {
    return "Complete the target role in Prepare before continuing.";
  }

  return null;
}

function buildTargetContext(
  company: CompanyInfo,
  interviewer: InterviewerProfile
): TargetContext {
  return {
    company: {
      name: company.name,
      industry: company.industry,
      size: company.size,
      culture: company.culture,
      mission: company.mission,
      values: company.values,
      tech_stack: company.tech_stack,
      summary: company.company_summary,
      products_services: company.products_services,
      recent_focus: company.recent_focus,
      source_urls: company.source_urls,
      research_notes: company.research_notes,
      context_id: company.context_id,
    },
    role: {
      title: company.role_title,
      level: company.role_level,
      description: company.job_description,
      requirements: company.role_requirements,
      responsibilities: company.role_responsibilities,
      interview_type: company.interview_type,
      interview_focus: company.interview_focus,
      max_words: company.max_words,
    },
    interviewer,
  };
}

const EMPTY_CANDIDATE_PROFILE: CandidateProfile = {
  name: "",
  current_role: "",
  company: "",
  years_experience: 0,
  skills: [],
  education: "",
  languages: [],
  certifications: [],
  summary: "",
  achievements: [],
  target_role: "",
  industry: "",
  location: "",
  cv_text: "",
};

const EMPTY_COMPANY_INFO: CompanyInfo = {
  name: "",
  industry: "",
  size: "medium",
  culture: "",
  mission: "",
  values: [],
  tech_stack: [],
  role_title: "",
  role_level: "mid",
  role_requirements: [],
  role_responsibilities: [],
  interview_type: "mixed",
  interview_focus: [],
  job_description: "",
  company_summary: "",
  products_services: [],
  recent_focus: [],
  source_urls: [],
  research_notes: "",
  context_id: "",
  max_words: 200,
};

const EMPTY_INTERVIEWER_PROFILE: InterviewerProfile = {
  name: "",
  role_title: "",
  company: "",
  background_summary: "",
  expertise: [],
  career_highlights: [],
  likely_focus_areas: [],
  communication_style: "",
  notes: "",
  source_urls: [],
  context_id: "",
};

function initialLiveSession(): LiveSessionState {
  return {
    sessionId: null,
    isActive: false,
    mode: null,
    startedAt: null,
    durationSec: 0,
    exchangeCount: 0,
    averageLatencyMs: 0,
  };
}

function normalizePlatform(value: string): Platform {
  const normalized = value.toLowerCase();
  if (normalized.includes("mac")) return "macos";
  if (normalized.includes("win")) return "windows";
  if (normalized.includes("linux")) return "linux";
  return "unknown";
}

function normalizePermission(value: unknown): PermissionState {
  if (typeof value !== "string") return "unknown";
  const normalized = value.toLowerCase();
  if (normalized === "granted") return "granted";
  if (normalized === "denied") return "denied";
  if (normalized === "restricted") return "restricted";
  if (
    normalized === "prompt" ||
    normalized === "notdetermined" ||
    normalized === "not_determined"
  ) {
    return "prompt";
  }
  return "unknown";
}

function wsUrlFromBackendUrl(backendUrl: string): string {
  return `${backendUrl.replace(/^http/, "ws")}/ws/pipeline`;
}

function safeBase64Length(value: unknown): number {
  return typeof value === "string" ? value.length : 0;
}

function estimatePcmBytesFromBase64Length(base64Len: number): number {
  if (base64Len <= 0) return 0;
  const padding = base64Len >= 2 ? 2 : base64Len;
  return Math.max(0, Math.floor((base64Len * 3) / 4) - padding);
}

function formatDuration(seconds: number): string {
  const min = Math.floor(seconds / 60);
  const sec = seconds % 60;
  return `${min}:${sec.toString().padStart(2, "0")}`;
}

function loadConversationHistory(): ConversationEntry[] {
  try {
    const raw = readProfileStorageItem(CONVERSATION_HISTORY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];

    return parsed
      .filter((entry): entry is ConversationEntry => {
        if (!entry || typeof entry !== "object") return false;
        const candidate = entry as ConversationEntry;
        return (
          typeof candidate.id === "string" &&
          typeof candidate.timestamp === "string" &&
          typeof candidate.question === "string" &&
          Boolean(candidate.suggestion && typeof candidate.suggestion === "object")
        );
      })
      .slice(0, MAX_PERSISTED_HISTORY);
  } catch {
    return [];
  }
}

function saveConversationHistory(entries: ConversationEntry[]): void {
  try {
    if (entries.length === 0) {
      removeProfileStorageItem(CONVERSATION_HISTORY_STORAGE_KEY);
      return;
    }
    writeProfileStorageItem(
      CONVERSATION_HISTORY_STORAGE_KEY,
      JSON.stringify(entries.slice(0, MAX_PERSISTED_HISTORY))
    );
  } catch {
    // no-op by design
  }
}

function clearConversationHistoryPersistence(): void {
  try {
    removeProfileStorageItem(CONVERSATION_HISTORY_STORAGE_KEY);
  } catch {
    // no-op by design
  }
}

function App() {
  const [activeTab, setActiveTab] = useState<AppTab>("coach");

  // Required shell state
  const [candidateProfile, setCandidateProfile] = useState<CandidateProfile | null>(() =>
    loadCandidateProfile()
  );
  const [companyInfo, setCompanyInfo] = useState<CompanyInfo | null>(() => loadCompanyInfo());
  const [interviewerProfile, setInterviewerProfile] = useState<InterviewerProfile | null>(() =>
    loadInterviewerProfile()
  );
  const [selectedStyle, setSelectedStyle] = useState(() => loadStyle());
  const [language, setLanguage] = useState(() => loadLanguage());
  const [currentSuggestion, setCurrentSuggestion] = useState<SuggestionResponse | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [conversationHistory, setConversationHistory] = useState<ConversationEntry[]>(() =>
    loadConversationHistory()
  );
  const [isLoading, setIsLoading] = useState(false);
  const [backendHealth, setBackendHealth] = useState<BackendHealth | null>(null);
  const [backendMode, setBackendMode] = useState<"real" | "demo">("demo");

  // History count for suggestions (default: 5, range: 1-20)
  const [historyCount, setHistoryCount] = useState<number>(5);

  // Settings
  const [backendUrl, setBackendUrl] = useState(() => loadBackendUrl());

  // Status/errors
  const [coachError, setCoachError] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  
  // Debug info - always shows what was sent to the coach
  const [debugInfo, setDebugInfo] = useState<{
    sessionId: string;
    historyCount: number;
    transcriptsCount: number;
    request: Record<string, unknown>;
    response: Record<string, unknown> | null;
    error: string | null;
  } | null>(null);
  
  const [cvAnalysis, setCvAnalysis] = useState<CVAnalysisResponse | null>(null);
  const [cvText, setCvText] = useState(() => loadCvText());
  const [refreshingFallbackProfile, setRefreshingFallbackProfile] = useState(false);
  const [prepareDraftFromInsights, setPrepareDraftFromInsights] = useState<PrepareDraftFromInsights | null>(null);
  const [contextPersisted, setContextPersisted] = useState(() => hasPersistedContext());
  const [companyContextStatus, setCompanyContextStatus] = useState<string | null>(null);
  const [companyAnalyzeBusy, setCompanyAnalyzeBusy] = useState(false);
  const [companyIndexBusy, setCompanyIndexBusy] = useState(false);
  const [interviewerContextStatus, setInterviewerContextStatus] = useState<string | null>(null);
  const [interviewerAnalyzeBusy, setInterviewerAnalyzeBusy] = useState(false);
  const [interviewerIndexBusy, setInterviewerIndexBusy] = useState(false);
  const didInitPersistenceRef = useRef(false);
  const skipNextContextPersistRef = useRef(false);
  const lastAutoRepairJobUrlRef = useRef<string | null>(null);
  const companyInfoRef = useRef<CompanyInfo | null>(companyInfo);
  const interviewerProfileRef = useRef<InterviewerProfile | null>(interviewerProfile);

  useEffect(() => {
    companyInfoRef.current = companyInfo;
  }, [companyInfo]);

  useEffect(() => {
    interviewerProfileRef.current = interviewerProfile;
  }, [interviewerProfile]);

  // Realtime state
  const [liveSession, setLiveSession] = useState<LiveSessionState>(initialLiveSession);
  const [liveProcessing, setLiveProcessing] = useState(false);
  const [liveSuggestion, setLiveSuggestion] = useState<LiveSuggestion | null>(null);
  const [liveTranscripts, setLiveTranscripts] = useState<LiveTranscriptEntry[]>([]);
  // Manual suggestions button state
  const [isSuggestionsLoading, setIsSuggestionsLoading] = useState(false);
  // DUAL_STT_PHASE3: Live captions for Zoom/Teams-like real-time display
  // Single entry per speaker that updates in-place
  const [liveCaptions, setLiveCaptions] = useState<Record<string, { text: string; isPartial: boolean; timestamp: number }>>({});
  const [liveQuestionInput, setLiveQuestionInput] = useState("");

  // WebSocket state
  const wsRef = useRef<WebSocket | null>(null);
  const latencyWindowRef = useRef<number[]>([]);
  const audioUnlistenRef = useRef<UnlistenFn | null>(null);
  const liveSessionIdRef = useRef<string | null>(null);
  const audioEventSeqRef = useRef(0);
  const lastAudioEventTimestampRef = useRef<number | null>(null);
  const wsAudioSentSeqRef = useRef(0);
  const audioQueueRef = useRef<QueuedAudioPayload[]>([]);
  const audioSendTimerRef = useRef<number | null>(null);
  const lastWsAudioSentAtRef = useRef<number | null>(null);
  const firstAudioQueuedAtRef = useRef<number | null>(null);
  const firstWsAudioSentAtRef = useRef<number | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [wsConnecting, setWsConnecting] = useState(false);
  const [wsError, setWsError] = useState<string | null>(null);
  const [wsLastHeartbeat, setWsLastHeartbeat] = useState<string | null>(null);

  // Audio/platform state
  const [platformInfo, setPlatformInfo] = useState<PlatformInfo | null>(null);
  const [platform, setPlatform] = useState<Platform>("unknown");
  const [audioDevices, setAudioDevices] = useState<AudioDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState("default");
  const [inputMode, setInputMode] = useState<InputMode>("system");
  const [micPermission, setMicPermission] = useState<PermissionState>("unknown");
  const [systemAudioPermission, setSystemAudioPermission] =
    useState<PermissionState>("unknown");
  const [captureStatus, setCaptureStatus] = useState<CaptureStatus | null>(null);
  const [captureBusy, setCaptureBusy] = useState(false);

  useEffect(() => {
    liveSessionIdRef.current = liveSession.sessionId;
  }, [liveSession.sessionId]);

  const screenPermissionGuidance =
    "Screen Recording permission required. Open System Settings → Privacy & Security → Screen Recording → Enable Interview Coach";
  const screenPermissionRestrictedGuidance =
    "Screen Recording access is restricted by parental controls or system policy. Please contact your administrator.";
  const audioDeviceUnavailableMessage =
    "Audio device unavailable. Please check your microphone and try again.";

  const resetAudioSendState = useCallback(() => {
    audioQueueRef.current = [];
    if (audioSendTimerRef.current !== null) {
      window.clearTimeout(audioSendTimerRef.current);
      audioSendTimerRef.current = null;
    }
    lastWsAudioSentAtRef.current = null;
    firstAudioQueuedAtRef.current = null;
    firstWsAudioSentAtRef.current = null;
    wsAudioSentSeqRef.current = 0;
  }, []);

  const flushAudioQueue = useCallback(() => {
    const payload = audioQueueRef.current.shift();
    if (!payload) return;

    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      const wsState = ws?.readyState ?? null;
      console.warn(
        "[AUDIO][APP][WS_SKIP]",
        JSON.stringify({
          tauri_event_seq: payload.tauriEventSeq,
          session_id: liveSessionIdRef.current,
          timestamp_ms: payload.timestamp_ms,
          ws_ready_state: wsState,
          reason: "ws_not_open",
          queue_depth: audioQueueRef.current.length + 1,
        })
      );
      audioQueueRef.current = [];
      return;
    }

    const now = Date.now();
    const intervalMs =
      lastWsAudioSentAtRef.current === null
        ? 0
        : Math.max(0, now - lastWsAudioSentAtRef.current);

    if (firstWsAudioSentAtRef.current === null) {
      firstWsAudioSentAtRef.current = now;
      const initialDelayMs =
        firstAudioQueuedAtRef.current === null
          ? null
          : Math.max(0, now - firstAudioQueuedAtRef.current);
      console.info(
        "[AUDIO][APP][WS_FIRST_SEND]",
        JSON.stringify({
          session_id: liveSessionIdRef.current,
          initial_delay_ms: initialDelayMs,
        })
      );
    }

    lastWsAudioSentAtRef.current = now;
    wsAudioSentSeqRef.current += 1;
    const wsAudioSeq = wsAudioSentSeqRef.current;

    ws.send(
      JSON.stringify({
        type: "audio_data",
        audio: payload.data,
        timestamp: payload.timestamp_ms,
        sample_rate: payload.sample_rate,
        channels: payload.channels,
        source: payload.source,
      })
    );

    console.info(
      "[AUDIO][APP][WS_SEND]",
      JSON.stringify({
        seq: wsAudioSeq,
        tauri_event_seq: payload.tauriEventSeq,
        session_id: liveSessionIdRef.current,
        timestamp_ms: payload.timestamp_ms,
        sample_rate: payload.sample_rate,
        channels: payload.channels,
        source: payload.source,
        payload_b64_len: payload.payload_b64_len,
        estimated_pcm_bytes: payload.estimated_pcm_bytes,
        interval_ms: intervalMs,
        queued_delay_ms: Math.max(0, now - payload.queued_at_ms),
        queue_depth: audioQueueRef.current.length,
      })
    );
  }, []);

  const scheduleAudioSend = useCallback(() => {
    if (audioSendTimerRef.current !== null) return;
    if (audioQueueRef.current.length === 0) return;

    const now = Date.now();
    const lastSentAt = lastWsAudioSentAtRef.current;
    const elapsedMs = lastSentAt === null ? AUDIO_SEND_INTERVAL_MS : now - lastSentAt;
    const delayMs = Math.max(0, AUDIO_SEND_INTERVAL_MS - elapsedMs);

    audioSendTimerRef.current = window.setTimeout(() => {
      audioSendTimerRef.current = null;
      flushAudioQueue();
      if (audioQueueRef.current.length > 0) {
        scheduleAudioSend();
      }
    }, delayMs);
  }, [flushAudioQueue]);

  const enqueueAudioPayload = useCallback(
    (payload: QueuedAudioPayload) => {
      if (firstAudioQueuedAtRef.current === null) {
        firstAudioQueuedAtRef.current = payload.queued_at_ms;
      }
      audioQueueRef.current.push(payload);
      scheduleAudioSend();
    },
    [scheduleAudioSend]
  );

  const screenPermissionLabel = useMemo(() => {
    if (systemAudioPermission === "prompt") return "unknown";
    return systemAudioPermission;
  }, [systemAudioPermission]);

  const permissionGuidance = useMemo(() => {
    if (platform !== "macos") return null;
    if (systemAudioPermission === "restricted") return screenPermissionRestrictedGuidance;
    if (systemAudioPermission === "denied") return screenPermissionGuidance;
    if (systemAudioPermission === "prompt") {
      return "Screen Recording permission status: unknown. Request permission before starting system audio capture.";
    }
    return null;
  }, [platform, screenPermissionGuidance, screenPermissionRestrictedGuidance, systemAudioPermission]);

  const effectiveCandidate = candidateProfile ?? EMPTY_CANDIDATE_PROFILE;
  const effectiveCompany = companyInfo ?? EMPTY_COMPANY_INFO;
  const effectiveInterviewer = interviewerProfile ?? EMPTY_INTERVIEWER_PROFILE;
  const prepareCandidate = prepareDraftFromInsights?.profile ?? effectiveCandidate;
  const candidateProfileReadinessIssue = useMemo(
    () => getCandidateProfileReadinessIssue(candidateProfile, cvText),
    [candidateProfile, cvText]
  );

  const backendConnected = useMemo(() => {
    if (!backendHealth) return false;
    return backendHealth.status === "healthy" || backendHealth.status === "degraded";
  }, [backendHealth]);

  const captureType = useMemo<CaptureType>(() => {
    if (inputMode === "mic") return "Microphone";
    if (inputMode === "both") return "Both";
    return "SystemAudio";
  }, [inputMode]);

  const audioCapability = useMemo<"functional" | "partial" | "stub">(() => {
    if (platform !== "macos") return "stub";
    return "partial";
  }, [platform]);

  const captureLifecycleState = captureStatus?.capture_state ?? "idle";
  const fullResponseText = liveSuggestion?.fullResponse ?? "";
  const hasFullResponse = fullResponseText.trim().length > 0;
  const previewBullets = liveSuggestion?.bulletsPreview ?? [];
  const hasPreviewBullets = previewBullets.length > 0;

  // Keep API client in sync
  useEffect(() => {
    api.setBaseUrl(backendUrl);
  }, [backendUrl]);

  useEffect(() => {
    if (!didInitPersistenceRef.current) {
      didInitPersistenceRef.current = true;
      return;
    }

    if (skipNextContextPersistRef.current) {
      skipNextContextPersistRef.current = false;
      setContextPersisted(hasPersistedContext());
      return;
    }

    saveContext({
      candidateProfile,
      companyInfo,
      interviewerProfile,
      style: selectedStyle,
      language,
      cvText,
      backendUrl,
    });
    setContextPersisted(hasPersistedContext());
  }, [backendUrl, candidateProfile, companyInfo, cvText, interviewerProfile, language, selectedStyle]);

  useEffect(() => {
    saveConversationHistory(conversationHistory);
  }, [conversationHistory]);

  const checkBackendHealth = useCallback(async () => {
    try {
      const health = await api.health();
      setBackendHealth(health);
      setBackendMode(health.mode === "real" ? "real" : "demo");
    } catch {
      setBackendHealth(null);
    }
  }, []);

  // Backend health check on mount
  useEffect(() => {
    void checkBackendHealth();
    const timer = window.setInterval(() => {
      void checkBackendHealth();
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [checkBackendHealth]);

  // Session duration ticker
  useEffect(() => {
    if (!liveSession.isActive || !liveSession.startedAt) return;
    const timer = window.setInterval(() => {
      setLiveSession((prev) => {
        if (!prev.isActive || !prev.startedAt) return prev;
        return {
          ...prev,
          durationSec: Math.floor((Date.now() - prev.startedAt) / 1000),
        };
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [liveSession.isActive, liveSession.startedAt]);

  // ---- Tauri invoke functionality (preserved) ----
  const loadPlatformInfo = useCallback(async () => {
    try {
      const info = await invoke<PlatformInfo>("get_platform_info");
      setPlatformInfo(info);
      setPlatform(normalizePlatform(info.os));
    } catch {
      setPlatformInfo(null);
      setPlatform("unknown");
    }
  }, []);

  const refreshCaptureStatus = useCallback(async () => {
    try {
      const status = await invoke<CaptureStatus>("get_capture_status");
      setCaptureStatus(status);
    } catch {
      setCaptureStatus(null);
    }
  }, []);

  const refreshAudioDevices = useCallback(async () => {
    setAudioError(null);
    try {
      const devices = await invoke<AudioDeviceInfo[]>("list_audio_devices");
      setAudioDevices(devices);
      const firstDevice = devices.at(0);
      if (firstDevice && !devices.some((d) => d.id === selectedDeviceId)) {
        setSelectedDeviceId(firstDevice.id);
      }
      return;
    } catch {
      // fallback to existing command in this codebase
    }
    try {
      const devices = await invoke<AudioDeviceInfo[]>("get_audio_devices");
      setAudioDevices(devices);
      const firstDevice = devices.at(0);
      if (firstDevice && !devices.some((d) => d.id === selectedDeviceId)) {
        setSelectedDeviceId(firstDevice.id);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load audio devices";
      setAudioError(message);
    }
  }, [selectedDeviceId]);

  const refreshPermissions = useCallback(async () => {
    try {
      const info = await invoke<PermissionInfo>("check_audio_permissions");
      setMicPermission(normalizePermission(info.microphone));
      setSystemAudioPermission(normalizePermission(info.screen_recording));
      return;
    } catch {
      // fallback to existing command in this codebase
    }
    try {
      const info = await invoke<PermissionInfo>("check_permissions");
      setMicPermission(normalizePermission(info.microphone));
      setSystemAudioPermission(normalizePermission(info.screen_recording));
    } catch {
      setMicPermission("unknown");
      setSystemAudioPermission("unknown");
    }
  }, []);

  const requestPermission = useCallback(
    async (permissionType: "Microphone" | "ScreenRecording") => {
      setAudioError(null);
      try {
        await invoke("request_audio_permission", { permission_type: permissionType });
      } catch {
        try {
          await invoke("request_permission", { permission_type: permissionType });
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "Failed to request permission";
          setAudioError(message);
          return;
        }
      }
      await refreshPermissions();
    },
    [refreshPermissions]
  );

  const startCapture = useCallback(async () => {
    setCaptureBusy(true);
    setAudioError(null);
    resetAudioSendState();

    const usingSystemAudio = inputMode === "system" || inputMode === "both";
    if (platform === "macos" && usingSystemAudio) {
      if (systemAudioPermission === "denied") {
        setAudioError(screenPermissionGuidance);
        setCaptureBusy(false);
        return;
      }
      if (systemAudioPermission === "restricted") {
        setAudioError(screenPermissionRestrictedGuidance);
        setCaptureBusy(false);
        return;
      }
    }

    try {
      // Set up audio data listener first
      if (audioUnlistenRef.current) {
        audioUnlistenRef.current();
        audioUnlistenRef.current = null;
      }
      
      const unlisten = await listen<{
        data: string;
        timestamp_ms: number;
        sample_rate: number;
        channels: number;
        source: string;
      }>("audio-data", (event) => {
        audioEventSeqRef.current += 1;
        const eventSeq = audioEventSeqRef.current;
        const previousTimestamp = lastAudioEventTimestampRef.current;
        const intervalMs =
          previousTimestamp === null ? 0 : Math.max(0, event.payload.timestamp_ms - previousTimestamp);
        lastAudioEventTimestampRef.current = event.payload.timestamp_ms;

        const b64Len = safeBase64Length(event.payload.data);
        const estimatedPcmBytes = estimatePcmBytesFromBase64Length(b64Len);

        console.info(
          "[AUDIO][APP][TAURI_EVENT]",
          JSON.stringify({
            seq: eventSeq,
            session_id: liveSessionIdRef.current,
            timestamp_ms: event.payload.timestamp_ms,
            interval_ms: intervalMs,
            sample_rate: event.payload.sample_rate,
            channels: event.payload.channels,
            source: event.payload.source,
            payload_b64_len: b64Len,
            estimated_pcm_bytes: estimatedPcmBytes,
          })
        );

        // Forward audio data to WebSocket if connected
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          enqueueAudioPayload({
            tauriEventSeq: eventSeq,
            data: event.payload.data,
            timestamp_ms: event.payload.timestamp_ms,
            sample_rate: event.payload.sample_rate,
            channels: event.payload.channels,
            source: event.payload.source,
            payload_b64_len: b64Len,
            estimated_pcm_bytes: estimatedPcmBytes,
            queued_at_ms: Date.now(),
          });
        } else {
          const wsState = wsRef.current?.readyState ?? null;
          console.warn(
            "[AUDIO][APP][WS_SKIP]",
            JSON.stringify({
              tauri_event_seq: eventSeq,
              session_id: liveSessionIdRef.current,
              timestamp_ms: event.payload.timestamp_ms,
              ws_ready_state: wsState,
            })
          );
        }
      });
      audioUnlistenRef.current = unlisten;
      
      await invoke("start_capture", {
        deviceId: selectedDeviceId,
        captureType: captureType,
      });
      await refreshPermissions();
      await refreshCaptureStatus();
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "Failed to start capture";
      console.error("[DEBUG] start_capture error:", error);
      console.error("[DEBUG] rawMessage:", rawMessage);
      const lower = rawMessage.toLowerCase();

      // Check for Screen Recording permission errors - these are common on debug builds
      const isScreenPermissionError = 
        lower.includes("screen recording") || 
        lower.includes("screen recording permission") ||
        lower.includes("permission");

      // If system audio fails due to permission error and we're on macOS, offer fallback to mic
      const usingSystemAudio = inputMode === "system" || inputMode === "both";
      if (platform === "macos" && usingSystemAudio && isScreenPermissionError) {
        // Try microphone-only fallback
        console.log("[DEBUG] System audio failed due to permission, trying microphone-only...");
        try {
          await invoke("start_capture", {
            deviceId: selectedDeviceId,
            captureType: "Microphone" as CaptureType,
          });
          // If mic-only succeeds, update the UI to reflect this
          await refreshPermissions();
          await refreshCaptureStatus();
          // Show info message that mic-only mode is active
          setAudioError("System audio permission denied. Using microphone-only mode.");
          return;
        } catch (micError) {
          // Mic also failed, show the original error
          console.error("[DEBUG] Microphone fallback also failed:", micError);
        }
      }

      const message =
        lower.includes("sample rate")
          ? "Sample rate mismatch. Restarting capture..."
          : lower.includes("device unavailable") ||
              lower.includes("audio device unavailable") ||
              lower.includes("device")
            ? audioDeviceUnavailableMessage
            : isScreenPermissionError
              ? `${rawMessage}\n\nTip: You can try microphone-only mode instead of system audio.`
              : rawMessage;

      console.error("[DEBUG] Displaying error message:", message);
      setAudioError(message);
      await refreshPermissions();
    } finally {
      setCaptureBusy(false);
    }
  }, [
    audioDeviceUnavailableMessage,
    captureType,
    enqueueAudioPayload,
    inputMode,
    platform,
    refreshCaptureStatus,
    refreshPermissions,
    resetAudioSendState,
    screenPermissionGuidance,
    screenPermissionRestrictedGuidance,
    selectedDeviceId,
    systemAudioPermission,
  ]);

  const stopCapture = useCallback(async () => {
    setCaptureBusy(true);
    setAudioError(null);
    try {
      // Clean up audio listener
      if (audioUnlistenRef.current) {
        audioUnlistenRef.current();
        audioUnlistenRef.current = null;
      }
      
      await invoke("stop_capture");
      await refreshCaptureStatus();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to stop capture";
      setAudioError(message);
    } finally {
      resetAudioSendState();
      setCaptureBusy(false);
    }
  }, [refreshCaptureStatus]);

  const pauseCapture = useCallback(async () => {
    setCaptureBusy(true);
    setAudioError(null);
    try {
      await invoke("pause_capture");
      await refreshCaptureStatus();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to pause capture";
      setAudioError(message);
    } finally {
      setCaptureBusy(false);
    }
  }, [refreshCaptureStatus]);

  const resumeCapture = useCallback(async () => {
    setCaptureBusy(true);
    setAudioError(null);
    try {
      await invoke("resume_capture");
      await refreshCaptureStatus();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to resume capture";
      setAudioError(message);
    } finally {
      setCaptureBusy(false);
    }
  }, [refreshCaptureStatus]);

  useEffect(() => {
    void loadPlatformInfo();
    void refreshAudioDevices();
    void refreshPermissions();
    void refreshCaptureStatus();
  }, [loadPlatformInfo, refreshAudioDevices, refreshPermissions, refreshCaptureStatus]);

  // ---- WebSocket functionality (preserved) ----
  const sendWs = useCallback((type: string, payload: Record<string, unknown> = {}) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
    wsRef.current.send(JSON.stringify({ type, ...payload }));
    return true;
  }, []);

  const handleWsEvent = useCallback((event: WsEvent) => {
    const eventType = typeof event.type === "string" ? event.type : "unknown";

    if (eventType === "pong" || eventType === "heartbeat") {
      setWsLastHeartbeat(new Date().toISOString());
      return;
    }

    if (eventType === "session_started") {
      const receivedSessionId = typeof event.session_id === "string" ? event.session_id : null;
      console.info(
        "[AUDIO][APP][SESSION]",
        JSON.stringify({
          event: eventType,
          session_id: receivedSessionId,
          mode: event.mode === "real" ? "real" : "demo",
        })
      );

      setLiveSession({
        sessionId: receivedSessionId,
        isActive: true,
        mode: event.mode === "real" ? "real" : "demo",
        startedAt: Date.now(),
        durationSec: 0,
        exchangeCount: 0,
        averageLatencyMs: 0,
      });
      setLiveSuggestion(null);
      setLiveTranscripts([]);
      // DUAL_STT_PHASE3: Clear live captions on new session
      setLiveCaptions({});
      setLiveProcessing(false);
      setLiveError(null);
      return;
    }

    if (eventType === "analysis") {
      setLiveProcessing(true);
      return;
    }

    // DUAL_STT_PHASE3: Handle live_caption for Zoom/Teams-like real-time display
    // These events come in rapidly (every few hundred ms) and update in-place
    if (eventType === "live_caption") {
      const text = typeof event.text === "string" ? event.text.trim() : "";
      if (!text) {
        return;
      }

      // SYSTEM AUDIO MODE: All audio is from interviewer (the meeting participant)
      // Force speaker to always be interviewer - no diarization for system audio
      const speakerKey = "interviewer";
      const isPartial = event.is_partial !== false;

      // Update in-place - single entry per speaker, no appending
      setLiveCaptions(prev => ({
        ...prev,
        [speakerKey]: { 
          text, 
          isPartial, 
          timestamp: Date.now() 
        }
      }));
      return;
    }

    if (eventType === "transcript") {
      const text = typeof event.text === "string" ? event.text.trim() : "";
      if (!text) {
        return;
      }

      const rawSpeaker =
        typeof event.speaker === "string" ? event.speaker.toLowerCase() : "unknown";
      
      // SYSTEM AUDIO MODE: All audio is from interviewer
      // Force speaker to always be interviewer for conversation history too
      const speaker: LiveTranscriptEntry["speaker"] = "interviewer";

      const isFinal = event.is_final === true;
      const utteranceComplete = event.utterance_complete === true;

      setLiveTranscripts((prev) => {
        const lastIndex = prev.length - 1;
        const lastEntry = prev[lastIndex];
        const now = Date.now();

        // Simplified rolling window consolidation:
        // Always consolidate same-speaker entries within 5 seconds.
        // This handles Deepgram sending multiple final=true events for one utterance.
        // Key: Update timestamp on consolidation so window keeps rolling.
        const CONSOLIDATION_WINDOW_MS = 5000;
        const shouldConsolidate =
          lastEntry &&
          lastEntry.speaker === speaker &&
          now - lastEntry.timestamp < CONSOLIDATION_WINDOW_MS;

        if (shouldConsolidate) {
          // Append to existing entry (rolling window - update timestamp to keep window open)
          const updated = [...prev];
          updated[lastIndex] = {
            ...lastEntry,
            text: lastEntry.text + " " + text,
            timestamp: now, // Rolling: reset timer for next consolidation
            isFinal: isFinal,
          };
          return updated;
        }

        // New entry: speaker change OR >5 second silence
        return [
          ...prev,
          {
            id: `transcript-${now}`,
            text: text,
            timestamp: now,
            speaker,
            isFinal,
          },
        ];
      });
      return;
    }

    if (eventType === "suggestion") {
      const latencyMs =
        typeof event.latency_ms === "number" ? event.latency_ms : undefined;
      const bulletsPreview = Array.isArray(event.bullets_preview)
        ? event.bullets_preview.filter((v): v is string => typeof v === "string")
        : Array.isArray(event.bullets)
        ? event.bullets.filter((v): v is string => typeof v === "string")
        : [];
      const fullResponse =
        typeof event.full_response === "string"
          ? event.full_response
          : typeof event.fullResponse === "string"
          ? event.fullResponse
          : "";
      setLiveSuggestion((prev) => ({
        mode:
          event.mode === "real" || event.mode === "fallback"
            ? event.mode
            : prev?.mode ?? "demo",
        bulletsPreview:
          bulletsPreview.length > 0 ? bulletsPreview : prev?.bulletsPreview ?? [],
        fullResponse: fullResponse || prev?.fullResponse || "",
        confidence:
          typeof event.confidence === "number" ? event.confidence : prev?.confidence ?? 0.5,
        latencyMs: latencyMs ?? prev?.latencyMs,
        bulletsLatencyMs:
          typeof event.bullets_latency_ms === "number"
            ? event.bullets_latency_ms
            : prev?.bulletsLatencyMs,
        fullLatencyMs:
          typeof event.full_latency_ms === "number"
            ? event.full_latency_ms
            : prev?.fullLatencyMs,
        provider: typeof event.provider === "string" ? event.provider : prev?.provider,
        model: typeof event.model === "string" ? event.model : prev?.model,
        debug:
          event.debug && typeof event.debug === "object"
            ? (event.debug as LiveSuggestion["debug"])
            : prev?.debug,
      }));

      if (latencyMs !== undefined) {
        latencyWindowRef.current.push(latencyMs);
        if (latencyWindowRef.current.length > 10) latencyWindowRef.current.shift();
        const avg = Math.round(
          latencyWindowRef.current.reduce((acc, cur) => acc + cur, 0) /
            latencyWindowRef.current.length
        );
        setLiveSession((prev) => ({
          ...prev,
          exchangeCount: prev.exchangeCount + 1,
          averageLatencyMs: avg,
        }));
      } else {
        setLiveSession((prev) => ({ ...prev, exchangeCount: prev.exchangeCount + 1 }));
      }

      setLiveProcessing(event.processing_full_response === true);
      return;
    }

    if (eventType === "suggestion_stream") {
      const fullResponse =
        typeof event.full_response === "string"
          ? event.full_response
          : typeof event.fullResponse === "string"
          ? event.fullResponse
          : "";
      setLiveSuggestion((prev) => ({
        mode:
          event.mode === "real" || event.mode === "fallback"
            ? event.mode
            : prev?.mode ?? "demo",
        bulletsPreview: prev?.bulletsPreview ?? [],
        fullResponse,
        confidence:
          typeof event.confidence === "number" ? event.confidence : prev?.confidence ?? 0.5,
        latencyMs: prev?.latencyMs,
        bulletsLatencyMs: prev?.bulletsLatencyMs,
        fullLatencyMs: prev?.fullLatencyMs,
        provider: typeof event.provider === "string" ? event.provider : prev?.provider,
        model: typeof event.model === "string" ? event.model : prev?.model,
        debug: prev?.debug,
      }));
      setLiveProcessing(event.processing_full_response === true);
      return;
    }

    if (eventType === "session_ended") {
      setLiveSession(initialLiveSession());
      // DUAL_STT_PHASE3: Clear live captions when session ends
      setLiveCaptions({});
      setLiveProcessing(false);
      return;
    }

    if (eventType === "session_paused") {
      setLiveSession((prev) => ({
        ...prev,
        isActive: false,
      }));
      setLiveProcessing(false);
      return;
    }

    if (eventType === "session_resumed") {
      setLiveSession((prev) => ({
        ...prev,
        isActive: true,
      }));
      return;
    }

    if (eventType === "question_detected") {
      // Add detected question to transcripts
      const question = typeof event.question === "string" ? event.question : "";
      if (question) {
        setLiveTranscripts((prev) => [
          ...prev,
          {
            id: `transcript-${Date.now()}`,
            text: question,
            timestamp: Date.now(),
            speaker: "interviewer",
            isFinal: true,
          },
        ]);
      }
      return;
    }

    if (eventType === "error") {
      setLiveError(
        typeof event.message === "string" ? event.message : "Unknown WebSocket error"
      );
      setLiveProcessing(false);
    }
  }, []);

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
      };

      socket.onclose = () => {
        setWsConnected(false);
        setWsConnecting(false);
        setLiveSession((prev) => ({ ...prev, isActive: false }));
      };

      socket.onerror = () => {
        setWsConnected(false);
        setWsConnecting(false);
        setWsError("WebSocket connection error");
      };

      socket.onmessage = (message: MessageEvent<string>) => {
        try {
          handleWsEvent(JSON.parse(message.data) as WsEvent);
        } catch {
          setWsError("Invalid WebSocket payload");
        }
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to connect WebSocket";
      setWsError(message);
      setWsConnecting(false);
    }
  }, [backendUrl, handleWsEvent]);

  const disconnectWebSocket = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close(1000, "Client disconnect");
      wsRef.current = null;
    }
    setWsConnected(false);
    setWsConnecting(false);
    setLiveSession((prev) => ({ ...prev, isActive: false }));
  }, []);

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, "Unmount");
        wsRef.current = null;
      }
      resetAudioSendState();
    };
  }, []);

  // ---- App handlers ----
  const handleCvProfileExtracted = useCallback(
    (profile: CandidateProfile, analysis: CVAnalysisResponse) => {
      setCandidateProfile((current) => ({
        ...current,
        ...profile,
        target_role: current?.target_role ?? profile.target_role ?? "",
        industry: current?.industry ?? profile.industry ?? "",
        location: current?.location ?? profile.location ?? "",
        profile_id: current?.profile_id ?? profile.profile_id,
        insights_context_summary:
          current?.insights_context_summary ?? profile.insights_context_summary,
        insights_focus_areas: current?.insights_focus_areas ?? profile.insights_focus_areas,
        insights_reusable_evidence:
          current?.insights_reusable_evidence ?? profile.insights_reusable_evidence,
      }));
      setCvAnalysis(analysis);
      setCvText(profile.cv_text ?? "");
    },
    []
  );

  const handleCvTextChanged = useCallback((nextCvText: string) => {
    setCvText(nextCvText);
    setCvAnalysis((current) => {
      if (!current) return null;
      return current.profile.cv_text === nextCvText ? current : null;
    });
  }, []);

  const rebuildCandidateProfileFromCv = useCallback(
    async (onError?: (message: string) => void): Promise<CandidateProfile | null> => {
      if (!cvText.trim()) {
        const message = "Add or paste the CV text in Prepare before refreshing the extracted profile.";
        onError?.(message);
        return null;
      }

      setRefreshingFallbackProfile(true);
      try {
        const analysis = await api.analyzeCV({ cv_text: cvText, language });
        handleCvProfileExtracted(analysis.profile, analysis);
        return analysis.profile;
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Could not refresh the extracted profile from the CV.";
        onError?.(message);
        return null;
      } finally {
        setRefreshingFallbackProfile(false);
      }
    },
    [cvText, handleCvProfileExtracted, language]
  );

  const handleRefreshCandidateProfileFromCv = useCallback(async () => {
    if (!cvText.trim()) {
      setCoachError("Add or paste the CV text in Prepare before refreshing the extracted profile.");
      return;
    }

    setCoachError(null);
    await rebuildCandidateProfileFromCv((message) => setCoachError(message));
  }, [cvText, rebuildCandidateProfileFromCv]);

  const ensureCanonicalCandidateProfile = useCallback(
    async (surface: "coach" | "live"): Promise<CandidateProfile | undefined> => {
      const readinessIssue = getCandidateProfileReadinessIssue(candidateProfile, cvText);
      const syncIssue = getCandidateProfileSyncIssue(candidateProfile, cvText);
      if (!readinessIssue) {
        return candidateProfile ?? undefined;
      }

      const setSurfaceError = surface === "live" ? setLiveError : setCoachError;
      setSurfaceError(null);

      if (!cvText.trim()) {
        setSurfaceError(readinessIssue);
        return undefined;
      }

      if (!syncIssue) {
        setSurfaceError(readinessIssue);
        return undefined;
      }

      const rebuiltProfile = await rebuildCandidateProfileFromCv((message) => setSurfaceError(message));
      if (!rebuiltProfile) {
        return undefined;
      }

      const rebuiltIssue = getCandidateProfileReadinessIssue(rebuiltProfile, cvText);
      if (rebuiltIssue) {
        setSurfaceError(`${rebuiltIssue} Refresh the profile in Prepare before continuing.`);
        return undefined;
      }

      return rebuiltProfile;
    },
    [candidateProfile, cvText, rebuildCandidateProfileFromCv]
  );

  const handleInsightsProfileApplied = useCallback(
    (profile: CandidateProfile, contextSummary?: string) => {
      setPrepareDraftFromInsights({
        profile,
        sourceLabel: "Approved profile changes from Insights",
        contextSummary,
      });
      setActiveTab("prepare");
    },
    []
  );

  const handleInsightsCvApplied = useCallback(
    (nextCvText: string, contextSummary?: string, profile?: CandidateProfile) => {
      const baseProfile = profile ?? candidateProfile ?? EMPTY_CANDIDATE_PROFILE;
      setPrepareDraftFromInsights({
        profile: {
          ...baseProfile,
          cv_text: nextCvText,
          insights_context_summary:
            contextSummary || profile?.insights_context_summary || baseProfile.insights_context_summary,
        },
        sourceLabel: "Insights CV variant draft",
        contextSummary,
      });
      setActiveTab("prepare");
    },
    [candidateProfile]
  );

  const handleLoadInsightsDraftIntoPrepare = useCallback(() => {
    if (!prepareDraftFromInsights) {
      return;
    }
    setCandidateProfile(prepareDraftFromInsights.profile);
    setCvText(prepareDraftFromInsights.profile.cv_text ?? "");
    setCvAnalysis((current) =>
      current
        ? {
            ...current,
            profile: prepareDraftFromInsights.profile,
          }
        : current
    );
    setPrepareDraftFromInsights(null);
    setCoachError(null);
  }, [prepareDraftFromInsights]);

  const handleDiscardInsightsDraft = useCallback(() => {
    setPrepareDraftFromInsights(null);
  }, []);

  const handlePrepareProfileChange = useCallback(
    (next: CandidateProfile) => {
      if (prepareDraftFromInsights) {
        setPrepareDraftFromInsights((current) =>
          current
            ? {
                ...current,
                profile: next,
              }
            : current
        );
        return;
      }
      setCandidateProfile(next);
      setCvText(next.cv_text ?? "");
    },
    [prepareDraftFromInsights]
  );

  const mergeCompanyAnalysis = useCallback(
    (base: CompanyInfo, analyzed: Record<string, unknown>): CompanyInfo => {
      const next: CompanyInfo = { ...base };
      const mutableNext = next as unknown as Record<string, unknown>;
      const textFields: Array<keyof CompanyInfo> = [
        "name",
        "industry",
        "size",
        "culture",
        "mission",
        "role_title",
        "role_level",
        "interview_type",
        "job_description",
        "company_summary",
        "research_notes",
        "context_id",
      ];
      for (const key of textFields) {
        const value = analyzed[key];
        if (typeof value === "string") {
          mutableNext[key] = value;
        }
      }

      const arrayFields: Array<keyof CompanyInfo> = [
        "values",
        "tech_stack",
        "role_requirements",
        "role_responsibilities",
        "interview_focus",
        "products_services",
        "recent_focus",
      ];
      for (const key of arrayFields) {
        const value = analyzed[key];
        if (Array.isArray(value)) {
          mutableNext[key] = value.map((entry) => String(entry)).filter(Boolean);
        }
      }

      const analyzedSourceUrls = Array.isArray(analyzed.source_urls)
        ? analyzed.source_urls.map((entry) => String(entry)).filter(Boolean)
        : [];
      const currentSourceUrls = Array.isArray(base.source_urls)
        ? base.source_urls.map((entry) => String(entry)).filter(Boolean)
        : [];
      const mergedSourceUrls = currentSourceUrls.length > 0 ? [...currentSourceUrls] : ["", "", ""];
      for (const url of analyzedSourceUrls) {
        if (!mergedSourceUrls.includes(url)) {
          const nextIndex = mergedSourceUrls.findIndex((entry) => !entry.trim());
          if (nextIndex >= 0) {
            mergedSourceUrls[nextIndex] = url;
          } else {
            mergedSourceUrls.push(url);
          }
        }
      }
      if (mergedSourceUrls.length > 0) {
        mutableNext.source_urls = mergedSourceUrls;
      }

      if (typeof analyzed.max_words === "number") {
        next.max_words = analyzed.max_words;
      }

      return next;
    },
    []
  );

  const mergeInterviewerAnalysis = useCallback(
    (base: InterviewerProfile, analyzed: Record<string, unknown>): InterviewerProfile => {
      const next: InterviewerProfile = { ...base };
      const mutableNext = next as unknown as Record<string, unknown>;
      const textFields: Array<keyof InterviewerProfile> = [
        "name",
        "role_title",
        "company",
        "background_summary",
        "communication_style",
        "notes",
        "context_id",
      ];
      for (const key of textFields) {
        const value = analyzed[key];
        if (typeof value === "string") {
          mutableNext[key] = value;
        }
      }

      const arrayFields: Array<keyof InterviewerProfile> = [
        "expertise",
        "career_highlights",
        "likely_focus_areas",
        "source_urls",
      ];
      for (const key of arrayFields) {
        const value = analyzed[key];
        if (Array.isArray(value)) {
          mutableNext[key] = value.map((entry) => String(entry)).filter(Boolean);
        }
      }

      return next;
    },
    []
  );

  const normalizeAnalyzeResponse = useCallback((response: ContextAnalyzeResponse<Record<string, unknown>>) => {
    return (response.suggested_values ?? response.analyzed ?? {}) as Record<string, unknown>;
  }, []);

  const summarizeJobFocus = useCallback((value: unknown): string => {
    if (!Array.isArray(value)) {
      return "";
    }
    const items = value
      .filter((entry): entry is string => typeof entry === "string")
      .map((entry) => entry.trim())
      .filter(Boolean);
    if (items.length === 0) {
      return "";
    }
    return items.slice(0, 4).join(" · ");
  }, []);

  const jobPostingUrl = useMemo(
    () =>
      effectiveCompany.source_urls?.find((url) =>
        url.toLowerCase().includes("linkedin.com/jobs/view/")
      ) ?? "",
    [effectiveCompany.source_urls]
  );

  const updateCompanySourceUrl = useCallback((index: number, value: string) => {
    setCompanyInfo((current) => {
      const base = current ?? EMPTY_COMPANY_INFO;
      const nextUrls = [...(base.source_urls ?? [])];
      nextUrls[index] = value;
      return {
        ...base,
        source_urls: nextUrls,
      };
    });
  }, []);

  const updateInterviewerSourceUrl = useCallback((index: number, value: string) => {
    setInterviewerProfile((current) => {
      const base = current ?? EMPTY_INTERVIEWER_PROFILE;
      const nextUrls = [...(base.source_urls ?? [])];
      nextUrls[index] = value;
      return {
        ...base,
        source_urls: nextUrls,
      };
    });
  }, []);

  const buildCompanyResearchText = useCallback((company: CompanyInfo): string => {
    return [
      `Company: ${company.name}`,
      `Industry: ${company.industry}`,
      `Role level: ${company.role_level}`,
      `Job posting URL: ${(company.source_urls ?? []).find((url) =>
        url.toLowerCase().includes("linkedin.com/jobs/view/")
      ) ?? ""}`,
      `Interview type: ${company.interview_type}`,
      `Culture: ${company.culture}`,
      `Mission: ${company.mission}`,
      `Values: ${company.values.join(", ")}`,
      `Tech stack: ${company.tech_stack.join(", ")}`,
      `Requirements: ${company.role_requirements.join("; ")}`,
      `Responsibilities: ${company.role_responsibilities.join("; ")}`,
      `Interview focus: ${company.interview_focus.join(", ")}`,
      `Job description: ${company.job_description}`,
      `Source URLs: ${(company.source_urls ?? []).join(", ")}`,
      `Research notes: ${company.research_notes ?? ""}`,
    ]
      .filter((line) => line.trim())
      .join("\n");
  }, []);

  const buildInterviewerResearchText = useCallback((profile: InterviewerProfile): string => {
    return [
      `Name: ${profile.name}`,
      `Role title: ${profile.role_title}`,
      `Company: ${profile.company}`,
      `Background summary: ${profile.background_summary}`,
      `Expertise: ${profile.expertise.join(", ")}`,
      `Career highlights: ${profile.career_highlights.join("; ")}`,
      `Likely focus areas: ${profile.likely_focus_areas.join(", ")}`,
      `Communication style: ${profile.communication_style}`,
      `Source URLs: ${(profile.source_urls ?? []).join(", ")}`,
      `Notes: ${profile.notes}`,
    ]
      .filter((line) => line.trim())
      .join("\n");
  }, []);

  const handleCompanyAnalyze = useCallback(async () => {
    setCompanyAnalyzeBusy(true);
    setCompanyContextStatus(null);
    try {
      const response = await api.analyzeContext<Record<string, unknown>>({
        kind: "company",
        urls: (effectiveCompany.source_urls ?? []).filter(Boolean),
        manual_text: buildCompanyResearchText(effectiveCompany),
        language,
      });

      if (!response.success) {
        throw new Error(response.error || "Company analysis failed");
      }

      const analyzed = normalizeAnalyzeResponse(response);
      const updatedCompany = mergeCompanyAnalysis(companyInfoRef.current ?? EMPTY_COMPANY_INFO, analyzed);
      if (jobPostingUrl && typeof analyzed.role_title === "string" && analyzed.role_title.trim()) {
        updatedCompany.role_title = analyzed.role_title.trim();
      }
      setCompanyInfo(updatedCompany);
      const warningText = response.warnings?.length ? ` Warnings: ${response.warnings.join(" ")}` : "";
      const inferredRole =
        typeof analyzed.role_title === "string" && analyzed.role_title.trim()
          ? ` Role detected from job URL: ${analyzed.role_title.trim()}.`
          : "";
      const focusSummary = summarizeJobFocus(analyzed.interview_focus);
      const focusText = focusSummary ? ` Focus: ${focusSummary}.` : "";
      const jobUrl = effectiveCompany.source_urls?.find((url) =>
        url.toLowerCase().includes("linkedin.com/jobs/view/")
      );
      const sourceText = jobUrl ? ` Source: ${jobUrl}.` : "";
      setCompanyContextStatus(
        response.note
          ? `${response.note}${inferredRole}${focusText}${sourceText}${warningText}`
          : `Company context analyzed.${inferredRole}${focusText}${sourceText}${warningText}`
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Company analysis failed";
      setCompanyContextStatus(message);
    } finally {
      setCompanyAnalyzeBusy(false);
    }
  }, [
    buildCompanyResearchText,
    language,
    mergeCompanyAnalysis,
    normalizeAnalyzeResponse,
    summarizeJobFocus,
    jobPostingUrl,
  ]);

  const handleCompanyIndex = useCallback(async () => {
    setCompanyIndexBusy(true);
    setCompanyContextStatus(null);
    try {
      const response = await api.indexContext({
        kind: "company",
        context_id: effectiveCompany.context_id || undefined,
        payload: effectiveCompany as unknown as Record<string, unknown>,
        raw_text: effectiveCompany.research_notes || buildCompanyResearchText(effectiveCompany),
        source_urls: effectiveCompany.source_urls ?? [],
      });

      if (!response.success) {
        throw new Error(response.error || "Company indexing failed");
      }

      setCompanyInfo((current) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          context_id: response.context_id ?? current.context_id,
        };
      });

      const deleted = response.deleted?.document_chunks ?? 0;
      const indexed = response.indexed?.document_chunks ?? 0;
      const warningText = response.warnings?.length ? ` Warnings: ${response.warnings.join(" ")}` : "";
      setCompanyContextStatus(
        response.message ||
          `Company context indexed (${indexed} chunks, replaced ${deleted}).${warningText}`
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Company indexing failed";
      setCompanyContextStatus(message);
    } finally {
      setCompanyIndexBusy(false);
    }
  }, [buildCompanyResearchText, effectiveCompany]);

  const handleInterviewerAnalyze = useCallback(async () => {
    setInterviewerAnalyzeBusy(true);
    setInterviewerContextStatus(null);
    try {
      const response = await api.analyzeContext<Record<string, unknown>>({
        kind: "interviewer",
        urls: (effectiveInterviewer.source_urls ?? []).filter(Boolean),
        manual_text: buildInterviewerResearchText(effectiveInterviewer),
        language,
      });

      if (!response.success) {
        throw new Error(response.error || "Interviewer analysis failed");
      }

      const analyzed = normalizeAnalyzeResponse(response);
      setInterviewerProfile((current) =>
        mergeInterviewerAnalysis(current ?? EMPTY_INTERVIEWER_PROFILE, analyzed)
      );
      const warningText = response.warnings?.length ? ` Warnings: ${response.warnings.join(" ")}` : "";
      setInterviewerContextStatus(
        response.note ? `${response.note}${warningText}` : `Interviewer context analyzed.${warningText}`
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Interviewer analysis failed";
      setInterviewerContextStatus(message);
    } finally {
      setInterviewerAnalyzeBusy(false);
    }
  }, [buildInterviewerResearchText, effectiveInterviewer, language, mergeInterviewerAnalysis, normalizeAnalyzeResponse]);

  const handleInterviewerIndex = useCallback(async () => {
    setInterviewerIndexBusy(true);
    setInterviewerContextStatus(null);
    try {
      const response = await api.indexContext({
        kind: "interviewer",
        context_id: effectiveInterviewer.context_id || undefined,
        payload: effectiveInterviewer as unknown as Record<string, unknown>,
        raw_text: effectiveInterviewer.notes || buildInterviewerResearchText(effectiveInterviewer),
        source_urls: effectiveInterviewer.source_urls ?? [],
      });

      if (!response.success) {
        throw new Error(response.error || "Interviewer indexing failed");
      }

      setInterviewerProfile((current) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          context_id: response.context_id ?? current.context_id,
        };
      });

      const deleted = response.deleted?.document_chunks ?? 0;
      const indexed = response.indexed?.document_chunks ?? 0;
      const warningText = response.warnings?.length ? ` Warnings: ${response.warnings.join(" ")}` : "";
      setInterviewerContextStatus(
        response.message ||
          `Interviewer context indexed (${indexed} chunks, replaced ${deleted}).${warningText}`
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Interviewer indexing failed";
      setInterviewerContextStatus(message);
    } finally {
      setInterviewerIndexBusy(false);
    }
  }, [buildInterviewerResearchText, effectiveInterviewer]);

  const submitCoachQuestion = useCallback(
    async (question: string, selectedLanguage?: string) => {
      setIsLoading(true);
      setCoachError(null);
      setCurrentQuestion(question);
      if (selectedLanguage) setLanguage(selectedLanguage);

      try {
        const targetIssue = getTargetContextReadinessIssue(effectiveCompany);
        if (targetIssue) {
          setCoachError(targetIssue);
          return;
        }

        const preparedCandidate = await ensureCanonicalCandidateProfile("coach");
        if (cvText.trim() && !preparedCandidate) {
          return;
        }

        // Merge cv_text into candidate_profile before sending to API
        const candidateWithCv = preparedCandidate
          ? { ...preparedCandidate, cv_text: cvText || preparedCandidate.cv_text }
          : undefined;

        const suggestion = await api.suggest({
          question,
          session_id: liveSession.sessionId ?? undefined,
          candidate_profile: candidateWithCv,
          company_info: companyInfo ?? undefined,
          target_company_info: {
            name: effectiveCompany.name,
            industry: effectiveCompany.industry || undefined,
            size: effectiveCompany.size || undefined,
            culture: effectiveCompany.culture || undefined,
            mission: effectiveCompany.mission || undefined,
            values: effectiveCompany.values,
            tech_stack: effectiveCompany.tech_stack,
            summary: effectiveCompany.company_summary || undefined,
            products_services: effectiveCompany.products_services,
            recent_focus: effectiveCompany.recent_focus,
            source_urls: effectiveCompany.source_urls,
            research_notes: effectiveCompany.research_notes,
            context_id: effectiveCompany.context_id,
          },
          target_role_info: {
            title: effectiveCompany.role_title,
            level: effectiveCompany.role_level || undefined,
            description: effectiveCompany.job_description || undefined,
            requirements: effectiveCompany.role_requirements,
            responsibilities: effectiveCompany.role_responsibilities,
            interview_type: effectiveCompany.interview_type || undefined,
            interview_focus: effectiveCompany.interview_focus,
            max_words: companyInfo?.max_words ?? effectiveCompany.max_words ?? 200,
          },
          interviewer_profile: interviewerProfile ?? undefined,
          target_context: buildTargetContext(effectiveCompany, effectiveInterviewer),
          style_id: selectedStyle,
          language: selectedLanguage ?? language,
          mode: backendMode,
          // Profile ID for evidence filtering
          profile_id: preparedCandidate?.profile_id,
          company_context_id: companyInfo?.context_id,
          interviewer_context_id: interviewerProfile?.context_id,
          max_words: companyInfo?.max_words ?? effectiveCompany.max_words ?? 200,
        });

        setCurrentSuggestion(suggestion);
        setConversationHistory((prev) => [
          {
            id: suggestion.suggestion_id,
            timestamp: new Date().toISOString(),
            question,
            suggestion,
          },
          ...prev,
        ]);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to generate coaching suggestion";
        setCoachError(message);
      } finally {
        setIsLoading(false);
      }
    },
    [
      backendMode,
      companyInfo,
      cvText,
      effectiveCompany,
      effectiveInterviewer,
      ensureCanonicalCandidateProfile,
      interviewerProfile,
      language,
      liveSession.sessionId,
      selectedStyle,
    ]
  );

  // Handler for manual "Get Suggestions" button
  // Sends session_id plus the last N live turns, and derives the primary
  // interviewer question from the latest contiguous interviewer block.
  const handleGetSuggestions = useCallback(async () => {
    if (!liveSession.sessionId) {
      console.warn('No active session');
      return;
    }

    const targetIssue = getTargetContextReadinessIssue(effectiveCompany);
    if (targetIssue) {
      setLiveError(targetIssue);
      return;
    }

    setIsSuggestionsLoading(true);
    setDebugInfo(null);

    const preparedCandidate = await ensureCanonicalCandidateProfile("live");
    if (cvText.trim() && !preparedCandidate) {
      setIsSuggestionsLoading(false);
      return;
    }

    // HR-2: Build conversation history from live transcripts (last N messages)
    // Get the last historyCount transcripts (or all if fewer)
    const transcriptsToUse = liveTranscripts.slice(-historyCount);
    
    // Build conversation history array for the backend
    const conversationHistory = transcriptsToUse.map(t => ({
      speaker: t.speaker,
      text: t.text,
      timestamp_ms: t.timestamp,
    }));
    
    const questionText =
      buildLatestInterviewerQuestionBlock(conversationHistory) ||
      transcriptsToUse.map(t => t.text).join(' ');
    
    console.log('[DEBUG][Get Suggestions] ==========================================');
    console.log('[DEBUG][Get Suggestions] Session ID:', liveSession.sessionId);
    console.log('[DEBUG][Get Suggestions] History count requested:', historyCount);
    console.log('[DEBUG][Get Suggestions] Total transcripts available:', liveTranscripts.length);
    console.log('[DEBUG][Get Suggestions] Using last N transcripts:', transcriptsToUse.length);
    console.log('[DEBUG][Get Suggestions] Conversation history built:', conversationHistory);
    console.log('[DEBUG][Get Suggestions] Question text (latest interviewer block):', questionText);
    console.log('[DEBUG][Get Suggestions] Final question text:', questionText);
    console.log('[DEBUG][Get Suggestions] ==========================================');

    // DEBUG: Prepare request info
    const requestInfo = {
      question: questionText,
      session_id: liveSession.sessionId,
      candidate_profile: preparedCandidate
        ? { ...preparedCandidate, cv_text: cvText || preparedCandidate.cv_text }
        : undefined,
      company_info: companyInfo ?? undefined,
      target_company_info: {
        name: effectiveCompany.name,
        industry: effectiveCompany.industry || undefined,
        size: effectiveCompany.size || undefined,
        culture: effectiveCompany.culture || undefined,
        mission: effectiveCompany.mission || undefined,
        values: effectiveCompany.values,
        tech_stack: effectiveCompany.tech_stack,
        summary: effectiveCompany.company_summary || undefined,
        products_services: effectiveCompany.products_services,
        recent_focus: effectiveCompany.recent_focus,
        source_urls: effectiveCompany.source_urls,
        research_notes: effectiveCompany.research_notes,
        context_id: effectiveCompany.context_id,
      },
      target_role_info: {
        title: effectiveCompany.role_title,
        level: effectiveCompany.role_level || undefined,
        description: effectiveCompany.job_description || undefined,
        requirements: effectiveCompany.role_requirements,
        responsibilities: effectiveCompany.role_responsibilities,
        interview_type: effectiveCompany.interview_type || undefined,
        interview_focus: effectiveCompany.interview_focus,
        max_words: companyInfo?.max_words ?? effectiveCompany.max_words ?? 200,
      },
      interviewer_profile: interviewerProfile ?? undefined,
      target_context: buildTargetContext(effectiveCompany, effectiveInterviewer),
      style_id: selectedStyle,
      language: language,
      mode: backendMode,
      history_count: historyCount,
      profile_id: preparedCandidate?.profile_id,
      company_context_id: companyInfo?.context_id,
      interviewer_context_id: interviewerProfile?.context_id,
      max_words: companyInfo?.max_words ?? effectiveCompany.max_words ?? 200,
      conversation_history: conversationHistory, // HR-2: Send conversation history explicitly
      preserve_question_text: true,
    };

    try {
      // Call the suggest endpoint with session_id
      // Backend will automatically get the configured number of messages from conversation history
      // Empty question is passed as placeholder - backend uses session history instead
      const response = await api.suggest(requestInfo);

      // DEBUG: Save debug info
      console.log('[DEBUG][Get Suggestions] Response:', response);
      console.log('[DEBUG][Get Suggestions] Debug info:', response.debug);
      
      setDebugInfo({
        sessionId: liveSession.sessionId,
        historyCount: historyCount,
        transcriptsCount: liveTranscripts.length,
        request: requestInfo as unknown as Record<string, unknown>,
        response: response as unknown as Record<string, unknown>,
        error: null,
      });

      // Display the suggestion in the live suggestion area
      setLiveSuggestion({
        fullResponse: response.full_response,
        bulletsPreview: response.bullets,
        confidence: response.confidence,
        mode: response.mode,
        latencyMs: response.latency_ms,
        debug: response.debug,
      });

      // Also add to conversationHistory (like submitCoachQuestion does)
      // This ensures the Q&A pair appears in the ConversationHistory component
      const suggestion_id = response.suggestion_id || `live-${Date.now()}`;
      setConversationHistory((prev) => [
        {
          id: suggestion_id,
          timestamp: new Date().toISOString(),
          question: questionText, // Use the question text derived from transcripts
          suggestion: {
            suggestion_id,
            question: questionText,
            full_response: response.full_response,
            bullets: response.bullets || [],
            confidence: response.confidence,
            quality_score: response.quality_score || 0,
            mode: response.mode,
            language: response.language || language,
            latency_ms: response.latency_ms,
          },
        },
        ...prev,
      ]);
    } catch (error) {
      console.error('Error getting suggestions:', error);
      const errorMsg = error instanceof Error ? error.message : 'Failed to get suggestions';
      setLiveError(errorMsg);
      
      // DEBUG: Save debug info even on error
      setDebugInfo({
        sessionId: liveSession.sessionId,
        historyCount: historyCount,
        transcriptsCount: liveTranscripts.length,
        request: requestInfo,
        response: null,
        error: errorMsg,
      });
    } finally {
      setIsSuggestionsLoading(false);
    }
  }, [
    backendMode,
    companyInfo,
    cvText,
    effectiveCompany,
    effectiveInterviewer,
    ensureCanonicalCandidateProfile,
    historyCount,
    interviewerProfile,
    language,
    liveSession.sessionId,
    liveTranscripts,
    selectedStyle,
  ]);

  // Keyboard shortcut: Ctrl+Enter to get suggestions during live session
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'Enter' && liveSession.sessionId && !isSuggestionsLoading) {
        e.preventDefault();
        handleGetSuggestions();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [liveSession.sessionId, isSuggestionsLoading, handleGetSuggestions]);

  const startLiveSession = useCallback(async () => {
    if (!wsConnected) {
      setLiveError("Connect WebSocket before starting a live session");
      return;
    }

    const targetIssue = getTargetContextReadinessIssue(effectiveCompany);
    if (targetIssue) {
      setLiveError(targetIssue);
      return;
    }

    latencyWindowRef.current = [];
    setLiveError(null);
    const preparedCandidate = await ensureCanonicalCandidateProfile("live");
    if (cvText.trim() && !preparedCandidate) {
      return;
    }
    const candidateForLive = preparedCandidate ?? effectiveCandidate;
    const candidatePayload = {
      name: candidateForLive.name,
      current_role: candidateForLive.current_role || undefined,
      currentRole: candidateForLive.current_role || undefined,
      company: candidateForLive.company || undefined,
      current_company: candidateForLive.company || undefined,
      currentCompany: candidateForLive.company || undefined,
      years_experience: candidateForLive.years_experience || undefined,
      yearsExperience: candidateForLive.years_experience || undefined,
      summary: candidateForLive.summary || undefined,
      skills: candidateForLive.skills,
      achievements: candidateForLive.achievements,
      certifications: candidateForLive.certifications,
      education: candidateForLive.education || undefined,
      languages: candidateForLive.languages,
      cv_text: cvText || candidateForLive.cv_text || undefined,
    };
    const targetContext = buildTargetContext(effectiveCompany, effectiveInterviewer);
    const companyPayload = {
      companyName: effectiveCompany.name,
      industry: effectiveCompany.industry || undefined,
      positionTitle: effectiveCompany.role_title,
      roleTitle: effectiveCompany.role_title,
      positionDescription: effectiveCompany.job_description || undefined,
      jobDescription: effectiveCompany.job_description || undefined,
      positionRequirements: effectiveCompany.role_requirements,
      roleRequirements: effectiveCompany.role_requirements,
      roleResponsibilities: effectiveCompany.role_responsibilities,
      companyCulture: effectiveCompany.culture || undefined,
      companySummary: effectiveCompany.company_summary || undefined,
      companyDescription: effectiveCompany.company_summary || undefined,
      values: effectiveCompany.values,
      roleLevel: effectiveCompany.role_level || undefined,
      interviewFocus: effectiveCompany.interview_focus,
      interviewType: effectiveCompany.interview_type || undefined,
      sourceUrls: effectiveCompany.source_urls,
      researchNotes: effectiveCompany.research_notes || undefined,
      max_words: companyInfo?.max_words ?? effectiveCompany.max_words ?? 200,
      productsServices: effectiveCompany.products_services,
      recentFocus: effectiveCompany.recent_focus,
    };
    const interviewerPayload = {
      name: effectiveInterviewer.name,
      roleTitle: effectiveInterviewer.role_title,
      company: effectiveInterviewer.company,
      backgroundSummary: effectiveInterviewer.background_summary,
      expertise: effectiveInterviewer.expertise,
      careerHighlights: effectiveInterviewer.career_highlights,
      likelyFocusAreas: effectiveInterviewer.likely_focus_areas,
      communicationStyle: effectiveInterviewer.communication_style,
      notes: effectiveInterviewer.notes,
      sourceUrls: effectiveInterviewer.source_urls,
    };
    sendWs("start_session", {
      config: {
        mode: backendMode,
        delivery_mode: "manual",
        language_preference: language,
        response_style: selectedStyle,
        style_id: selectedStyle,
        interview_type: effectiveCompany.interview_type || "mixed",
        max_words: companyInfo?.max_words ?? effectiveCompany.max_words ?? 200,
        company_name: effectiveCompany.name,
        role_title: effectiveCompany.role_title,
        company_context_id: effectiveCompany.context_id || undefined,
        interviewer_context_id: effectiveInterviewer.context_id || undefined,
        candidate: candidatePayload,
        candidate_profile: candidatePayload,
        target_company_info: {
          name: effectiveCompany.name,
          industry: effectiveCompany.industry || undefined,
          size: effectiveCompany.size || undefined,
          culture: effectiveCompany.culture || undefined,
          mission: effectiveCompany.mission || undefined,
          values: effectiveCompany.values,
          tech_stack: effectiveCompany.tech_stack,
          summary: effectiveCompany.company_summary || undefined,
          products_services: effectiveCompany.products_services,
          recent_focus: effectiveCompany.recent_focus,
          source_urls: effectiveCompany.source_urls,
          research_notes: effectiveCompany.research_notes,
          context_id: effectiveCompany.context_id || undefined,
        },
        target_role_info: {
          title: effectiveCompany.role_title,
          level: effectiveCompany.role_level || undefined,
          description: effectiveCompany.job_description || undefined,
          requirements: effectiveCompany.role_requirements,
          responsibilities: effectiveCompany.role_responsibilities,
          interview_type: effectiveCompany.interview_type || undefined,
          interview_focus: effectiveCompany.interview_focus,
          max_words: companyInfo?.max_words ?? effectiveCompany.max_words ?? 200,
        },
        target: targetContext,
        target_context: targetContext,
        company: companyPayload,
        company_info: companyPayload,
        interviewer: interviewerPayload,
        interviewer_profile: interviewerPayload,
      },
    });
  }, [
    backendMode,
    cvText,
    effectiveCandidate,
    effectiveCompany,
    effectiveInterviewer,
    ensureCanonicalCandidateProfile,
    language,
    selectedStyle,
    sendWs,
    wsConnected,
  ]);

  const endLiveSession = useCallback(() => {
    sendWs("end_session");
    setLiveProcessing(false);
  }, [sendWs]);

  const pauseLiveSession = useCallback(() => {
    if (!liveSession.isActive) return;
    sendWs("pause_session");
    setLiveProcessing(false);
  }, [liveSession.isActive, sendWs]);

  const resumeLiveSession = useCallback(() => {
    if (liveSession.isActive) return; // Already active
    sendWs("resume_session");
  }, [liveSession.isActive, sendWs]);

  const submitLiveQuestion = useCallback(() => {
    const text = liveQuestionInput.trim();
    if (!text || !liveSession.isActive) return;

    setLiveTranscripts((prev) => [
      ...prev,
      {
        id: `transcript-${Date.now()}`,
        text,
        timestamp: Date.now(),
        speaker: "interviewer",
        isFinal: true,
      },
    ]);
    sendWs("transcript_ready", { text, is_final: true });
    setLiveQuestionInput("");
    setLiveProcessing(true);
  }, [liveQuestionInput, liveSession.isActive, sendWs]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b bg-card/60 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-3 px-4 py-3 md:px-6">
          <div>
            <h1 className="text-xl font-semibold md:text-2xl">Interview Coach</h1>
            <p className="text-xs text-muted-foreground">Component shell with preserved realtime/audio</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={
                backendConnected
                  ? "status-badge-success"
                  : "border-red-500/40 bg-red-500/10 text-red-600"
              }
            >
              {backendConnected ? (
                <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
              ) : (
                <AlertCircle className="mr-1 h-3.5 w-3.5" />
              )}
              Backend {backendConnected ? "connected" : "offline"}
            </Badge>
            <Badge variant="outline">
              {wsConnected ? <Wifi className="mr-1 h-3.5 w-3.5" /> : <WifiOff className="mr-1 h-3.5 w-3.5" />}
              WS {wsConnected ? "connected" : wsConnecting ? "connecting" : "disconnected"}
            </Badge>
            <Badge variant="outline" className={modeBadgeClass(backendMode)}>
              Backend mode: {modeLabel(backendMode)}
            </Badge>
            <Badge variant="outline">Lang: {language}</Badge>
            <Badge variant={contextPersisted ? "secondary" : "outline"}>
              Context {contextPersisted ? "persisted" : "default"}
            </Badge>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-4 md:px-6 md:py-5">
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as AppTab)}>
          <TabsList className="grid h-auto w-full grid-cols-2 gap-1 p-1 md:grid-cols-5">
            <TabsTrigger value="prepare">Prepare</TabsTrigger>
            <TabsTrigger value="insights">Insights</TabsTrigger>
            <TabsTrigger value="coach">Coach</TabsTrigger>
            <TabsTrigger value="live">Live</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
          </TabsList>

          <TabsContent value="prepare">
            <ScrollArea className="h-[calc(100vh-190px)] rounded-md border">
              <div className="space-y-4 p-4">
                {cvAnalysis && (
                  <Alert>
                    <CheckCircle2 className="h-4 w-4" />
                    <AlertTitle>CV analysis completed</AlertTitle>
                    <AlertDescription>
                      {cvAnalysis.analysis_summary || "Profile extracted and loaded into form fields."}
                    </AlertDescription>
                  </Alert>
                )}
                {candidateProfileReadinessIssue && (
                  <Alert>
                    <AlertTitle>Candidate profile is out of sync with Prepare</AlertTitle>
                    <AlertDescription className="space-y-3">
                      <p>
                        {candidateProfileReadinessIssue} Refresh it from the current CV text before relying on Coach or
                        Live.
                      </p>
                      <div>
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => void handleRefreshCandidateProfileFromCv()}
                          disabled={refreshingFallbackProfile}
                        >
                          {refreshingFallbackProfile ? "Refreshing profile..." : "Refresh extracted profile from CV"}
                        </Button>
                      </div>
                    </AlertDescription>
                  </Alert>
                )}
                <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(360px,420px)_minmax(0,1fr)]">
                  <section className="min-w-0 self-start space-y-4">
                    <CVIntake
                      cvText={cvText}
                      analysis={cvAnalysis}
                      onCvTextChange={handleCvTextChanged}
                      onProfileExtracted={handleCvProfileExtracted}
                    />
                    <ResearchContextIntake
                      title="Company research intake"
                      description="Capture URLs and notes that can be analyzed and indexed into company context."
                      fields={[
                        {
                          label: "Official website",
                          value: effectiveCompany.source_urls?.[0] ?? "",
                          onChange: (value) => updateCompanySourceUrl(0, value),
                          placeholder: "https://company.com",
                          helpText: "Primary company website or landing page.",
                        },
                        {
                          label: "LinkedIn / company page",
                          value: effectiveCompany.source_urls?.[1] ?? "",
                          onChange: (value) => updateCompanySourceUrl(1, value),
                          placeholder: "https://linkedin.com/company/...",
                          helpText: "Public company profile or social presence.",
                        },
                        {
                          label: "Job posting URL",
                          value: effectiveCompany.source_urls?.[2] ?? "",
                          onChange: (value) => updateCompanySourceUrl(2, value),
                          placeholder: "https://jobs.example.com/role",
                          helpText: "The posting that defines the role context.",
                        },
                      ]}
                      notesLabel="Research notes / pasted context"
                      notes={effectiveCompany.research_notes ?? ""}
                      onNotesChange={(value) =>
                        setCompanyInfo((current) =>
                          current
                            ? { ...current, research_notes: value }
                            : { ...EMPTY_COMPANY_INFO, research_notes: value }
                        )
                      }
                      analyzeLabel="Analyze company"
                      indexLabel="Index company"
                      onAnalyze={handleCompanyAnalyze}
                      onIndex={handleCompanyIndex}
                      isAnalyzing={companyAnalyzeBusy}
                      isIndexing={companyIndexBusy}
                      statusMessage={companyContextStatus}
                      sourceCountLabel={`${(effectiveCompany.source_urls ?? []).filter(Boolean).length} sources`}
                    />
                    <ResearchContextIntake
                      title="Interviewer research intake"
                      description="Capture the interviewer profile, source URLs, and notes to tailor the coach."
                      fields={[
                        {
                          label: "LinkedIn profile",
                          value: effectiveInterviewer.source_urls?.[0] ?? "",
                          onChange: (value) => updateInterviewerSourceUrl(0, value),
                          placeholder: "https://linkedin.com/in/...",
                          helpText: "Primary interviewer profile source.",
                        },
                        {
                          label: "Bio / company page",
                          value: effectiveInterviewer.source_urls?.[1] ?? "",
                          onChange: (value) => updateInterviewerSourceUrl(1, value),
                          placeholder: "https://company.com/team/...",
                          helpText: "Public bio or team page.",
                        },
                        {
                          label: "Additional URL",
                          value: effectiveInterviewer.source_urls?.[2] ?? "",
                          onChange: (value) => updateInterviewerSourceUrl(2, value),
                          placeholder: "https://...",
                          helpText: "Any extra public context worth preserving.",
                        },
                      ]}
                      notesLabel="Fallback notes / extracted text"
                      notes={effectiveInterviewer.notes}
                      onNotesChange={(value) =>
                        setInterviewerProfile((current) =>
                          current
                            ? { ...current, notes: value }
                            : { ...EMPTY_INTERVIEWER_PROFILE, notes: value }
                        )
                      }
                      analyzeLabel="Analyze interviewer"
                      indexLabel="Index interviewer"
                      onAnalyze={handleInterviewerAnalyze}
                      onIndex={handleInterviewerIndex}
                      isAnalyzing={interviewerAnalyzeBusy}
                      isIndexing={interviewerIndexBusy}
                      statusMessage={interviewerContextStatus}
                      sourceCountLabel={`${(effectiveInterviewer.source_urls ?? []).filter(Boolean).length} sources`}
                    />
                  </section>
                  <section className="min-w-0 self-start space-y-3">
                    <div className="flex items-end justify-between gap-4">
                      <div className="space-y-1">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
                          Context & coaching
                        </p>
                        <h2 className="text-sm font-semibold text-foreground">
                          Candidate, company, and style
                        </h2>
                      </div>
                      <p className="hidden max-w-[20rem] text-right text-xs text-muted-foreground xl:block">
                        Keep the right side focused on the inputs that shape the next response.
                      </p>
                    </div>
                    {prepareDraftFromInsights && (
                      <Alert>
                        <AlertTitle>Insights draft ready in Prepare</AlertTitle>
                        <AlertDescription className="space-y-3">
                          <p>
                            {prepareDraftFromInsights.sourceLabel}
                            {prepareDraftFromInsights.contextSummary
                              ? ` This draft carries the approved context summary: ${prepareDraftFromInsights.contextSummary}`
                              : " This draft stays isolated here until you explicitly load it."}
                          </p>
                          <p>
                            Live and Coach keep the current saved profile until you load this draft into
                            Prepare.
                          </p>
                          <div className="flex flex-wrap gap-2">
                            <Button type="button" size="sm" onClick={handleLoadInsightsDraftIntoPrepare}>
                              Load draft into Prepare
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={handleDiscardInsightsDraft}
                            >
                              Discard draft
                            </Button>
                          </div>
                        </AlertDescription>
                      </Alert>
                    )}
    {(effectiveCompany.role_title.trim() ||
      effectiveCompany.interview_focus.length > 0 ||
      effectiveCompany.role_requirements.length > 0) && (
      <Card className="border-dashed bg-muted/20">
        <CardHeader className="pb-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <CardTitle className="text-base">Detected job signals</CardTitle>
                            {effectiveCompany.source_urls?.some((url) =>
                              url.toLowerCase().includes("linkedin.com/jobs/view/")
                            ) && (
                              <Badge variant="outline" className="whitespace-nowrap">
                                Source: LinkedIn job posting
                              </Badge>
                            )}
                          </div>
          <CardDescription>
            Pulled from the job posting URL and kept visible as quick context.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {effectiveCompany.source_urls?.find((url) =>
            url.toLowerCase().includes("linkedin.com/jobs/view/")
          ) && (
            <div className="rounded-md border bg-background px-3 py-2">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Job posting URL
              </p>
              <p className="mt-1 break-all text-xs text-foreground">
                {effectiveCompany.source_urls.find((url) =>
                  url.toLowerCase().includes("linkedin.com/jobs/view/")
                )}
              </p>
            </div>
          )}
                          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                            <div className="space-y-1">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                                Role Title
                              </p>
                              <p className="text-sm font-medium text-foreground">
                                {effectiveCompany.role_title || "Not detected yet"}
                              </p>
                            </div>
                            <div className="space-y-1">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                                Company
                              </p>
                              <p className="text-sm font-medium text-foreground">
                                {effectiveCompany.name || "Not detected yet"}
                              </p>
                            </div>
                            <div className="space-y-1">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                                Level
                              </p>
                              <p className="text-sm font-medium text-foreground">
                                {effectiveCompany.role_level || "Not detected yet"}
                              </p>
                            </div>
                          </div>

                          {effectiveCompany.interview_focus.length > 0 && (
                            <div className="space-y-2">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                                Top signals
                              </p>
                              <div className="flex flex-wrap gap-2">
                                {effectiveCompany.interview_focus.slice(0, 6).map((item) => (
                                  <Badge
                                    key={item}
                                    variant="secondary"
                                    className="max-w-full whitespace-normal break-words"
                                  >
                                    {item}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          )}

                          {effectiveCompany.role_requirements.length > 0 && (
                            <div className="space-y-2">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                                Priority requirements
                              </p>
                              <ul className="space-y-1 text-sm text-muted-foreground">
                                {effectiveCompany.role_requirements.slice(0, 3).map((item) => (
                                  <li key={item} className="flex gap-2">
                                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                                    <span className="break-words">{item}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    )}
                    <CandidateProfileForm
                      profile={prepareCandidate}
                      onChange={handlePrepareProfileChange}
                    />
                    <CompanyInfoForm
                      companyInfo={effectiveCompany}
                      onChange={(next) => setCompanyInfo(next)}
                    />
                    <InterviewerProfileForm
                      profile={effectiveInterviewer}
                      onChange={(next) => setInterviewerProfile(next)}
                    />
                    <StyleSelector selectedStyle={selectedStyle} onStyleChange={setSelectedStyle} />
                  </section>
                </div>
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="insights">
            <ScrollArea className="h-[calc(100vh-190px)] rounded-md border">
              <InsightsWorkspace
                candidateProfile={effectiveCandidate}
                companyInfo={effectiveCompany}
                interviewerProfile={effectiveInterviewer}
                cvText={cvText}
                language={language}
                onApplyProfile={handleInsightsProfileApplied}
                onApplyCvText={handleInsightsCvApplied}
              />
            </ScrollArea>
          </TabsContent>

          <TabsContent value="coach">
            <ScrollArea className="h-[calc(100vh-190px)] rounded-md border">
              <div className="space-y-4 p-4">
                {coachError && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>Suggestion failed</AlertTitle>
                    <AlertDescription>{coachError}</AlertDescription>
                  </Alert>
                )}
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
                  <section className="xl:col-span-4">
                    <QuestionInput
                      onSubmit={submitCoachQuestion}
                      isLoading={isLoading}
                      mode={backendMode}
                      defaultLanguage={language}
                    />
                  </section>
                  <section className="xl:col-span-5">
                    <SuggestionDisplay
                      suggestion={currentSuggestion}
                      isLoading={isLoading}
                      question={currentQuestion}
                    />
                  </section>
                  <section className="xl:col-span-3">
                    <ConversationHistory entries={conversationHistory} />
                    <Button
                      type="button"
                      variant="outline"
                      className="mt-4 w-full"
                      onClick={() => {
                        setConversationHistory([]);
                        clearConversationHistoryPersistence();
                      }}
                      disabled={conversationHistory.length === 0}
                    >
                      Clear session history
                    </Button>
                  </section>
                </div>
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="live">
            <ScrollArea className="h-[calc(100vh-190px)] rounded-md border">
              <div className="space-y-4 p-4">
                {(wsError || liveError || audioError) && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>Live warning</AlertTitle>
                    <AlertDescription>{wsError || liveError || audioError}</AlertDescription>
                  </Alert>
                )}

                <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
                  {/* LEFT COLUMN: Live Captions + Session controls */}
                  <section className="space-y-4 xl:col-span-3">
                    {/* Live Captions - First in left column */}
                    <Card className="bg-surface-800 border-l-4 border-l-primary-500 shadow-lg shadow-black/10">
                      <CardHeader className="pb-2 bg-gradient-to-r from-primary-500/10 to-transparent -mx-4 -mt-4 px-4 pt-4 mb-2">
                        <CardTitle className="text-lg font-semibold flex items-center gap-2">
                          <span className="relative flex h-3 w-3">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
                          </span>
                          Live Captions
                        </CardTitle>
                        <CardDescription className="text-surface-400">Real-time transcription as you speak</CardDescription>
                      </CardHeader>
                      <CardContent>
                        <ScrollArea className="h-[200px] rounded-md border bg-muted/30 p-3">
                          {Object.keys(liveCaptions).length === 0 ? (
                            <p className="text-sm text-muted-foreground">Waiting for speech...</p>
                          ) : (
                            <div className="space-y-3">
                              {Object.entries(liveCaptions).map(([speaker, caption]) => {
                                const speakerLabel = 
                                  speaker === "interviewer" ? "Interviewer" :
                                  speaker === "candidate" ? "You" :
                                  "System";
                                const speakerColorClass =
                                  speaker === "interviewer" ? "text-primary-600" :
                                  speaker === "candidate" ? "text-accent-600" :
                                  "text-purple-600";
                                return (
                                  <div key={speaker} className="rounded-md bg-background p-2 border">
                                    <div className="mb-1 flex items-center gap-2 text-xs">
                                      <span className={`font-semibold ${speakerColorClass}`}>
                                        {speakerLabel}
                                      </span>
                                      {caption.isPartial && (
                                        <span className="flex items-center gap-1 text-muted-foreground">
                                          <span className="relative flex h-2 w-2">
                                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                                            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                                          </span>
                                          speaking...
                                        </span>
                                      )}
                                    </div>
                                    <p className={`text-sm ${caption.isPartial ? "italic" : ""}`}>
                                      {caption.text}
                                      {caption.isPartial && <span className="animate-pulse">▌</span>}
                                    </p>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </ScrollArea>
                      </CardContent>
                    </Card>

                    {/* Session controls - Second in left column */}
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-base">Session controls</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3 text-sm">
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          <Badge variant="outline">WS: {wsConnected ? "on" : "off"}</Badge>
                          <Badge variant="outline">Session: {liveSession.isActive ? "active" : "idle"}</Badge>
                          <Badge variant="outline" className={modeBadgeClass(liveSession.mode)}>
                            Mode: {modeLabel(liveSession.mode)}
                          </Badge>
                          <Badge variant="outline">Duration: {formatDuration(liveSession.durationSec)}</Badge>
                          <Badge variant="outline">Exchanges: {liveSession.exchangeCount}</Badge>
                          <Badge variant="outline">Avg: {liveSession.averageLatencyMs}ms</Badge>
                        </div>
                        <Separator />
                        {!wsConnected ? (
                          <Button type="button" className="w-full" onClick={connectWebSocket} disabled={wsConnecting}>
                            {wsConnecting ? (
                              <>
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                Connecting...
                              </>
                            ) : (
                              "Connect WebSocket"
                            )}
                          </Button>
                        ) : (
                          <Button type="button" variant="outline" className="w-full" onClick={disconnectWebSocket}>
                            Disconnect WebSocket
                          </Button>
                        )}
                        {!liveSession.sessionId ? (
                          <Button type="button" className="w-full" onClick={startLiveSession} disabled={!wsConnected}>
                            Start session
                          </Button>
                        ) : (
                          <>
                            {liveSession.isActive ? (
                              <Button type="button" variant="outline" className="w-full" onClick={pauseLiveSession}>
                                Pause session
                              </Button>
                            ) : (
                              <Button type="button" className="w-full" onClick={resumeLiveSession}>
                                Resume session
                              </Button>
                            )}
                            <Button type="button" variant="destructive" className="w-full" onClick={endLiveSession}>
                              End session
                            </Button>
                            {/* History count selector - visible during active session */}
                            {liveSession.sessionId && (
                              <div className="flex items-center gap-2">
                                <Label htmlFor="history-count" className="text-xs whitespace-nowrap">
                                  History:
                                </Label>
                                <Select
                                  value={historyCount.toString()}
                                  onValueChange={(value) => setHistoryCount(parseInt(value, 10))}
                                >
                                  <SelectTrigger id="history-count" className="w-full h-8">
                                    <SelectValue placeholder="4 messages" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((num) => (
                                      <SelectItem key={num} value={num.toString()}>
                                        {num} {num === 1 ? 'message' : 'messages'}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                            )}
                            {/* Manual "Get Suggestions" button - visible during active session */}
                            {liveSession.sessionId && (
                              <Button
                                type="button"
                                className="w-full bg-blue-600 hover:bg-blue-700"
                                onClick={handleGetSuggestions}
                                disabled={isSuggestionsLoading}
                              >
                                {isSuggestionsLoading ? (
                                  <>
                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                    Getting...
                                  </>
                                ) : (
                                  <>
                                    <MessageSquare className="mr-2 h-4 w-4" />
                                    Get Suggestions (Ctrl+Enter)
                                  </>
                                )}
                              </Button>
                            )}
                            
                            {/* DEBUG PANEL - Always shows what was sent to coach */}
                            {debugInfo && (
                              <div className="mt-3 rounded-md border border-surface-600 bg-surface-800 p-3">
                                <div className="flex items-center gap-2 mb-2">
                                  <Bug className="h-4 w-4 text-yellow-400" />
                                  <span className="text-xs font-bold text-yellow-400 uppercase">Debug: What was sent to coach</span>
                                </div>
                                <div className="space-y-2 text-xs">
                                  <div className="grid grid-cols-2 gap-2">
                                    <Badge variant="outline" className="text-[10px]">Session: {debugInfo.sessionId.slice(0, 8)}...</Badge>
                                    <Badge variant="outline" className="text-[10px]">History Count: {debugInfo.historyCount}</Badge>
                                    <Badge variant="outline" className="text-[10px]">Transcripts: {debugInfo.transcriptsCount}</Badge>
                                    <Badge variant="outline" className={debugInfo.error ? "text-[10px] bg-red-100" : "text-[10px] bg-green-100"}>
                                      {debugInfo.error ? 'ERROR' : 'SUCCESS'}
                                    </Badge>
                                  </div>
                                  
                                  {debugInfo.error && (
                                    <div className="rounded bg-red-100 p-2 text-red-700">
                                      Error: {debugInfo.error}
                                    </div>
                                  )}
                                  
                                  {/* SHOW QUESTIONS SENT TO COACH */}
                                  {(() => {
                                    const response = debugInfo.response as Record<string, unknown> | null;
                                    const debug = response?.debug as Record<string, unknown> | undefined;
                                    const history = debug?.conversation_history as Array<{speaker: string; text: string}> | undefined;
                                    const question = debug?.question as string | undefined;
                                    
                                    // Show error debug info if no history found
                                    const activePipelines = debug?.active_pipelines as string[] | undefined;
                                    const historyFound = debug?.conversation_history_found as number | undefined;
                                    const historyRequested = debug?.history_count_requested as number | undefined;
                                    
                                    return (
                                      <>
                                        {/* ERROR DEBUG INFO */}
                                        {debugInfo.error && debug && (
                                          <div className="rounded bg-red-50 border border-red-200 p-2">
                                            <div className="font-semibold text-red-800">⚠️ Error Debug Info:</div>
                                            <div className="mt-1 space-y-1 text-[10px]">
                                              <p><strong>Session ID:</strong> {(debug.session_id as string) || 'N/A'}</p>
                                              <p><strong>History Requested:</strong> {historyRequested ?? 'N/A'}</p>
                                              <p><strong>History Found:</strong> {historyFound ?? 0}</p>
                                              <p><strong>Active Pipelines:</strong> {activePipelines?.join(', ') || 'None'}</p>
                                              <p><strong>Question Text:</strong> {(debug.question_text as string) || 'Empty'}</p>
                                            </div>
                                          </div>
                                        )}
                                        
                                        {history && history.length > 0 && (
                                          <div className="rounded bg-surface-700 border border-surface-600">
                                            <div className="p-2 bg-surface-800 font-semibold text-yellow-400">
                                              📋 Questions/Messages Sent to Coach ({history.length}):
                                            </div>
                                            <div className="max-h-48 overflow-y-auto p-2 space-y-2">
                                              {history.map((msg, idx) => (
                                                <div key={idx} className="border-l-2 border-yellow-500 pl-2">
                                                  <span className={msg.speaker === 'interviewer' ? 'text-primary-400 font-bold' : 'text-accent-400 font-bold'}>
                                                    {msg.speaker?.toUpperCase() || 'UNKNOWN'}:
                                                  </span>
                                                  <p className="text-surface-100 mt-0.5">{msg.text}</p>
                                                </div>
                                              ))}
                                            </div>
                                          </div>
                                        )}
                                        
                                        {question && (
                                          <div className="rounded bg-blue-50 border border-blue-200 p-2">
                                            <div className="font-semibold text-blue-800">❓ Current Question Being Processed:</div>
                                            <p className="text-blue-700 mt-1">{question}</p>
                                          </div>
                                        )}
                                      </>
                                    );
                                  })()}
                                  
                                  <details className="rounded bg-surface-700 border border-surface-600">
                                    <summary className="cursor-pointer p-2 font-semibold text-yellow-400 hover:bg-surface-600">View Full Request JSON</summary>
                                    <pre className="max-h-40 overflow-auto p-2 text-[10px] bg-surface-800 text-surface-200">
                                      {JSON.stringify(debugInfo.request, null, 2)}
                                    </pre>
                                  </details>
                                  
                                  {debugInfo.response && (
                                    <details className="rounded bg-surface-700 border border-surface-600">
                                      <summary className="cursor-pointer p-2 font-semibold text-yellow-400 hover:bg-surface-600">View Full Response JSON</summary>
                                      <pre className="max-h-40 overflow-auto p-2 text-[10px] bg-surface-800 text-surface-200">
                                        {JSON.stringify(debugInfo.response, null, 2)}
                                      </pre>
                                    </details>
                                  )}
                                </div>
                              </div>
                            )}
                          </>
                        )}
                        <p className="text-xs text-muted-foreground">
                          Last heartbeat: {wsLastHeartbeat ? new Date(wsLastHeartbeat).toLocaleTimeString() : "-"}
                        </p>
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="flex items-center gap-2 text-base">
                          <Mic className="h-4 w-4" /> Audio settings
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3 text-sm">
                        {permissionGuidance && (
                          <Alert variant="destructive">
                            <AlertCircle className="h-4 w-4" />
                            <AlertTitle>Permission required</AlertTitle>
                            <AlertDescription>{permissionGuidance}</AlertDescription>
                          </Alert>
                        )}
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          <Badge variant="outline">Platform: {platformInfo?.os ?? "unknown"}</Badge>
                          <Badge variant="outline">Audio capability: {audioCapability}</Badge>
                          <Badge variant="outline">Mic: {micPermission}</Badge>
                          <Badge variant="outline">Screen: {screenPermissionLabel}</Badge>
                          <Badge
                            variant="outline"
                            className={captureStateBadgeClass(captureLifecycleState)}
                          >
                            Capture: {captureStateLabel(captureLifecycleState)}
                          </Badge>
                          <Badge variant="outline">
                            Session: {captureStatus?.session_id ?? "-"}
                          </Badge>
                        </div>
                        <div className="grid grid-cols-3 gap-2">
                          {(["system", "mic", "both"] as const).map((mode) => (
                            <Button
                              key={mode}
                              type="button"
                              variant={inputMode === mode ? "default" : "outline"}
                              onClick={() => setInputMode(mode)}
                              className="text-xs"
                            >
                              {mode}
                            </Button>
                          ))}
                        </div>
                        <Select value={selectedDeviceId} onValueChange={setSelectedDeviceId}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select input device" />
                          </SelectTrigger>
                          <SelectContent>
                            {audioDevices.length === 0 ? (
                              <SelectItem value="default">No devices detected</SelectItem>
                            ) : (
                              audioDevices.map((device) => (
                                <SelectItem key={device.id} value={device.id}>
                                  {device.name}
                                </SelectItem>
                              ))
                            )}
                          </SelectContent>
                        </Select>
                        <Button type="button" variant="outline" onClick={refreshAudioDevices}>
                          Refresh devices
                        </Button>
                        <Button type="button" variant="outline" onClick={refreshPermissions}>
                          Refresh permissions
                        </Button>
                        <Button type="button" variant="outline" onClick={() => void requestPermission("Microphone")}>
                          Request microphone permission
                        </Button>
                        <Button type="button" variant="outline" onClick={() => void requestPermission("ScreenRecording")}>
                          Request screen permission
                        </Button>
                        <div className="grid grid-cols-2 gap-2">
                        <Button
                          type="button"
                          onClick={() => void startCapture()}
                          disabled={
                            captureBusy ||
                            !liveSession.isActive ||
                            captureLifecycleState !== "idle" ||
                            (platform === "macos" &&
                              (inputMode === "system" || inputMode === "both") &&
                              systemAudioPermission === "restricted")
                          }
                        >
                          Start capture
                        </Button>
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => void stopCapture()}
                            disabled={captureBusy || captureLifecycleState === "idle"}
                          >
                            Stop capture
                          </Button>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => void pauseCapture()}
                            disabled={captureBusy || captureLifecycleState !== "capturing"}
                          >
                            Pause capture
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => void resumeCapture()}
                            disabled={captureBusy || captureLifecycleState !== "paused"}
                          >
                            Resume capture
                          </Button>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          Capture active: {captureStatus?.is_capturing ? "yes" : "no"} · Duration: {Math.floor((captureStatus?.duration_ms ?? 0) / 1000)}s
                        </p>
                      </CardContent>
                    </Card>
                  </section>

                  {/* RIGHT COLUMN: Conversation History */}
                  <section className="space-y-4 xl:col-span-4">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-base">Conversation History</CardTitle>
                        <CardDescription>Finalized transcripts from live captions</CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        <ScrollArea className="h-[320px] rounded-md border p-3">
                          {liveTranscripts.length === 0 ? (
                            <p className="text-sm text-muted-foreground">No transcript entries yet.</p>
                          ) : (
                            <div className="space-y-2">
                              {/* Reverse to show newest messages at top */}
                              {[...liveTranscripts].reverse().map((entry) => {
                                // Map speaker to user-friendly label
                                const speakerLabel = 
                                  entry.speaker === "interviewer" ? "Interviewer" :
                                  entry.speaker === "candidate" ? "You" :
                                  entry.speaker === "system" ? "System" : "Unknown";
                                
                                // Style based on speaker
                                const speakerColorClass =
                                  entry.speaker === "interviewer" ? "text-primary-600" :
                                  entry.speaker === "candidate" ? "text-accent-600" :
                                  entry.speaker === "system" ? "text-purple-600" : "text-surface-500";
                                
                                return (
                                  <div 
                                    key={entry.id} 
                                    className={`rounded border p-2 text-sm ${
                                      entry.isFinal ? "bg-card" : "bg-muted/50 border-dashed"
                                    }`}
                                  >
                                    <div className="mb-1 flex justify-between text-xs">
                                      <span className={`font-medium ${speakerColorClass}`}>
                                        {speakerLabel}
                                        {!entry.isFinal && (
                                          <span className="ml-2 text-muted-foreground animate-pulse">
                                            (typing...)
                                          </span>
                                        )}
                                      </span>
                                      <span className="text-muted-foreground">
                                        {new Date(entry.timestamp).toLocaleTimeString()}
                                      </span>
                                    </div>
                                    <p className={entry.isFinal ? "" : "italic text-muted-foreground"}>
                                      {entry.text}
                                      {!entry.isFinal && "..."}
                                    </p>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </ScrollArea>
                        <Label htmlFor="live-question">Manual live question</Label>
                        <Textarea
                          id="live-question"
                          value={liveQuestionInput}
                          onChange={(event) => setLiveQuestionInput(event.target.value)}
                          className="min-h-[120px]"
                        />
                        <Button
                          type="button"
                          className="w-full"
                          onClick={submitLiveQuestion}
                          disabled={!liveSession.isActive || !liveQuestionInput.trim()}
                        >
                          Send to realtime pipeline
                        </Button>
                      </CardContent>
                    </Card>
                  </section>

                  {/* CENTER COLUMN: Realtime suggestion */}
                  <section className="space-y-4 xl:col-span-5">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="flex items-center gap-2 text-base">
                          <Radio className="h-4 w-4" /> Realtime suggestion
                        </CardTitle>
                        <CardDescription>
                          A short usable answer arrives first. The refined full response can replace it if it improves quality.
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {liveProcessing && !liveSuggestion && (
                          <Alert>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            <AlertTitle>Processing</AlertTitle>
                            <AlertDescription>Realtime pipeline is generating output.</AlertDescription>
                          </Alert>
                        )}

                        {liveProcessing && liveSuggestion && !hasFullResponse && (
                          <Alert>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            <AlertTitle>Refining full response</AlertTitle>
                            <AlertDescription>The first answer is already visible while the refined version is composed.</AlertDescription>
                          </Alert>
                        )}

                        {!liveSuggestion ? (
                          <p className="text-sm text-muted-foreground">No realtime suggestion yet.</p>
                        ) : (
                          <>
                            <div className="flex flex-wrap gap-2 text-xs">
                              <Badge variant="outline" className={modeBadgeClass(liveSuggestion.mode)}>
                                Mode: {modeLabel(liveSuggestion.mode)}
                              </Badge>
                              <Badge variant="outline">Confidence: {Math.round(liveSuggestion.confidence * 100)}%</Badge>
                              {liveSuggestion.latencyMs !== undefined && (
                                <Badge variant="outline">Latency: {liveSuggestion.latencyMs}ms</Badge>
                              )}
                            </div>

                            {/* Full Response - shown FIRST */}
                            <section
                              className={`space-y-2 rounded-md border p-3 transition-all duration-300 ${
                                hasFullResponse ? "bg-card" : "bg-muted/20"
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <h3 className="text-xs font-semibold uppercase text-muted-foreground">
                                  Full response
                                </h3>
                                {liveProcessing && hasFullResponse ? (
                                  <span className="text-[10px] uppercase text-primary">
                                    Streaming...
                                  </span>
                                ) : !hasFullResponse && (
                                  <span className="text-[10px] uppercase text-muted-foreground">
                                    Waiting...
                                  </span>
                                )}
                              </div>
                              {hasFullResponse ? (
                                <div className="space-y-4 whitespace-pre-wrap transition-opacity duration-300">
                                  {renderLiveSuggestionParagraphs(liveSuggestion.fullResponse)}
                                  {liveProcessing && (
                                    <span className="inline-block animate-pulse text-primary">|</span>
                                  )}
                                </div>
                              ) : (
                                <div className="space-y-2">
                                  <div className="h-4 w-4/5 animate-pulse rounded bg-muted" />
                                  <div className="h-4 w-full animate-pulse rounded bg-muted" />
                                  <div className="h-4 w-11/12 animate-pulse rounded bg-muted" />
                                </div>
                              )}
                            </section>

                            {/* Preview Bullets - shown SECOND, below Full Response */}
                            <section
                              className={`space-y-2 rounded-md border border-dashed p-3 text-xs transition-opacity duration-300 ${
                                hasFullResponse ? "opacity-70" : "opacity-100"
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <h3 className="text-xs font-semibold uppercase text-muted-foreground">
                                  Preview bullets
                                </h3>
                                <span className="text-[10px] uppercase text-muted-foreground">
                                  Preview only
                                </span>
                              </div>
                              {hasPreviewBullets ? (
                                <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                                  {previewBullets.map((bullet, index) => (
                                    <li key={`${bullet}-${index}`}>{bullet}</li>
                                  ))}
                                </ul>
                              ) : (
                                <p className="text-xs text-muted-foreground">
                                  No preview bullets yet.
                                </p>
                              )}
                            </section>

                            {/* Debug Panel */}
                            {liveSuggestion.debug && (
                              <section className="space-y-2 rounded-md border border-warning-200 bg-warning-50/50 p-3">
                                <Accordion type="single" collapsible className="w-full">
                                  <AccordionItem value="debug" className="border-none">
                                    <AccordionTrigger className="py-2 hover:no-underline">
                                      <div className="flex items-center gap-2 text-warning-700">
                                        <Bug className="h-4 w-4" />
                                        <span className="text-xs font-semibold">Debug: What was sent to the coach</span>
                                      </div>
                                    </AccordionTrigger>
                                    <AccordionContent>
                                      <div className="space-y-3 pt-2 text-xs">
                                        {/* History Count */}
                                        <div className="flex items-center gap-2">
                                          <Badge variant="outline" className="text-[10px]">
                                            History Count: {liveSuggestion.debug.history_count ?? 0}
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Messages: {liveSuggestion.debug.conversation_history?.length ?? 0}
                                          </Badge>
                                          {liveSuggestion.debug.path_used && (
                                            <Badge variant="outline" className="text-[10px]">
                                              Path: {liveSuggestion.debug.path_used}
                                            </Badge>
                                          )}
                                        </div>

                                        {/* Conversation History */}
                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Conversation History:</p>
                                          <div className="max-h-32 overflow-y-auto rounded bg-white p-2">
                                            {(liveSuggestion.debug.conversation_history ?? []).map((msg, idx) => (
                                              <div key={idx} className="mb-1">
                                                <span className={msg.speaker === 'interviewer' ? 'text-primary-600 font-semibold' : 'text-accent-600 font-semibold'}>
                                                  {msg.speaker.toUpperCase()}:
                                                </span>
                                                <span className="text-surface-700"> {msg.text}</span>
                                              </div>
                                            ))}
                                          </div>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Semantic Blocks Window:</p>
                                          <div className="max-h-32 overflow-y-auto rounded bg-white p-2">
                                            {(liveSuggestion.debug.semantic_blocks_window ?? []).length > 0 ? (
                                              (liveSuggestion.debug.semantic_blocks_window ?? []).map((msg, idx) => (
                                                <div key={idx} className="mb-1">
                                                  <span className={msg.speaker === 'interviewer' ? 'text-primary-600 font-semibold' : 'text-accent-600 font-semibold'}>
                                                    {msg.speaker.toUpperCase()}:
                                                  </span>
                                                  <span className="text-surface-700"> {msg.text}</span>
                                                </div>
                                              ))
                                            ) : (
                                              <p className="text-surface-700">N/A</p>
                                            )}
                                          </div>
                                        </div>

                                        {/* Question */}
                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Question:</p>
                                          <p className="rounded bg-white p-2 text-surface-700">{liveSuggestion.debug.question ?? "N/A"}</p>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Resolved Question:</p>
                                          <p className="rounded bg-white p-2 text-surface-700">{liveSuggestion.debug.resolved_question ?? "N/A"}</p>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Literal Question:</p>
                                          <p className="rounded bg-white p-2 text-surface-700">{liveSuggestion.debug.literal_question ?? liveSuggestion.debug.brain_contract?.literal_question ?? "N/A"}</p>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Contextualized Question:</p>
                                          <p className="rounded bg-white p-2 text-surface-700">{liveSuggestion.debug.contextualized_question ?? liveSuggestion.debug.brain_contract?.contextualized_question ?? "N/A"}</p>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Detected Asks In Order:</p>
                                          <div className="rounded bg-white p-2 text-surface-700">
                                            {(liveSuggestion.debug.asks_in_order ?? []).length > 0 ? (
                                              <ol className="list-decimal space-y-1 pl-4">
                                                {(liveSuggestion.debug.asks_in_order ?? []).map((ask, index) => (
                                                  <li key={`${ask}-${index}`}>{ask}</li>
                                                ))}
                                              </ol>
                                            ) : (
                                              <p>N/A</p>
                                            )}
                                          </div>
                                        </div>

                                        <div className="grid grid-cols-2 gap-2">
                                          <Badge variant="outline" className="text-[10px]">
                                            Plan Stage: {liveSuggestion.debug.plan_stage ?? "N/A"}
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Planner: {liveSuggestion.debug.planner_source ?? "N/A"}
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Effective Turns: {liveSuggestion.debug.effective_turn_count ?? "N/A"}
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Latest Included: {String(liveSuggestion.debug.latest_turn_included ?? "N/A")}
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Draft Ready: {String(liveSuggestion.debug.draft_ready_at_silence ?? "N/A")}
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Fallback: {String(liveSuggestion.debug.fallback_used ?? "N/A")}
                                          </Badge>
                                        </div>

                                        <div className="grid grid-cols-2 gap-2">
                                          <Badge variant="outline" className="text-[10px]">
                                            Base Plan: {liveSuggestion.debug.time_to_base_plan_ms ?? "N/A"} ms
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Semantic Plan: {liveSuggestion.debug.time_to_semantic_plan_ms ?? "N/A"} ms
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Silence Wait: {liveSuggestion.debug.silence_wait_ms ?? "N/A"} ms
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Silence To Answer: {liveSuggestion.debug.time_from_silence_to_answer_ms ?? "N/A"} ms
                                          </Badge>
                                        </div>

                                        <div className="grid grid-cols-2 gap-2">
                                          <Badge variant="outline" className="text-[10px]">
                                            Brain Status: {liveSuggestion.debug.brain_status ?? "N/A"}
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Brain Duration: {liveSuggestion.debug.brain_duration_ms ?? "N/A"} ms
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Brain Started: {liveSuggestion.debug.brain_started_at_ms ?? "N/A"} ms
                                          </Badge>
                                          <Badge variant="outline" className="text-[10px]">
                                            Brain Completed: {liveSuggestion.debug.brain_completed_at_ms ?? "N/A"} ms
                                          </Badge>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Brain Failure Reason:</p>
                                          <p className="rounded bg-white p-2 text-surface-700">{liveSuggestion.debug.brain_failure_reason ?? "N/A"}</p>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Brain Guidance:</p>
                                          <div className="rounded bg-white p-2 text-surface-700">
                                            <p><strong>Focus:</strong> {liveSuggestion.debug.answer_focus ?? "N/A"}</p>
                                            <p><strong>Style:</strong> {liveSuggestion.debug.answer_style_guidance ?? "N/A"}</p>
                                            <p><strong>Reasoning:</strong> {liveSuggestion.debug.planner_reasoning_summary ?? "N/A"}</p>
                                          </div>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Brain Contract:</p>
                                          <div className="rounded bg-white p-2 text-surface-700">
                                            <p><strong>Interviewer Need:</strong> {liveSuggestion.debug.brain_contract?.interviewer_need?.summary ?? "N/A"}</p>
                                            <p><strong>Context Focus:</strong> {(liveSuggestion.debug.brain_contract?.context_focus ?? []).join(" | ") || "N/A"}</p>
                                          </div>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Draft Answer From Brain:</p>
                                          <pre className="max-h-32 overflow-y-auto rounded bg-surface-100 p-2 text-[10px] whitespace-pre-wrap">
                                            {liveSuggestion.debug.draft_answer ?? "N/A"}
                                          </pre>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Latest Live Tail Seen By Brain:</p>
                                          <div className="rounded bg-white p-2 text-surface-700">
                                            <p><strong>Latest Display Caption:</strong> {liveSuggestion.debug.latest_display_caption ?? "N/A"}</p>
                                            <p><strong>Pending Interviewer Candidate:</strong> {liveSuggestion.debug.pending_interviewer_candidate ?? "N/A"}</p>
                                          </div>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">Request Payload:</p>
                                          <pre className="max-h-40 overflow-y-auto rounded bg-surface-100 p-2 text-[10px]">
                                            {JSON.stringify(liveSuggestion.debug.request_payload ?? {}, null, 2)}
                                          </pre>
                                        </div>

                                        {/* Legacy prompt fields, when available */}
                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">System Prompt (first 500 chars):</p>
                                          <pre className="max-h-24 overflow-y-auto rounded bg-surface-100 p-2 text-[10px]">
                                            {liveSuggestion.debug.system_prompt?.slice(0, 500) ?? "N/A"}
                                          </pre>
                                        </div>

                                        <div className="space-y-1">
                                          <p className="font-semibold text-warning-800">User Prompt (first 1000 chars):</p>
                                          <pre className="max-h-32 overflow-y-auto rounded bg-surface-100 p-2 text-[10px]">
                                            {liveSuggestion.debug.user_prompt?.slice(0, 1000) ?? "N/A"}
                                          </pre>
                                        </div>
                                      </div>
                                    </AccordionContent>
                                  </AccordionItem>
                                </Accordion>
                              </section>
                            )}
                          </>
                        )}
                      </CardContent>
                    </Card>
                  </section>
                </div>
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="settings">
            <ScrollArea className="h-[calc(100vh-190px)] rounded-md border">
              <div className="p-4">
                <SettingsPanel backendUrl={backendUrl} />
              </div>
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

export default App;
