import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { InterviewerProfile } from "@/types";

interface InterviewerProfileFormProps {
  profile: InterviewerProfile;
  onChange: (profile: InterviewerProfile) => void;
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

export function InterviewerProfileForm({
  profile,
  onChange,
  readOnly = false,
}: InterviewerProfileFormProps) {
  const update = <K extends keyof InterviewerProfile>(key: K, value: InterviewerProfile[K]) => {
    onChange({ ...profile, [key]: value });
  };

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">Interviewer Profile</CardTitle>
        <CardDescription>
          Capture interviewer context to tune the coach to their priorities and style.
        </CardDescription>
      </CardHeader>

      <CardContent className="min-w-0">
        <div className="space-y-6 pb-2">
          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Identity
              </div>
              <p className="text-sm text-muted-foreground">
                Who is the interviewer and how are they positioned in the process?
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="interviewer-name">Name</Label>
                <Input
                  id="interviewer-name"
                  value={profile.name}
                  onChange={(event) => update("name", event.target.value)}
                  readOnly={readOnly}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="interviewer-role">Role title</Label>
                <Input
                  id="interviewer-role"
                  value={profile.role_title}
                  onChange={(event) => update("role_title", event.target.value)}
                  readOnly={readOnly}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="interviewer-company">Company</Label>
                <Input
                  id="interviewer-company"
                  value={profile.company}
                  onChange={(event) => update("company", event.target.value)}
                  readOnly={readOnly}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="interviewer-context-id">Context ID</Label>
                <Input
                  id="interviewer-context-id"
                  value={profile.context_id ?? ""}
                  onChange={(event) => update("context_id", event.target.value)}
                  placeholder="Assigned after indexing"
                  readOnly={readOnly}
                />
              </div>
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Background
              </div>
              <p className="text-sm text-muted-foreground">
                Useful for anticipating their level of detail, interests, and decision lens.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="interviewer-background">Background summary</Label>
              <Textarea
                id="interviewer-background"
                value={profile.background_summary}
                onChange={(event) => update("background_summary", event.target.value)}
                readOnly={readOnly}
                rows={4}
                className="min-h-[120px] resize-y"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="interviewer-notes">Notes</Label>
              <Textarea
                id="interviewer-notes"
                value={profile.notes}
                onChange={(event) => update("notes", event.target.value)}
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
                Interviewer lens
              </div>
              <p className="text-sm text-muted-foreground">
                Signals that help tailor the answer to what this person likely values.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="interviewer-expertise">Expertise (comma-separated)</Label>
              <Textarea
                id="interviewer-expertise"
                value={toCommaSeparated(profile.expertise)}
                onChange={(event) => update("expertise", parseCommaSeparated(event.target.value))}
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && <WrappedTagList items={profile.expertise} tone="secondary" />}
            </div>

            <div className="space-y-2">
              <Label htmlFor="interviewer-highlights">Career highlights (one per line)</Label>
              <Textarea
                id="interviewer-highlights"
                value={toLineSeparated(profile.career_highlights)}
                onChange={(event) => update("career_highlights", parseLineSeparated(event.target.value))}
                readOnly={readOnly}
                rows={4}
                className="min-h-[120px] resize-y"
              />
              {readOnly && <WrappedTagList items={profile.career_highlights} tone="outline" />}
            </div>

            <div className="space-y-2">
              <Label htmlFor="interviewer-focus">Likely focus areas (comma-separated)</Label>
              <Textarea
                id="interviewer-focus"
                value={toCommaSeparated(profile.likely_focus_areas)}
                onChange={(event) =>
                  update("likely_focus_areas", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && <WrappedTagList items={profile.likely_focus_areas} tone="secondary" />}
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Communication
              </div>
              <p className="text-sm text-muted-foreground">
                Keep the coach aligned with their likely communication style.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="interviewer-style">Communication style</Label>
              <Input
                id="interviewer-style"
                value={profile.communication_style}
                onChange={(event) => update("communication_style", event.target.value)}
                readOnly={readOnly}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="interviewer-source-urls">Source URLs (comma-separated)</Label>
              <Textarea
                id="interviewer-source-urls"
                value={toCommaSeparated(profile.source_urls ?? [])}
                onChange={(event) => update("source_urls", parseCommaSeparated(event.target.value))}
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && <WrappedTagList items={profile.source_urls ?? []} tone="outline" />}
            </div>
          </section>
        </div>
      </CardContent>
    </Card>
  );
}
