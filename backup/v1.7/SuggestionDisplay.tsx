import { useMemo, useState } from "react";
import { Check, Copy, Lightbulb, Sparkles } from "lucide-react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
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
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { SuggestionResponse } from "@/types";

export interface SuggestionDisplayProps {
  suggestion: SuggestionResponse | null;
  isLoading?: boolean;
  question?: string;
}

function renderParagraphs(text: string): JSX.Element[] {
  return text
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((paragraph, index) => (
      <p key={`${paragraph.slice(0, 16)}-${index}`} className="leading-8 text-base md:text-lg">
        {paragraph}
      </p>
    ));
}

export function SuggestionDisplay({
  suggestion,
  isLoading = false,
  question,
}: SuggestionDisplayProps) {
  const [copied, setCopied] = useState(false);

  const confidencePercent = useMemo(
    () => Math.round((suggestion?.confidence ?? 0) * 100),
    [suggestion?.confidence]
  );

  const qualityPercent = useMemo(() => {
    const raw = suggestion?.quality_score ?? 0;
    if (raw <= 1) {
      return Math.round(raw * 100);
    }
    if (raw > 100) {
      return 100;
    }
    return Math.round(raw);
  }, [suggestion?.quality_score]);

  const modeBadge = useMemo(() => {
    const mode = suggestion?.mode;
    if (mode === "real") {
      return {
        label: "Real mode",
        variant: "default" as const,
        helper: "Live providers enabled",
      };
    }
    if (mode === "fallback") {
      return {
        label: "Fallback mode",
        variant: "secondary" as const,
        helper: "Real path failed, demo fallback used",
      };
    }
    return {
      label: "Demo mode",
      variant: "secondary" as const,
      helper: "Simulated coaching output",
    };
  }, [suggestion?.mode]);

  const handleCopy = async () => {
    if (!suggestion?.full_response) {
      return;
    }

    await navigator.clipboard.writeText(suggestion.full_response);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  if (!suggestion && !isLoading) {
    return (
      <Card className="min-h-[440px]">
        <CardContent className="flex h-full min-h-[440px] flex-col items-center justify-center gap-2 text-center">
          <Lightbulb className="h-12 w-12 text-muted-foreground/40" />
          <h3 className="text-xl font-semibold">No coaching suggestion yet</h3>
          <p className="max-w-md text-sm text-muted-foreground">
            Submit an interview question to see a full coaching response with supporting key points.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (!suggestion && isLoading) {
    return (
      <Card className="min-h-[440px]">
        <CardHeader>
          <CardTitle>Generating coaching response</CardTitle>
          <CardDescription>Preparing full response from the selected pipeline mode.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Progress value={72} className="w-full" />
          <p className="text-sm text-muted-foreground">Building primary full response...</p>
        </CardContent>
      </Card>
    );
  }

  if (!suggestion) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="h-5 w-5" />
              Coaching Response
            </CardTitle>
            <CardDescription className="line-clamp-2">
              {question ?? suggestion.question}
            </CardDescription>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge className="status-badge-live">
              <span className="relative flex h-2 w-2 mr-1">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
              LIVE
            </Badge>
            <Badge variant={qualityPercent >= 70 ? "default" : "secondary"}>
              Quality {qualityPercent}%
            </Badge>
            <Badge variant="outline">Confidence {confidencePercent}%</Badge>
            <Badge variant={modeBadge.variant}>{modeBadge.label}</Badge>
            <Badge variant="outline">{suggestion.latency_ms} ms</Badge>
          </div>
        </div>

        {suggestion.mode !== "real" && (
          <Alert>
            <Lightbulb className="h-4 w-4" />
            <AlertTitle>{modeBadge.label}</AlertTitle>
            <AlertDescription>{modeBadge.helper}</AlertDescription>
          </Alert>
        )}
      </CardHeader>

      <CardContent className="space-y-5">
        <section className="space-y-3 rounded-lg border p-4 md:p-6">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold tracking-wider text-primary">FULL RESPONSE</h3>
            <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
              {copied ? (
                <>
                  <Check className="mr-1 h-4 w-4" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="mr-1 h-4 w-4" />
                  Copy
                </>
              )}
            </Button>
          </div>

          <ScrollArea className="max-h-[420px] pr-3">
            <div className="space-y-4 text-foreground">{renderParagraphs(suggestion.full_response)}</div>
          </ScrollArea>
        </section>

        <Separator />

        <section className="space-y-3">
          <h4 className="text-sm font-medium">Supporting Details</h4>

          <Accordion type="single" collapsible defaultValue="none" className="w-full">
            <AccordionItem value={`key-points-${suggestion.suggestion_id}`}>
              <AccordionTrigger>Key Points</AccordionTrigger>
              <AccordionContent>
                {suggestion.bullets.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No key points available for this response.</p>
                ) : (
                  <ul className="list-disc space-y-2 pl-5 text-sm">
                    {suggestion.bullets.map((point, index) => (
                      <li key={`${point}-${index}`}>{point}</li>
                    ))}
                  </ul>
                )}
              </AccordionContent>
            </AccordionItem>
          </Accordion>

          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">Language: {suggestion.language}</Badge>
            <Badge variant="outline">Latency: {suggestion.latency_ms} ms</Badge>
            <Badge variant="outline">ID: {suggestion.suggestion_id}</Badge>
          </div>

          {isLoading && (
            <Alert>
              <Lightbulb className="h-4 w-4" />
              <AlertTitle>Refreshing response</AlertTitle>
              <AlertDescription>
                A newer coaching response is in progress. Current full response remains visible.
              </AlertDescription>
            </Alert>
          )}
        </section>
      </CardContent>
    </Card>
  );
}
