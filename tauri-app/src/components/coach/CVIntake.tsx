import { useRef, useState } from "react";
import { FileText, Loader2, Sparkles, Upload } from "lucide-react";

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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import api from "@/lib/api-client";
import type { CVAnalysisResponse, CandidateProfile } from "@/types";

interface CVIntakeProps {
  cvText: string;
  analysis: CVAnalysisResponse | null;
  onCvTextChange: (value: string) => void;
  onProfileExtracted: (
    profile: CandidateProfile,
    analysis: CVAnalysisResponse
  ) => void;
  isAnalyzing?: boolean;
}

export function CVIntake({
  cvText,
  analysis,
  onCvTextChange,
  onProfileExtracted,
  isAnalyzing,
}: CVIntakeProps) {
  const [internalAnalyzing, setInternalAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loading = Boolean(isAnalyzing || internalAnalyzing);

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    const isTextFile =
      file.type.startsWith("text/") || extension === "txt" || extension === "md";

    if (!isTextFile) {
      setError("Only text files are supported (.txt, .md)");
      return;
    }

    try {
      const text = await file.text();
      onCvTextChange(text);
      setError(null);
    } catch {
      setError("Failed to read file content");
    }
  };

  const handleAnalyze = async () => {
    if (!cvText.trim()) {
      setError("Please paste CV content or upload a text file first");
      return;
    }

    setInternalAnalyzing(true);
    setError(null);

    try {
      const response = await api.analyzeCV({ cv_text: cvText });
      onProfileExtracted(response.profile, response);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "CV analysis failed unexpectedly";
      setError(message);
    } finally {
      setInternalAnalyzing(false);
    }
  };

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-lg">
          <FileText className="h-5 w-5" />
          CV Intake
        </CardTitle>
        <CardDescription>
          Paste your CV text or upload a plain text file for profile extraction.
        </CardDescription>
      </CardHeader>

      <CardContent className="min-w-0">
        <div className="space-y-4 pb-2">
          <div className="space-y-2">
            <Label htmlFor="cv-text">CV content</Label>
            <Textarea
              id="cv-text"
              value={cvText}
              onChange={(event) => {
                onCvTextChange(event.target.value);
                if (error) {
                  setError(null);
                }
              }}
              placeholder="Paste your CV content here..."
              rows={12}
              className="min-h-[220px] resize-y"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="cv-file">Upload file</Label>
            <input
              id="cv-file"
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
              className="w-full"
            >
              <Upload className="mr-2 h-4 w-4" />
              Upload File
            </Button>
          </div>

          <Button
            type="button"
            onClick={handleAnalyze}
            disabled={loading || !cvText.trim()}
            className="w-full"
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Analyzing CV...
              </>
            ) : (
              <>
                <Sparkles className="mr-2 h-4 w-4" />
                Analyze CV
              </>
            )}
          </Button>

          {error && (
            <Alert variant="destructive">
              <AlertTitle>Analysis error</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {analysis && (
            <div className="space-y-4 rounded-md border p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge>Analysis Ready</Badge>
                <Badge variant="outline">{analysis.profile.name || "Unnamed"}</Badge>
                <Badge variant="default">
                  Mode: {analysis.mode ?? "real"}
                </Badge>
              </div>

              <div className="space-y-1">
                <Label>Summary</Label>
                <p className="text-sm text-muted-foreground">
                  {analysis.analysis_summary || "No summary available."}
                </p>
              </div>

              <div className="space-y-2">
                <Label>Strengths</Label>
                <div className="flex flex-wrap gap-2">
                  {analysis.strengths.length > 0 ? (
                    analysis.strengths.map((strength, index) => (
                      <Badge key={`${strength}-${index}`} variant="secondary">
                        {strength}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">No strengths listed.</span>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label>Gaps</Label>
                <div className="flex flex-wrap gap-2">
                  {analysis.gaps.length > 0 ? (
                    analysis.gaps.map((gap, index) => (
                      <Badge key={`${gap}-${index}`} variant="outline">
                        {gap}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">No gaps listed.</span>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label>Recommendations</Label>
                {analysis.recommendations.length > 0 ? (
                  <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                    {analysis.recommendations.map((recommendation, index) => (
                      <li key={`${recommendation}-${index}`}>{recommendation}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-sm text-muted-foreground">
                    No recommendations available.
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
