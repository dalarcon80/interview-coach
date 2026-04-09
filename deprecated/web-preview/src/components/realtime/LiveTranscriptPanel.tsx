/**
 * Live Transcript Panel
 * 
 * Displays real-time transcription of interview conversation.
 * Shows partial (live) and final transcriptions with speaker identification.
 */

'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { 
  User, 
  MessageSquare,
  Languages 
} from 'lucide-react';

export interface TranscriptEntry {
  id: string;
  text: string;
  type: 'partial' | 'final';
  speaker?: 'interviewer' | 'candidate';
  language?: string;
  timestamp: number;
}

export interface LiveTranscriptPanelProps {
  transcripts: TranscriptEntry[];
  currentPartial?: string;
  language?: string;
  maxEntries?: number;
  capability?: 'functional' | 'partial' | 'stub';
}

export function LiveTranscriptPanel({
  transcripts = [],
  currentPartial,
  language = 'es',
  maxEntries = 50,
  capability = 'functional',
}: LiveTranscriptPanelProps) {
  const displayTranscripts = (transcripts || []).slice(-maxEntries);

  return (
    <Card className="w-full h-full flex flex-col">
      <CardHeader className="pb-3 flex-shrink-0">
        <CardTitle className="text-lg flex items-center justify-between">
          <span className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            Transcripción
          </span>
          <div className="flex items-center gap-2">
            {language && (
              <Badge variant="outline" className="text-xs">
                <Languages className="h-3 w-3 mr-1" />
                {language.toUpperCase()}
              </Badge>
            )}
            <Badge
              variant={capability === 'functional' ? 'default' : 'outline'}
              className={
                capability === 'stub'
                  ? 'border-amber-300 text-amber-700 text-xs'
                  : capability === 'partial'
                  ? 'border-blue-300 text-blue-700 text-xs'
                  : 'text-xs'
              }
            >
              {capability}
            </Badge>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-0">
        <ScrollArea className="h-full px-4 pb-4">
          <div className="space-y-3">
            {/* Partial (live) transcript */}
            {currentPartial && (
              <div className="p-3 bg-primary/5 border border-primary/20 rounded-lg border-l-4 border-l-primary">
                <div className="flex items-start gap-2">
                  <div className="flex-shrink-0 mt-0.5">
                    <div className="w-2 h-2 bg-primary rounded-full animate-pulse" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-muted-foreground mb-1">
                      Hablando...
                    </p>
                    <p className="text-sm italic text-foreground/80">
                      {currentPartial}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Final transcripts */}
            {displayTranscripts.length === 0 && !currentPartial ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <MessageSquare className="h-12 w-12 text-muted-foreground/30 mb-3" />
                <p className="text-sm text-muted-foreground">
                  La transcripción aparecerá aquí
                </p>
                <p className="text-xs text-muted-foreground/70 mt-1">
                  Inicia una sesión para comenzar
                </p>
              </div>
            ) : (
              displayTranscripts.map((entry, index) => (
                <div
                  key={entry.id || index}
                  className={`p-3 rounded-lg border-l-4 ${
                    entry.speaker === 'interviewer'
                      ? 'bg-blue-500/5 border-l-blue-500 ml-0 mr-4'
                      : entry.speaker === 'candidate'
                      ? 'bg-green-500/5 border-l-green-500 ml-4 mr-0'
                      : 'bg-muted border-l-muted-foreground'
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      {entry.speaker === 'interviewer' ? (
                        <User className="h-4 w-4 text-blue-500" />
                      ) : entry.speaker === 'candidate' ? (
                        <User className="h-4 w-4 text-green-500" />
                      ) : (
                        <MessageSquare className="h-4 w-4 text-muted-foreground" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-medium text-muted-foreground">
                          {entry.speaker === 'interviewer' 
                            ? 'Entrevistador' 
                            : entry.speaker === 'candidate'
                            ? 'Tú'
                            : 'Sistema'}
                        </span>
                        <span className="text-xs text-muted-foreground/50">
                          {new Date(entry.timestamp).toLocaleTimeString()}
                        </span>
                        {entry.language && entry.language !== language && (
                          <Badge variant="outline" className="text-[10px] px-1 py-0">
                            {entry.language.toUpperCase()}
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm">{entry.text}</p>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

export default LiveTranscriptPanel;
