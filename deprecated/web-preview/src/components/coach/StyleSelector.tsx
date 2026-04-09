'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { 
  Zap, 
  Target, 
  Code, 
  Layers, 
  CheckCircle2 
} from 'lucide-react';

export type ResponseStyle = 'executive' | 'commercial' | 'technical' | 'mixed';

interface StyleConfig {
  id: ResponseStyle;
  name: string;
  icon: React.ReactNode;
  description: string;
  focus: string[];
  tone: string;
  maxLength: number;
  color: string;
}

const STYLES: StyleConfig[] = [
  {
    id: 'executive',
    name: 'Executive',
    icon: <Zap className="h-5 w-5" />,
    description: 'Respuestas concisas y directas para C-level y tomadores de decisión',
    focus: ['Decisiones clave', 'Métricas', 'Impacto negocio'],
    tone: 'Profesional y directo',
    maxLength: 150,
    color: 'bg-amber-500'
  },
  {
    id: 'commercial',
    name: 'Commercial',
    icon: <Target className="h-5 w-5" />,
    description: 'Respuestas persuasivas orientadas a resultados y beneficios',
    focus: ['Beneficios', 'Valor agregado', 'Resultados tangibles'],
    tone: 'Persuasivo y orientado a resultados',
    maxLength: 200,
    color: 'bg-emerald-500'
  },
  {
    id: 'technical',
    name: 'Technical',
    icon: <Code className="h-5 w-5" />,
    description: 'Respuestas detalladas con profundidad técnica',
    focus: ['Implementación', 'Arquitectura', 'Mejores prácticas'],
    tone: 'Técnico y detallado',
    maxLength: 300,
    color: 'bg-violet-500'
  },
  {
    id: 'mixed',
    name: 'Mixed',
    icon: <Layers className="h-5 w-5" />,
    description: 'Balance entre aspectos técnicos y de negocio',
    focus: ['Contexto', 'Solución', 'Resultado'],
    tone: 'Equilibrado',
    maxLength: 250,
    color: 'bg-sky-500'
  }
];

interface StyleSelectorProps {
  selectedStyle: ResponseStyle;
  onStyleChange: (style: ResponseStyle) => void;
}

export function StyleSelector({ selectedStyle, onStyleChange }: StyleSelectorProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Estilo de Respuesta</CardTitle>
        <CardDescription>
          Selecciona el estilo más apropiado para tu entrevista
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3">
          {STYLES.map((style) => (
            <button
              key={style.id}
              onClick={() => onStyleChange(style.id)}
              className={`relative p-3 rounded-lg border-2 transition-all text-left ${
                selectedStyle === style.id 
                  ? 'border-primary bg-primary/5' 
                  : 'border-border hover:border-primary/50 hover:bg-muted/50'
              }`}
            >
              {selectedStyle === style.id && (
                <CheckCircle2 className="absolute top-2 right-2 h-4 w-4 text-primary" />
              )}
              <div className="flex items-center gap-2 mb-2">
                <div className={`p-1.5 rounded ${style.color} text-white`}>
                  {style.icon}
                </div>
                <span className="font-medium text-sm">{style.name}</span>
              </div>
              <p className="text-xs text-muted-foreground mb-2 line-clamp-2">
                {style.description}
              </p>
              <div className="flex flex-wrap gap-1">
                {style.focus.slice(0, 2).map((f, i) => (
                  <Badge key={i} variant="outline" className="text-[10px] px-1 py-0">
                    {f}
                  </Badge>
                ))}
              </div>
            </button>
          ))}
        </div>
        
        {/* Selected Style Details */}
        {selectedStyle && (
          <div className="mt-3 p-3 bg-muted/50 rounded-lg">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Tono:</span>
              <span className="font-medium">{STYLES.find(s => s.id === selectedStyle)?.tone}</span>
            </div>
            <div className="flex items-center justify-between text-sm mt-1">
              <span className="text-muted-foreground">Longitud máx:</span>
              <span className="font-medium">{STYLES.find(s => s.id === selectedStyle)?.maxLength} palabras</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
