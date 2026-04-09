import { useCallback, useEffect, useState } from "react";
import { Loader2, Save, CheckCircle2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import api from "@/lib/api-client";
import {
  loadRuntimeConfig,
  mergeRuntimeConfig,
  saveRuntimeConfig,
  type RuntimeConfig,
  type LatencyConfig,
  DEFAULT_RUNTIME_CONFIG,
} from "@/lib/persistence";

interface SettingsPanelProps {
  backendUrl: string;
}

const LLM_PROVIDERS = [
  { value: "anthropic", label: "Anthropic (Claude)" },
  { value: "openai", label: "OpenAI (GPT)" },
  { value: "ollama", label: "Ollama (Local)" },
];

const LLM_MODELS = {
  anthropic: [
    // Claude 4.6 Series (Feb 2026)
    { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6 (Latest)" },
    { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
    // Claude 4.5 Series
    { value: "claude-opus-4-5-20251101", label: "Claude Opus 4.5" },
    { value: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5" },
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
    // Claude 4.1 Series
    { value: "claude-opus-4-1-20250805", label: "Claude Opus 4.1" },
    // Claude 4 Series (May 2025)
    { value: "claude-opus-4-20250514", label: "Claude Opus 4" },
    { value: "claude-sonnet-4-20250514", label: "Claude Sonnet 4" },
    // Claude 3 Series
    { value: "claude-3-haiku-20240307", label: "Claude 3 Haiku" },
  ],
  openai: [
    { value: "gpt-4o", label: "GPT-4o" },
    { value: "gpt-4o-mini", label: "GPT-4o Mini" },
    { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
    { value: "gpt-4", label: "GPT-4" },
    { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
    { value: "o1", label: "o1 (Reasoning)" },
    { value: "o1-mini", label: "o1 Mini (Reasoning)" },
  ],
  ollama: [
    // Models will be dynamically loaded from Ollama server
    { value: "llama3.2", label: "Llama 3.2" },
    { value: "llama3.1", label: "Llama 3.1" },
    { value: "llama3", label: "Llama 3" },
    { value: "mistral", label: "Mistral" },
    { value: "mixtral", label: "Mixtral" },
    { value: "phi3", label: "Phi-3" },
    { value: "qwen2", label: "Qwen 2" },
    { value: "codellama", label: "Code Llama" },
  ],
};

const STT_PROVIDERS = [
  { value: "deepgram", label: "Deepgram (Cloud)" },
  { value: "whisper_local", label: "Whisper Local" },
];

const STT_MODELS = {
  deepgram: [
    { value: "nova-3", label: "Nova 3 (Recommended)" },
    { value: "nova-2", label: "Nova 2" },
    { value: "whisper", label: "Whisper" },
  ],
  whisper_local: [
    { value: "small", label: "Small (Recommended - Balance)" },
    { value: "base", label: "Base (Faster)" },
    { value: "medium", label: "Medium (More Accurate)" },
  ],
};

export function SettingsPanel({ backendUrl }: SettingsPanelProps) {
  const [config, setConfig] = useState<RuntimeConfig>(DEFAULT_RUNTIME_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [ollamaAvailable, setOllamaAvailable] = useState<boolean | null>(null);
  const [ollamaModels, setOllamaModels] = useState<Array<{ id: string; name: string }>>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  // Load config on mount
  useEffect(() => {
    const loadConfig = async () => {
      try {
        // First load from local storage
        const localConfig = loadRuntimeConfig();
        setConfig(localConfig);

        // Then try to fetch from backend
        if (backendUrl) {
          api.setBaseUrl(backendUrl);
          try {
            const backendConfig = await api.getRuntimeConfig();
            if (backendConfig) {
              const mergedConfig = mergeRuntimeConfig(backendConfig, localConfig);
              setConfig(mergedConfig);
              saveRuntimeConfig(mergedConfig);
            }
          } catch (e) {
            console.log("Could not fetch runtime config from backend:", e);
          }
        }
      } catch (e) {
        console.error("Error loading runtime config:", e);
      } finally {
        setLoading(false);
      }
    };

    loadConfig();
  }, [backendUrl]);

  // Check Ollama availability on mount and when config changes
  useEffect(() => {
    const checkOllama = async () => {
      if (backendUrl) {
        try {
          api.setBaseUrl(backendUrl);
          const response = await fetch(`${backendUrl}/api/ollama/status`);
          const data = await response.json();
          setOllamaAvailable(data.available);
          
          // If Ollama is available, fetch the models
          if (data.available) {
            const modelsResponse = await fetch(`${backendUrl}/api/models/ollama`);
            const modelsData = await modelsResponse.json();
            if (modelsData.success && modelsData.models) {
              setOllamaModels(modelsData.models);
            }
          }
        } catch (e) {
          console.log("Could not check Ollama status:", e);
          setOllamaAvailable(false);
        }
      }
    };

    checkOllama();
  }, [backendUrl]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);

    try {
      // Persist locally first so the runtime config survives even if the backend
      // is temporarily unavailable.
      saveRuntimeConfig(config);

      // Best-effort sync to the backend.
      if (backendUrl) {
        api.setBaseUrl(backendUrl);
        await api.updateRuntimeConfig(config);
      }

      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e) {
      console.error("Error saving runtime config:", e);
      setError(
        e instanceof Error
          ? `Saved locally, but could not sync to the backend: ${e.message}`
          : "Saved locally, but could not sync configuration to the backend"
      );
    } finally {
      setSaving(false);
    }
  }, [config, backendUrl]);

  const updateLlmConfig = useCallback((updates: Partial<RuntimeConfig["llm"]>) => {
    setConfig((prev) => ({
      ...prev,
      llm: { 
        ...prev.llm, 
        ...updates,
        // Ensure base_url has a default
        base_url: updates.base_url ?? prev.llm.base_url ?? "http://localhost:11434",
      },
    }));
  }, []);

  const updateSttConfig = useCallback((updates: Partial<RuntimeConfig["stt"]>) => {
    setConfig((prev) => ({
      ...prev,
      stt: { ...prev.stt, ...updates },
    }));
  }, []);

  const updateLatencyConfig = useCallback((updates: Partial<LatencyConfig>) => {
    setConfig((prev) => ({
      ...prev,
      latency: {
        utterance_end_ms: updates.utterance_end_ms ?? prev.latency?.utterance_end_ms ?? 500,
        silence_threshold_ms: updates.silence_threshold_ms ?? prev.latency?.silence_threshold_ms ?? 200,
        min_utterance_duration_ms: updates.min_utterance_duration_ms ?? prev.latency?.min_utterance_duration_ms ?? 100,
        suggestion_cooldown_sec: updates.suggestion_cooldown_sec ?? prev.latency?.suggestion_cooldown_sec ?? 1,
      },
    }));
  }, []);

  const updateAutoSuggestionConfig = useCallback((updates: Partial<import("@/lib/persistence").AutoSuggestionConfig>) => {
    setConfig((prev) => ({
      ...prev,
      auto_suggestion: {
        enabled: updates.enabled ?? prev.auto_suggestion?.enabled ?? true,
        silence_threshold_ms: updates.silence_threshold_ms ?? prev.auto_suggestion?.silence_threshold_ms ?? 2000,
        cooldown_sec: updates.cooldown_sec ?? prev.auto_suggestion?.cooldown_sec ?? 5,
        min_turn_duration_ms: updates.min_turn_duration_ms ?? prev.auto_suggestion?.min_turn_duration_ms ?? 500,
        min_word_count: updates.min_word_count ?? prev.auto_suggestion?.min_word_count ?? 2,
        context_turn_limit: updates.context_turn_limit ?? prev.auto_suggestion?.context_turn_limit ?? 4,
      },
    }));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">Settings</h2>
          <p className="text-muted-foreground">
            Configure LLM and STT providers for real-time coaching
          </p>
        </div>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Save Configuration
        </Button>
      </div>

      {success && (
        <Alert className="status-badge-success">
          <CheckCircle2 className="h-4 w-4" />
          <AlertTitle>Configuration Saved</AlertTitle>
          <AlertDescription>
            Your runtime configuration has been saved successfully.
          </AlertDescription>
        </Alert>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* LLM Configuration */}
      <Card>
        <CardHeader>
          <CardTitle>LLM Configuration</CardTitle>
          <CardDescription>
            Configure the Language Model for generating interview responses
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="llm-enabled">Enable LLM</Label>
            <Switch
              id="llm-enabled"
              checked={config.llm.enabled}
              onCheckedChange={(checked) => updateLlmConfig({ enabled: checked })}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="llm-provider">Provider</Label>
            <Select
              value={config.llm.provider}
              onValueChange={(value: "anthropic" | "openai" | "ollama") => {
                const models = LLM_MODELS[value];
                updateLlmConfig({
                  provider: value,
                  model: models?.[0]?.value || "",
                });
              }}
              disabled={!config.llm.enabled}
            >
              <SelectTrigger id="llm-provider">
                <SelectValue placeholder="Select provider" />
              </SelectTrigger>
              <SelectContent>
                {LLM_PROVIDERS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="llm-model">
              Model 
              {config.llm.provider === "ollama" && ollamaAvailable === false && " (Ollama not available)"}
            </Label>
            <Select
              value={config.llm.model}
              onValueChange={(value) => updateLlmConfig({ model: value })}
              disabled={!config.llm.enabled || (config.llm.provider === "ollama" && !ollamaAvailable)}
            >
              <SelectTrigger id="llm-model">
                <SelectValue placeholder="Select model" />
              </SelectTrigger>
              <SelectContent>
                {config.llm.provider === "ollama" && ollamaModels.length > 0 ? (
                  ollamaModels.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.name}
                    </SelectItem>
                  ))
                ) : (
                  LLM_MODELS[config.llm.provider as keyof typeof LLM_MODELS]?.map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      {m.label}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {config.llm.provider === "ollama" && ollamaAvailable === false && (
              <p className="text-xs text-warning-500">
                Ollama is not running. Start Ollama to use local models.
              </p>
            )}
          </div>

          {/* Base URL for Ollama */}
          {config.llm.provider === "ollama" && (
            <div className="grid gap-2">
              <Label htmlFor="llm-base-url">Ollama Server URL</Label>
              <Input
                id="llm-base-url"
                type="text"
                placeholder="http://localhost:11434"
                value={config.llm.base_url || "http://localhost:11434"}
                onChange={(e) => updateLlmConfig({ base_url: e.target.value })}
                disabled={!config.llm.enabled}
              />
              <p className="text-xs text-muted-foreground">
                URL of your local Ollama server
              </p>
            </div>
          )}

          {/* API Key for Anthropic and OpenAI */}
          {config.llm.provider !== "ollama" && (
            <div className="grid gap-2">
              <Label htmlFor="llm-api-key">API Key</Label>
              <Input
                id="llm-api-key"
                type="password"
                placeholder={config.llm.provider === "anthropic" ? "sk-ant-..." : "sk-..."}
                value={config.llm.api_key}
                onChange={(e) => updateLlmConfig({ api_key: e.target.value })}
                disabled={!config.llm.enabled}
              />
              <p className="text-xs text-muted-foreground">
                {config.llm.provider === "anthropic"
                  ? "Get your API key from console.anthropic.com"
                  : "Get your API key from platform.openai.com"}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* STT Configuration */}
      <Card>
        <CardHeader>
          <CardTitle>STT Configuration</CardTitle>
          <CardDescription>
            Configure the Speech-to-Text provider for live transcription
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="stt-enabled">Enable STT</Label>
            <Switch
              id="stt-enabled"
              checked={config.stt.enabled}
              onCheckedChange={(checked) => updateSttConfig({ enabled: checked })}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="stt-model">Model</Label>
            <Select
              value={config.stt.model}
              onValueChange={(value) => updateSttConfig({ model: value })}
              disabled={!config.stt.enabled}
            >
              <SelectTrigger id="stt-model">
                <SelectValue placeholder="Select model" />
              </SelectTrigger>
              <SelectContent>
                {STT_MODELS.deepgram.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="stt-api-key">API Key</Label>
            <Input
              id="stt-api-key"
              type="password"
              placeholder="Enter your Deepgram API key"
              value={config.stt.api_key}
              onChange={(e) => updateSttConfig({ api_key: e.target.value })}
              disabled={!config.stt.enabled}
            />
            <p className="text-xs text-muted-foreground">
              Get your API key from console.deepgram.com
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Latency Configuration */}
      <Card>
        <CardHeader>
          <CardTitle>Latency Settings</CardTitle>
          <CardDescription>
            Configure transcription timing (these are the working defaults)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="latency-utterance">
                Utterance End
              </Label>
              <span className="text-sm font-medium">
                {config.latency?.utterance_end_ms ?? 2000}ms
              </span>
            </div>
            <Slider
              id="latency-utterance"
              min={100}
              max={3000}
              step={100}
              value={[config.latency?.utterance_end_ms ?? 2000]}
              onValueChange={(value) => updateLatencyConfig({ utterance_end_ms: value[0] })}
            />
            <p className="text-xs text-muted-foreground">
              How long to wait for speech to end before processing
            </p>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="latency-silence">
                Silence Threshold
              </Label>
              <span className="text-sm font-medium">
                {config.latency?.silence_threshold_ms ?? 500}ms
              </span>
            </div>
            <Slider
              id="latency-silence"
              min={100}
              max={1000}
              step={50}
              value={[config.latency?.silence_threshold_ms ?? 500]}
              onValueChange={(value) => updateLatencyConfig({ silence_threshold_ms: value[0] })}
            />
            <p className="text-xs text-muted-foreground">
              Silence duration to consider a turn complete
            </p>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="latency-min-duration">
                Min Utterance Duration
              </Label>
              <span className="text-sm font-medium">
                {config.latency?.min_utterance_duration_ms ?? 300}ms
              </span>
            </div>
            <Slider
              id="latency-min-duration"
              min={50}
              max={1000}
              step={50}
              value={[config.latency?.min_utterance_duration_ms ?? 300]}
              onValueChange={(value) => updateLatencyConfig({ min_utterance_duration_ms: value[0] })}
            />
            <p className="text-xs text-muted-foreground">
              Minimum speech duration to process
            </p>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="latency-cooldown">
                Suggestion Cooldown
              </Label>
              <span className="text-sm font-medium">
                {config.latency?.suggestion_cooldown_sec ?? 3}sec
              </span>
            </div>
            <Slider
              id="latency-cooldown"
              min={1}
              max={10}
              step={1}
              value={[config.latency?.suggestion_cooldown_sec ?? 3]}
              onValueChange={(value) => updateLatencyConfig({ suggestion_cooldown_sec: value[0] })}
            />
            <p className="text-xs text-muted-foreground">
              Minimum time between suggestions
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Auto-Suggestion Settings */}
      <Card>
        <CardHeader>
          <CardTitle>Auto-Suggestion</CardTitle>
          <CardDescription>
            Automatically trigger suggestions when interviewer stops talking
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="auto-suggestion-enabled">Enable Auto-Suggestions</Label>
            <Switch
              id="auto-suggestion-enabled"
              checked={config.auto_suggestion?.enabled ?? true}
              onCheckedChange={(checked) => updateAutoSuggestionConfig({ enabled: checked })}
            />
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="auto-silence-threshold">Silence Threshold</Label>
              <span className="text-sm font-medium">
                {config.auto_suggestion?.silence_threshold_ms ?? 2000}ms
              </span>
            </div>
            <Slider
              id="auto-silence-threshold"
              min={500}
              max={5000}
              step={100}
              value={[config.auto_suggestion?.silence_threshold_ms ?? 2000]}
              onValueChange={(value) => updateAutoSuggestionConfig({ silence_threshold_ms: value[0] })}
              disabled={!config.auto_suggestion?.enabled}
            />
            <p className="text-xs text-muted-foreground">
              Wait this long after interviewer stops talking before triggering
            </p>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="auto-cooldown">Cooldown</Label>
              <span className="text-sm font-medium">
                {config.auto_suggestion?.cooldown_sec ?? 5}sec
              </span>
            </div>
            <Slider
              id="auto-cooldown"
              min={1}
              max={30}
              step={1}
              value={[config.auto_suggestion?.cooldown_sec ?? 5]}
              onValueChange={(value) => updateAutoSuggestionConfig({ cooldown_sec: value[0] })}
              disabled={!config.auto_suggestion?.enabled}
            />
            <p className="text-xs text-muted-foreground">
              Minimum time between auto-suggestions
            </p>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="auto-context-turns">Context Turns</Label>
              <span className="text-sm font-medium">
                {config.auto_suggestion?.context_turn_limit ?? 4}
              </span>
            </div>
            <Slider
              id="auto-context-turns"
              min={1}
              max={10}
              step={1}
              value={[config.auto_suggestion?.context_turn_limit ?? 4]}
              onValueChange={(value) => updateAutoSuggestionConfig({ context_turn_limit: value[0] })}
              disabled={!config.auto_suggestion?.enabled}
            />
            <p className="text-xs text-muted-foreground">
              Number of conversation turns to include in context
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Status */}
      <Card>
        <CardHeader>
          <CardTitle>Configuration Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">LLM Status:</span>
              <span
                className={`text-sm ${
                  config.llm.enabled && (config.llm.provider === "ollama" || config.llm.api_key)
                    ? "text-green-600"
                    : "text-muted-foreground"
                }`}
              >
                {config.llm.enabled && (config.llm.provider === "ollama" || config.llm.api_key)
                  ? `${config.llm.provider} / ${config.llm.model}`
                  : "Not configured"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">STT Status:</span>
              <span
                className={`text-sm ${
                  config.stt.enabled && config.stt.api_key
                    ? "text-green-600"
                    : "text-muted-foreground"
                }`}
              >
                {config.stt.enabled && config.stt.api_key
                  ? `${config.stt.provider} / ${config.stt.model}`
                  : "Not configured"}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
