'use client';

import { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { 
  MessageSquare, 
  Send, 
  Loader2, 
  Mic, 
  MicOff, 
  Trash2,
  History
} from 'lucide-react';
import type { ResponseStyle } from './StyleSelector';

export interface Suggestion {
  id: string;
  suggestedAnswer: string;
  keyPoints: string[];
  confidence: number;
  questionType: string;
  tips: string[];
  detectedAt: string;
}

interface QuestionInputProps {
  sessionId: string | null;
  selectedStyle: ResponseStyle;
  onSuggestion: (suggestion: Suggestion) => void;
  onClear: () => void;
  isProcessing: boolean;
  setIsProcessing: (value: boolean) => void;
  candidate?: { name: string; summary?: string; achievements?: string[] } | null;
  company?: { companyName: string; roleTitle?: string; jobDescription?: string } | null;
  onQuestionSubmit?: (question: string) => void;
}

export function QuestionInput({
  sessionId,
  selectedStyle,
  onSuggestion,
  onClear,
  isProcessing,
  setIsProcessing,
  candidate,
  company,
  onQuestionSubmit
}: QuestionInputProps) {
  const [question, setQuestion] = useState('');
  const [recentQuestions, setRecentQuestions] = useState<string[]>([]);
  const [isListening, setIsListening] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load recent questions from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('recentQuestions');
    if (saved) {
      setRecentQuestions(JSON.parse(saved).slice(0, 5));
    }
  }, []);

  const handleSubmit = async () => {
    if (!question.trim() || isProcessing) return;

    setIsProcessing(true);
    
    try {
      const response = await fetch('/api/coach/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          questionText: question,
          sessionId,
          style: selectedStyle,
          candidate: candidate || undefined,
          company: company || undefined,
        }),
      });

      const data = await response.json();
      
      if (data.success) {
        onSuggestion(data.suggestion);
        onQuestionSubmit?.(question);
        
        // Save to recent questions
        const updated = [question, ...recentQuestions.filter(q => q !== question)].slice(0, 5);
        setRecentQuestions(updated);
        localStorage.setItem('recentQuestions', JSON.stringify(updated));
      }
    } catch (error) {
      console.error('Error getting suggestion:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleClear = () => {
    setQuestion('');
    onClear();
    textareaRef.current?.focus();
  };

  const handleRecentClick = (q: string) => {
    setQuestion(q);
    textareaRef.current?.focus();
  };

  // Voice input simulation (would need Web Speech API in real implementation)
  const toggleListening = () => {
    setIsListening(!isListening);
    // In a real implementation, this would use the Web Speech API
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">Pregunta del Entrevistador</CardTitle>
          </div>
          <Badge variant={(selectedStyle === 'executive' || selectedStyle === 'commercial' || selectedStyle === 'technical' || selectedStyle === 'mixed' ? 'default' : selectedStyle) as 'secondary' | 'destructive' | 'default' | 'outline' | null | undefined}>
            {selectedStyle.charAt(0).toUpperCase() + selectedStyle.slice(1)}
          </Badge>
        </div>
        <CardDescription>
          Escribe o dicta la pregunta que te han hecho
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="relative">
          <Textarea
            ref={textareaRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ejemplo: ¿Cuéntame sobre un desafío técnico que hayas resuelto recientemente?"
            className="min-h-[100px] pr-20 resize-none"
            disabled={isProcessing}
          />
          <div className="absolute bottom-2 right-2 flex gap-1">
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={toggleListening}
              className={isListening ? 'text-red-500' : ''}
            >
              {isListening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        <div className="flex gap-2">
          <Button 
            onClick={handleSubmit} 
            disabled={!question.trim() || isProcessing}
            className="flex-1"
          >
            {isProcessing ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Analizando...
              </>
            ) : (
              <>
                <Send className="h-4 w-4 mr-2" />
                Obtener Sugerencia
              </>
            )}
          </Button>
          <Button 
            variant="outline" 
            size="icon"
            onClick={handleClear}
            disabled={isProcessing}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>

        {/* Recent Questions */}
        {recentQuestions.length > 0 && (
          <div className="pt-2 border-t">
            <div className="flex items-center gap-1 text-xs text-muted-foreground mb-2">
              <History className="h-3 w-3" />
              Preguntas recientes
            </div>
            <div className="flex flex-wrap gap-1">
              {recentQuestions.map((q, i) => (
                <button
                  key={i}
                  onClick={() => handleRecentClick(q)}
                  className="text-xs bg-muted hover:bg-muted/80 px-2 py-1 rounded truncate max-w-[200px]"
                >
                  {q.length > 40 ? q.slice(0, 40) + '...' : q}
                </button>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
