import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
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
import api from "@/lib/api-client";
import type { CoachingStyle } from "@/types";

interface StyleSelectorProps {
  selectedStyle: string;
  onStyleChange: (styleId: string) => void;
  styles?: CoachingStyle[];
}

const BUILTIN_STYLES: CoachingStyle[] = [
  {
    id: "professional",
    name: "Professional",
    description: "Professional and polished responses",
  },
  {
    id: "conversational",
    name: "Conversational",
    description: "Natural, conversational tone",
  },
  {
    id: "concise",
    name: "Concise",
    description: "Brief and to-the-point answers",
  },
  {
    id: "detailed",
    name: "Detailed",
    description: "Comprehensive, detailed responses",
  },
  {
    id: "star",
    name: "STAR",
    description: "STAR method structured responses",
  },
];

export function StyleSelector({
  selectedStyle,
  onStyleChange,
  styles,
}: StyleSelectorProps) {
  const [apiStyles, setApiStyles] = useState<CoachingStyle[]>([]);

  useEffect(() => {
    if (styles && styles.length > 0) {
      return;
    }

    let active = true;

    const loadStyles = async () => {
      try {
        const fetched = await api.listStyles();
        if (active && fetched.length > 0) {
          setApiStyles(fetched);
        }
      } catch {
        if (active) {
          setApiStyles([]);
        }
      }
    };

    loadStyles();

    return () => {
      active = false;
    };
  }, [styles]);

  const availableStyles = useMemo(() => {
    if (styles && styles.length > 0) {
      return styles;
    }

    if (apiStyles.length > 0) {
      return apiStyles;
    }

    return BUILTIN_STYLES;
  }, [styles, apiStyles]);

  const selected =
    availableStyles.find((style) => style.id === selectedStyle) ?? null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Coaching Style</CardTitle>
        <CardDescription className="text-sm">
          Select the response style used to shape coaching suggestions.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        <div className="space-y-2">
          <Label htmlFor="style-selector">Available styles</Label>
          <Select value={selectedStyle} onValueChange={onStyleChange}>
            <SelectTrigger id="style-selector" className="w-full">
              <SelectValue placeholder="Select coaching style" />
            </SelectTrigger>
            <SelectContent>
              {availableStyles.map((style) => (
                <SelectItem key={style.id} value={style.id}>
                  {style.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2 rounded-md border p-3">
          <div className="flex items-center gap-2">
            <Label className="text-sm">Selected style</Label>
            <Badge variant="outline">{selected?.name ?? "None"}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            {selected?.description ?? "No style selected."}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
