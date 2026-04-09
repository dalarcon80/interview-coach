'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { 
  Lightbulb, 
  Copy, 
  Check, 
  ThumbsUp, 
  AlertCircle,
  Target,
  MessageSquare,
  Sparkles
} from 'lucide-react';

export interface Suggestion {
  id: string;
  suggestedAnswer: string;
  keyPoints: string[];
  confidence: number;
  questionType: string;
  tips: string[];
  detectedAt: string;
  processingFullResponse?: boolean;
}

interface SuggestionDisplayProps {
  suggestion: Suggestion | null;
  question: string;
}

const QUESTION_TYPE_LABELS: Record<string, string> = {
  behavioral: 'Comportamental',
  technical: 'Técnica',
  situational: 'Situacional',
  cultural_fit: 'Ajuste Cultural',
  salary: 'Salarial',
  experience: 'Experiencia',
  leadership: 'Liderazgo',
  problem_solving: 'Resolución de Problemas',
  motivation: 'Motivación',
  weakness: 'Debilidades',
  strength: 'Fortalezas',
  why_company: 'Por qué la empresa',
  why_role: 'Por qué el puesto',
  career_goals: 'Objetivos de Carrera',
  team_work: 'Trabajo en Equipo',
  conflict: 'Manejo de Conflictos',
  general: 'General'
};

export function SuggestionDisplay({ suggestion, question }: SuggestionDisplayProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (suggestion?.suggestedAnswer) {
      await navigator.clipboard.writeText(suggestion.suggestedAnswer);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (!suggestion) {
    return (
      <Card className="h-full flex items-center justify-center min-h-[400px]">
        <CardContent className="text-center py-12">
          <Lightbulb className="h-12 w-12 text-muted-foreground/30 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-muted-foreground">Esperando pregunta</h3>
          <p className="text-sm text-muted-foreground/70 mt-1">
            Ingresa una pregunta para recibir una sugerencia personalizada
          </p>
        </CardContent>
      </Card>
    );
  }

  const confidencePercent = Math.round((suggestion.confidence || 0.8) * 100);
  const questionTypeLabel = QUESTION_TYPE_LABELS[suggestion.questionType] || suggestion.questionType;

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-amber-500" />
            <CardTitle className="text-base">Respuesta Sugerida</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              {questionTypeLabel}
            </Badge>
            <div className={`flex items-center gap-1 text-xs ${confidencePercent >= 80 ? 'text-emerald-500' : confidencePercent >= 60 ? 'text-amber-500' : 'text-red-500'}`}>
              <Target className="h-3 w-3" />
              {confidencePercent}%
            </div>
          </div>
        </div>
        <CardDescription className="line-clamp-1">
          Basada en tu perfil y el estilo seleccionado
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Question asked */}
        <div className="bg-muted/50 p-3 rounded-lg">
          <div className="flex items-center gap-1 text-xs text-muted-foreground mb-1">
            <MessageSquare className="h-3 w-3" />
            Pregunta detectada
          </div>
          <p className="text-sm font-medium">{question}</p>
        </div>

        {/* Suggested Answer */}
        <div className="bg-primary/5 border border-primary/20 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-primary">RESPUESTA SUGERIDA</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={handleCopy}
            >
              {copied ? (
                <>
                  <Check className="h-3 w-3 mr-1 text-emerald-500" />
                  Copiado
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3 mr-1" />
                  Copiar
                </>
              )}
            </Button>
          </div>
          <p className="text-sm leading-relaxed">{suggestion.suggestedAnswer}</p>
          {suggestion.processingFullResponse && (
            <p className="text-xs text-muted-foreground mt-2">
              Generating full response...
            </p>
          )}
        </div>

        {/* Key Points */}
        {suggestion.keyPoints && suggestion.keyPoints.length > 0 && (
          <div>
            <div className="flex items-center gap-1 text-xs text-muted-foreground mb-2">
              <ThumbsUp className="h-3 w-3" />
              Puntos clave a destacar
            </div>
            <div className="flex flex-wrap gap-2">
              {suggestion.keyPoints.map((point, i) => (
                <Badge key={i} variant="secondary" className="text-xs">
                  {point}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Tips */}
        {suggestion.tips && suggestion.tips.length > 0 && (
          <div className="bg-amber-50 dark:bg-amber-950/20 p-3 rounded-lg border border-amber-200 dark:border-amber-800">
            <div className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400 mb-2">
              <AlertCircle className="h-3 w-3" />
              Consejos adicionales
            </div>
            <ul className="text-xs space-y-1 text-amber-700 dark:text-amber-300">
              {suggestion.tips.map((tip, i) => (
                <li key={i} className="flex items-start gap-1">
                  <span className="text-amber-500">•</span>
                  {tip}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Timestamp */}
        <div className="text-xs text-muted-foreground text-right">
          Generado: {new Date(suggestion.detectedAt).toLocaleTimeString()}
        </div>
      </CardContent>
    </Card>
  );
}
