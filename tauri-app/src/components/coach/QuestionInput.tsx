import { useEffect, useRef, useState } from "react";
import { Loader2, MessageSquare, Send } from "lucide-react";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "pt", label: "Portuguese" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
] as const;

const HISTORY_STORAGE_KEY = "coach.question.history";

export interface QuestionInputProps {
  onSubmit: (question: string, language?: string) => void;
  isLoading?: boolean;
  mode?: "real" | "demo";
  defaultLanguage?: string;
  disabled?: boolean;
  placeholder?: string;
}

export function QuestionInput({
  onSubmit,
  isLoading = false,
  mode = "demo",
  defaultLanguage = "en",
  disabled = false,
  placeholder = "Type the interview question here...",
}: QuestionInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState(defaultLanguage);
  const [questionHistory, setQuestionHistory] = useState<string[]>([]);

  useEffect(() => {
    setLanguage(defaultLanguage || "en");
  }, [defaultLanguage]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(HISTORY_STORAGE_KEY);
      if (!raw) {
        return;
      }

      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        setQuestionHistory(
          parsed.filter((item): item is string => typeof item === "string")
        );
      }
    } catch {
      setQuestionHistory([]);
    }
  }, []);

  const submit = () => {
    const trimmed = question.trim();
    if (!trimmed || isLoading || disabled) {
      return;
    }

    onSubmit(trimmed, language);
    setQuestion("");

    const updated = [trimmed, ...questionHistory.filter((item) => item !== trimmed)].slice(
      0,
      8
    );

    setQuestionHistory(updated);
    try {
      localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(updated));
    } catch {
      // Ignore storage write errors.
    }
  };

  const onQuestionKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  };

  const isSubmitDisabled = disabled || isLoading || !question.trim();

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-lg">
              <MessageSquare className="h-5 w-5" />
              Question Input
            </CardTitle>
            <CardDescription>
              Enter the interviewer question and request coaching instantly.
            </CardDescription>
          </div>

          <Badge variant={mode === "real" ? "default" : "secondary"}>
            {mode === "real" ? "Real mode" : "Demo mode"}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="coach-language">Response language</Label>
          <Select value={language} onValueChange={setLanguage} disabled={disabled || isLoading}>
            <SelectTrigger id="coach-language" className="w-full">
              <SelectValue placeholder="Select language" />
            </SelectTrigger>
            <SelectContent>
              {LANGUAGE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {questionHistory.length > 0 && (
          <div className="space-y-2">
            <Label htmlFor="question-history">Recent questions</Label>
            <Select
              onValueChange={(value) => {
                setQuestion(value);
                textareaRef.current?.focus();
              }}
              disabled={disabled || isLoading}
            >
              <SelectTrigger id="question-history" className="w-full">
                <SelectValue placeholder="Reuse a recent question (optional)" />
              </SelectTrigger>
              <SelectContent>
                {questionHistory.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item.length > 90 ? `${item.slice(0, 90)}...` : item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="coach-question">Interview question</Label>
          <Textarea
            id="coach-question"
            ref={textareaRef}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={onQuestionKeyDown}
            placeholder={placeholder}
            disabled={disabled || isLoading}
            className="min-h-[180px] resize-y"
          />
          <p className="text-xs text-muted-foreground">
            Shortcut: Ctrl/Cmd + Enter to submit.
          </p>
        </div>

        <Button
          type="button"
          className="w-full"
          onClick={submit}
          disabled={isSubmitDisabled}
        >
          {isLoading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Getting coaching...
            </>
          ) : (
            <>
              <Send className="mr-2 h-4 w-4" />
              Get Coaching
            </>
          )}
        </Button>

        {isLoading && (
          <p className="text-sm text-muted-foreground">
            Generating recommendation from the coaching pipeline...
          </p>
        )}
      </CardContent>
    </Card>
  );
}
