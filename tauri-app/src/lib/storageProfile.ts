const DEFAULT_EXECUTION_PROFILE = "default";
const PROFILE_ENV_KEY = "VITE_INTERVIEW_COACH_PROFILE";
const PROFILE_STORAGE_PREFIX = "ic.profile";

function sanitizeExecutionProfile(value: string | null | undefined): string {
  const cleaned = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "");

  return cleaned || DEFAULT_EXECUTION_PROFILE;
}

export function getExecutionProfile(): string {
  const metaEnv = (import.meta as ImportMeta & { env?: Record<string, unknown> }).env;
  const envValue = typeof metaEnv?.[PROFILE_ENV_KEY] === "string" ? String(metaEnv[PROFILE_ENV_KEY]) : "";

  return sanitizeExecutionProfile(envValue);
}

export function getBrowserStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

export function getProfileStorageKey(baseKey: string): string {
  return `${PROFILE_STORAGE_PREFIX}:${getExecutionProfile()}:${baseKey}`;
}

export function readProfileStorageItem(baseKey: string): string | null {
  try {
    return getBrowserStorage()?.getItem(getProfileStorageKey(baseKey)) ?? null;
  } catch {
    return null;
  }
}

export function writeProfileStorageItem(baseKey: string, value: string): void {
  try {
    getBrowserStorage()?.setItem(getProfileStorageKey(baseKey), value);
  } catch {
    // no-op by design
  }
}

export function removeProfileStorageItem(baseKey: string): void {
  try {
    getBrowserStorage()?.removeItem(getProfileStorageKey(baseKey));
  } catch {
    // no-op by design
  }
}
