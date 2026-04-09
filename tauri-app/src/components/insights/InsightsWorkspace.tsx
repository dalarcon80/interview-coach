import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Download,
  FilePenLine,
  Lightbulb,
  Loader2,
  ShieldCheck,
  Sparkles,
  Target,
  Wand2,
} from "lucide-react";

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
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import api from "@/lib/api-client";
import type {
  ApprovedContextPreview,
  CVVariantPreview,
  CandidateProfile,
  CompanyInfo,
  EvidenceCard,
  EvidenceGap,
  InsightQuestion,
  InsightsActionStep,
  InsightsAnalysisResponse,
  InterviewerProfile,
  ProposedChange,
  ScoreHistoryEvent,
  SupportLevel,
} from "@/types";

interface InsightsWorkspaceProps {
  candidateProfile: CandidateProfile;
  companyInfo: CompanyInfo;
  interviewerProfile: InterviewerProfile;
  cvText: string;
  language: string;
  onApplyProfile: (profile: CandidateProfile, contextSummary: string) => void;
  onApplyCvText: (cvText: string, contextSummary: string, profile?: CandidateProfile) => void;
}

type WorkspaceTab = "overview" | "action-plan" | "evidence" | "cv-studio";

interface LocalWorkspaceState {
  workspaceId?: string;
  runId?: string;
  selectedVariant?: "master_cv" | "role_variant_cv";
  selectedChangeIds?: string[];
  selectedEvidenceIds?: string[];
  answerDrafts?: Record<string, string>;
  answerFieldDrafts?: Record<string, Record<string, string>>;
  activeTab?: WorkspaceTab;
  lastAnalyzedFingerprint?: string | null;
  analysisSnapshot?: InsightsAnalysisResponse | null;
}

type SaveState = "idle" | "saving" | "saved" | "unsaved" | "error";

const VARIANT_LABELS: Record<"master_cv" | "role_variant_cv", string> = {
  master_cv: "Master CV",
  role_variant_cv: "Role Variant",
};

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "default";
}

function buildFingerprint(payload: {
  candidateProfile: CandidateProfile;
  companyInfo: CompanyInfo;
  interviewerProfile: InterviewerProfile;
  cvText: string;
  language: string;
}): string {
  return JSON.stringify(payload);
}

function buildWorkspaceStorageKey(candidateProfile: CandidateProfile, companyInfo: CompanyInfo): string {
  const profileScope = slug(candidateProfile.profile_id || candidateProfile.name || candidateProfile.current_role || "anonymous");
  const roleScope = slug(companyInfo.role_title || candidateProfile.target_role || candidateProfile.current_role || "role");
  return `interview-coach:insights-workspace:${profileScope}:${roleScope}`;
}

function readWorkspaceState(key: string): LocalWorkspaceState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as LocalWorkspaceState) : null;
  } catch {
    return null;
  }
}

function writeWorkspaceState(key: string, value: LocalWorkspaceState): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

function buildAnswerFromFields(fields: Record<string, string> | undefined): string {
  if (!fields) return "";
  return Object.entries(fields)
    .map(([key, value]) => {
      const trimmed = value.trim();
      if (!trimmed) return "";
      return `${key.replace(/_/g, " ")}: ${trimmed}`;
    })
    .filter(Boolean)
    .join("\n");
}

function buildBackendUiState(params: {
  activeTab: WorkspaceTab;
  selectedVariant: "master_cv" | "role_variant_cv";
  selectedChangeIds: string[];
  selectedEvidenceIds: string[];
  answerDrafts: Record<string, string>;
  answerFieldDrafts: Record<string, Record<string, string>>;
  lastAnalyzedFingerprint: string | null;
  scoreHistory: ScoreHistoryEvent[];
}) {
  return {
    active_tab: params.activeTab,
    selected_variant: params.selectedVariant,
    selected_change_ids: params.selectedChangeIds,
    selected_evidence_ids: params.selectedEvidenceIds,
    answer_drafts: params.answerDrafts,
    answer_field_drafts: params.answerFieldDrafts,
    last_analyzed_fingerprint: params.lastAnalyzedFingerprint,
    score_history: params.scoreHistory,
  };
}

function downloadBase64File(filename: string, mimeType: string, contentBase64: string): void {
  const binary = window.atob(contentBase64);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function scoreVariant(score: number) {
  if (score >= 80) return "default";
  if (score >= 65) return "secondary";
  return "outline";
}

function supportLevelVariant(level: SupportLevel) {
  if (level === "curated") return "default";
  if (level === "derived") return "secondary";
  return "outline";
}

function severityVariant(severity: "high" | "medium" | "low") {
  if (severity === "high") return "destructive";
  if (severity === "medium") return "outline";
  return "secondary";
}

function formatDelta(delta?: {
  global?: number;
  roleFit?: number;
  proofStrength?: number;
  cvRepresentationQuality?: number;
}): string {
  if (!delta) return "No delta estimate";
  const parts = [
    delta.global ? `Global +${delta.global}` : "",
    delta.roleFit ? `Role Fit +${delta.roleFit}` : "",
    delta.proofStrength ? `Proof +${delta.proofStrength}` : "",
    delta.cvRepresentationQuality ? `CV +${delta.cvRepresentationQuality}` : "",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" / ") : "No delta estimate";
}

function sourceLabel(source: EvidenceCard["source"]) {
  switch (source) {
    case "user_answer":
      return "Question answer";
    case "imported_profile":
      return "Profile";
    case "system_extraction":
      return "System extraction";
    case "generated_rewrite":
      return "Generated rewrite";
    default:
      return "CV";
  }
}

function SectionList({
  title,
  items,
  emptyText,
}: {
  title: string;
  items: string[];
  emptyText: string;
}) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <ul className="space-y-1 text-sm text-muted-foreground">
          {items.map((item) => (
            <li key={`${title}-${item}`} className="flex gap-2">
              <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
              <span className="break-words">{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LabelLike({ children }: { children: string }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
      {children}
    </p>
  );
}

function HeroMetricCard({
  label,
  value,
  caption,
}: {
  label: string;
  value: number;
  caption: string;
}) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-foreground">{label}</p>
        <Badge variant={scoreVariant(value)}>{value}/100</Badge>
      </div>
      <Progress value={value} className="mt-3" />
      <p className="mt-2 text-xs text-muted-foreground">{caption}</p>
    </div>
  );
}

function ActionCard({
  step,
  onAction,
}: {
  step: InsightsActionStep;
  onAction?: (step: InsightsActionStep) => void;
}) {
  const ctaLabel =
    step.type === "question"
      ? "Answer now"
      : step.type === "approve_evidence"
        ? "Review evidence"
        : step.type === "apply_rewrite"
          ? "Approve change"
          : step.type === "add_project"
            ? "Open project form"
            : "Regenerate role variant";
  return (
    <div className="rounded-xl border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{step.type.replace(/_/g, " ")}</Badge>
        <Badge variant={step.effort === "low" ? "secondary" : "outline"}>{step.effort} effort</Badge>
      </div>
      <p className="mt-3 text-sm font-medium text-foreground">{step.title}</p>
      <p className="mt-2 text-sm text-muted-foreground">{step.why_it_matters}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary">{formatDelta(step.estimated_delta)}</Badge>
        {step.improves_dimensions.map((dimension) => (
          <Badge key={`${step.step_id}-${dimension}`} variant="outline">
            {dimension.replace(/_/g, " ")}
          </Badge>
        ))}
      </div>
      {onAction && (
        <div className="mt-4">
          <Button type="button" size="sm" variant="outline" onClick={() => onAction(step)}>
            {ctaLabel}
          </Button>
        </div>
      )}
    </div>
  );
}

function QuestionCard({
  question,
  value,
  fields,
  busy,
  onChange,
  onFieldChange,
  onSubmit,
}: {
  question: InsightQuestion;
  value: string;
  fields: Record<string, string>;
  busy: boolean;
  onChange: (value: string) => void;
  onFieldChange: (field: string, value: string) => void;
  onSubmit: () => void;
}) {
  const fieldList = question.answer_schema?.fields ?? [];
  const canSubmit = Boolean(value.trim() || buildAnswerFromFields(fields).trim());
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={severityVariant(question.priority || "medium")}>{question.priority || "medium"}</Badge>
          <Badge variant="outline">{formatDelta(question.estimated_delta)}</Badge>
          {question.improves_dimensions?.map((dimension) => (
            <Badge key={`${question.id}-${dimension}`} variant="secondary">
              {dimension.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
        <CardTitle className="text-base">{question.title}</CardTitle>
        <CardDescription>{question.question}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border bg-muted/20 p-3 text-sm text-muted-foreground">
          <p className="font-medium text-foreground">Why this matters</p>
          <p className="mt-1">{question.why_it_matters || question.rationale}</p>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg border p-3">
            <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Good answer format</p>
            <p className="mt-2 text-sm text-foreground">{question.answer_schema?.format_hint || "Concrete example + impact"}</p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Prompt guide</p>
            <p className="mt-2 text-sm text-foreground">{question.answer_guidance || "Answer with a concrete example."}</p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Useful fields</p>
            <p className="mt-2 text-sm text-foreground">{question.answer_schema?.fields.join(", ") || "result, metric, ownership"}</p>
          </div>
        </div>
        {question.example_answer && (
          <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Example:</span> {question.example_answer}
          </div>
        )}
        {fieldList.length > 0 && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {fieldList.map((field) => (
              <div key={`${question.id}-${field}`} className="space-y-2">
                <LabelLike>{field.replace(/_/g, " ")}</LabelLike>
                <Input
                  value={fields[field] ?? ""}
                  onChange={(event) => onFieldChange(field, event.target.value)}
                  placeholder={`Add ${field.replace(/_/g, " ")}`}
                />
              </div>
            ))}
          </div>
        )}
        <Textarea
          rows={5}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={question.placeholder}
        />
        <div className="flex justify-end">
          <Button type="button" onClick={onSubmit} disabled={busy || !canSubmit}>
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                Save answer
                <ArrowRight className="ml-2 h-4 w-4" />
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function EvidenceCardView({
  card,
  selected,
  approveBusy,
  onApprove,
  onUseInCv,
  onFollowUp,
  onToggle,
}: {
  card: EvidenceCard;
  selected: boolean;
  approveBusy: boolean;
  onApprove: (card: EvidenceCard) => void;
  onUseInCv: (card: EvidenceCard) => void;
  onFollowUp: (card: EvidenceCard) => void;
  onToggle: (id: string) => void;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={card.strength === "strong" ? "default" : card.strength === "moderate" ? "secondary" : "outline"}>
                {card.strength}
              </Badge>
              <Badge variant="outline">{card.type.replace(/_/g, " ")}</Badge>
              <Badge variant="secondary">{sourceLabel(card.source)}</Badge>
              {card.confidence && <Badge variant="outline">{card.confidence} confidence</Badge>}
              {card.approval_status && <Badge variant="outline">{card.approval_status.replace(/_/g, " ")}</Badge>}
            </div>
            <CardTitle className="text-base">{card.summary}</CardTitle>
            <CardDescription>{formatDelta(card.estimated_delta)}</CardDescription>
          </div>
          <div className="flex flex-col gap-2">
            <Button type="button" size="sm" variant={selected ? "default" : "outline"} disabled={approveBusy} onClick={() => onApprove(card)}>
              {approveBusy ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : selected ? "Approved into context" : "Approve into context"}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => onUseInCv(card)}>
              Use in CV
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{card.raw_evidence}</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <SectionList
            title="Improves"
            items={card.dimensions.map((dimension) => dimension.replace(/_/g, " "))}
            emptyText="This card still needs stronger benchmark tagging."
          />
          <SectionList
            title="Matched signals"
            items={card.signal_ids}
            emptyText="No specific benchmark signal matched yet."
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" onClick={() => onFollowUp(card)}>
            Ask follow-up
          </Button>
          {selected && (
            <Button type="button" size="sm" variant="ghost" onClick={() => onToggle(card.id)}>
              Discard
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function GapCard({ gap, onResolve }: { gap: EvidenceGap; onResolve: (gap: EvidenceGap) => void }) {
  return (
    <div className="rounded-xl border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={severityVariant(gap.severity)}>{gap.severity}</Badge>
        <Badge variant="outline">{gap.dimension.replace(/_/g, " ")}</Badge>
      </div>
      <p className="mt-3 text-sm font-medium text-foreground">{gap.title}</p>
      <p className="mt-2 text-sm text-muted-foreground">{gap.why_it_matters}</p>
      <p className="mt-3 text-xs uppercase tracking-[0.18em] text-muted-foreground">Evidence needed</p>
      <p className="mt-1 text-sm text-foreground">{gap.evidence_needed}</p>
      {gap.follow_up_hint && (
        <>
          <p className="mt-3 text-xs uppercase tracking-[0.18em] text-muted-foreground">Suggested follow-up</p>
          <p className="mt-1 text-sm text-foreground">{gap.follow_up_hint}</p>
        </>
      )}
      <div className="mt-4">
        <Button type="button" size="sm" variant="outline" onClick={() => onResolve(gap)}>
          Answer question
        </Button>
      </div>
    </div>
  );
}

function ApprovedContextCard({
  preview,
  contextSaved,
}: {
  preview: ApprovedContextPreview;
  contextSaved: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4" />
          Approved context
        </CardTitle>
        <CardDescription>
          Saved in the dedicated Insights lane. It stays isolated from Brain and Live in this phase.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={contextSaved ? "default" : "outline"}>
            {contextSaved ? "approved_context_saved" : "approval_needed"}
          </Badge>
          {preview.support_level && <Badge variant="secondary">{preview.support_level}</Badge>}
        </div>
        <div className="rounded-lg border bg-muted/20 p-4">
          <p className="text-sm font-medium text-foreground">{preview.benchmark_headline}</p>
          <p className="mt-1 text-sm text-muted-foreground">{preview.summary}</p>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <SectionList title="Focus areas" items={preview.focus_areas} emptyText="No focus areas captured yet." />
          <SectionList title="Top role signals" items={preview.top_role_signals} emptyText="No role signals promoted yet." />
          <SectionList title="Reusable evidence" items={preview.reusable_evidence} emptyText="No reusable evidence approved yet." />
          <SectionList title="Project evidence" items={preview.project_evidence} emptyText="No project evidence approved yet." />
        </div>
      </CardContent>
    </Card>
  );
}

function ProposedChangeCard({
  change,
  selected,
  onToggle,
}: {
  change: ProposedChange;
  selected: boolean;
  onToggle: (changeId: string) => void;
}) {
  return (
    <div className="rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{change.category}</Badge>
            <Badge variant="outline">{change.target.replace(/_/g, " ")}</Badge>
          </div>
          <p className="mt-3 text-sm font-medium text-foreground">{change.title}</p>
          <p className="mt-2 text-sm text-muted-foreground">{change.reason}</p>
        </div>
        <Button type="button" size="sm" variant={selected ? "default" : "outline"} onClick={() => onToggle(change.id)}>
          {selected ? "Selected" : "Select"}
        </Button>
      </div>
    </div>
  );
}

export function InsightsWorkspace({
  candidateProfile,
  companyInfo,
  interviewerProfile,
  cvText,
  language,
  onApplyProfile,
  onApplyCvText,
}: InsightsWorkspaceProps) {
  const [analysis, setAnalysis] = useState<InsightsAnalysisResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("overview");
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({});
  const [answerFieldDrafts, setAnswerFieldDrafts] = useState<Record<string, Record<string, string>>>({});
  const [selectedChangeIds, setSelectedChangeIds] = useState<string[]>([]);
  const [selectedEvidenceIds, setSelectedEvidenceIds] = useState<string[]>([]);
  const [selectedVariant, setSelectedVariant] = useState<"master_cv" | "role_variant_cv">("role_variant_cv");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [pendingSaveAnnouncement, setPendingSaveAnnouncement] = useState<"benchmark_refresh" | "workspace_update" | null>(null);
  const [busyQuestionId, setBusyQuestionId] = useState<string | null>(null);
  const [applyProfileBusy, setApplyProfileBusy] = useState(false);
  const [applyVariantBusy, setApplyVariantBusy] = useState(false);
  const [approveEvidenceBusyId, setApproveEvidenceBusyId] = useState<string | null>(null);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastAnalyzedFingerprint, setLastAnalyzedFingerprint] = useState<string | null>(null);
  const [localRecoveryMode, setLocalRecoveryMode] = useState(false);
  const [expandedDimensionId, setExpandedDimensionId] = useState<string | null>(null);

  const storageKey = useMemo(
    () => buildWorkspaceStorageKey(candidateProfile, companyInfo),
    [candidateProfile, companyInfo]
  );

  const currentFingerprint = useMemo(
    () =>
      buildFingerprint({
        candidateProfile,
        companyInfo,
        interviewerProfile,
        cvText,
        language,
      }),
    [candidateProfile, companyInfo, interviewerProfile, cvText, language]
  );

  const hasMinimumInput = useMemo(
    () =>
      Boolean(
        cvText.trim().length >= 50 ||
          candidateProfile.summary.trim() ||
          candidateProfile.skills.length > 0 ||
          candidateProfile.achievements.length > 0
      ),
    [candidateProfile.achievements.length, candidateProfile.skills.length, candidateProfile.summary, cvText]
  );

  const topStrengths = analysis?.top_strengths ?? [];
  const topGaps = analysis?.top_gaps ?? [];
  const nextActions = analysis?.next_actions ?? [];
  const questionQueue = analysis?.questions.slice(0, 3) ?? [];
  const contextSaved = Boolean(analysis?.context_index_status?.saved);
  const selectedVariantPreview: CVVariantPreview | null = analysis ? analysis.cv_variants[selectedVariant] : null;
  const isStale = Boolean(analysis && lastAnalyzedFingerprint && lastAnalyzedFingerprint !== currentFingerprint);
  const supportIsLimited = analysis?.support_level === "unsupported";
  const scoreHistory = analysis?.score_history ?? [];
  const initialScore = scoreHistory[0]?.score_after ?? analysis?.global_score ?? analysis?.overall_match ?? 0;
  const currentScore = analysis?.global_score ?? analysis?.overall_match ?? 0;
  const lastScoreEvent: ScoreHistoryEvent | null = scoreHistory[scoreHistory.length - 1] ?? null;
  const scoreTimeline = [...scoreHistory].reverse().slice(0, 5);

  const applyAnalysis = (
    next: InsightsAnalysisResponse,
    options?: { fingerprint?: string | null; preserveDrafts?: boolean; confirmed?: boolean }
  ) => {
    const uiState = (next.ui_state ?? {}) as Record<string, unknown>;
    setAnalysis(next);
    setAnswerDrafts((current) => {
      const serverDrafts = (uiState.answer_drafts as Record<string, string> | undefined) ?? next.answers ?? {};
      if (options?.preserveDrafts) {
        return { ...(next.answers ?? {}), ...current };
      }
      return serverDrafts;
    });
    setAnswerFieldDrafts((current) => {
      const serverFieldDrafts =
        (uiState.answer_field_drafts as Record<string, Record<string, string>> | undefined) ?? {};
      if (options?.preserveDrafts) {
        return { ...serverFieldDrafts, ...current };
      }
      return serverFieldDrafts;
    });
    setLastAnalyzedFingerprint(options?.fingerprint ?? currentFingerprint);
    setSelectedChangeIds((current) => {
      const available = new Set(next.proposed_changes.map((change) => change.id));
      const saved = ((uiState.selected_change_ids as string[] | undefined) ?? []).filter((id) => available.has(id));
      const preserved = current.filter((id) => available.has(id));
      const preferred = saved.length > 0 ? saved : preserved;
      if (preferred.length > 0) {
        return preferred;
      }
      return next.proposed_changes.map((change) => change.id);
    });
    setSelectedEvidenceIds((current) => {
      const available = new Set(next.evidence_cards.map((card) => card.id));
      const saved = ((uiState.selected_evidence_ids as string[] | undefined) ?? []).filter((id) => available.has(id));
      const preserved = current.filter((id) => available.has(id));
      const preferred = saved.length > 0 ? saved : preserved;
      return preferred.length > 0
        ? preferred
        : next.evidence_cards.filter((card) => card.strength === "strong").slice(0, 4).map((card) => card.id);
    });
    const uiTab = uiState.active_tab as WorkspaceTab | undefined;
    if (uiTab) {
      setActiveTab(uiTab);
    }
    const uiVariant = uiState.selected_variant as "master_cv" | "role_variant_cv" | undefined;
    if (uiVariant) {
      setSelectedVariant(uiVariant);
    }
    setSaveState(options?.confirmed === false ? "unsaved" : "saved");
  };

  useEffect(() => {
    let cancelled = false;
    const cached = readWorkspaceState(storageKey);
    if (cached) {
      setActiveTab(cached.activeTab ?? "overview");
      setSelectedVariant(cached.selectedVariant ?? "role_variant_cv");
      setSelectedChangeIds(cached.selectedChangeIds ?? []);
      setSelectedEvidenceIds(cached.selectedEvidenceIds ?? []);
      setAnswerDrafts(cached.answerDrafts ?? {});
      setAnswerFieldDrafts(cached.answerFieldDrafts ?? {});
      setLastAnalyzedFingerprint(cached.lastAnalyzedFingerprint ?? null);
      if (cached.analysisSnapshot) {
        applyAnalysis(cached.analysisSnapshot, {
          fingerprint: cached.lastAnalyzedFingerprint ?? currentFingerprint,
          preserveDrafts: true,
          confirmed: false,
        });
      }
    }
    setIsRestoring(true);
    const restorePromise = cached?.workspaceId
      ? api.getInsightsWorkspace(cached.workspaceId, cached.runId)
      : api.findInsightsWorkspace({
          profile_id: candidateProfile.profile_id,
          target_role: companyInfo.role_title || candidateProfile.target_role || candidateProfile.current_role,
        });
    restorePromise
      .then((response) => {
        if (cancelled) return;
        applyAnalysis(response, {
          fingerprint: cached?.lastAnalyzedFingerprint ?? currentFingerprint,
          preserveDrafts: true,
          confirmed: true,
        });
        setLocalRecoveryMode(false);
        setSaveState("saved");
        setStatusMessage("Restored the previous Insights workspace.");
      })
      .catch(() => {
        if (cancelled) return;
        if (cached?.analysisSnapshot) {
          applyAnalysis(cached.analysisSnapshot, {
            fingerprint: cached.lastAnalyzedFingerprint ?? currentFingerprint,
            preserveDrafts: true,
            confirmed: false,
          });
          setLocalRecoveryMode(true);
          setSaveState("error");
          setStatusMessage(
            "Backend restore failed. The last local Insights draft is still visible in recovery mode until autosave succeeds again."
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsRestoring(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [candidateProfile.current_role, candidateProfile.profile_id, candidateProfile.target_role, currentFingerprint, companyInfo.role_title, storageKey]);

  useEffect(() => {
    const payload: LocalWorkspaceState = {
      workspaceId: analysis?.workspace_id,
      runId: analysis?.run_id,
      selectedVariant,
      selectedChangeIds,
      selectedEvidenceIds,
      answerDrafts,
      answerFieldDrafts,
      activeTab,
      lastAnalyzedFingerprint,
      analysisSnapshot: analysis,
    };
    if (!payload.workspaceId && !payload.analysisSnapshot && Object.keys(answerDrafts).length === 0) {
      return;
    }
    writeWorkspaceState(storageKey, payload);
  }, [
    activeTab,
    analysis,
    analysis?.run_id,
    analysis?.workspace_id,
    answerDrafts,
    answerFieldDrafts,
    lastAnalyzedFingerprint,
    selectedChangeIds,
    selectedEvidenceIds,
    selectedVariant,
    storageKey,
  ]);

  useEffect(() => {
    if (isRestoring || !analysis?.workspace_id) return;
    const uiState = buildBackendUiState({
      activeTab,
      selectedVariant,
      selectedChangeIds,
      selectedEvidenceIds,
      answerDrafts,
      answerFieldDrafts,
      lastAnalyzedFingerprint,
      scoreHistory,
    });
    setSaveState((current) => (current === "saving" ? current : "unsaved"));
    const handle = window.setTimeout(() => {
      setSaveState("saving");
      api
        .autosaveInsightsWorkspace({
          workspace_id: analysis.workspace_id,
          ui_state: uiState,
          workspace_state: isStale ? "stale" : contextSaved ? "approved" : "active",
        })
        .then((response) => {
          setAnalysis((current) => (current ? { ...current, ui_state: response.ui_state, workspace_state: response.workspace_state } : current));
          setLocalRecoveryMode(false);
          setSaveState("saved");
          if (pendingSaveAnnouncement === "benchmark_refresh") {
            setStatusMessage(
              "Benchmark refreshed and saved. You can leave this module and return to the same workspace state."
            );
          }
          setPendingSaveAnnouncement(null);
        })
        .catch(() => {
          setSaveState("error");
          setPendingSaveAnnouncement(null);
          setStatusMessage(
            "Benchmark refreshed, but workspace autosave failed. The current run is still visible locally. Backend restore may fail until autosave succeeds."
          );
        });
    }, 500);
    return () => window.clearTimeout(handle);
  }, [
    activeTab,
    analysis?.workspace_id,
    answerDrafts,
    answerFieldDrafts,
    contextSaved,
    isStale,
    isRestoring,
    lastAnalyzedFingerprint,
    pendingSaveAnnouncement,
    selectedChangeIds,
    selectedEvidenceIds,
    selectedVariant,
  ]);

  const handleAnalyze = async () => {
    if (!hasMinimumInput) {
      setErrorMessage("Add CV text or enough profile detail in Prepare before generating insights.");
      return;
    }
    setIsAnalyzing(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const response = await api.analyzeInsights({
        workspace_id: analysis?.workspace_id ?? null,
        candidate_profile: candidateProfile,
        company_info: companyInfo,
        interviewer_profile: interviewerProfile,
        cv_text: cvText,
        language,
      });
      applyAnalysis(response, { confirmed: false });
      setPendingSaveAnnouncement("benchmark_refresh");
      setStatusMessage("Benchmark refreshed. Autosave pending.");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Insights generation failed.");
      setSaveState("error");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleAnswer = async (question: InsightQuestion) => {
    if (!analysis) return;
    const structuredAnswer = buildAnswerFromFields(answerFieldDrafts[question.id]);
    const answer = (answerDrafts[question.id]?.trim() || structuredAnswer).trim();
    if (!answer) {
      setErrorMessage("Please write an answer before saving it.");
      return;
    }
    setAnswerDrafts((current) => ({
      ...current,
      [question.id]: answer,
    }));
    setBusyQuestionId(question.id);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const response = await api.answerInsightQuestion({
        workspace_id: analysis.workspace_id,
        run_id: analysis.run_id,
        question_id: question.id,
        answer,
      });
      applyAnalysis(response, { confirmed: false });
      setPendingSaveAnnouncement("workspace_update");
      setStatusMessage("Answer saved locally. Autosave pending.");
      setActiveTab("action-plan");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not save the answer.");
    } finally {
      setBusyQuestionId(null);
    }
  };

  const handleAction = (step: InsightsActionStep) => {
    if (step.type === "question" || step.type === "add_project") {
      setActiveTab("action-plan");
      return;
    }
    if (step.type === "approve_evidence") {
      setActiveTab("evidence");
      return;
    }
    setActiveTab("cv-studio");
  };

  const handleUseEvidenceInCv = (card: EvidenceCard) => {
    if (!selectedEvidenceIds.includes(card.id)) {
      toggleEvidence(card.id);
    }
    setActiveTab("cv-studio");
    setStatusMessage("Evidence selected for the next CV variant regeneration and approval flow.");
  };

  const handleFollowUp = (card: EvidenceCard) => {
    setActiveTab("action-plan");
    setStatusMessage(`Open questions are now the best path to strengthen: ${card.summary}`);
  };

  const handleResolveGap = (gap: EvidenceGap) => {
    setActiveTab("action-plan");
    setStatusMessage(`Next best move: ${gap.follow_up_hint || gap.evidence_needed}`);
  };

  const handleApproveEvidence = async (card: EvidenceCard) => {
    if (!analysis) return;
    const approvedEvidenceIds = Array.from(new Set([...selectedEvidenceIds, card.id]));
    setSelectedEvidenceIds(approvedEvidenceIds);
    setApproveEvidenceBusyId(card.id);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const response = await api.applyInsightChanges({
        workspace_id: analysis.workspace_id,
        run_id: analysis.run_id,
        approved_change_ids: selectedChangeIds,
        approved_evidence_ids: approvedEvidenceIds,
        targets: [],
      });
      applyAnalysis(response, { confirmed: false, preserveDrafts: true });
      setPendingSaveAnnouncement("workspace_update");
      setStatusMessage("Evidence approved into the Insights context lane. Autosave pending.");
      setActiveTab("evidence");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not approve this evidence.");
    } finally {
      setApproveEvidenceBusyId(null);
    }
  };

  const toggleChange = (changeId: string) => {
    setSelectedChangeIds((current) =>
      current.includes(changeId) ? current.filter((id) => id !== changeId) : [...current, changeId]
    );
  };

  const toggleEvidence = (evidenceId: string) => {
    setSelectedEvidenceIds((current) =>
      current.includes(evidenceId) ? current.filter((id) => id !== evidenceId) : [...current, evidenceId]
    );
  };

  const handleApplyProfile = async () => {
    if (!analysis) return;
    setApplyProfileBusy(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const response = await api.applyInsightChanges({
        workspace_id: analysis.workspace_id,
        run_id: analysis.run_id,
        approved_change_ids: selectedChangeIds,
        approved_evidence_ids: selectedEvidenceIds,
        targets: ["candidate_profile"],
      });
      applyAnalysis(response, { confirmed: false, preserveDrafts: true });
      onApplyProfile(response.candidate_profile, response.approved_context_preview?.summary ?? "");
      setPendingSaveAnnouncement("workspace_update");
      setStatusMessage(
        "Approved profile changes were sent to Prepare as a draft. Live and Coach keep the current profile until you load that draft in Prepare."
      );
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not apply profile changes.");
    } finally {
      setApplyProfileBusy(false);
    }
  };

  const handleApplyVariant = async () => {
    if (!analysis) return;
    setApplyVariantBusy(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const response = await api.applyInsightChanges({
        workspace_id: analysis.workspace_id,
        run_id: analysis.run_id,
        approved_change_ids: selectedChangeIds,
        approved_evidence_ids: selectedEvidenceIds,
        targets: ["cv_text"],
        variant: selectedVariant,
      });
      applyAnalysis(response, { confirmed: false, preserveDrafts: true });
      onApplyCvText(response.cv_text, response.approved_context_preview?.summary ?? "", response.candidate_profile);
      setPendingSaveAnnouncement("workspace_update");
      setStatusMessage(
        `${VARIANT_LABELS[selectedVariant]} was sent to Prepare as a draft. Live and Coach keep the current profile until you load that draft in Prepare.`
      );
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not apply the selected CV variant.");
    } finally {
      setApplyVariantBusy(false);
    }
  };

  const handleDownload = async () => {
    if (!analysis) return;
    setDownloadBusy(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const response = await api.exportInsightCv({
        workspace_id: analysis.workspace_id,
        run_id: analysis.run_id,
        variant: selectedVariant,
      });
      downloadBase64File(response.filename, response.mime_type, response.content_base64);
      setStatusMessage(`Downloaded ${response.filename}.`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not download the DOCX.");
    } finally {
      setDownloadBusy(false);
    }
  };

  return (
    <div className="space-y-4 p-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg">
                <Lightbulb className="h-5 w-5" />
                Insights
              </CardTitle>
              <CardDescription>
                Role Benchmark &amp; Evidence Studio. This workspace is isolated from Coach and Live in this phase.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {analysis && (
                <>
                  <Badge variant="outline">{analysis.benchmark_source.target_role || "Target role pending"}</Badge>
                  <Badge variant="outline">{analysis.benchmark_source.family}</Badge>
                  <Badge variant="outline">{analysis.benchmark_source.archetype}</Badge>
                  <Badge variant="outline">{analysis.benchmark_source.seniority}</Badge>
                  <Badge variant="outline">
                    pack {analysis.benchmark_source.versions.role_family_pack_version}
                  </Badge>
                  <Badge variant={supportLevelVariant(analysis.support_level)}>{analysis.support_level}</Badge>
                </>
              )}
              {analysis?.last_generated_at && (
                <Badge variant="outline">
                  Last updated {new Date(analysis.last_generated_at).toLocaleString()}
                </Badge>
              )}
              {analysis && (
                <Badge variant={saveState === "saved" ? "default" : saveState === "saving" ? "secondary" : "outline"}>
                  {saveState}
                </Badge>
              )}
              {localRecoveryMode && <Badge variant="destructive">local recovery mode</Badge>}
              {analysis && isStale && <Badge variant="outline">stale</Badge>}
              <Button type="button" onClick={handleAnalyze} disabled={isAnalyzing || !hasMinimumInput}>
                {isAnalyzing || isRestoring ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {isRestoring ? "Restoring..." : "Analyzing..."}
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    {analysis ? "Refresh benchmark" : "Generate insights"}
                  </>
                )}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {!hasMinimumInput && (
            <Alert>
              <AlertTitle>Prepare needs a bit more signal first</AlertTitle>
              <AlertDescription>
                Paste the CV or add summary, skills, or achievements in Prepare, then come back here to benchmark the role more reliably.
              </AlertDescription>
            </Alert>
          )}

          {errorMessage && (
            <Alert variant="destructive">
              <AlertTitle>Insights error</AlertTitle>
              <AlertDescription>{errorMessage}</AlertDescription>
            </Alert>
          )}

          {statusMessage && (
            <Alert>
              <CheckCircle2 className="h-4 w-4" />
              <AlertTitle>Insights updated</AlertTitle>
              <AlertDescription>{statusMessage}</AlertDescription>
            </Alert>
          )}

          {analysis && saveState === "error" && (
            <Alert variant="destructive">
              <AlertTitle>Workspace autosave failed</AlertTitle>
              <AlertDescription>
                Benchmark refreshed, but workspace autosave failed. The current run is still visible locally. Backend restore may fail until autosave succeeds.
              </AlertDescription>
            </Alert>
          )}

          {analysis && localRecoveryMode && (
            <Alert>
              <AlertTitle>Local recovery mode</AlertTitle>
              <AlertDescription>
                Backend restore is not confirmed right now, but the last local draft is still loaded so you can keep working inside Insights without losing the current run.
              </AlertDescription>
            </Alert>
          )}

          {!analysis ? (
            <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
              Generate insights to create a persistent role benchmark workspace, recover stronger evidence, improve the CV, and save approved context.
            </div>
          ) : (
            <>
              {isStale && (
                <Alert>
                  <AlertTitle>Inputs changed after the last benchmark</AlertTitle>
                  <AlertDescription>
                    The current Insights workspace was restored, but Prepare changed after the last generation. Review it as-is or refresh the benchmark when you want a re-score.
                  </AlertDescription>
                </Alert>
              )}

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
                <div className="space-y-4">
                  {supportIsLimited ? (
                    <Card>
                      <CardHeader className="pb-3">
                        <CardTitle className="text-base">Limited benchmark support</CardTitle>
                        <CardDescription>
                          This role is currently running in fallback evidence mode. Role-specific scoring is low-confidence, but evidence recovery, project capture, CV structure, and positioning are still active.
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        <Badge variant="outline">support level: {analysis.support_level}</Badge>
                        <p className="text-sm text-muted-foreground">{analysis.interpretation || analysis.analysis_summary}</p>
                      </CardContent>
                    </Card>
                  ) : (
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
                      <HeroMetricCard
                        label="Global Score"
                        value={analysis.global_score ?? analysis.overall_match}
                        caption="Weighted benchmark readout across role fit, proof, profile strength, and CV quality."
                      />
                      <HeroMetricCard
                        label="Role Fit"
                        value={analysis.primary_scores.role_fit}
                        caption="How aligned the profile is to the target role right now."
                      />
                      <HeroMetricCard
                        label="Proof Strength"
                        value={analysis.primary_scores.proof_strength}
                        caption="How well the strongest claims are actually demonstrated."
                      />
                      <HeroMetricCard
                        label="CV Representation Quality"
                        value={analysis.primary_scores.cv_representation_quality}
                        caption="How well the current CV expresses the profile you already have."
                      />
                    </div>
                  )}

                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="flex items-center gap-2 text-base">
                        <BarChart3 className="h-4 w-4" />
                        What this means
                      </CardTitle>
                      <CardDescription>
                        Use this to understand where the profile stands and what will move the benchmark fastest.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="rounded-lg border bg-muted/20 p-4">
                        <p className="text-sm text-muted-foreground">{analysis.interpretation || analysis.analysis_summary}</p>
                      </div>
                      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                        <div className="rounded-lg border p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Initial score</p>
                          <p className="mt-2 text-2xl font-semibold text-foreground">{initialScore}/100</p>
                        </div>
                        <div className="rounded-lg border p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Current score</p>
                          <p className="mt-2 text-2xl font-semibold text-foreground">{currentScore}/100</p>
                        </div>
                        <div className="rounded-lg border p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Last delta</p>
                          <p className="mt-2 text-2xl font-semibold text-foreground">
                            {lastScoreEvent ? `${lastScoreEvent.delta >= 0 ? "+" : ""}${lastScoreEvent.delta}` : "0"}
                          </p>
                        </div>
                        <div className="rounded-lg border p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Coverage</p>
                          <p className="mt-2 text-2xl font-semibold text-foreground">{analysis.coverage_pct}%</p>
                        </div>
                        <div className="rounded-lg border p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Confidence</p>
                          <div className="mt-2 flex items-center gap-2">
                            <Badge variant={scoreVariant(analysis.confidence.score)}>{analysis.confidence.label}</Badge>
                            <span className="text-sm text-muted-foreground">{analysis.confidence.score}/100</span>
                          </div>
                        </div>
                        <div className="rounded-lg border p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Support level</p>
                          <div className="mt-2">
                            <Badge variant={supportLevelVariant(analysis.support_level)}>{analysis.support_level}</Badge>
                          </div>
                        </div>
                        <div className="rounded-lg border p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Top recoverable gain</p>
                          <p className="mt-2 text-2xl font-semibold text-foreground">+{analysis.score_delta_available ?? 0}</p>
                        </div>
                      </div>
                      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                        <SectionList title="Top strengths" items={topStrengths} emptyText="No strong signals surfaced yet." />
                        <SectionList title="Top gaps" items={topGaps} emptyText="No major benchmark gaps were highlighted." />
                      </div>
                      {scoreTimeline.length > 0 && (
                        <div className="space-y-2">
                          <LabelLike>Score progression</LabelLike>
                          <div className="space-y-2">
                            {scoreTimeline.map((event) => (
                              <div key={event.event_id} className="rounded-lg border p-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <p className="text-sm font-medium text-foreground">{event.label}</p>
                                  <Badge variant={event.delta >= 0 ? "default" : "destructive"}>
                                    {event.delta >= 0 ? "+" : ""}
                                    {event.delta}
                                  </Badge>
                                </div>
                                <p className="mt-1 text-sm text-muted-foreground">
                                  {event.score_before}/100 to {event.score_after}/100
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Target className="h-4 w-4" />
                      What to do next
                    </CardTitle>
                    <CardDescription>
                      Focus on the next few actions with the best score gain for the least effort.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {nextActions.length === 0 ? (
                      <p className="text-sm text-muted-foreground">Generate or refresh the benchmark to build the next action plan.</p>
                    ) : (
                      nextActions.map((step) => <ActionCard key={step.step_id} step={step} onAction={handleAction} />)
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {analysis && (
        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as WorkspaceTab)} className="space-y-4">
          <TabsList className="grid h-auto w-full grid-cols-2 gap-1 p-1 md:grid-cols-4">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="action-plan">Action Plan</TabsTrigger>
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="cv-studio">CV Studio</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Benchmark snapshot</CardTitle>
                <CardDescription>Dimension-level readout for the resolved pack and current role target.</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {analysis.dimension_states.map((dimension) => (
                  <div key={dimension.id} className="rounded-xl border p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-foreground">{dimension.label}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{dimension.summary}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={scoreVariant(dimension.score)}>{dimension.score}/100</Badge>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            setExpandedDimensionId((current) => (current === dimension.id ? null : dimension.id))
                          }
                        >
                          {expandedDimensionId === dimension.id ? "Hide why" : "Show why"}
                        </Button>
                      </div>
                    </div>
                    <div className="mt-3 space-y-2">
                      <div className="flex items-center justify-between text-sm">
                        <span>Coverage</span>
                        <span className="font-medium">{dimension.coverage}%</span>
                      </div>
                      <Progress value={dimension.coverage} />
                    </div>
                    <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                      <SectionList title="Signals found" items={dimension.signals_found} emptyText="Nothing strong yet." />
                      <SectionList title="Signals missing" items={dimension.signals_missing} emptyText="No material misses here." />
                    </div>
                    {expandedDimensionId === dimension.id && (
                      <div className="mt-4 space-y-3 rounded-lg border bg-muted/10 p-3">
                        <div>
                          <LabelLike>Why score is not higher</LabelLike>
                          <p className="mt-2 text-sm text-muted-foreground">
                            {dimension.why_score_is_not_higher || "This area still needs stronger evidence and clearer proof."}
                          </p>
                        </div>
                        <div>
                          <LabelLike>Evidence supporting this readout</LabelLike>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {(dimension.supporting_evidence_ids ?? []).length === 0 ? (
                              <p className="text-sm text-muted-foreground">No supporting evidence surfaced yet.</p>
                            ) : (
                              (dimension.supporting_evidence_ids ?? []).map((evidenceId) => (
                                <Badge key={`${dimension.id}-${evidenceId}`} variant="secondary">
                                  {evidenceId}
                                </Badge>
                              ))
                            )}
                          </div>
                        </div>
                        <div>
                          <LabelLike>Next best action</LabelLike>
                          <p className="mt-2 text-sm text-foreground">
                            {dimension.next_best_action || "Open the action plan and answer the next guided question."}
                          </p>
                        </div>
                        <div className="flex justify-end">
                          <Button type="button" size="sm" variant="outline" onClick={() => setActiveTab("action-plan")}>
                            Open action plan
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>

            <ApprovedContextCard preview={analysis.approved_context_preview} contextSaved={contextSaved} />
          </TabsContent>

          <TabsContent value="action-plan" className="space-y-4">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
              <div className="space-y-4">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Wand2 className="h-4 w-4" />
                      Improvement plan
                    </CardTitle>
                    <CardDescription>
                      A guided route from the current benchmark to a stronger role-ready profile and CV.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                      <div className="rounded-lg border p-3">
                        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Current global score</p>
                        <p className="mt-2 text-2xl font-semibold text-foreground">{analysis.improvement_plan?.current_global_score ?? analysis.overall_match}</p>
                      </div>
                      <div className="rounded-lg border p-3">
                        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Target score</p>
                        <p className="mt-2 text-2xl font-semibold text-foreground">{analysis.improvement_plan?.target_score ?? analysis.overall_match}</p>
                      </div>
                      <div className="rounded-lg border p-3">
                        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Open gaps</p>
                        <p className="mt-2 text-2xl font-semibold text-foreground">{analysis.improvement_plan?.open_gap_count ?? analysis.gap_map.length}</p>
                      </div>
                    </div>
                    <div className="space-y-3">
                      {(analysis.improvement_plan?.steps ?? nextActions).map((step) => (
                        <ActionCard key={step.step_id} step={step} onAction={handleAction} />
                      ))}
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Question rounds</CardTitle>
                    <CardDescription>
                      Answer the next few high-leverage questions to recover stronger evidence and re-score the benchmark.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {questionQueue.length === 0 ? (
                      <Alert variant={analysis.gap_map.length > 0 || currentScore < 70 || analysis.coverage_pct < 70 ? "destructive" : "default"}>
                        <AlertTitle>
                          {analysis.gap_map.length > 0 || currentScore < 70 || analysis.coverage_pct < 70
                            ? "Question planner needs attention"
                            : "No open questions right now"}
                        </AlertTitle>
                        <AlertDescription>
                          {analysis.gap_map.length > 0 || currentScore < 70 || analysis.coverage_pct < 70
                            ? "Insights still has open gaps, but no guided questions were returned. This is a product issue, not a completed workspace."
                            : "The current workspace does not have critical follow-up questions pending."}
                        </AlertDescription>
                      </Alert>
                    ) : (
                      questionQueue.map((question) => (
                        <QuestionCard
                          key={question.id}
                          question={question}
                          value={answerDrafts[question.id] ?? ""}
                          fields={answerFieldDrafts[question.id] ?? {}}
                          busy={busyQuestionId === question.id}
                          onChange={(value) =>
                            setAnswerDrafts((current) => ({
                              ...current,
                              [question.id]: value,
                            }))
                          }
                          onFieldChange={(field, value) =>
                            setAnswerFieldDrafts((current) => ({
                              ...current,
                              [question.id]: {
                                ...(current[question.id] ?? {}),
                                [field]: value,
                              },
                            }))
                          }
                          onSubmit={() => handleAnswer(question)}
                        />
                      ))
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Top benchmark gaps</CardTitle>
                  <CardDescription>
                    These are the current reasons the benchmark is still below a stronger role-ready state.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {analysis.gap_map.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No major benchmark gaps surfaced in this run.</p>
                  ) : (
                    analysis.gap_map.map((gap) => <GapCard key={gap.id} gap={gap} onResolve={handleResolveGap} />)
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="evidence" className="space-y-4">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(340px,0.95fr)]">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Evidence Studio</CardTitle>
                  <CardDescription>
                    Select the strongest reusable evidence to support approved context and stronger rewrites.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {analysis.evidence_cards.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No evidence cards were generated for this workspace yet.</p>
                  ) : (
                    analysis.evidence_cards.map((card) => (
                      <EvidenceCardView
                        key={card.id}
                        card={card}
                        selected={selectedEvidenceIds.includes(card.id)}
                        approveBusy={approveEvidenceBusyId === card.id}
                        onApprove={handleApproveEvidence}
                        onUseInCv={handleUseEvidenceInCv}
                        onFollowUp={handleFollowUp}
                        onToggle={toggleEvidence}
                      />
                    ))
                  )}
                </CardContent>
              </Card>

              <div className="space-y-4">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Signal groups</CardTitle>
                    <CardDescription>
                      This shows what the pack expects, what is already covered, and where more proof is still needed.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <SectionList
                      title="Required signals"
                      items={analysis.required_signals.map((signal) => `${signal.label} (${signal.coverage}%)`)}
                      emptyText="No required signals resolved."
                    />
                    <SectionList
                      title="Supporting signals"
                      items={analysis.supporting_signals.map((signal) => `${signal.label} (${signal.coverage}%)`)}
                      emptyText="No supporting signals resolved."
                    />
                    <SectionList
                      title="Differentiators"
                      items={analysis.differentiator_signals.map((signal) => `${signal.label} (${signal.coverage}%)`)}
                      emptyText="No differentiators surfaced yet."
                    />
                    <SectionList
                      title="Anti-signals"
                      items={analysis.anti_signals.filter((signal) => signal.status === "active").map((signal) => signal.label)}
                      emptyText="No active anti-signals right now."
                    />
                  </CardContent>
                </Card>

                <ApprovedContextCard preview={analysis.approved_context_preview} contextSaved={contextSaved} />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="cv-studio" className="space-y-4">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
              <div className="space-y-4">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <FilePenLine className="h-4 w-4" />
                      CV variants
                    </CardTitle>
                    <CardDescription>
                      Use the master version for broad leadership positioning or the role variant for the current target role.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      {(["master_cv", "role_variant_cv"] as const).map((variantId) => {
                        const variant = analysis.cv_variants[variantId];
                        const isSelected = selectedVariant === variantId;
                        return (
                          <button
                            key={variantId}
                            type="button"
                            onClick={() => setSelectedVariant(variantId)}
                            className={`rounded-xl border p-4 text-left transition ${
                              isSelected ? "border-primary bg-primary/5" : "hover:border-primary/40"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-sm font-medium text-foreground">{variant.title}</p>
                              {isSelected && <Badge>selected</Badge>}
                            </div>
                            <p className="mt-2 text-sm text-muted-foreground">{variant.description}</p>
                            <p className="mt-3 text-xs text-muted-foreground">{variant.change_summary}</p>
                          </button>
                        );
                      })}
                    </div>
                    {selectedVariantPreview && (
                      <>
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                          <SectionList
                            title="Evidence used"
                            items={selectedVariantPreview.evidence_card_ids_used}
                            emptyText="No evidence selected yet."
                          />
                          <SectionList
                            title="Unresolved gaps"
                            items={selectedVariantPreview.unresolved_gap_ids}
                            emptyText="No unresolved gaps highlighted."
                          />
                        </div>
                        <div className="space-y-3">
                          <LabelLike>Variant sections</LabelLike>
                          {selectedVariantPreview.sections.map((section) => (
                            <div key={`${selectedVariantPreview.variant_id}-${section.id}`} className="rounded-lg border p-3">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <p className="text-sm font-medium text-foreground">{section.title}</p>
                                <Badge variant="outline">
                                  Supported by {selectedVariantPreview.evidence_card_ids_used.length} evidence cards
                                </Badge>
                              </div>
                              {section.content && <p className="mt-2 text-sm text-muted-foreground">{section.content}</p>}
                              {section.items.length > 0 && (
                                <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                                  {section.items.slice(0, 3).map((item) => (
                                    <li key={`${section.id}-${item}`} className="flex gap-2">
                                      <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
                                      <span>{item}</span>
                                    </li>
                                  ))}
                                </ul>
                              )}
                              <div className="mt-3">
                                <Button type="button" size="sm" variant="outline" onClick={() => setActiveTab("evidence")}>
                                  Open supporting evidence
                                </Button>
                              </div>
                            </div>
                          ))}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button type="button" onClick={handleApplyVariant} disabled={applyVariantBusy}>
                            {applyVariantBusy ? (
                              <>
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                Applying...
                              </>
                            ) : (
                              <>
                                <Wand2 className="mr-2 h-4 w-4" />
                                Use this variant in Prepare
                              </>
                            )}
                          </Button>
                          <Button type="button" variant="outline" onClick={handleDownload} disabled={downloadBusy}>
                            {downloadBusy ? (
                              <>
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                Preparing...
                              </>
                            ) : (
                              <>
                                <Download className="mr-2 h-4 w-4" />
                                Download DOCX
                              </>
                            )}
                          </Button>
                        </div>
                      </>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Apply approved profile changes</CardTitle>
                    <CardDescription>
                      Only the selected changes are written back into Prepare. Nothing is auto-applied.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {analysis.proposed_changes.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No proposed profile changes are available yet for this workspace.</p>
                    ) : (
                      analysis.proposed_changes.map((change) => (
                        <ProposedChangeCard
                          key={change.id}
                          change={change}
                          selected={selectedChangeIds.includes(change.id)}
                          onToggle={toggleChange}
                        />
                      ))
                    )}
                    <Separator />
                    <Button type="button" onClick={handleApplyProfile} disabled={applyProfileBusy}>
                      {applyProfileBusy ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Applying...
                        </>
                      ) : (
                        <>
                          <ShieldCheck className="mr-2 h-4 w-4" />
                          Apply selected profile changes
                        </>
                      )}
                    </Button>
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">{selectedVariantPreview?.title || "CV Preview"}</CardTitle>
                  <CardDescription>
                    Preview the structured CV output before applying it back into Prepare or downloading the editable DOCX.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {!selectedVariantPreview ? (
                    <p className="text-sm text-muted-foreground">Generate insights to preview the CV variants.</p>
                  ) : (
                    <ScrollArea className="h-[720px] rounded-xl border bg-muted/10 p-4">
                      <div className="space-y-6">
                        {selectedVariantPreview.sections.map((section) => (
                          <div key={section.id} className="space-y-2">
                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                              {section.title}
                            </p>
                            {section.content && <p className="text-sm text-foreground">{section.content}</p>}
                            {section.items.length > 0 && (
                              <ul className="space-y-2 text-sm text-muted-foreground">
                                {section.items.map((item) => (
                                  <li key={`${section.id}-${item}`} className="flex gap-2">
                                    <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
                                    <span>{item}</span>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
