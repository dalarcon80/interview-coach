'use client';

import { useState, useRef } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { 
  FileText, 
  Upload, 
  Loader2, 
  CheckCircle2, 
  AlertCircle,
  ArrowDownToLine,
  Sparkles
} from 'lucide-react';

interface CVProfile {
  name: string;
  email?: string;
  currentRole?: string;
  company?: string;
  summary?: string;
  yearsExperience?: number;
  skills?: string[];
  achievements?: string[];
  leadershipRoles?: string[];
  technicalStack?: string[];
  metrics?: string[];
}

interface CVAnalysisResult {
  success: boolean;
  mode: string;
  profile: CVProfile;
  highlights?: string[];
  suggestedTalkingPoints?: string[];
  confidence?: number;
  error?: string;
}

interface CVIntakeProps {
  onApplyToProfile: (profile: CVProfile) => void;
}

export function CVIntake({ onApplyToProfile }: CVIntakeProps) {
  const [cvText, setCvText] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<CVAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const allowedTypes = ['.txt', '.md', 'text/plain', 'text/markdown'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    
    if (!allowedTypes.includes(fileExtension) && !allowedTypes.includes(file.type)) {
      setError('Solo se permiten archivos .txt o .md');
      return;
    }

    try {
      const text = await file.text();
      setCvText(text);
      setError(null);
    } catch (err) {
      setError('Error al leer el archivo');
    }
  };

  const handleAnalyze = async () => {
    if (!cvText.trim()) {
      setError('Por favor ingresa el texto del CV');
      return;
    }

    setAnalyzing(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch('/api/coach/analyze-cv', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ cvText }),
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        setError(data.error || 'Error al analizar el CV');
        return;
      }

      setResult(data);
    } catch (err) {
      setError('Error de conexión. Asegúrate de que el backend está corriendo en puerto 8000.');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleApplyToProfile = () => {
    if (result?.profile) {
      onApplyToProfile(result.profile);
    }
  };

  const isRealMode = result?.mode === 'real';

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <FileText className="h-5 w-5 text-primary" />
          <CardTitle className="text-lg">Intake de CV</CardTitle>
        </div>
        <CardDescription>
          Pega tu CV o sube un archivo .txt/.md para extraer tu perfil
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* CV Text Input */}
        <div className="space-y-2">
          <Label htmlFor="cv-text">Texto del CV</Label>
          <Textarea
            id="cv-text"
            value={cvText}
            onChange={(e) => setCvText(e.target.value)}
            placeholder="Pega el contenido de tu CV aquí..."
            rows={6}
            className="resize-none"
          />
        </div>

        {/* File Upload */}
        <div className="space-y-2">
          <Label>Ó subir archivo</Label>
          <div className="flex gap-2">
            <Input
              ref={fileInputRef}
              type="file"
              accept=".txt,.md,text/plain,text/markdown"
              onChange={handleFileUpload}
              className="hidden"
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              className="flex-1"
            >
              <Upload className="h-4 w-4 mr-2" />
              Subir .txt/.md
            </Button>
          </div>
        </div>

        {/* Error Message */}
        {error && (
          <div className="flex items-center gap-2 text-sm text-red-500 bg-red-50 p-2 rounded">
            <AlertCircle className="h-4 w-4" />
            {error}
          </div>
        )}

        {/* Analyze Button */}
        <Button 
          onClick={handleAnalyze} 
          disabled={analyzing || !cvText.trim()}
          className="w-full"
        >
          {analyzing ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Analizando...
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4 mr-2" />
              Analizar CV
            </>
          )}
        </Button>

        {/* Results */}
        {result && (
          <div className="space-y-3 pt-2 border-t">
            {/* Mode Badge */}
            <div className="flex items-center justify-between">
              <Badge variant={isRealMode ? 'default' : 'secondary'}>
                {isRealMode ? 'Real' : 'Demo'} Mode
              </Badge>
              {result.confidence && (
                <span className="text-xs text-muted-foreground">
                  Confidence: {Math.round(result.confidence * 100)}%
                </span>
              )}
            </div>

            {/* Extracted Name */}
            {result.profile.name && (
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
                <span className="font-medium">{result.profile.name}</span>
              </div>
            )}

            {/* Summary Preview */}
            {result.profile.summary && (
              <div className="text-sm text-muted-foreground bg-muted p-2 rounded">
                {result.profile.summary.substring(0, 150)}
                {result.profile.summary.length > 150 ? '...' : ''}
              </div>
            )}

            {/* Skills Preview */}
            {result.profile.skills && result.profile.skills.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {result.profile.skills.slice(0, 5).map((skill, index) => (
                  <Badge key={index} variant="outline" className="text-xs">
                    {skill}
                  </Badge>
                ))}
                {result.profile.skills.length > 5 && (
                  <Badge variant="outline" className="text-xs">
                    +{result.profile.skills.length - 5} more
                  </Badge>
                )}
              </div>
            )}

            {/* Apply to Profile Button */}
            <Button 
              onClick={handleApplyToProfile}
              variant="secondary"
              className="w-full"
            >
              <ArrowDownToLine className="h-4 w-4 mr-2" />
              Aplicar al Perfil
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
