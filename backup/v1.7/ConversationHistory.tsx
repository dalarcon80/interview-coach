import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { SuggestionResponse } from "@/types";

interface ConversationEntry {
  id: string;
  timestamp: string;
  question: string;
  suggestion: SuggestionResponse;
}

export interface ConversationHistoryProps {
  entries: ConversationEntry[];
  onEntryClick?: (entry: {
    question: string;
    suggestion: SuggestionResponse;
  }) => void;
}

function previewText(entry: ConversationEntry): string {
  const firstBullet = entry.suggestion.bullets[0];
  if (firstBullet) {
    return firstBullet;
  }

  const firstLine = entry.suggestion.full_response.split("\n").find((line) => line.trim());
  return firstLine?.trim() ?? "No preview available";
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

export function ConversationHistory({ entries, onEntryClick }: ConversationHistoryProps) {
  return (
    <Card className="card-elevated h-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">Conversation History</CardTitle>
      </CardHeader>

      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No question/response pairs in this session yet.</p>
        ) : (
          <ScrollArea className="h-[520px] pr-3">
            <Accordion type="single" collapsible className="w-full">
              {entries.map((entry, index) => (
                <AccordionItem 
                  key={`${entry.id}-${index}`} 
                  value={`${entry.id}-${index}`}
                  className={index % 2 === 0 ? "bg-surface-800/50" : "bg-surface-800/30"}
                >
                  <AccordionTrigger
                    onClick={() =>
                      onEntryClick?.({
                        question: entry.question,
                        suggestion: entry.suggestion,
                      })
                    }
                    className="hover:no-underline"
                  >
                    <div className="flex min-w-0 flex-1 flex-col items-start gap-2 pr-3 text-left">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-surface-500">
                        <span>{formatTimestamp(entry.timestamp)}</span>
                        <Badge variant="outline">{entry.suggestion.mode}</Badge>
                        <Badge variant="outline">{entry.suggestion.language}</Badge>
                      </div>

                      <p className="line-clamp-2 text-sm font-medium">{entry.question}</p>
                      <p className="line-clamp-2 text-xs text-muted-foreground">{previewText(entry)}</p>
                    </div>
                  </AccordionTrigger>

                  <AccordionContent className="space-y-3">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Full Response
                      </p>
                      <p className="whitespace-pre-wrap text-sm leading-6">
                        {entry.suggestion.full_response}
                      </p>
                    </div>

                    {entry.suggestion.bullets.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          Key Points
                        </p>
                        <ul className="list-disc space-y-1 pl-5 text-sm">
                          {entry.suggestion.bullets.map((bullet, bulletIndex) => (
                            <li key={`${entry.id}-bullet-${bulletIndex}`}>{bullet}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <Badge variant="outline">Quality {entry.suggestion.quality_score}</Badge>
                      <Badge variant="outline">Confidence {Math.round(entry.suggestion.confidence * 100)}%</Badge>
                      <Badge variant="outline">Latency {entry.suggestion.latency_ms} ms</Badge>
                    </div>
                  </AccordionContent>

                  {index < entries.length - 1 && <Separator />}
                </AccordionItem>
              ))}
            </Accordion>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
