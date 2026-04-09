/**
 * Audio Settings Panel
 * 
 * Controls for audio capture configuration.
 * Shows real status of audio providers, not placeholder text.
 */

'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { 
  Mic, 
  MicOff, 
  Volume2, 
  VolumeX, 
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Keyboard
} from 'lucide-react';

export interface AudioSettingsPanelProps {
  // Input mode
  inputMode: 'system' | 'mic' | 'both';
  onInputModeChange: (mode: 'system' | 'mic' | 'both') => void;
  
  // Provider status
  audioProviderStatus: 'available' | 'partial' | 'unavailable';
  audioProviderName: string;
  
  // Permission status
  micPermission: 'granted' | 'denied' | 'prompt' | 'unknown';
  systemAudioPermission: 'granted' | 'denied' | 'prompt' | 'unknown';
  
  // Connection
  isReconnecting: boolean;
  onReconnect: () => void;
  
  // Manual text mode
  manualTextMode: boolean;
  onManualTextModeChange: (enabled: boolean) => void;
  
  // Platform
  platform: 'macos' | 'windows' | 'linux' | 'unknown';
  capability?: 'functional' | 'partial' | 'stub';
}

export function AudioSettingsPanel({
  inputMode,
  onInputModeChange,
  audioProviderStatus,
  audioProviderName,
  micPermission,
  systemAudioPermission,
  isReconnecting,
  onReconnect,
  manualTextMode,
  onManualTextModeChange,
  platform,
  capability = 'stub',
}: AudioSettingsPanelProps) {
  const isAudioAvailable = audioProviderStatus === 'available';
  const isAudioPartial = audioProviderStatus === 'partial';
  
  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg flex items-center justify-between">
          <span>Audio Settings</span>
          <div className="flex items-center gap-2">
            {audioProviderStatus === 'available' && (
              <Badge className="bg-green-500">
                <CheckCircle2 className="h-3 w-3 mr-1" />
                Audio Ready
              </Badge>
            )}
            {audioProviderStatus === 'partial' && (
              <Badge className="bg-amber-500">
                <AlertTriangle className="h-3 w-3 mr-1" />
                Partial
              </Badge>
            )}
            {audioProviderStatus === 'unavailable' && (
              <Badge variant="destructive">
                <MicOff className="h-3 w-3 mr-1" />
                Unavailable
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
        {/* Provider Info */}
        <div className="p-3 bg-muted rounded-md">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Provider</span>
            <Badge variant="outline">{audioProviderName}</Badge>
          </div>
          <div className="text-xs text-muted-foreground">
            Platform: {platform === 'macos' ? 'macOS' : platform === 'windows' ? 'Windows' : platform === 'linux' ? 'Linux' : 'Unknown'}
          </div>
        </div>

        {/* Input Mode Selection */}
        <div className="space-y-3">
          <Label className="text-sm font-medium">Input Mode</Label>
          <div className="grid grid-cols-3 gap-2">
            <Button
              variant={inputMode === 'system' ? 'default' : 'outline'}
              size="sm"
              onClick={() => onInputModeChange('system')}
              disabled={!isAudioAvailable && !isAudioPartial}
              className="flex-col h-auto py-2"
            >
              <Volume2 className="h-4 w-4 mb-1" />
              <span className="text-xs">System</span>
            </Button>
            <Button
              variant={inputMode === 'mic' ? 'default' : 'outline'}
              size="sm"
              onClick={() => onInputModeChange('mic')}
              disabled={micPermission === 'denied'}
              className="flex-col h-auto py-2"
            >
              <Mic className="h-4 w-4 mb-1" />
              <span className="text-xs">Mic</span>
            </Button>
            <Button
              variant={inputMode === 'both' ? 'default' : 'outline'}
              size="sm"
              onClick={() => onInputModeChange('both')}
              disabled={!isAudioAvailable || micPermission === 'denied'}
              className="flex-col h-auto py-2"
            >
              <div className="flex gap-1 mb-1">
                <Volume2 className="h-3 w-3" />
                <Mic className="h-3 w-3" />
              </div>
              <span className="text-xs">Both</span>
            </Button>
          </div>
        </div>

        <Separator />

        {/* Permission Status */}
        <div className="space-y-2">
          <Label className="text-sm font-medium">Permissions</Label>
          
          {/* Mic Permission */}
          <div className="flex items-center justify-between p-2 bg-muted/50 rounded">
            <div className="flex items-center gap-2">
              <Mic className="h-4 w-4" />
              <span className="text-sm">Microphone</span>
            </div>
            {micPermission === 'granted' ? (
              <Badge className="bg-green-500 text-xs">Granted</Badge>
            ) : micPermission === 'denied' ? (
              <Badge variant="destructive" className="text-xs">Denied</Badge>
            ) : (
              <Badge variant="outline" className="text-xs">Prompt</Badge>
            )}
          </div>
          
          {/* System Audio Permission */}
          <div className="flex items-center justify-between p-2 bg-muted/50 rounded">
            <div className="flex items-center gap-2">
              <Volume2 className="h-4 w-4" />
              <span className="text-sm">System Audio</span>
            </div>
            {systemAudioPermission === 'granted' ? (
              <Badge className="bg-green-500 text-xs">Granted</Badge>
            ) : systemAudioPermission === 'denied' ? (
              <Badge variant="destructive" className="text-xs">Denied</Badge>
            ) : (
              <Badge variant="outline" className="text-xs">Prompt</Badge>
            )}
          </div>
        </div>

        <Separator />

        {/* Manual Text Mode */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-sm font-medium flex items-center gap-2">
              <Keyboard className="h-4 w-4" />
              Manual Text Mode
            </Label>
            <p className="text-xs text-muted-foreground">
              Type questions instead of audio capture
            </p>
          </div>
          <Switch
            checked={manualTextMode}
            onCheckedChange={onManualTextModeChange}
          />
        </div>

        {/* Reconnect Button */}
        {(isAudioPartial || audioProviderStatus === 'unavailable') && (
          <Button
            variant="outline"
            size="sm"
            onClick={onReconnect}
            disabled={isReconnecting}
            className="w-full"
          >
            {isReconnecting ? (
              <>
                <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                Reconnecting...
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4 mr-2" />
                Reconnect Audio
              </>
            )}
          </Button>
        )}

        {/* Status Note */}
        {isAudioPartial && (
          <div className="p-3 bg-amber-500/10 border border-amber-300 rounded-md">
            <div className="flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5" />
              <div className="text-xs text-amber-700">
                <p className="font-medium">Partial Audio Support</p>
                <p className="mt-1">
                  System audio capture requires ScreenCaptureKit integration.
                  Microphone input is available.
                </p>
              </div>
            </div>
          </div>
        )}

        {audioProviderStatus === 'unavailable' && (
          <div className="p-3 bg-destructive/10 border border-destructive rounded-md">
            <div className="flex items-start gap-2">
              <VolumeX className="h-4 w-4 text-destructive mt-0.5" />
              <div className="text-xs text-destructive">
                <p className="font-medium">Audio Unavailable</p>
                <p className="mt-1">
                  Audio capture is not available on this platform.
                  Use Manual Text Mode to type questions.
                </p>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default AudioSettingsPanel;
