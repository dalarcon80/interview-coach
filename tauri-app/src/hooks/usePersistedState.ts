import { useCallback, useEffect, useState } from "react";
import { getBrowserStorage, getProfileStorageKey } from "@/lib/storageProfile";

/**
 * Like useState but automatically persists to localStorage.
 * Loads initial value from localStorage on mount.
 * Saves to localStorage on every change.
 */
export function usePersistedState<T>(
  key: string,
  defaultValue: T,
  serialize?: (value: T) => string,
  deserialize?: (raw: string) => T
): [T, (value: T | ((prev: T) => T)) => void, () => void] {
  const toRaw = useCallback(
    (value: T): string => {
      try {
        if (serialize) return serialize(value);
        return JSON.stringify(value);
      } catch {
        return JSON.stringify(defaultValue);
      }
    },
    [defaultValue, serialize]
  );

  const fromRaw = useCallback(
    (raw: string): T => {
      try {
        if (deserialize) return deserialize(raw);
        return JSON.parse(raw) as T;
      } catch {
        return defaultValue;
      }
    },
    [defaultValue, deserialize]
  );

  const [value, setValue] = useState<T>(() => {
    const storage = getBrowserStorage();
    if (!storage) return defaultValue;
    try {
      const raw = storage.getItem(getProfileStorageKey(key));
      if (raw === null) return defaultValue;
      return fromRaw(raw);
    } catch {
      return defaultValue;
    }
  });

  useEffect(() => {
    const storage = getBrowserStorage();
    if (!storage) return;
    try {
      storage.setItem(getProfileStorageKey(key), toRaw(value));
    } catch {
      // no-op by design
    }
  }, [key, toRaw, value]);

  const clearValue = useCallback(() => {
    const storage = getBrowserStorage();
    if (storage) {
      try {
        storage.removeItem(getProfileStorageKey(key));
      } catch {
        // no-op by design
      }
    }
    setValue(defaultValue);
  }, [defaultValue, key]);

  return [value, setValue, clearValue];
}
