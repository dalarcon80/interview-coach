import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { CompanyInfo } from "@/types";

interface CompanyInfoFormProps {
  companyInfo: CompanyInfo;
  onChange: (info: CompanyInfo) => void;
  readOnly?: boolean;
}

const COMPANY_SIZES = [
  "startup",
  "small",
  "medium",
  "large",
  "enterprise",
] as const;

const ROLE_LEVELS = [
  "junior",
  "mid",
  "senior",
  "lead",
  "staff",
  "principal",
  "director",
  "vp",
  "c-level",
] as const;

const INTERVIEW_TYPES = [
  "behavioral",
  "technical",
  "system_design",
  "case_study",
  "mixed",
] as const;

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

export function CompanyInfoForm({
  companyInfo,
  onChange,
  readOnly = false,
}: CompanyInfoFormProps) {
  const update = <K extends keyof CompanyInfo>(key: K, value: CompanyInfo[K]) => {
    onChange({ ...companyInfo, [key]: value });
  };

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">Company & Role Information</CardTitle>
        <CardDescription>
          Add company context and role details for targeted interview coaching.
        </CardDescription>
      </CardHeader>

      <CardContent className="min-w-0">
        <div className="space-y-6 pb-2">
          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Company snapshot
              </div>
              <p className="text-sm text-muted-foreground">
                Core company and role metadata used to frame the interview.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="company-name">Name</Label>
                <Input
                  id="company-name"
                  value={companyInfo.name}
                  onChange={(event) => update("name", event.target.value)}
                  readOnly={readOnly}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="company-industry">Industry</Label>
                <Input
                  id="company-industry"
                  value={companyInfo.industry}
                  onChange={(event) => update("industry", event.target.value)}
                  readOnly={readOnly}
                />
              </div>

              <div className="space-y-2">
                <Label>Size</Label>
                <Select
                  value={companyInfo.size}
                  onValueChange={(value) => update("size", value)}
                  disabled={readOnly}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select company size" />
                  </SelectTrigger>
                  <SelectContent>
                    {COMPANY_SIZES.map((size) => (
                      <SelectItem key={size} value={size}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="company-role-title">Role title</Label>
                <Input
                  id="company-role-title"
                  value={companyInfo.role_title}
                  onChange={(event) => update("role_title", event.target.value)}
                  readOnly={readOnly}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-culture">Culture</Label>
              <Textarea
                id="company-culture"
                value={companyInfo.culture}
                onChange={(event) => update("culture", event.target.value)}
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-mission">Mission</Label>
              <Textarea
                id="company-mission"
                value={companyInfo.mission}
                onChange={(event) => update("mission", event.target.value)}
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Role snapshot
              </div>
              <p className="text-sm text-muted-foreground">
                Role title and interview settings extracted from the job posting URL.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Role level</Label>
                <Select
                  value={companyInfo.role_level}
                  onValueChange={(value) => update("role_level", value)}
                  disabled={readOnly}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select role level" />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLE_LEVELS.map((level) => (
                      <SelectItem key={level} value={level}>
                        {level}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Interview type</Label>
                <Select
                  value={companyInfo.interview_type}
                  onValueChange={(value) => update("interview_type", value)}
                  disabled={readOnly}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select interview type" />
                  </SelectTrigger>
                  <SelectContent>
                    {INTERVIEW_TYPES.map((type) => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Response length (words)</Label>
                <span className="text-sm font-medium">
                  {companyInfo.max_words || 200} words
                </span>
              </div>
              <Slider
                min={50}
                max={500}
                step={10}
                value={[companyInfo.max_words || 200]}
                onValueChange={(value) => update("max_words", value[0])}
                disabled={readOnly}
              />
              <p className="text-xs text-muted-foreground">
                Approximate word count for coach responses
              </p>
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Coaching preferences
              </div>
              <p className="text-sm text-muted-foreground">
                Signals that tune the tone and focus of the coach.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-values">Values (comma-separated)</Label>
              <Textarea
                id="company-values"
                value={toCommaSeparated(companyInfo.values)}
                onChange={(event) =>
                  update("values", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && <WrappedTagList items={companyInfo.values} tone="secondary" />}
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-tech-stack">Tech stack (comma-separated)</Label>
              <Textarea
                id="company-tech-stack"
                value={toCommaSeparated(companyInfo.tech_stack)}
                onChange={(event) =>
                  update("tech_stack", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && <WrappedTagList items={companyInfo.tech_stack} tone="outline" />}
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-interview-focus">
                Interview focus (comma-separated)
              </Label>
              <Textarea
                id="company-interview-focus"
                value={toCommaSeparated(companyInfo.interview_focus)}
                onChange={(event) =>
                  update("interview_focus", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && (
                <WrappedTagList items={companyInfo.interview_focus} tone="secondary" />
              )}
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Requirements & responsibilities
              </div>
              <p className="text-sm text-muted-foreground">
                Role details that the coach should keep in view.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-role-requirements">
                Role requirements (one per line)
              </Label>
              <Textarea
                id="company-role-requirements"
                value={toLineSeparated(companyInfo.role_requirements)}
                onChange={(event) =>
                  update("role_requirements", parseLineSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={4}
                className="min-h-[120px] resize-y"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-role-responsibilities">
                Role responsibilities (one per line)
              </Label>
              <Textarea
                id="company-role-responsibilities"
                value={toLineSeparated(companyInfo.role_responsibilities)}
                onChange={(event) =>
                  update("role_responsibilities", parseLineSeparated(event.target.value))
                }
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
                Job description
              </div>
              <p className="text-sm text-muted-foreground">
                The source narrative that can be referenced during coaching.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-job-description">Job description</Label>
              <Textarea
                id="company-job-description"
                value={companyInfo.job_description}
                onChange={(event) => update("job_description", event.target.value)}
                readOnly={readOnly}
                rows={8}
                className="min-h-[220px] resize-y"
              />
            </div>
          </section>

          <Separator />

          <section className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Research-backed context
              </div>
              <p className="text-sm text-muted-foreground">
                Optional research context that can be indexed and reused by the coach.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-summary">Company summary</Label>
              <Textarea
                id="company-summary"
                value={companyInfo.company_summary ?? ""}
                onChange={(event) => update("company_summary", event.target.value)}
                readOnly={readOnly}
                rows={4}
                className="min-h-[120px] resize-y"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-products-services">
                Products or services (comma-separated)
              </Label>
              <Textarea
                id="company-products-services"
                value={toCommaSeparated(companyInfo.products_services ?? [])}
                onChange={(event) =>
                  update("products_services", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && (
                <WrappedTagList items={companyInfo.products_services ?? []} tone="outline" />
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-recent-focus">Recent focus (comma-separated)</Label>
              <Textarea
                id="company-recent-focus"
                value={toCommaSeparated(companyInfo.recent_focus ?? [])}
                onChange={(event) =>
                  update("recent_focus", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && (
                <WrappedTagList items={companyInfo.recent_focus ?? []} tone="secondary" />
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-source-urls">Source URLs (comma-separated)</Label>
              <Textarea
                id="company-source-urls"
                value={toCommaSeparated(companyInfo.source_urls ?? [])}
                onChange={(event) =>
                  update("source_urls", parseCommaSeparated(event.target.value))
                }
                readOnly={readOnly}
                rows={3}
                className="resize-y"
              />
              {readOnly && <WrappedTagList items={companyInfo.source_urls ?? []} tone="outline" />}
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-research-notes">Research notes</Label>
              <Textarea
                id="company-research-notes"
                value={companyInfo.research_notes ?? ""}
                onChange={(event) => update("research_notes", event.target.value)}
                readOnly={readOnly}
                rows={4}
                className="min-h-[120px] resize-y"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-context-id">Context ID</Label>
              <Input
                id="company-context-id"
                value={companyInfo.context_id ?? ""}
                onChange={(event) => update("context_id", event.target.value)}
                placeholder="Assigned after indexing"
                readOnly={readOnly}
              />
            </div>
          </section>
        </div>
      </CardContent>
    </Card>
  );
}
