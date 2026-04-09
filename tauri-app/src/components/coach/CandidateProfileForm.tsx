import { useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

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
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import api from "@/lib/api-client";
import type { CandidateProfile } from "@/types";

interface CandidateProfileFormProps {
  profile: CandidateProfile;
  onChange: (profile: CandidateProfile) => void;
  readOnly?: boolean;
}

function parseCommaSeparated(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseLineSeparated(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function toCommaSeparated(values: string[]): string {
  return values.join(", ");
}

function toLineSeparated(values: string[]): string {
  return values.join("\n");
}

function WrappedTagList({
  items,
  tone,
}: {
  items: string[];
  tone: "secondary" | "outline";
}) {
  if (items.length === 0) {
    return <span className="text-sm text-muted-foreground">No items listed.</span>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item, index) => (
        <span
          key={`${item}-${index}`}
          className={cn(
            "inline-flex max-w-full items-start rounded-md border px-2 py-0.5 text-xs font-medium leading-snug whitespace-normal break-words",
            tone === "secondary"
              ? "border-transparent bg-secondary text-secondary-foreground"
              : "bg-transparent text-foreground"
          )}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

export function CandidateProfileForm({
  profile,
  onChange,
  readOnly = false,
}: CandidateProfileFormProps) {
  const [isReindexing, setIsReindexing] = useState(false);
  const [reindexMessage, setReindexMessage] = useState<string | null>(null);

  const handleReindex = async () => {
    setIsReindexing(true);
    setReindexMessage(null);

    try {
      // Use current profile state (including any edits made by the user)
      const currentProfile = {
        profile_id: profile.profile_id,
        name: profile.name,
        current_role: profile.current_role,
        company: profile.company,
        years_experience: profile.years_experience,
        skills: profile.skills,
        achievements: profile.achievements,
        summary: profile.summary,
        cv_text: profile.cv_text || "",
      };
      
      console.log("[Reindex] Sending profile with cv_text length:", currentProfile.cv_text.length);
      console.log("[Reindex] Achievements count:", currentProfile.achievements.length);
      
      const result = await api.reindexProfile(currentProfile);

      if (result.success) {
        // Update profile with the returned profile_id
        if (result.profile_id) {
          onChange({ ...profile, profile_id: result.profile_id });
        }
        setReindexMessage(
          `✅ Indexed: ${result.indexed?.achievements} achievements, ${result.indexed?.document_chunks} CV chunks (ID: ${result.profile_id?.slice(0, 8)}...)`
        );
      } else {
        setReindexMessage(`❌ Error: ${result.error}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setReindexMessage(`❌ Error: ${msg}`);
    } finally {
      setIsReindexing(false);
    }
  };

  const update = <K extends keyof CandidateProfile>(
    key: K,
    value: CandidateProfile[K]
  ) => {
    onChange({ ...profile, [key]: value });
  };

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg">Candidate Profile</CardTitle>
            <CardDescription>
              Capture candidate context used for personalized interview coaching.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleReindex}
            disabled={isReindexing}
            title="Reindex profile to update embeddings in database"
          >
            {isReindexing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            Reindex
          </Button>
        </div>
        {reindexMessage && (
          <div className="mt-2 text-sm text-muted-foreground">{reindexMessage}</div>
        )}
      </CardHeader>

      <CardContent className="min-w-0">
        <div className="space-y-6 pb-2">
          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Identity
              </div>
              <p className="text-sm text-muted-foreground">
                Core candidate details used across preparation and coaching.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="candidate-name">Name</Label>
                <Input
                  id="candidate-name"
                  value={profile.name}
                  onChange={(event) => update("name", event.target.value)}
                  readOnly={readOnly}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="candidate-current-role">Current role</Label>
                <Input
                  id="candidate-current-role"
                  value={profile.current_role}
                  onChange={(event) => update("current_role", event.target.value)}
                  readOnly={readOnly}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="candidate-current-company">Current company</Label>
                <Input
                  id="candidate-current-company"
                  value={profile.company ?? ""}
                  onChange={(event) => update("company", event.target.value)}
                  readOnly={readOnly}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="candidate-years">Years of experience</Label>
                <Input
                  id="candidate-years"
                  type="number"
                  min={0}
                  value={profile.years_experience}
                  onChange={(event) =>
                    update(
                      "years_experience",
                      Number.parseInt(event.target.value, 10) || 0
                    )
                  }
                  readOnly={readOnly}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="candidate-target-role">Target role</Label>
                <Input
                  id="candidate-target-role"
                  value={profile.target_role}
                  onChange={(event) => update("target_role", event.target.value)}
                  readOnly={readOnly}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="candidate-industry">Industry</Label>
                <Input
                  id="candidate-industry"
                  value={profile.industry}
                  onChange={(event) => update("industry", event.target.value)}
                  readOnly={readOnly}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="candidate-location">Location</Label>
                <Input
                  id="candidate-location"
                  value={profile.location}
                  onChange={(event) => update("location", event.target.value)}
                  readOnly={readOnly}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="candidate-education">Education</Label>
              <Input
                id="candidate-education"
                value={profile.education}
                onChange={(event) => update("education", event.target.value)}
                readOnly={readOnly}
              />
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Background
              </div>
              <p className="text-sm text-muted-foreground">
                Skills, languages, and certifications that shape the coaching context.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="candidate-skills">Skills (comma-separated)</Label>
              <Textarea
                id="candidate-skills"
                value={toCommaSeparated(profile.skills)}
                onChange={(event) =>
                  update("skills", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && <WrappedTagList items={profile.skills} tone="secondary" />}
            </div>

            <div className="space-y-2">
              <Label htmlFor="candidate-languages">Languages (comma-separated)</Label>
              <Textarea
                id="candidate-languages"
                value={toCommaSeparated(profile.languages)}
                onChange={(event) =>
                  update("languages", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && <WrappedTagList items={profile.languages} tone="outline" />}
            </div>

            <div className="space-y-2">
              <Label htmlFor="candidate-certifications">
                Certifications (comma-separated)
              </Label>
              <Textarea
                id="candidate-certifications"
                value={toCommaSeparated(profile.certifications)}
                onChange={(event) =>
                  update("certifications", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && (
                <WrappedTagList items={profile.certifications} tone="secondary" />
              )}
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Achievements & summary
              </div>
              <p className="text-sm text-muted-foreground">
                High-signal material that the coach should emphasize.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="candidate-achievements">Achievements (one per line)</Label>
              <Textarea
                id="candidate-achievements"
                value={toLineSeparated(profile.achievements)}
                onChange={(event) =>
                  update("achievements", parseLineSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={4}
                className="resize-y"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="candidate-summary">Summary</Label>
              <Textarea
                id="candidate-summary"
                value={profile.summary}
                onChange={(event) => update("summary", event.target.value)}
                readOnly={readOnly}
                rows={4}
                className="min-h-[120px] resize-y"
              />
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                CV text
              </div>
              <p className="text-sm text-muted-foreground">
                Editable source text used for reindexing and profile extraction.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="candidate-cv-text">
                CV text
                <span className="ml-2 text-xs text-muted-foreground">
                  (editable - changes will be reindexed)
                </span>
              </Label>
              <Textarea
                id="candidate-cv-text"
                value={profile.cv_text ?? ""}
                onChange={(event) => update("cv_text", event.target.value)}
                readOnly={readOnly}
                rows={8}
                className="min-h-[180px] resize-y font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Edit this text and click "Reindex" to update the embeddings used for responses.
              </p>
            </div>
          </section>
          </div>
      </CardContent>
    </Card>
  );
}
