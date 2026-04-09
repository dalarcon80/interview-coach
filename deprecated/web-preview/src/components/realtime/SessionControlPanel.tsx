/**
 * Session Control Panel
 * 
 * UI for managing interview sessions.
 * Start/end sessions, connection status, session controls.
 */

'use client';

import React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { 
  Play, 
  Square, 
  Wifi, 
  WifiOff, 
  RefreshCw,
  Clock,
  MessageSquare,
  Zap
} from 'lucide-react';

export interface SessionControlPanelProps {
  connected: boolean;
  sessionActive: boolean;
  processing: boolean;
  error: string | null;
  onConnect: () => void;
  onDisconnect: () => void;
  onStartSession: () => void;
  onEndSession: () => void;
  companyName?: string;
  roleTitle?: string;
  // Session stats
  sessionDuration?: number;
  exchangeCount?: number;
  averageLatency?: number;
  mode?: 'demo' | 'real' | 'mixed';
  capability?: 'functional' | 'partial' | 'stub';
}

export function SessionControlPanel({
  connected,
  sessionActive,
  processing,
  error,
  onConnect,
  onDisconnect,
  onStartSession,
  onEndSession,
  companyName = 'Empresa',
  roleTitle = 'Puesto',
  sessionDuration = 0,
  exchangeCount = 0,
  averageLatency = 0,
  mode,
  capability = 'partial',
}: SessionControlPanelProps) {
  
  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg flex items-center justify-between">
          <span>Control de Sesión</span>
          <div className="flex items-center gap-2">
            {connected ? (
              <Badge className="bg-green-500">
                <Wifi className="h-3 w-3 mr-1" />
                Conectado
              </Badge>
            ) : (
              <Badge variant="destructive">
                <WifiOff className="h-3 w-3 mr-1" />
                Desconectado
              </Badge>
            )}
            {mode && (
              <Badge variant={mode === 'real' ? 'default' : 'outline'}>
                {mode === 'real' ? 'Real' : mode === 'demo' ? 'Demo' : 'Mixed'}
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
      
      <CardContent className="space-y-4">
        {/* Error Display */}
        {error && (
          <div className="p-3 bg-destructive/10 border border-destructive rounded-md">
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}

        {/* Session Info */}
        {sessionActive && (
          <div className="p-3 bg-muted rounded-md space-y-2">
            <div>
              <p className="text-sm font-medium">{companyName}</p>
              <p className="text-xs text-muted-foreground">{roleTitle}</p>
            </div>
            
            <Separator />
            
            {/* Session Stats */}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  Duración
                </div>
                <p className="text-sm font-mono font-medium">
                  {formatDuration(sessionDuration)}
                </p>
              </div>
              <div>
                <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                  <MessageSquare className="h-3 w-3" />
                  Exchanges
                </div>
                <p className="text-sm font-mono font-medium">
                  {exchangeCount}
                </p>
              </div>
              <div>
                <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                  <Zap className="h-3 w-3" />
                  Latencia
                </div>
                <p className="text-sm font-mono font-medium">
                  {averageLatency}ms
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Controls */}
        <div className="flex flex-wrap gap-2">
          {!connected ? (
            <Button onClick={onConnect} className="flex-1">
              <RefreshCw className="h-4 w-4 mr-2" />
              Conectar
            </Button>
          ) : !sessionActive ? (
            <Button onClick={onStartSession} className="flex-1">
              <Play className="h-4 w-4 mr-2" />
              Iniciar Sesión
            </Button>
          ) : (
            <Button 
              onClick={onEndSession} 
              variant="destructive"
              className="flex-1"
            >
              <Square className="h-4 w-4 mr-2" />
              Terminar Sesión
            </Button>
          )}
        </div>

        {/* Processing Indicator */}
        {processing && (
          <div className="flex items-center justify-center p-3 bg-primary/10 rounded-md">
            <RefreshCw className="h-4 w-4 animate-spin mr-2" />
            <span className="text-sm">Procesando...</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default SessionControlPanel;
