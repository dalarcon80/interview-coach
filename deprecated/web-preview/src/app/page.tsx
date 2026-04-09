'use client';

/**
 * Interview Coach - Development Preview
 * 
 * ARCHITECTURE NOTE:
 * This is a DEVELOPMENT PREVIEW only. Per ARCHITECTURE.md:
 * - Platform: macOS-first Desktop App (Tauri 2.0)
 * - This page is an ORCHESTRATOR that composes official components.
 * 
 * Components Used:
 * - SessionControlPanel: Session management UI
 * - AudioSettingsPanel: Audio configuration UI
 * - LiveTranscriptPanel: Real-time transcript display
 * - RealtimeSuggestionPanel: AI suggestion display
 * 
 * The page wires useRealtimeWebSocket to these components via props.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input'; 
import { 
  AlertTriangle, 
  Terminal, 
  Database, 
  Server, 
  Cpu, 
  Mic,
  CheckCircle2,
  XCircle,
  Loader2,
  Settings,
  Send,
  BookOpen,
  Radio,
  ChevronsUpDown,
  User,
  Building2
} from 'lucide-react';

// Official realtime hook
import { useRealtimeWebSocket } from '@/hooks/realtime/useRealtimeWebSocket';
import type { SessionConfig, SuggestionResult } from '@/hooks/realtime/useRealtimeWebSocket';

// Official UI components
import { 
  SessionControlPanel, 
  AudioSettingsPanel, 
  LiveTranscriptPanel, 
  RealtimeSuggestionPanel 
} from '@/components/realtime';
import type { TranscriptEntry, Suggestion } from '@/components/realtime';

import { CandidateProfileForm } from '@/components/coach/CandidateProfileForm';
import { CompanyInfoForm } from '@/components/coach/CompanyInfoForm';
import { QuestionInput } from '@/components/coach/QuestionInput';
import { StyleSelector } from '@/components/coach/StyleSelector';
import { SuggestionDisplay } from '@/components/coach/SuggestionDisplay';
import { CVIntake } from '@/components/coach/CVIntake';
import type { CandidateProfile } from '@/components/coach/CandidateProfileForm';
import type { CompanyInfo } from '@/components/coach/CompanyInfoForm';
import type { ResponseStyle } from '@/components/coach/StyleSelector';
import type { Suggestion as PrepSuggestion } from '@/components/coach/QuestionInput';

// ============================================
// Types
// ============================================

interface BackendHealth {
  status: string;
  timestamp: string;
  db_connected: boolean;
  version: string;
  providers_loaded: boolean;
}

// ============================================
// Audio State Hook
// ============================================

function useAudioState() {
  const [audioState, setAudioState] = useState({
    inputMode: 'system' as 'system' | 'mic' | 'both',
    providerStatus: 'unavailable' as 'available' | 'partial' | 'unavailable',
    providerName: 'Not Available',
    micPermission: 'unknown' as 'granted' | 'denied' | 'prompt' | 'unknown',
    systemAudioPermission: 'unknown' as 'granted' | 'denied' | 'prompt' | 'unknown',
    platform: 'unknown' as 'macos' | 'windows' | 'linux' | 'unknown',
    manualTextMode: true
  });

  useEffect(() => {
    // Detect platform
    const platform = typeof navigator !== 'undefined' 
      ? (navigator.platform?.toLowerCase().includes('mac') ? 'macos' :
         navigator.platform?.toLowerCase().includes('win') ? 'windows' :
         navigator.platform?.toLowerCase().includes('linux') ? 'linux' : 'unknown')
      : 'unknown';

    // Check mic permission
    if (typeof navigator !== 'undefined' && navigator.permissions) {
      navigator.permissions.query({ name: 'microphone' as PermissionName })
        .then((status) => {
          setAudioState(prev => ({
            ...prev,
            micPermission: status.state as 'granted' | 'denied' | 'prompt'
          }));
        })
        .catch(() => {});
    }

    // Audio is stub in web preview - defer setState to avoid cascading renders
    const timeoutId = setTimeout(() => {
      setAudioState(prev => ({
        ...prev,
        platform,
        providerStatus: 'unavailable',
        providerName: 'Requires Tauri Desktop',
        manualTextMode: true
      }));
    }, 0);
    
    return () => clearTimeout(timeoutId);
  }, []);

  const setInputMode = useCallback((mode: 'system' | 'mic' | 'both') => {
    setAudioState(prev => ({ ...prev, inputMode: mode }));
  }, []);

  const setManualTextMode = useCallback((enabled: boolean) => {
    setAudioState(prev => ({ ...prev, manualTextMode: enabled }));
  }, []);

  const reconnect = useCallback(() => {
    // No-op in web preview - audio requires Tauri
    console.log('[Audio] Reconnect attempted - audio is stub in web preview');
  }, []);

  return {
    ...audioState,
    setInputMode,
    setManualTextMode,
    reconnect
  };
}

// ============================================
// Main Page Component
// ============================================

export default function Page() {
  // Backend health state
  const [backendHealth, setBackendHealth] = useState<BackendHealth | null>(null);
  const [loading, setLoading] = useState(true);
  
  // Manual input for testing (audio is stub)
  const [manualQuestion, setManualQuestion] = useState('');

  // ---- Mode ----
  const [activeMode, setActiveMode] = useState<string>('preparation');

  // ---- Candidate Profile ----
  const [candidateProfile, setCandidateProfile] = useState<CandidateProfile | null>(null);

  // ---- Company Info ----
  const [companyInfo, setCompanyInfo] = useState<CompanyInfo | null>(null);

  // ---- Style ----
  const [responseStyle, setResponseStyle] = useState<ResponseStyle>('mixed');

  // ---- Preparation suggestion ----
  const [prepSuggestion, setPrepSuggestion] = useState<PrepSuggestion | null>(null);
  const [prepQuestion, setPrepQuestion] = useState<string>('');
  const [prepProcessing, setPrepProcessing] = useState(false);

  const sessionConfig: SessionConfig = useMemo(() => ({
    company_name: companyInfo?.companyName || '',
    role_title: companyInfo?.positionTitle || '',
    response_style: responseStyle,
    language_preference: 'auto',
    // Full context objects for unified interview context flow
    // This ensures candidate profile and company/role data flows from Preparation mode to Live Session
    candidate: candidateProfile ? {
      name: candidateProfile.name || '',
      email: candidateProfile.email,
      phone: candidateProfile.phone,
      currentRole: candidateProfile.currentRole,
      currentCompany: candidateProfile.currentCompany,
      yearsExperience: candidateProfile.yearsExperience,
      skills: candidateProfile.skills,
      achievements: candidateProfile.achievements,
      education: candidateProfile.education,
      languages: candidateProfile.languages,
      certifications: candidateProfile.certifications,
      linkedinUrl: candidateProfile.linkedinUrl,
      portfolioUrl: candidateProfile.portfolioUrl,
      summary: candidateProfile.summary,
      rawResume: candidateProfile.rawResume,
    } : undefined,
    company: companyInfo ? {
      companyName: companyInfo.companyName || '',
      industry: companyInfo.industry,
      companySize: companyInfo.companySize,
      companyDescription: companyInfo.companyDescription,
      companyValues: companyInfo.companyValues,
      companyCulture: companyInfo.companyCulture,
      positionTitle: companyInfo.positionTitle || '',
      positionLevel: companyInfo.positionLevel,
      positionDepartment: companyInfo.positionDepartment,
      positionDescription: companyInfo.positionDescription,
      positionRequirements: companyInfo.positionRequirements,
      salaryRange: companyInfo.salaryRange,
      location: companyInfo.location,
      workMode: companyInfo.workMode,
      jobPostingUrl: companyInfo.jobPostingUrl,
      notes: companyInfo.notes,
    } : undefined,
  }), [candidateProfile, companyInfo, responseStyle]);

  // Official WebSocket hook
  const realtime = useRealtimeWebSocket();
  
  // Audio state
  const audio = useAudioState();

  // ============================================
  // Backend Health Check
  // ============================================

  useEffect(() => {
    const checkBackend = async () => {
      try {
        const res = await fetch('/api/coach/backend-health');
        const data = await res.json();
        setBackendHealth(data);
      } catch (e) {
        setBackendHealth(null);
      } finally {
        setLoading(false);
      }
    };
    
    checkBackend();
    const interval = setInterval(checkBackend, 10000);
    return () => clearInterval(interval);
  }, []);

  // ============================================
  // Preparation Handlers
  // ============================================

  const handleSaveProfile = useCallback(async (profile: CandidateProfile) => {
    setCandidateProfile(profile);
  }, []);

  const handleSaveCompany = useCallback(async (company: CompanyInfo) => {
    setCompanyInfo(company);
  }, []);

  const handlePrepSuggestion = useCallback((suggestion: PrepSuggestion) => {
    setPrepSuggestion(suggestion);
  }, []);

  const handleClearPrepSuggestion = useCallback(() => {
    setPrepSuggestion(null);
    setPrepQuestion('');
  }, []);

  // Handle CV analysis result - map to CandidateProfile format
  const handleCVApplyToProfile = useCallback((cvProfile: {
    name: string;
    email?: string;
    currentRole?: string;
    company?: string;
    summary?: string;
    yearsExperience?: number;
    skills?: string[];
    achievements?: string[];
  }) => {
    const profile: CandidateProfile = {
      name: cvProfile.name || '',
      email: cvProfile.email,
      currentRole: cvProfile.currentRole,
      currentCompany: cvProfile.company,
      summary: cvProfile.summary,
      yearsExperience: cvProfile.yearsExperience,
      skills: cvProfile.skills || [],
      achievements: cvProfile.achievements || [],
    };
    setCandidateProfile(profile);
  }, []);

  // ============================================
  // Session Handlers
  // ============================================

  const handleStartSession = useCallback(() => {
    realtime.startSession(sessionConfig);
  }, [realtime, sessionConfig]);

  const handleEndSession = useCallback(() => {
    realtime.endSession();
    realtime.clearSuggestion();
  }, [realtime]);

  const handleSendQuestion = useCallback(() => {
    if (!manualQuestion.trim()) return;
    realtime.sendTranscript(manualQuestion.trim(), true);
    setManualQuestion('');
  }, [manualQuestion, realtime]);

  // ============================================
  // Transform suggestion for RealtimeSuggestionPanel
  // ============================================

const suggestionForPanel: Suggestion | null = realtime.suggestion ? {
    exchangeIndex: realtime.session.exchangeCount,
    mode: realtime.suggestion.mode,
    provider: realtime.suggestion.provider,
    model: realtime.suggestion.model,
    bullets: realtime.suggestion.bullets,
    fullResponse: realtime.suggestion.full_response,
    confidence: realtime.suggestion.confidence,
    latencyMs: realtime.suggestion.latency_ms,
    processingFullResponse: realtime.suggestion.processing_full_response,
    bulletsLatencyMs: realtime.suggestion.bullets_latency_ms,
    fullLatencyMs: realtime.suggestion.full_latency_ms,
  } : null;

  // ============================================
  // Transform transcripts for LiveTranscriptPanel
  // ============================================

  const transcriptsForPanel: TranscriptEntry[] = realtime.transcripts;

  // ============================================
  // Render
  // ============================================

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b bg-card sticky top-0 z-50">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center">
              <Mic className="w-5 w-5 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-xl font-bold">Interview Coach</h1>
              <p className="text-sm text-muted-foreground">Development Preview</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="gap-1 text-amber-600 border-amber-300">
              <AlertTriangle className="h-3 w-3" />
              DEV PREVIEW
            </Badge>
            <Badge variant={backendHealth?.status === 'healthy' ? 'default' : 'destructive'} className="gap-1">
              <Server className="h-3 w-3" />
              Backend: {backendHealth?.status || 'Offline'}
            </Badge>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-6 space-y-6 flex-1">
        {/* Architecture Warning */}
        <Alert className="border-amber-500 bg-amber-500/10">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          <AlertTitle className="text-amber-600">Architecture Notice</AlertTitle>
          <AlertDescription className="text-amber-700/80">
            <p className="mb-2">
              <strong>This is NOT the application.</strong> Per ARCHITECTURE.md, Interview Coach is a
              <strong> macOS-first Tauri Desktop App</strong>, not a web application.
            </p>
            <p>
              This page is a development preview to verify backend connectivity and test components.
            </p>
          </AlertDescription>
        </Alert>

        {/* Status Summary */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Backend</span>
                {backendHealth ? (
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-500" />
                )}
              </div>
              <p className="text-lg font-semibold mt-1">
                {backendHealth ? 'Connected' : 'Offline'}
              </p>
              <p className="text-xs text-muted-foreground">Port 8000</p>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Database</span>
                {backendHealth?.db_connected ? (
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                ) : (
                  <AlertTriangle className="h-5 w-5 text-amber-500" />
                )}
              </div>
              <p className="text-lg font-semibold mt-1">
                {backendHealth?.db_connected ? 'Connected' : 'Docker Required'}
              </p>
              <p className="text-xs text-muted-foreground">PostgreSQL + pgvector</p>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">WebSocket</span>
                {realtime.connected ? (
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                ) : realtime.connecting ? (
                  <Loader2 className="h-5 w-5 text-amber-500 animate-spin" />
                ) : (
                  <XCircle className="h-5 w-5 text-muted-foreground" />
                )}
              </div>
              <p className="text-lg font-semibold mt-1">
                {realtime.connected ? 'Connected' : realtime.connecting ? 'Connecting...' : 'Disconnected'}
              </p>
              <p className="text-xs text-muted-foreground">ws://localhost:8000</p>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Audio</span>
                <XCircle className="h-5 w-5 text-muted-foreground" />
              </div>
              <p className="text-lg font-semibold mt-1">Unavailable</p>
              <p className="text-xs text-muted-foreground">Requires Tauri Desktop</p>
            </CardContent>
          </Card>
        </div>

        {/* Mode Tabs */}
        <Tabs value={activeMode} onValueChange={setActiveMode} className="w-full">
          <TabsList className="grid w-full grid-cols-2 mb-4">
            <TabsTrigger value="preparation">
              <BookOpen className="h-4 w-4 mr-2" />
              Preparation
            </TabsTrigger>
            <TabsTrigger value="live">
              <Radio className="h-4 w-4 mr-2" />
              Live Session
            </TabsTrigger>
          </TabsList>

          <div className="mb-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            <Alert className="border-green-300 bg-green-500/5">
              <BookOpen className="h-4 w-4 text-green-600" />
              <AlertTitle className="text-green-700">Preparation Mode (functional)</AlertTitle>
              <AlertDescription className="text-green-800/80">
                Candidate/Company context, CV intake, style selection, and manual question coaching are active.
              </AlertDescription>
            </Alert>
            <Alert className="border-blue-300 bg-blue-500/5">
              <Radio className="h-4 w-4 text-blue-600" />
              <AlertTitle className="text-blue-700">Live Mode (partial)</AlertTitle>
              <AlertDescription className="text-blue-800/80">
                Realtime coaching is active with bullets-first suggestions. Audio capture is still a stub in web preview.
              </AlertDescription>
            </Alert>
          </div>

          <TabsContent value="preparation" className="space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
              <div className="lg:col-span-5 space-y-4">
                {/* CV Intake - Before Profile Form */}
                <CVIntake onApplyToProfile={handleCVApplyToProfile} />

                <Collapsible defaultOpen>
                  <CollapsibleTrigger asChild>
                    <Button variant="ghost" className="w-full justify-between">
                      <span className="flex items-center gap-2">
                        <User className="h-4 w-4" /> Candidate Profile
                      </span>
                      <ChevronsUpDown className="h-4 w-4" />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <CandidateProfileForm
                      profile={candidateProfile}
                      onSave={handleSaveProfile}
                    />
                  </CollapsibleContent>
                </Collapsible>

                <Collapsible defaultOpen>
                  <CollapsibleTrigger asChild>
                    <Button variant="ghost" className="w-full justify-between">
                      <span className="flex items-center gap-2">
                        <Building2 className="h-4 w-4" /> Company & Role
                      </span>
                      <ChevronsUpDown className="h-4 w-4" />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <CompanyInfoForm
                      company={companyInfo}
                      onSave={handleSaveCompany}
                    />
                  </CollapsibleContent>
                </Collapsible>
              </div>

              <div className="lg:col-span-7 space-y-4">
                <StyleSelector
                  selectedStyle={responseStyle}
                  onStyleChange={setResponseStyle}
                />

                <QuestionInput
                  sessionId={null}
                  selectedStyle={responseStyle}
                  onSuggestion={handlePrepSuggestion}
                  onClear={handleClearPrepSuggestion}
                  isProcessing={prepProcessing}
                  setIsProcessing={setPrepProcessing}
                  candidate={candidateProfile ? {
                    name: candidateProfile.name,
                    summary: candidateProfile.summary,
                    achievements: candidateProfile.achievements
                  } : null}
                  company={companyInfo ? {
                    companyName: companyInfo.companyName,
                    roleTitle: companyInfo.positionTitle,
                    jobDescription: companyInfo.positionDescription
                  } : null}
                  onQuestionSubmit={(question) => setPrepQuestion(question)}
                />

                <SuggestionDisplay
                  suggestion={prepSuggestion}
                  question={prepQuestion}
                />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="live" className="space-y-4">
            {/* Tabs for different views */}
            <Tabs defaultValue="session" className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="session">Session</TabsTrigger>
                <TabsTrigger value="architecture">Architecture</TabsTrigger>
                <TabsTrigger value="status">Backend Status</TabsTrigger>
              </TabsList>

              {/* Session Tab - Uses Official Components */}
              <TabsContent value="session" className="space-y-4">
                {/* Error Alert */}
                {realtime.error && (
                  <Alert variant="destructive">
                    <AlertTriangle className="h-4 w-4" />
                    <AlertTitle>Error</AlertTitle>
                    <AlertDescription className="flex justify-between items-center">
                      {realtime.error}
                      <Button variant="outline" size="sm" onClick={realtime.clearError}>
                        Dismiss
                      </Button>
                    </AlertDescription>
                  </Alert>
                )}

                {/* Main Grid Layout */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                  {/* Left Column - Controls */}
                  <div className="lg:col-span-3 space-y-4">
                    {/* Session Control Panel */}
                    <SessionControlPanel
                      connected={realtime.connected}
                      sessionActive={realtime.session.active}
                      processing={realtime.processing}
                      error={null}
                      onConnect={realtime.connect}
                      onDisconnect={realtime.disconnect}
                      onStartSession={handleStartSession}
                      onEndSession={handleEndSession}
                      companyName={sessionConfig.company_name}
                      roleTitle={sessionConfig.role_title}
                      sessionDuration={realtime.session.duration}
                      exchangeCount={realtime.session.exchangeCount}
                      averageLatency={realtime.averageLatency}
                      mode={realtime.session.mode || undefined}
                      capability={realtime.connected ? 'functional' : 'partial'}
                    />

                    {/* Audio Settings Panel */}
                    <AudioSettingsPanel
                      inputMode={audio.inputMode}
                      onInputModeChange={audio.setInputMode}
                      audioProviderStatus={audio.providerStatus}
                      audioProviderName={audio.providerName}
                      micPermission={audio.micPermission}
                      systemAudioPermission={audio.systemAudioPermission}
                      isReconnecting={false}
                      onReconnect={audio.reconnect}
                      manualTextMode={audio.manualTextMode}
                      onManualTextModeChange={audio.setManualTextMode}
                      platform={audio.platform}
                      capability={audio.providerStatus === 'available' ? 'functional' : audio.providerStatus === 'partial' ? 'partial' : 'stub'}
                    />
                  </div>

                  {/* Middle Column - Transcript */}
                  <div className="lg:col-span-4">
                    <LiveTranscriptPanel
                      transcripts={transcriptsForPanel}
                      currentPartial={realtime.currentPartial || undefined}
                      language={realtime.suggestion?.language || 'es'}
                      capability={realtime.session.active ? 'functional' : 'partial'}
                    />

                    {/* Manual Input (audio is stub) */}
                    {realtime.session.active && audio.manualTextMode && (
                      <div className="mt-4 p-4 border rounded-lg">
                        <label className="text-sm font-medium">Manual Question Input</label>
                        <p className="text-xs text-muted-foreground mb-2">
                          Audio capture is a STUB. Type interviewer questions here for testing.
                        </p>
                        <div className="flex gap-2">
                          <Input
                            value={manualQuestion}
                            onChange={(e) => setManualQuestion(e.target.value)}
                            placeholder="Type interviewer question..."
                            onKeyDown={(e) => e.key === 'Enter' && handleSendQuestion()}
                            disabled={realtime.processing}
                          />
                          <Button 
                            onClick={handleSendQuestion} 
                            disabled={!manualQuestion.trim() || realtime.processing}
                          >
                            {realtime.processing ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Send className="h-4 w-4" />
                            )}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Right Column - Suggestion */}
                  <div className="lg:col-span-5">
                    <RealtimeSuggestionPanel
                      suggestion={suggestionForPanel}
                      processing={realtime.processing}
                      style={sessionConfig.response_style}
                      capability={realtime.connected ? 'functional' : 'partial'}
                    />
                  </div>
                </div>
              </TabsContent>

              {/* Architecture Tab */}
              <TabsContent value="architecture" className="space-y-4">
                <Card>
                  <CardHeader>
                    <CardTitle>Architecture Compliance</CardTitle>
                    <CardDescription>Per ARCHITECTURE.md v3.2.1 (FROZEN)</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                      <div className="p-4 border rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                          <Cpu className="h-5 w-5 text-primary" />
                          <span className="font-medium">Platform</span>
                        </div>
                        <div className="text-sm text-muted-foreground mb-2">Tauri 2.0 Desktop App</div>
                        <Badge className="bg-green-500 text-white">macOS-first V1</Badge>
                      </div>

                      <div className="p-4 border rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                          <Server className="h-5 w-5 text-primary" />
                          <span className="font-medium">Backend</span>
                        </div>
                        <div className="text-sm text-muted-foreground mb-2">Python 3.11+ / FastAPI</div>
                        {backendHealth ? (
                          <Badge className="bg-green-500 text-white">Running on :8000</Badge>
                        ) : (
                          <Badge variant="destructive">Offline</Badge>
                        )}
                      </div>

                      <div className="p-4 border rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                          <Database className="h-5 w-5 text-primary" />
                          <span className="font-medium">Storage</span>
                        </div>
                        <div className="text-sm text-muted-foreground mb-2">PostgreSQL + pgvector</div>
                        {backendHealth?.db_connected ? (
                          <Badge className="bg-green-500 text-white">Connected</Badge>
                        ) : (
                          <Badge variant="outline" className="text-amber-600 border-amber-300">Docker Required</Badge>
                        )}
                      </div>

                      <div className="p-4 border rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                          <Terminal className="h-5 w-5 text-primary" />
                          <span className="font-medium">Providers</span>
                        </div>
                        <div className="text-sm text-muted-foreground mb-2">config/providers.yaml</div>
                        {backendHealth?.providers_loaded ? (
                          <Badge className="bg-green-500 text-white">Loaded</Badge>
                        ) : (
                          <Badge variant="destructive">Not Loaded</Badge>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              {/* Status Tab */}
              <TabsContent value="status" className="space-y-4">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      {loading ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : backendHealth ? (
                        <CheckCircle2 className="h-5 w-5 text-green-500" />
                      ) : (
                        <XCircle className="h-5 w-5 text-red-500" />
                      )}
                      Python Backend Status
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {loading ? (
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Checking backend health...
                      </div>
                    ) : backendHealth ? (
                      <div className="space-y-2">
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Status:</span>
                          <Badge className={backendHealth.status === 'healthy' ? 'bg-green-500' : 'bg-amber-500'}>{backendHealth.status}</Badge>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Version:</span>
                          <span className="font-mono">{backendHealth.version}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Database:</span>
                          <Badge variant={backendHealth.db_connected ? 'default' : 'outline'}>
                            {backendHealth.db_connected ? 'Connected' : 'Docker Required'}
                          </Badge>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Providers:</span>
                          <Badge variant={backendHealth.providers_loaded ? 'default' : 'destructive'}>
                            {backendHealth.providers_loaded ? 'Loaded' : 'Not Loaded'}
                          </Badge>
                        </div>
                      </div>
                    ) : (
                      <div className="text-red-500">
                        Backend not responding. Start it with: <code className="bg-muted px-1 rounded">cd python-core && python main.py</code>
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Settings className="h-5 w-5" />
                      How to Run
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="p-4 bg-slate-900 rounded-lg text-green-400 font-mono text-sm overflow-x-auto">
                      <div className="text-slate-400 mb-2"># 1. Start PostgreSQL + pgvector</div>
                      <div>docker compose up -d</div>
                      <div className="text-slate-400 mb-2 mt-4"># 2. Start Python backend</div>
                      <div>cd python-core && python main.py</div>
                      <div className="text-slate-400 mb-2 mt-4"># 3. Start Tauri Desktop App (requires macOS)</div>
                      <div>cd tauri-app && npm install && npm run tauri dev</div>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </TabsContent>
        </Tabs>
      </main>

      {/* Footer */}
      <footer className="border-t bg-card py-3 text-center text-sm text-muted-foreground mt-auto">
        Interview Coach • Architecture: Tauri 2.0 + Python/FastAPI + PostgreSQL/pgvector • macOS-first V1
      </footer>
    </div>
  );
}
