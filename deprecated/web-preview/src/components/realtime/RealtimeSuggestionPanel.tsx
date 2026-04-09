/**
 * Realtime Suggestion Panel
 * 
 * Displays AI-generated interview suggestions in real-time.
 * Shows bullets first (fast) then full response (after quality gate).
 */

'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { 
  Lightbulb, 
  Sparkles, 
  Copy, 
  Check, 
  Clock,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Loader2
} from 'lucide-react';

export interface Suggestion {
  exchangeIndex: number;
  mode?: 'demo' | 'real' | 'fallback';
  provider?: string;
  model?: string;
  bullets?: string[];
  fullResponse?: string;
  confidence?: number;
  latencyMs?: number;
  processingFullResponse?: boolean;
  bulletsLatencyMs?: number;
  fullLatencyMs?: number;
}

export interface RealtimeSuggestionPanelProps {
  suggestion: Suggestion | null;
  processing?: boolean;
  style?: 'executive' | 'commercial' | 'technical' | 'mixed';
  onCopy?: (text: string) => void;
  capability?: 'functional' | 'partial' | 'stub';
}

const STYLE_CONFIG = {
  executive: {
    label: 'Ejecutivo',
    color: 'bg-purple-500',
    description: 'Conciso, métricas, ROI'
  },
  commercial: {
    label: 'Comercial',
    color: 'bg-blue-500',
    description: 'Persuasivo, valor, beneficios'
  },
  technical: {
    label: 'Técnico',
    color: 'bg-orange-500',
    description: 'Detallado, arquitectura'
  },
  mixed: {
    label: 'Mixto',
    color: 'bg-green-500',
    description: 'Balanceado, STAR'
  }
};

export function RealtimeSuggestionPanel({
  suggestion,
  processing = false,
  style = 'mixed',
  onCopy,
  capability = 'functional',
}: RealtimeSuggestionPanelProps) {
  const [copied, setCopied] = React.useState(false);
  const [showFullResponse, setShowFullResponse] = React.useState(true);
  
  const styleInfo = STYLE_CONFIG[style];

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    onCopy?.(text);
    setTimeout(() => setCopied(false), 2000);
  };

  const formatLatency = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const hasBullets = Boolean(suggestion?.bullets && suggestion.bullets.length > 0);
  const hasFullResponse = Boolean(suggestion?.fullResponse && suggestion.fullResponse.trim().length > 0);
  const waitingForFullResponse = Boolean(
    suggestion &&
    hasBullets &&
    !hasFullResponse &&
    (processing || suggestion.processingFullResponse)
  );

  return (
    <Card className="w-full h-full flex flex-col">
      <CardHeader className="pb-3 flex-shrink-0">
        <CardTitle className="text-lg flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Sugerencia
          </span>
          <div className="flex items-center gap-2">
            <Badge className={`${styleInfo.color} text-white`}>
              {styleInfo.label}
            </Badge>
            {suggestion?.mode && (
              <Badge variant={suggestion.mode === 'real' ? 'default' : 'secondary'}>
                Mode: {suggestion.mode}
              </Badge>
            )}
            <Badge
              variant={capability === 'functional' ? 'default' : 'outline'}
              className={
                capability === 'stub'
                  ? 'border-amber-300 text-amber-700'
                  : capability === 'partial'
                  ? 'border-blue-300 text-blue-700'
                  : ''
              }
            >
              {capability}
            </Badge>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-0">
        <ScrollArea className="h-full px-4 pb-4">
          {/* Processing State */}
          {processing && !suggestion && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <div className="relative">
                <Lightbulb className="h-12 w-12 text-primary animate-pulse" />
                <Sparkles className="h-4 w-4 text-primary absolute -top-1 -right-1 animate-bounce" />
              </div>
              <p className="text-sm text-muted-foreground mt-4">
                Analizando pregunta...
              </p>
              <p className="text-xs text-muted-foreground/70 mt-1">
                Generando sugerencia personalizada
              </p>
            </div>
          )}

          {/* No Suggestion State */}
          {!processing && !suggestion && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Lightbulb className="h-12 w-12 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">
                Las sugerencias aparecerán aquí
              </p>
              <p className="text-xs text-muted-foreground/70 mt-1">
                Cuando se detecte una pregunta
              </p>
            </div>
          )}

          {/* Suggestion Display */}
          {suggestion && (
            <div className="space-y-4">
              {/* Metrics Bar */}
              {(suggestion.latencyMs !== undefined || suggestion.bulletsLatencyMs !== undefined || suggestion.fullLatencyMs !== undefined) && (
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  {suggestion.provider && (
                    <div className="flex items-center gap-1">
                      <span>Provider: {suggestion.provider}</span>
                    </div>
                  )}
                  {suggestion.model && (
                    <div className="flex items-center gap-1">
                      <span>Model: {suggestion.model}</span>
                    </div>
                  )}
                  {suggestion.bulletsLatencyMs !== undefined && (
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      <span>Bullets: {formatLatency(suggestion.bulletsLatencyMs)}</span>
                    </div>
                  )}
                  {suggestion.fullLatencyMs !== undefined && (
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      <span>Full: {formatLatency(suggestion.fullLatencyMs)}</span>
                    </div>
                  )}
                  {suggestion.bulletsLatencyMs === undefined && suggestion.fullLatencyMs === undefined && suggestion.latencyMs !== undefined && (
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      <span>{formatLatency(suggestion.latencyMs)}</span>
                    </div>
                  )}
                  {suggestion.confidence !== undefined && (
                    <div className="flex items-center gap-1">
                      <AlertCircle className="h-3 w-3" />
                      <span>{Math.round(suggestion.confidence * 100)}% confianza</span>
                    </div>
                  )}
                </div>
              )}

              {/* Bullets */}
              {suggestion.bullets && suggestion.bullets.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-medium flex items-center gap-2">
                    <Lightbulb className="h-4 w-4 text-yellow-500" />
                    Puntos Clave
                    <Badge variant="secondary" className="text-[10px]">Bullets-first</Badge>
                  </h4>
                  <ul className="space-y-2">
                    {suggestion.bullets.map((bullet, index) => (
                      <li 
                        key={index}
                        className="flex items-start gap-2 text-sm"
                      >
                        <span className="text-primary mt-1">•</span>
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Full response in progress indicator */}
              {waitingForFullResponse && (
                <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
                  <div className="flex items-center gap-2 text-sm text-primary">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Generando respuesta completa...
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Ya puedes empezar con los bullets mientras llega la respuesta final.
                  </p>
                </div>
              )}

              {/* Full Response */}
              {suggestion.fullResponse && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-primary" />
                      Respuesta Sugerida
                    </h4>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setShowFullResponse(!showFullResponse)}
                        className="h-6 px-2"
                      >
                        {showFullResponse ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleCopy(suggestion.fullResponse || '')}
                        className="h-6 px-2"
                      >
                        {copied ? (
                          <Check className="h-3 w-3 text-green-500" />
                        ) : (
                          <Copy className="h-3 w-3" />
                        )}
                      </Button>
                    </div>
                  </div>
                  {showFullResponse && (
                    <div className="p-4 bg-muted/50 rounded-lg border">
                      <p className="text-sm whitespace-pre-wrap">
                        {suggestion.fullResponse}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Style Hint */}
              <div className="pt-2 border-t">
                <p className="text-xs text-muted-foreground">
                  <span className="font-medium">{styleInfo.label}:</span>{' '}
                  {styleInfo.description}
                </p>
              </div>
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

export default RealtimeSuggestionPanel;
