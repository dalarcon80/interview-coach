import { Loader2, Sparkles, FileSearch2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface ResearchField {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  helpText?: string;
}

interface ResearchContextIntakeProps {
  title: string;
  description: string;
  fields: ResearchField[];
  notesLabel: string;
  notes: string;
  onNotesChange: (value: string) => void;
  analyzeLabel: string;
  indexLabel: string;
  onAnalyze: () => Promise<void>;
  onIndex: () => Promise<void>;
  isAnalyzing?: boolean;
  isIndexing?: boolean;
  statusMessage?: string | null;
  sourceCountLabel?: string;
}

export function ResearchContextIntake({
  title,
  description,
  fields,
  notesLabel,
  notes,
  onNotesChange,
  analyzeLabel,
  indexLabel,
  onAnalyze,
  onIndex,
  isAnalyzing = false,
  isIndexing = false,
  statusMessage,
  sourceCountLabel,
}: ResearchContextIntakeProps) {
  const loading = isAnalyzing || isIndexing;

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-lg">
          <FileSearch2 className="h-5 w-5" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>

      <CardContent className="min-w-0">
        <div className="space-y-4 pb-2">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {fields.map((field) => (
              <div key={field.label} className="space-y-2 md:col-span-1">
                <Label>{field.label}</Label>
                <Input
                  value={field.value}
                  onChange={(event) => field.onChange(event.target.value)}
                  placeholder={field.placeholder}
                />
                {field.helpText && (
                  <p className="text-xs text-muted-foreground">{field.helpText}</p>
                )}
              </div>
            ))}
          </div>

          <div className="space-y-2">
            <Label>{notesLabel}</Label>
            <Textarea
              value={notes}
              onChange={(event) => onNotesChange(event.target.value)}
              placeholder="Paste supporting notes, extracted text, or research snippets here..."
              rows={4}
              className="min-h-[120px] resize-y"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => void onAnalyze()}
              disabled={loading}
            >
              {isAnalyzing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-2 h-4 w-4" />
              )}
              {analyzeLabel}
            </Button>
            <Button
              type="button"
              onClick={() => void onIndex()}
              disabled={loading}
            >
              {isIndexing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <FileSearch2 className="mr-2 h-4 w-4" />
              )}
              {indexLabel}
            </Button>
            {sourceCountLabel && (
              <Badge variant="outline" className="self-center">
                {sourceCountLabel}
              </Badge>
            )}
          </div>

          {statusMessage && (
            <Alert>
              <AlertTitle>Context status</AlertTitle>
              <AlertDescription>{statusMessage}</AlertDescription>
            </Alert>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
